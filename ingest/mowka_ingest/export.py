"""Build the site's data.json payload from a catalog plus latest offers.

Shared by scripts/export_site.py (local SQLite path) and mowka_ingest.snapshot
(git-as-database cron path) so both produce byte-identical structures under
the same ranking rule.
"""
from datetime import datetime, timezone

from .models import Sku
from .ranking import rank


def build_payload(catalog: list[Sku], offers: list[dict],
                  generated_at: str | None = None) -> dict:
    by_sku: dict[str, list[dict]] = {}
    for o in offers:
        by_sku.setdefault(o["sku_id"], []).append(o)
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
            "stores_tracked": len(sku_offers),
        })
    return out
