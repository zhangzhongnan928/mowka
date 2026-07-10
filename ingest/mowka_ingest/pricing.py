"""Scan-to-price resolution engine — the scan MVP backend.

The spec every frontend (web, iOS, Android) follows is docs/SCAN_PRICING.md.
This module is the reference implementation; the static artifacts it consumes
(card-index.json, au-prices.json, fx.json) are published on the site so
clients can resolve identically without a server.

Identify: the printed collector fraction ("161/131") selects candidate sets
by official card count, then the card by number. OCR'd name tokens rank
candidates when sets collide on the same official total.

Resolution order (AUD only in the index; conversions clearly labeled):
1. AU local price from Mowka's tracked offers — real listing, real source URL
2. TCGplayer USD market x ECB USD->AUD  ("usd_converted")
3. Cardmarket EUR trend  x ECB EUR->AUD ("eur_converted")

    python -m mowka_ingest.pricing "161/131"
    python -m mowka_ingest.pricing "umbreon 161/131" --json
"""
import argparse
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

import requests

from .cardcatalog import CardInfo, get_adapter
from .normalize import _clean

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_INDEX = ROOT / "site" / "api" / "card-index.json"
DEFAULT_AU_PRICES = ROOT / "site" / "api" / "au-prices.json"
FRANKFURTER = "https://api.frankfurter.dev/v1/latest"
FX_UA = "MowkaAU/0.1 (+contact: zhangzhongnan928@gmail.com) fx fetch"

FRACTION_RE = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})")

SOURCE_TYPE_LABELS = {
    "store_shopify": "au_store",
    "ebay_active": "au_ebay",
}


def parse_fraction(text: str) -> tuple[int, int] | None:
    """First plausible collector fraction in scanned text, e.g. '161/131'."""
    for m in FRACTION_RE.finditer(text):
        num, den = int(m.group(1)), int(m.group(2))
        if den > 0:
            return num, den
    return None


def _name_tokens(text: str) -> set[str]:
    return {t for t in _clean(text).split() if not t.isdigit() and len(t) > 2}


def identify(text: str, index: dict, limit: int = 10) -> list[dict]:
    """Scanned text -> candidate cards, best first."""
    sets_by_id = {s["id"]: s for s in index["sets"]}
    fraction = parse_fraction(text)
    tokens = _name_tokens(text)

    def entry(card_row, set_id):
        s = sets_by_id.get(set_id, {})
        return {"id": card_row[0], "localId": card_row[1], "name": card_row[2],
                "set_id": set_id, "set_name": s.get("name", set_id)}

    def name_score(name: str) -> int:
        return len(tokens & _name_tokens(name)) if tokens else 0

    candidates: list[dict] = []
    if fraction:
        num, den = fraction
        matching_sets = {s["id"] for s in index["sets"] if s.get("official") == den}
        for row in index["cards"]:
            set_id = row[0].rsplit("-", 1)[0]
            if set_id in matching_sets and row[1].isdigit() and int(row[1]) == num:
                candidates.append(entry(row, set_id))
        candidates.sort(key=lambda c: -name_score(c["name"]))
    if not candidates and tokens:
        needle = " ".join(sorted(tokens))
        scored = []
        for row in index["cards"]:
            score = name_score(row[2])
            if score:
                scored.append((score, row))
        scored.sort(key=lambda pair: -pair[0])
        candidates = [entry(row, row[0].rsplit("-", 1)[0]) for _, row in scored]
    return candidates[:limit]


def fetch_fx(session: requests.Session | None = None) -> dict:
    """ECB reference rates via frankfurter.dev (free, keyless)."""
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", FX_UA)
    rates = {}
    date = None
    for base in ("USD", "EUR"):
        resp = s.get(FRANKFURTER, params={"base": base, "symbols": "AUD"}, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        rates[f"{base.lower()}_aud"] = float(payload["rates"]["AUD"])
        date = payload["date"]
    return {"date": date, "source": "ECB reference rates via frankfurter.dev",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **rates}


def resolve_price(ref: str, au_prices: dict, info: CardInfo | None, fx: dict | None) -> dict:
    """One card -> AUD price with source. See module docstring for the order."""
    au = au_prices.get(ref)
    if au:
        return {
            "aud_cents": au["price_cents"],
            "source_type": SOURCE_TYPE_LABELS.get(au.get("source_type", "store_shopify"),
                                                  "au_store"),
            "source_label": f"{au['store']} (AU local price)",
            "source_url": au["url"],
            "in_stock": bool(au.get("in_stock")),
            "observed_at": au.get("observed_at"),
            "converted": False,
        }
    for amount, currency, rate_key, market_label in (
            (info.usd_market if info else None, "USD", "usd_aud", "US market (TCGplayer)"),
            (info.eur_market if info else None, "EUR", "eur_aud", "EU market (Cardmarket)")):
        if amount and fx and fx.get(rate_key):
            rate = fx[rate_key]
            return {
                "aud_cents": round(amount * rate * 100),
                "source_type": f"{currency.lower()}_converted",
                "source_label": f"{market_label}, converted at ECB rate {fx['date']}",
                "source_url": info.source_url if info else None,
                "converted": True,
                "base_amount": amount,
                "base_currency": currency,
                "fx_rate": rate,
                "fx_date": fx["date"],
            }
    return {"aud_cents": None, "source_type": "none",
            "source_label": "no price found", "source_url": None, "converted": False}


def _load_json(path: pathlib.Path, fallback):
    return json.loads(path.read_text()) if path.exists() else fallback


def main() -> None:
    ap = argparse.ArgumentParser(description="Resolve a scanned card to an AUD price")
    ap.add_argument("text", help="scanned text, e.g. '161/131' or 'umbreon ex 161/131'")
    ap.add_argument("--index", default=str(DEFAULT_INDEX))
    ap.add_argument("--au-prices", default=str(DEFAULT_AU_PRICES))
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    index = _load_json(pathlib.Path(args.index), None)
    if index is None:
        sys.exit(f"card index not found at {args.index} — run scripts/build_card_index.py")
    au_artifact = _load_json(pathlib.Path(args.au_prices), {})
    au_prices = au_artifact.get("prices", au_artifact)

    candidates = identify(args.text, index, limit=args.limit)
    if not candidates:
        print(json.dumps({"candidates": [], "note": "no match — check the fraction/name"}))
        return

    top = candidates[0]
    adapter = get_adapter("tcgdex")
    info = adapter.card(top["id"])
    fx = fetch_fx()
    price = resolve_price(top["id"], au_prices, info, fx)
    print(json.dumps({
        "identified": top,
        "other_candidates": candidates[1:],
        "price": price,
        "image": info.image_url if info else None,
    }, indent=1))


if __name__ == "__main__":
    main()
