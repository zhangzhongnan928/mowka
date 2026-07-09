"""eBay Browse API source: "cheapest available in AUD right now" for cards.

Dormant without EBAY_CLIENT_ID / EBAY_CLIENT_SECRET (a standard eBay keyset;
Browse works with client-credentials OAuth). Marketplace EBAY_AU, item
location Australia, fixed-price AUD listings only. Sold prices (Marketplace
Insights) are a separate restricted API and land later.

A result only counts when the listing title alias-matches the exact card
(number-qualified aliases + the shared EXCLUDE_TERMS, so graded slabs,
played-condition and foreign-language cards never price the index).

Failure isolation mirrors the sealed lane's per-store rule: one malformed
listing or one flaky search must never sink the whole run. Only an auth
failure (401) aborts — every search would fail the same way.
"""
import time
from datetime import datetime, timezone

import requests

from ..models import Offer, Sku
from ..normalize import match

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
CCG_SINGLES_CATEGORY = "183454"  # Collectible Card Games > Individual Cards
PAGE_LIMIT = 50


def get_token(client_id: str, client_secret: str,
              session: requests.Session | None = None) -> str:
    s = session or requests.Session()
    resp = s.post(TOKEN_URL, auth=(client_id, client_secret),
                  data={"grant_type": "client_credentials",
                        "scope": "https://api.ebay.com/oauth/api_scope"},
                  timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _query(card: Sku) -> str:
    return f"pokemon {card.name.split('(')[0].strip()} {card.number}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _aud_cents(item: dict) -> int | None:
    """Defensive price parse: eBay summaries do ship without a usable value."""
    price = item.get("price") or {}
    if price.get("currency") != "AUD":
        return None
    try:
        return round(float(price["value"]) * 100)
    except (KeyError, TypeError, ValueError):
        return None


def search_card(card: Sku, token: str,
                session: requests.Session | None = None) -> tuple[Offer | None, int, bool]:
    """One Browse call. Returns (cheapest matching offer or None,
    matching count on the cheapest page, count_capped)."""
    s = session or requests.Session()
    resp = s.get(
        SEARCH_URL,
        params={
            "q": _query(card),
            "category_ids": CCG_SINGLES_CATEGORY,
            "limit": str(PAGE_LIMIT),
            "sort": "price",
            "filter": "itemLocationCountry:AU,priceCurrency:AUD,buyingOptions:{FIXED_PRICE}",
        },
        headers={"Authorization": f"Bearer {token}",
                 "X-EBAY-C-MARKETPLACE-ID": "EBAY_AU"},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json().get("itemSummaries") or []
    matching = [
        (cents, item) for item in items
        if (cents := _aud_cents(item)) is not None
        and item.get("itemWebUrl")
        and match(item.get("title", ""), [card]) is not None
    ]
    # a full page means the count is a floor, not a total
    capped = len(items) == PAGE_LIMIT
    if not matching:
        return None, 0, capped
    cents, cheapest = min(matching, key=lambda pair: pair[0])
    offer = Offer(
        sku_id=card.id,
        store="eBay AU",
        url=cheapest["itemWebUrl"],
        price_cents=cents,
        currency="AUD",
        in_stock=True,
        observed_at=_now(),
        source_type="ebay_active",
    )
    return offer, len(matching), capped


def fetch_cards(cards: list[Sku], client_id: str, client_secret: str,
                max_calls: int = 300,
                session: requests.Session | None = None) -> tuple[list[Offer], dict[str, dict], list[str]]:
    """Search each card within the call budget (1 req/s; Browse quota is
    5,000/day). Returns (offers, {sku: {count, capped, searched_at}},
    successfully-searched sku ids). Cards beyond the budget or whose search
    failed stay untouched until a later run; the caller orders `cards`
    stalest-first so the budget rotates through the whole chase list."""
    s = session or requests.Session()
    token = get_token(client_id, client_secret, s)
    offers: list[Offer] = []
    counts: dict[str, dict] = {}
    searched: list[str] = []
    for card in cards[:max_calls]:
        try:
            offer, count, capped = search_card(card, token, s)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 401:
                raise  # bad/expired token: every remaining search would fail
            print(f"WARN ebay {card.id}: search failed: {exc}")
            continue
        except requests.RequestException as exc:
            print(f"WARN ebay {card.id}: search failed: {exc}")
            continue
        searched.append(card.id)
        counts[card.id] = {"count": count, "capped": capped, "searched_at": _now()}
        if offer:
            offers.append(offer)
        time.sleep(1.0)
    if len(cards) > max_calls:
        print(f"WARN ebay: call budget ({max_calls}) reached; "
              f"{len(cards) - max_calls} cards deferred to a later run")
    return offers, counts, searched
