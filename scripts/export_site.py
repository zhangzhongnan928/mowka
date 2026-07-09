"""Build site/data.json from the SQLite db.

THE RANKING RULE (public, verifiable, no exceptions):
  best offer = lowest price among in-stock offers;
  if nothing is in stock, lowest price overall, flagged out of stock;
  ties broken by most recent observation.
Any first-party store we ever operate ranks under this same function.
"""
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

from mowka_ingest import db  # noqa: E402


def rank(offers: list[dict]) -> dict | None:
    if not offers:
        return None
    in_stock = [o for o in offers if o["in_stock"]]
    pool = in_stock or offers
    return sorted(pool, key=lambda o: (o["price_cents"], o["observed_at"]))[0] if pool else None


def main(db_path: str, out_path: str) -> None:
    conn = db.connect(db_path)
    products = conn.execute("SELECT id, name, set_name, category FROM products").fetchall()
    offers = db.latest_offers(conn)
    by_sku: dict[str, list[dict]] = {}
    for o in offers:
        by_sku.setdefault(o["sku_id"], []).append(o)

    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "products": []}
    for pid, name, set_name, category in products:
        sku_offers = sorted(by_sku.get(pid, []), key=lambda o: o["price_cents"])
        best = rank(sku_offers)
        out["products"].append({
            "id": pid, "name": name, "set": set_name, "category": category,
            "best": best, "offers": sku_offers, "stores_tracked": len(sku_offers),
        })
    pathlib.Path(out_path).write_text(json.dumps(out, indent=1))
    print(f"exported {len(out['products'])} products -> {out_path}")


if __name__ == "__main__":
    main(str(ROOT / "mowka.db"), str(ROOT / "site" / "data.json"))
