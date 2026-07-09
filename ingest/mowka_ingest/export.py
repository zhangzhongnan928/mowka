"""Build the site's data.json payload from a catalog plus latest offers.

Shared by scripts/export_site.py (local SQLite path) and mowka_ingest.snapshot
(git-as-database cron path) so both produce byte-identical structures under
the same ranking rule.
"""
from datetime import datetime, timezone

from .models import Sku
from .ranking import rank

# The sealed data.json schema predates Offer.source_type; emit exactly these
# keys so the public sealed payload never changes shape underneath consumers.
_SEALED_OFFER_KEYS = ("sku_id", "store", "url", "price_cents", "currency",
                      "in_stock", "observed_at")


def build_payload(catalog: list[Sku], offers: list[dict],
                  generated_at: str | None = None) -> dict:
    by_sku: dict[str, list[dict]] = {}
    for o in offers:
        slim = {k: o[k] for k in _SEALED_OFFER_KEYS}
        by_sku.setdefault(slim["sku_id"], []).append(slim)
    out = {
        "generated_at": generated_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "products": [],
    }
    for sku in catalog:
        sku_offers = sorted(by_sku.get(sku.id, []), key=lambda o: o["price_cents"])
        out["products"].append({
            "id": sku.id, "name": sku.name, "set": sku.set, "category": sku.category,
            "best": rank(sku_offers), "offers": sku_offers,
            "stores_tracked": len({o["store"] for o in sku_offers}),
        })
    return out
