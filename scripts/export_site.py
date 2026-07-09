"""Build site/data.json from the local SQLite db (local/dev path).

THE RANKING RULE is public, verifiable code: ingest/mowka_ingest/ranking.py::rank
  best offer = lowest price among in-stock offers;
  if nothing is in stock, lowest price overall, flagged out of stock;
  ties broken by most recent observation.
The cron path (mowka_ingest.snapshot) uses the same rank() and payload builder.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

from mowka_ingest import db  # noqa: E402
from mowka_ingest.export import build_payload  # noqa: E402
from mowka_ingest.normalize import load_catalog  # noqa: E402


def main(db_path: str, out_path: str) -> None:
    catalog = load_catalog(str(ROOT / "catalog" / "skus.yaml"))
    conn = db.connect(db_path)
    payload = build_payload(catalog, db.latest_offers(conn))
    pathlib.Path(out_path).write_text(json.dumps(payload, indent=1) + "\n")
    print(f"exported {len(payload['products'])} products -> {out_path}")


if __name__ == "__main__":
    main(str(ROOT / "mowka.db"), str(ROOT / "site" / "data.json"))
