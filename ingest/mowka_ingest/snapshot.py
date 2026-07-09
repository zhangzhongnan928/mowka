"""Cron entrypoint: one full index run against the git-as-database store.

    python -m mowka_ingest.snapshot --stores stores.yaml --data-dir ../data \
        --site-out ../site-data.json
    python -m mowka_ingest.snapshot --fixture tests/fixtures/shopify_products.json \
        --data-dir /tmp/data --site-out /tmp/data.json

Steps: fetch offers -> diff against latest.json -> append change events ->
export site data.json -> queue restock alerts (flap-guarded) in the outbox.
Alerts are QUEUED here, not sent: the caller commits the data directory first,
then runs `python -m mowka_ingest.send_outbox` — so an email can never go out
before the flap-guard state that suppresses its duplicate is durable, and a
delivery outage can never block data collection or the site export.
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
    """Returns (offers, active_store_names). A store stays 'active' (retained
    in latest.json) as long as it is configured, even if this fetch failed;
    only removal from stores.yaml evicts it."""
    if args.fixture:
        payload = json.loads(pathlib.Path(args.fixture).read_text())
        offers = shopify.parse_products(payload, store="Fixture Store",
                                        base_url="https://fixture.example", catalog=catalog)
        return offers, {"Fixture Store"}
    cfg = yaml.safe_load(pathlib.Path(args.stores).read_text())
    contact = cfg.get("contact", "")
    if not contact or "example.com" in contact:
        sys.exit("stores.yaml must set a real contact email (scraping etiquette)")
    offers, active = [], set()
    for store in cfg.get("stores", []):
        # one bad store (or one malformed yaml entry) must not sink the run
        try:
            name = store.get("name") or store.get("base_url") or "<unnamed>"
            if store.get("type") != "shopify":
                print(f"skip {name}: unsupported type {store.get('type')}")
                continue
            if not store.get("base_url"):
                print(f"WARN skip {name}: missing base_url", file=sys.stderr)
                continue
            active.add(name)
            got = shopify.fetch(name, store["base_url"], catalog, contact=contact)
            print(f"{name}: {len(got)} offers")
            offers.extend(got)
        except Exception as exc:
            print(f"WARN {store}: fetch failed: {exc}", file=sys.stderr)
    return offers, active


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
    offers, active_stores = gather_offers(args, catalog)

    prev = gitstore.load_latest(args.data_dir)
    latest, events = gitstore.apply_run(prev, offers, active_stores)
    gitstore.save_run(args.data_dir, latest, events)
    print(f"{len(offers)} offers -> {len(events)} change events")

    payload = build_payload(catalog, list(latest.values()))
    site_out = pathlib.Path(args.site_out)
    site_out.parent.mkdir(parents=True, exist_ok=True)
    site_out.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"exported {len(payload['products'])} products -> {site_out}")

    restock_events = alerts.filter_flapping(gitstore.restocks(events), args.data_dir)
    if restock_events:
        history = gitstore.load_events(args.data_dir)
        medians = {e["sku_id"]: gitstore.median_30d(history, e["sku_id"], e["observed_at"])
                   for e in restock_events}
        names = {s.id: s.name for s in catalog}
        email = alerts.compose_email(restock_events, names, medians, args.site_url)
        queued = alerts.deliver(email, args.data_dir, api_key=None)  # queue only; see module docstring
        print(f"restock alert queued ({len(restock_events)} SKUs): {queued}")


if __name__ == "__main__":
    main()
