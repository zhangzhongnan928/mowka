"""Cron entrypoint: one full index run against the git-as-database store.

    python -m mowka_ingest.snapshot --stores stores.yaml --data-dir ../data \
        --site-out ../site-data.json
    python -m mowka_ingest.snapshot --fixture tests/fixtures/shopify_products.json \
        --data-dir /tmp/data --site-out /tmp/data.json

Steps: fetch offers -> diff against latest.json -> append change events ->
detect restocks (flap-guarded) -> deliver alert email (Buttondown or outbox)
-> export site data.json. Designed to run inside GitHub Actions; the caller
commits the data directory afterwards.
"""
import argparse
import json
import os
import pathlib
import sys

import yaml

from . import alerts, gitstore
from .export import build_payload
from .normalize import load_catalog
from .sources import shopify

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_SITE_URL = "https://mowka.com"


def gather_offers(args, catalog):
    if args.fixture:
        payload = json.loads(pathlib.Path(args.fixture).read_text())
        return shopify.parse_products(payload, store="Fixture Store",
                                      base_url="https://fixture.example", catalog=catalog)
    cfg = yaml.safe_load(pathlib.Path(args.stores).read_text())
    contact = cfg.get("contact", "")
    if not contact or "example.com" in contact:
        sys.exit("stores.yaml must set a real contact email (scraping etiquette)")
    offers = []
    for store in cfg["stores"]:
        if store.get("type") != "shopify":
            print(f"skip {store['name']}: unsupported type {store.get('type')}")
            continue
        try:
            got = shopify.fetch(store["name"], store["base_url"], catalog, contact=contact)
            print(f"{store['name']}: {len(got)} offers")
            offers.extend(got)
        except Exception as exc:  # one bad store must not sink the run
            print(f"WARN {store['name']}: fetch failed: {exc}", file=sys.stderr)
    return offers


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=str(ROOT / "catalog" / "skus.yaml"))
    ap.add_argument("--stores", default=None)
    ap.add_argument("--fixture", default=None)
    ap.add_argument("--data-dir", required=True, help="private data repo's data/ dir")
    ap.add_argument("--site-out", required=True, help="where to write site data.json")
    ap.add_argument("--site-url", default=os.environ.get("MOWKA_SITE_URL", DEFAULT_SITE_URL))
    args = ap.parse_args()
    if not args.stores and not args.fixture:
        ap.error("provide --stores or --fixture")

    catalog = load_catalog(args.catalog)
    offers = gather_offers(args, catalog)

    prev = gitstore.load_latest(args.data_dir)
    latest, events = gitstore.apply_run(prev, offers)
    gitstore.save_run(args.data_dir, latest, events)
    print(f"{len(offers)} offers -> {len(events)} change events")

    restock_events = alerts.filter_flapping(gitstore.restocks(events), args.data_dir)
    if restock_events:
        history = gitstore.load_events(args.data_dir)
        medians = {e["sku_id"]: gitstore.median_30d(history, e["sku_id"], e["observed_at"])
                   for e in restock_events}
        names = {s.id: s.name for s in catalog}
        email = alerts.compose_email(restock_events, names, medians, args.site_url)
        result = alerts.deliver(email, args.data_dir, os.environ.get("BUTTONDOWN_API_KEY"))
        print(f"restock alert ({len(restock_events)} SKUs): {result}")

    payload = build_payload(catalog, list(latest.values()))
    site_out = pathlib.Path(args.site_out)
    site_out.parent.mkdir(parents=True, exist_ok=True)
    site_out.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"exported {len(payload['products'])} products -> {site_out}")


if __name__ == "__main__":
    main()
