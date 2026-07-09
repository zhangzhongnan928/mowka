# Mowka

Free, open-source AUD price index for Pokémon TCG in Australia — **every card
and sealed product**. Live stock, restock alerts, honest prices. Built by
collectors, for collectors and stores.

The sealed index with restock alerts is the acquisition wedge and ships first;
card-level pricing (beta, `site/cards.html`) is the platform's core long-term
asset.

## Why

Sealed product is supply-constrained and AU prices are scattered across dozens
of stores; card prices barely exist in AUD outside USD-mirror charts. Nobody
publishes a neutral AUD reference for either. We do, and the ranking rule is
public code:

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
log, `alerts/` restock-alert history and outbox. The snapshot only QUEUES
restock alerts (to `alerts/outbox/`); delivery is a separate step so an email
can never leave before its flap-guard state is committed:

```bash
BUTTONDOWN_API_KEY=... python -m mowka_ingest.send_outbox --data-dir /path/to/data
```

Without the key, `send_outbox` is a no-op and the queue survives for the next
run; queued alerts older than 6 hours are retired unsent (restocks are
time-sensitive).

`mowka_ingest.run` + `scripts/export_site.py` remain as the SQLite local/dev path.

## Scraping etiquette (hard rules)

Identified User-Agent with a real contact email (from `stores.yaml`, enforced).
Max 1 request/second per store. A store asks us to stop: we stop and remove them
the same day. We link every price to its source.

## Kill gate

500 weekly visitors OR 100 restock-alert signups by end of week 4 after launch.
Instrumented with GoatCounter (privacy-friendly, no cookies) + Buttondown;
`scripts/kill_gate.py` renders the dashboard, which also tracks weekly card
lookups/searches as the card-lane retention metric (no gate threshold).

## Card lane (beta)

Mowka's long-term core: AUD prices for every card, starting with a draft
14-card sample chase list (`catalog/cards.yaml`) that Simon's curated Top-200
replaces wholesale before card ids freeze. Card identity comes from an
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
