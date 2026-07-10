# Scan → price: the spec

The scan feature's backend is **static artifacts + a resolution algorithm**,
not a server. Any frontend (web page, iOS, Android) that follows this document
produces identical results. The Python reference implementation is
`ingest/mowka_ingest/pricing.py`; run it as a CLI to check behavior:

```bash
cd ingest && python -m mowka_ingest.pricing "umbreon 161/131"
```

## Artifacts (refreshed by cron)

Canonical base URL today: **`https://zhangzhongnan928.github.io/mowka`**
(GitHub Pages origin — serves gzip with open CORS). `mowka.com` currently
points at a different deployment and does NOT serve these paths; when the
domain decision lands, this section names the new canonical base.

| Path | Refreshed | Contents |
|---|---|---|
| `/api/card-index.json` | weekly | identify index: every English card's `[tcgdex_id, localId, name]` + per-set `{id, name, official, total}`. Card data © [TCGdex](https://tcgdex.dev) — keep the `attribution` field intact wherever bundled |
| `/api/au-prices.json` | every 3h | `{prices: {tcgdex_ref: offer}}` — Mowka's tracked AU offers (stores + eBay AU when live), each with `price_cents`, `store`, `url`, `in_stock`, `observed_at`, `source_type` |
| `/api/fx.json` | every 3h | `{date, usd_aud, eur_aud, source}` — ECB reference rates via frankfurter.dev |

Live per-card USD/EUR references come straight from TCGdex in the client
(`https://api.tcgdex.net/v2/en/cards/{ref}`, CORS-open, no key):
USD = best `pricing.tcgplayer.{holofoil>normal>reverseHolofoil}.marketPrice`,
EUR = first `pricing.cardmarket.trend` (fallback `avg30`) — checking each
`variants_detailed[].pricing` first, then the card's TOP-LEVEL `pricing`
(vintage cards like `base1-4` only carry the latter).

`au-prices.json` excludes placeholder listings: a card offer priced below 20%
of its USD-converted reference (when that reference is ≥ A$20) is a sold-out
placeholder, not a price (live-verified: A$99.99 "listings" against a
US$1,528 card).

## Identify (OCR text → card)

1. Find ALL collector fractions `N/D` in the scanned text with the
   digit-bounded regex `(?<![\d/])(\d{1,3})\s*/\s*(\d{1,3})(?![\d/])`
   (reject `D = 0`). The boundaries stop dates ("12/2025") and OCR run-ons
   ("161/1311") from truncating into confident wrong answers. Modern cards
   print the fraction bottom-left/bottom-right; secret rares print `N > D` —
   that's fine.
2. For each fraction: candidate sets = sets whose `official` count equals
   `D`. Fractions matching no set (dates, HP values) contribute nothing and
   can never shadow the true fraction.
3. Candidate cards = cards in those sets whose numeric `localId` equals `N`
   (localIds are zero-padded strings — compare as integers).
4. Rank all candidates by overlap between OCR'd name tokens and the card
   name; show the user the top candidates with images and let them tap to
   confirm. Never auto-commit when more than one candidate survives.
5. No fraction found → name-token search over the index (normalized, ranked
   by token overlap) as the type-to-search fallback.

Non-numeric localIds (`TG12`, `GG70`, promo `SVP` cards without a printed
fraction) are out of the fraction path — they resolve via name search only in
v0.

## Price resolution (strict order — AUD only in the index)

1. **AU local price**: `au-prices.json.prices[ref]` if present.
   `source_type`: `au_store` (from `store_shopify`) or `au_ebay` (from
   `ebay_active`). Show the store name, link the `url`, and surface
   `in_stock` honestly (an out-of-stock AU price is still shown as AU local,
   flagged out of stock). Never convert, never mix.
2. **USD converted**: TCGplayer market × `fx.usd_aud`.
   `source_type: usd_converted`; label MUST name the source and the rate date:
   *"US market (TCGplayer), converted at ECB rate {fx.date}"*.
3. **EUR converted**: Cardmarket trend × `fx.eur_aud`.
   `source_type: eur_converted`; label mentions Cardmarket + rate date.
4. Nothing found → `source_type: none`; show "no price found", never a blank.

Converted results carry `base_amount`, `base_currency`, `fx_rate`, `fx_date`
so the UI can show the working (e.g. "US$100.00 × 1.441"). A converted price
is a **reference**, not an AU market price — the label must make that
distinction; this mirrors the sealed index's US-reference rule.

Rounding convention: cents round **half-up** (`Math.round` in JS;
`int(x * 100 + 0.5)` in Python) so every client agrees at .5 boundaries.

If the AU price artifact itself fails to load, say so — do NOT fall through
to a converted price as if the card had no AU listing; the strict order only
applies when the AU data was actually consulted.

## Collection storage (client-side, no accounts in v0)

Store scans on-device (web: `localStorage` key `mowka.collection.v1`;
apps: equivalent local store) as:

```json
[{"ref": "sv08.5-161", "added_at": "2026-07-10T02:00:00Z",
  "price_snapshot": {"aud_cents": 140000, "source_type": "au_store",
                      "source_label": "GD Games (AU local price)"}}]
```

`price_snapshot` is the resolution result at scan time (what it was worth when
you found it); current value is re-resolved on view. The schema is versioned
via the storage key — never mutate v1 in place.

## Failure behavior

- `fx.json` stale (> 7 days) → still convert, but flag the rate date in the UI.
- TCGdex unreachable → AU path still works from artifacts; conversions show
  "reference price unavailable".
- OCR gibberish → identify returns `[]`; fall through to type-to-search.
