# Methodology

## What Mowka tracks

Sealed Pokémon TCG product (Elite Trainer Boxes, booster boxes, bundles,
collection boxes) sold online by Australian specialty stores. Card singles are
out of scope. Prices are AUD as listed by the store; every offer links to the
store page it came from.

## How prices are collected

Tracked stores run Shopify, which publishes a structured public catalog at
`/products.json`. Mowka reads that JSON — no HTML scraping, no accounts, no
bypassing of anything. A cron ingests each store hourly.

Etiquette, enforced in code and non-negotiable:

- Identified `User-Agent` including a real contact email
- At most 1 request per second per store
- A store that asks us to stop is removed the same day
- Every published price links back to its source listing

The store target list is private (the engine is open; the dataset and target
list are the project's asset), but any store can check its own logs for the
`MowkaAU` user agent and reach us at the contact address inside it. Removing
a store from the target list also removes all of its offers from the site on
the next hourly run — a takedown request takes effect the same day.

## How listings map to SKUs

`catalog/skus.yaml` defines every tracked SKU with a permanent id and a list
of lowercase aliases. A store listing matches a SKU when its title contains an
alias (case-insensitive; the longest matching alias wins). Titles containing
an exclusion term (`psa`, `graded`, `japanese`, `empty box`, …) never match:
they are graded slabs, foreign-language variants, or empty packaging, not the
English sealed product. Both lists are public code — deliberately dumb and
auditable — see `ingest/mowka_ingest/normalize.py`.

For one SKU at one store, the offer shown is the cheapest available variant;
if no variant is available the listing counts as out of stock at its cheapest
listed price.

## The ranking rule

> **best offer = lowest price among in-stock offers; if nothing is in stock,
> lowest price overall, flagged out of stock; ties broken by most recent
> observation.**

The rule is public, verifiable code: `ingest/mowka_ingest/ranking.py::rank`.
Nothing pays to move up. Any first-party store Mowka ever operates ranks under
the same function.

## Restock alerts

An alert fires when a tracked SKU transitions out-of-stock → in-stock at a
store, at most once per 24 hours per (SKU, store) to absorb inventory
flapping. When at least 7 days of price history exist, the alert includes the
price relative to the SKU's 30-day median (median of the daily best in-stock
price). Signup is double-opt-in; unsubscribe is one click in every email.

## History

Price observations are stored as an append-only change log in a git
repository — full audit trail, reproducible at any point in time.
