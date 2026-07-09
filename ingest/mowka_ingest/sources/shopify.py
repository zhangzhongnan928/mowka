"""Generic Shopify storefront source.

Most AU specialty TCG stores run Shopify, which exposes a public, structured
catalog at /products.json. Structured JSON beats HTML parsing: fewer breakages,
no layout coupling.

Etiquette (non-negotiable for this project):
- identify ourselves in the User-Agent with a real contact email (enforced here)
- 1 request/second minimum spacing per store; a 429 is retried once, politely
- respect a store's robots.txt and any takedown request: remove the store, move on
"""
import json
import time
from datetime import datetime, timezone

import requests

from ..models import Offer, Sku
from ..normalize import match

UA_TEMPLATE = "MowkaAU/0.1 (+contact: {contact}) price index bot"
PAGE_SIZE = 250


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _variant_prices(variants: list[dict]) -> tuple[list[float], list[float]]:
    """(in-stock prices, all prices). A malformed variant is skipped, never fatal:
    one bad listing must not sink a store's whole ingest."""
    in_stock: list[float] = []
    all_prices: list[float] = []
    for v in variants:
        raw = v.get("price")
        if raw in (None, ""):
            continue
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        all_prices.append(price)
        if v.get("available"):
            in_stock.append(price)
    return in_stock, all_prices


def parse_products(payload: dict, store: str, base_url: str, catalog: list[Sku]) -> list[Offer]:
    """Pure function: Shopify products.json payload -> Offers. Unit-testable offline."""
    offers: list[Offer] = []
    for product in payload.get("products", []):
        sku = match(product.get("title", ""), catalog)
        if sku is None:
            continue
        in_stock_prices, any_price = _variant_prices(product.get("variants", []))
        if not any_price:
            continue
        in_stock = bool(in_stock_prices)
        price = min(in_stock_prices) if in_stock else min(any_price)
        offers.append(Offer(
            sku_id=sku.id,
            store=store,
            url=f"{base_url.rstrip('/')}/products/{product.get('handle', '')}",
            price_cents=round(price * 100),
            currency="AUD",
            in_stock=in_stock,
            observed_at=_now(),
        ))
    return offers


def _retry_after_seconds(resp) -> int:
    try:
        return min(int(resp.headers.get("Retry-After", "15")), 60)
    except (TypeError, ValueError):
        return 15


def fetch(store: str, base_url: str, catalog: list[Sku], max_pages: int = 40,
          session: requests.Session | None = None, contact: str | None = None) -> list[Offer]:
    """Fetch live prices from one Shopify store."""
    if not contact or "example.com" in contact or "set-me" in contact:
        raise ValueError(
            f"{store}: refusing to fetch without a real contact email in the "
            "User-Agent (etiquette hard rule; set 'contact' in stores.yaml)")
    s = session or requests.Session()
    s.headers["User-Agent"] = UA_TEMPLATE.format(contact=contact)
    offers: list[Offer] = []
    page = 1
    retried_429 = False
    while page <= max_pages:
        url = f"{base_url.rstrip('/')}/products.json?limit={PAGE_SIZE}&page={page}"
        resp = s.get(url, timeout=20)
        if resp.status_code == 429 and not retried_429:
            wait = _retry_after_seconds(resp)
            print(f"WARN {store}: 429 rate-limited on page {page}, retrying once in {wait}s")
            retried_429 = True
            time.sleep(wait)
            continue
        if resp.status_code != 200:
            # visible in cron logs: distinguishes "blocked" from "stocks nothing"
            print(f"WARN {store}: HTTP {resp.status_code} on page {page}, stopping")
            break
        payload = json.loads(resp.text)
        products = payload.get("products", [])
        offers.extend(parse_products(payload, store, base_url, catalog))
        if not products:
            break
        if page == max_pages and len(products) == PAGE_SIZE:
            print(f"WARN {store}: pagination cap ({max_pages} pages) hit with a "
                  "full page — catalog truncated, coverage may be incomplete")
        page += 1
        time.sleep(1.0)  # etiquette: never faster than 1 req/s per store
    return offers
