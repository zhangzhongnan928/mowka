"""Pipeline entrypoint.

Live mode:     python -m mowka_ingest.run --stores stores.yaml
Fixture mode:  python -m mowka_ingest.run --fixture tests/fixtures/shopify_products.json
Fixture mode exists so anyone can run the full pipeline offline in 5 seconds.
"""
import argparse
import json
import pathlib

import yaml

from . import db
from .normalize import load_catalog
from .sources import shopify

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / "catalog" / "skus.yaml"
DEFAULT_DB = ROOT / "mowka.db"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--stores", default=None, help="stores.yaml for live fetch")
    ap.add_argument("--fixture", default=None, help="local products.json for offline demo")
    args = ap.parse_args()

    catalog = load_catalog(args.catalog)
    conn = db.connect(args.db)
    db.upsert_products(conn, catalog)

    offers = []
    if args.fixture:
        payload = json.loads(pathlib.Path(args.fixture).read_text())
        offers = shopify.parse_products(payload, store="Fixture Store",
                                        base_url="https://fixture.example", catalog=catalog)
    elif args.stores:
        cfg = yaml.safe_load(pathlib.Path(args.stores).read_text())
        for store in cfg.get("stores", []):
            name = store.get("name") or store.get("base_url") or "<unnamed>"
            if store.get("type") != "shopify":
                print(f"skip {name}: unsupported type {store.get('type')}")
                continue
            got = shopify.fetch(name, store["base_url"], catalog,
                                contact=cfg.get("contact"))
            print(f"{name}: {len(got)} offers")
            offers.extend(got)
    else:
        ap.error("provide --stores or --fixture")

    db.insert_offers(conn, offers)
    print(f"wrote {len(offers)} offers -> {args.db}")


if __name__ == "__main__":
    main()
