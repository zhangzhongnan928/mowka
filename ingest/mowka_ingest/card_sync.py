"""Card lane cron entrypoint: catalog enrich + AU prices + site/cards.json.

    python -m mowka_ingest.card_sync --cards catalog/cards.yaml \
        --data-dir ../data --site-out ../site/cards.json [--max-calls 300]

Three stages, each degrading gracefully:
1. Catalog enrich (TCGdex, no key): names/sets/images + the USD reference,
   cached in data-dir/cards/catalog.json and refreshed when older than
   CATALOG_TTL_HOURS. The USD figure is reference-only — never ranked.
2. AU active-listing prices (eBay Browse) when EBAY_CLIENT_ID/SECRET are set.
   Only the (sku, eBay AU) entries actually re-searched this run are replaced,
   so a budget-limited run never erases cards it didn't reach. Store-singles
   offers arrive via the sealed cron's matcher and are read, not written, here.
3. cards.json export: per card — catalog info, ranked best AU offer (same
   public rank() as sealed), all AU offers, active-listing count, USD ref.

The sealed lane is untouched: no sealed SKUs are read or written.
"""
import argparse
import json
import os
import pathlib
import time
from datetime import datetime, timedelta, timezone

from . import gitstore
from .cardcatalog import get_adapter
from .normalize import load_catalog
from .ranking import rank
from .sources import ebay

ROOT = pathlib.Path(__file__).resolve().parents[2]
CATALOG_TTL_HOURS = 24
TCGDEX_SPACING_SECONDS = 0.5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_card_catalog_cache(data_dir: pathlib.Path) -> dict:
    path = data_dir / "cards" / "catalog.json"
    return json.loads(path.read_text()) if path.exists() else {}


def refresh_catalog(cards, cache: dict, adapter) -> dict:
    """Fetch missing/stale catalog entries; keep the rest. Returns new cache."""
    cutoff = (_now() - timedelta(hours=CATALOG_TTL_HOURS)).isoformat(timespec="seconds")
    out = dict(cache)
    for card in cards:
        if not card.catalog_ref:
            continue
        entry = out.get(card.catalog_ref)
        if entry and entry.get("fetched_at", "") > cutoff:
            continue
        try:
            info = adapter.card(card.catalog_ref)
        except Exception as exc:  # one flaky lookup must not sink the run
            print(f"WARN catalog lookup failed for {card.catalog_ref}: {exc}")
            continue
        if info is None:
            print(f"WARN {card.id}: catalog_ref {card.catalog_ref} not found upstream")
            continue
        out[card.catalog_ref] = {
            "name": info.name, "set_name": info.set_name, "set_code": info.set_code,
            "number": info.number, "image_url": info.image_url,
            "usd_market": info.usd_market, "source_url": info.source_url,
            "fetched_at": _now().isoformat(timespec="seconds"),
        }
        time.sleep(TCGDEX_SPACING_SECONDS)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", default=str(ROOT / "catalog" / "cards.yaml"))
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--site-out", required=True)
    ap.add_argument("--max-calls", type=int, default=300)
    args = ap.parse_args()

    data_dir = pathlib.Path(args.data_dir)
    cards = [s for s in load_catalog(args.cards) if s.kind == "card"]
    print(f"{len(cards)} cards in chase list")

    # 1. catalog enrich (TCGdex)
    cache = refresh_catalog(cards, load_card_catalog_cache(data_dir), get_adapter("tcgdex"))
    cards_dir = data_dir / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / "catalog.json").write_text(json.dumps(cache, indent=1) + "\n")

    # 2. AU prices from eBay (dormant without keys)
    counts_path = cards_dir / "ebay_counts.json"
    counts = json.loads(counts_path.read_text()) if counts_path.exists() else {}
    client_id = os.environ.get("EBAY_CLIENT_ID")
    client_secret = os.environ.get("EBAY_CLIENT_SECRET")
    prev = gitstore.load_latest(data_dir)
    if client_id and client_secret:
        offers, new_counts, searched = ebay.fetch_cards(
            cards, client_id, client_secret, max_calls=args.max_calls)
        counts.update(new_counts)
        counts_path.write_text(json.dumps(counts, indent=1) + "\n")
        searched_set = set(searched)
        pruned = {k: v for k, v in prev.items()
                  if not (v.get("source_type") == "ebay_active" and k[0] in searched_set)}
        latest, events = gitstore.apply_run(pruned, offers)
        gitstore.save_run(data_dir, latest, events)
        print(f"ebay: {len(offers)} offers over {len(searched)} cards "
              f"-> {len(events)} change events")
    else:
        latest = prev
        print("ebay: EBAY_CLIENT_ID/SECRET not set — price refresh skipped")

    # 3. cards.json export
    by_sku: dict[str, list[dict]] = {}
    for offer in latest.values():
        by_sku.setdefault(offer["sku_id"], []).append(offer)
    payload = {"generated_at": _now().isoformat(timespec="seconds"), "cards": []}
    for card in cards:
        info = cache.get(card.catalog_ref or "", {})
        offers = sorted(by_sku.get(card.id, []), key=lambda o: o["price_cents"])
        payload["cards"].append({
            "id": card.id, "name": card.name, "set": card.set,
            "set_code": card.set_code, "number": card.number,
            "variant": card.variant, "language": card.language,
            "image": info.get("image_url"),
            "usd_reference": info.get("usd_market"),
            "best": rank(offers), "offers": offers,
            "active_count": counts.get(card.id),
        })
    site_out = pathlib.Path(args.site_out)
    site_out.parent.mkdir(parents=True, exist_ok=True)
    site_out.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"exported {len(payload['cards'])} cards -> {site_out}")


if __name__ == "__main__":
    main()
