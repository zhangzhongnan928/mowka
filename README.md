# Mowka

Free, open-source price index for sealed Pokémon TCG product in Australia.
One page, AUD prices, live stock, restock alerts. Built by collectors, for collectors and stores.

**Working name.** Rename is a find-and-replace; the SKU ids are the only thing that must stay stable.

## Why

Sealed product is supply-constrained and AU prices are scattered across dozens of stores.
Nobody publishes a neutral AUD reference. We do, and the ranking rule is public code:

> **best offer = lowest in-stock price; ties broken by freshest observation.**
> Nothing pays to move up. Any first-party store we ever run ranks under the same function.
> See `scripts/export_site.py::rank`.

## Open / closed line (read before contributing)

| Public (this repo)                     | Private (never in this repo)         |
|----------------------------------------|--------------------------------------|
| Site, ranking rule, schema, engine     | `ingest/stores.yaml` target list     |
| SKU catalog (`catalog/skus.yaml`)      | The accumulated price database       |
| Fixtures and tests                     | Alert subscriber list                |

The engine is open so the ranking is verifiable. The dataset is the project's asset.

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
cd ingest && python -m mowka_ingest.run --stores stores.yaml
cd .. && python scripts/export_site.py
```

Run on a cron (hourly is plenty). Deploy `site/` anywhere static: Vercel, Cloudflare Pages, S3.

## Scraping etiquette (hard rules)

Identified User-Agent with a contact email. Max 1 request/second per store.
A store asks us to stop: we stop and remove them the same day. We link every price to its source.

## Roadmap

1. **Now:** sealed index + restock alerts. Kill gate: 500 weekly visitors or 100 alert signups by week 4.
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
