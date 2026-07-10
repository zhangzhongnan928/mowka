"""Scan-to-price resolution: identify + fallback chain (docs/SCAN_PRICING.md)."""
import pathlib
import sys

import pytest

from mowka_ingest import pricing
from mowka_ingest.cardcatalog import CardInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))

INDEX = {
    "sets": [
        {"id": "sv08.5", "name": "Prismatic Evolutions", "official": 131, "total": 180},
        {"id": "sv03.5", "name": "151", "official": 165, "total": 207},
        {"id": "xx01", "name": "Fake Twin", "official": 131, "total": 131},
    ],
    "cards": [
        ["sv08.5-161", "161", "Umbreon ex"],
        ["sv08.5-060", "060", "Umbreon ex"],
        ["sv03.5-161", "161", "Zapdos"],
        ["xx01-161", "161", "Pidgey"],
        ["sv03.5-199", "199", "Charizard ex"],
    ],
}

FX = {"date": "2026-07-09", "usd_aud": 1.441, "eur_aud": 1.68,
      "source": "ECB reference rates via frankfurter.dev", "fetched_at": "t"}


def info(usd=None, eur=None):
    return CardInfo(ref="sv08.5-161", name="Umbreon ex", set_name="Prismatic Evolutions",
                    set_code="sv08.5", number="161", image_url=None,
                    usd_market=usd, source_url="https://api.tcgdex.net/v2/en/cards/sv08.5-161",
                    eur_market=eur)


# --- fraction parsing ---------------------------------------------------------

def test_parse_fraction_variants():
    assert pricing.parse_fraction("161/131") == (161, 131)
    assert pricing.parse_fraction("Umbreon ex 161 / 131 SIR") == (161, 131)
    assert pricing.parse_fraction("064/198") == (64, 198)
    assert pricing.parse_fraction("no numbers here") is None
    assert pricing.parse_fraction("1/0") is None  # zero denominator implausible


def test_parse_fraction_rejects_embedded_digit_runs():
    assert pricing.parse_fraction("12/2025") is None       # a date, not a card
    assert pricing.parse_fraction("161/1311") is None      # OCR run-on
    assert pricing.parse_fraction("1234/165") is None      # OCR run-on numerator
    assert pricing.parse_fractions("12/2025 umbreon 161/131") == [(161, 131)]


def test_identify_date_noise_cannot_shadow_real_fraction():
    # even a plausible-looking noise fraction contributes nothing when its
    # denominator matches no set; the real fraction still identifies
    got = pricing.identify("07/25 umbreon 161/131", INDEX)
    assert got[0]["id"] == "sv08.5-161"


# --- identify -----------------------------------------------------------------

def test_identify_by_fraction_unique_set():
    got = pricing.identify("199/165", INDEX)
    assert [c["id"] for c in got] == ["sv03.5-199"]


def test_identify_fraction_collision_ranked_by_name_tokens():
    got = pricing.identify("umbreon 161/131", INDEX)
    assert got[0]["id"] == "sv08.5-161"          # name token breaks the tie
    assert {c["id"] for c in got} == {"sv08.5-161", "xx01-161"}


def test_identify_fraction_collision_without_name_returns_both():
    got = pricing.identify("161/131", INDEX)
    assert {c["id"] for c in got} == {"sv08.5-161", "xx01-161"}


def test_identify_name_only_fallback():
    got = pricing.identify("umbreon", INDEX)
    assert {c["id"] for c in got} == {"sv08.5-161", "sv08.5-060"}


def test_identify_no_match():
    assert pricing.identify("charmander 999/999", INDEX) == []


def test_identify_zero_padded_local_id():
    idx = {"sets": [{"id": "sv08", "name": "Surging Sparks", "official": 191, "total": 252}],
           "cards": [["sv08-064", "064", "Milotic ex"]]}
    got = pricing.identify("64/191", idx)
    assert got and got[0]["id"] == "sv08-064"


# --- price resolution chain ----------------------------------------------------

AU = {"sv08.5-161": {"price_cents": 140000, "store": "GD Games",
                     "url": "https://gd/x", "in_stock": True,
                     "observed_at": "2026-07-09T10:00:00+00:00",
                     "source_type": "store_shopify"}}


def test_au_local_price_wins_over_conversions():
    got = pricing.resolve_price("sv08.5-161", AU, info(usd=1528.09, eur=972.02), FX)
    assert got["aud_cents"] == 140000
    assert got["source_type"] == "au_store"
    assert got["source_url"] == "https://gd/x"
    assert got["converted"] is False


def test_au_ebay_source_labeled():
    au = {"r": {**AU["sv08.5-161"], "source_type": "ebay_active", "store": "eBay AU"}}
    got = pricing.resolve_price("r", au, None, FX)
    assert got["source_type"] == "au_ebay"
    assert "eBay AU" in got["source_label"]


def test_usd_conversion_when_no_au():
    got = pricing.resolve_price("sv08.5-161", {}, info(usd=100.0, eur=90.0), FX)
    assert got["aud_cents"] == 14410              # 100 * 1.441 * 100
    assert got["source_type"] == "usd_converted"
    assert got["converted"] is True
    assert got["fx_rate"] == 1.441 and got["base_currency"] == "USD"
    assert "TCGplayer" in got["source_label"] and "2026-07-09" in got["source_label"]


def test_eur_conversion_when_no_usd():
    got = pricing.resolve_price("sv08.5-161", {}, info(usd=None, eur=90.0), FX)
    assert got["aud_cents"] == 15120              # 90 * 1.68 * 100
    assert got["source_type"] == "eur_converted"
    assert "Cardmarket" in got["source_label"]


def test_no_price_anywhere():
    got = pricing.resolve_price("sv08.5-161", {}, info(), FX)
    assert got["aud_cents"] is None and got["source_type"] == "none"


def test_no_conversion_without_fx():
    got = pricing.resolve_price("sv08.5-161", {}, info(usd=100.0), None)
    assert got["aud_cents"] is None and got["source_type"] == "none"


def test_out_of_stock_au_price_still_au_but_flagged():
    au = {"r": {**AU["sv08.5-161"], "in_stock": False}}
    got = pricing.resolve_price("r", au, info(usd=100.0), FX)
    assert got["source_type"] == "au_store" and got["in_stock"] is False


# --- fx fetch ----------------------------------------------------------------

def test_fetch_fx_single_call_inverts_aud_base(monkeypatch):
    calls = []

    class Resp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"base": "AUD", "date": "2026-07-09",
                    "rates": {"USD": 0.5, "EUR": 0.625}}

    class S:
        headers = {}
        def get(self, url, params=None, timeout=None):
            calls.append(params)
            return Resp()

    fx = pricing.fetch_fx(session=S())
    assert len(calls) == 1                      # one request = one shared date
    assert fx["usd_aud"] == 2.0 and fx["eur_aud"] == 1.6
    assert fx["date"] == "2026-07-09" and "ECB" in fx["source"]


def test_index_build_refuses_partial_output():
    from build_card_index import safe_to_write
    full = {"cards": [[str(i), str(i), "x"] for i in range(100)]}
    ok, _ = safe_to_write(full, skipped=0, previous=None)
    assert ok
    ok, reason = safe_to_write(full, skipped=3, previous=None)
    assert not ok and "3 set fetches failed" in reason
    shrunken = {"cards": full["cards"][:80]}
    ok, reason = safe_to_write(shrunken, skipped=0, previous=full)
    assert not ok and "dropped" in reason
    slightly_smaller = {"cards": full["cards"][:97]}
    ok, _ = safe_to_write(slightly_smaller, skipped=0, previous=full)
    assert ok


def test_cli_answers_from_artifacts_when_network_is_down(tmp_path, monkeypatch, capsys):
    import json as jsonlib
    import sys as syslib
    (tmp_path / "index.json").write_text(jsonlib.dumps(INDEX))
    (tmp_path / "au.json").write_text(jsonlib.dumps({"prices": AU}))
    (tmp_path / "fx.json").write_text(jsonlib.dumps(FX))

    def down(*a, **k):
        raise pricing.requests.ConnectionError("network down")

    monkeypatch.setattr(pricing, "get_adapter",
                        lambda name: type("A", (), {"card": staticmethod(down)})())
    monkeypatch.setattr(pricing, "fetch_fx", down)
    monkeypatch.setattr(syslib, "argv",
                        ["pricing", "umbreon 161/131",
                         "--index", str(tmp_path / "index.json"),
                         "--au-prices", str(tmp_path / "au.json"),
                         "--fx", str(tmp_path / "fx.json")])
    pricing.main()
    out = jsonlib.loads(capsys.readouterr().out)
    assert out["price"]["aud_cents"] == 140000
    assert out["price"]["source_type"] == "au_store"
