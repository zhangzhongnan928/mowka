# Mowka

Free, open-source price index for sealed Pokémon TCG product in Australia.
One page, AUD prices, live stock, restock alerts. Built by collectors, for collectors and stores.

## Why

Sealed product is supply-constrained and AU prices are scattered across dozens of stores.
Nobody publishes a neutral AUD reference. We do, and the ranking rule is public code:

> **best offer = lowest in-stock price; if nothing is in stock, lowest price flagged out of stock;
> ties broken by freshest observation.**
> Nothing pays to move up. Any first-party store we ever run ranks under the same function.
> See `ingest/mowka_ingest/ranking.py::rank` and [docs/METHODOLOGY.md](docs/METHODOLOGY.md).

## Open / closed line (read before contributing)

| Public (this repo)                     | Private (never in this repo)         |
|----------------------------------------|--------------------------------------|
| Site, ranking rule, schema, engine     | `stores.yaml` target list            |
| SKU catalog (`catalog/skus.yaml`)      | The accumulated price database       |
| Fixtures and tests                     | Alert subscriber list                |

The engine is open so the ranking is verifiable. The dataset is the project's asset.
The private side lives in a separate data repo whose hourly GitHub Actions cron runs
`mowka_ingest.snapshot` and commits each run's changes — git is the database.

## Quickstart (offline, 60 seconds)

```bash
cd ingest && pip install -r requirements.txt
python -m mowka_ingest.run --fixture tests/fixtures/shopify_products.json
cd .. && python scripts/export_site.py
cd site && python -m http.server 8080   # open http://localhost:8080
```

## Live mode

```bash
cp ingest/stores.example.yaml ingest/stores.yaml   # fill in real stores + contact email
cd ingest && python -m mowka_ingest.snapshot --stores stores.yaml \
    --data-dir /path/to/data --site-out ../site/data.json
```

`--data-dir` is the git-as-database directory (in production, the private data
repo): `latest.json` current state, `events/YYYY-MM.jsonl` append-only change
log, `alerts/` restock-alert history and outbox. Restock alerts send via
Buttondown when `BUTTONDOWN_API_KEY` is set, otherwise they land in the outbox.

`mowka_ingest.run` + `scripts/export_site.py` remain as the SQLite local/dev path.

## Scraping etiquette (hard rules)

Identified User-Agent with a real contact email (from `stores.yaml`, enforced).
Max 1 request/second per store. A store asks us to stop: we stop and remove them
the same day. We link every price to its source.

## Kill gate

500 weekly visitors OR 100 restock-alert signups by end of week 4 after launch.
Instrumented with GoatCounter (privacy-friendly, no cookies) + Buttondown;
`scripts/kill_gate.py` renders the dashboard.

## Card lane (beta)

Mowka's long-term core: AUD prices for every card, starting with a curated
chase list (`catalog/cards.yaml`, Simon's Top-200). Card identity comes from an
external catalog behind the `mowka_ingest/cardcatalog` adapter (TCGdex first —
single-maintainer insurance). AU prices come from store listings (same ingest)
plus eBay AU active listings (`mowka_ingest/sources/ebay.py`, dormant until an
eBay keyset is configured). `mowka_ingest.card_sync` builds `site/cards.json`;
the same `rank()` picks the cheapest available. USD reference is display-only.

## Roadmap

1. **Now:** sealed index + restock alerts (kill gate above) + card lane beta.
2. Phone scan app: identify card → price → collection tracker (also the future sorter brain).
3. UGC price reports, reputation-weighted. Points ledger, token-convertible schema, no token at launch.
4. Commerce, ranked by the same public rule.
5. Sorting hardware.

## Tests

```bash
cd ingest && python -m pytest -q
```

## License

Recommended: **AGPL-3.0** for the engine and site (closed-source clones of the service must open their changes);
catalog data in this repo under CC BY-SA 4.0. MIT is the friendlier-to-contributors alternative; decide before first release.
