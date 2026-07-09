"""Generic Shopify storefront source.

Most AU specialty TCG stores run Shopify, which exposes a public, structured
catalog at /products.json. Structured JSON beats HTML parsing: fewer breakages,
no layout coupling.

Etiquette (non-negotiable for this project):
- identify ourselves in the User-Agent
- 1 request/second minimum spacing per store
- respect a store's robots.txt and any takedown request: remove the store, move on
"""
import json
import time
from datetime import datetime, timezone

import requests

from ..models import Offer, Sku
from ..normalize import match

UA = "MowkaAU/0.1 (+contact: set-me-in-stores.yaml) price index bot"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_products(payload: dict, store: str, base_url: str, catalog: list[Sku]) -> list[Offer]:
    """Pure function: Shopify products.json payload -> Offers. Unit-testable offline."""
    offers: list[Offer] = []
    for product in payload.get("products", []):
        sku = match(product.get("title", ""), catalog)
        if sku is None:
            continue
        variants = product.get("variants", [])
        if not variants:
            continue
        in_stock_prices = [float(v["price"]) for v in variants if v.get("available")]
        any_price = [float(v["price"]) for v in variants if v.get("price") is not None]
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


def fetch(store: str, base_url: str, catalog: list[Sku], max_pages: int = 8,
          session: requests.Session | None = None) -> list[Offer]:
    """Fetch live prices from one Shopify store."""
    s = session or requests.Session()
    s.headers["User-Agent"] = UA
    offers: list[Offer] = []
    for page in range(1, max_pages + 1):
        url = f"{base_url.rstrip('/')}/products.json?limit=250&page={page}"
        resp = s.get(url, timeout=20)
        if resp.status_code != 200:
            break
        payload = json.loads(resp.text)
        batch = parse_products(payload, store, base_url, catalog)
        offers.extend(batch)
        if not payload.get("products"):
            break
        time.sleep(1.0)  # etiquette: never faster than 1 req/s per store
    return offers
