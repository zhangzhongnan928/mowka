"""Card lane: chase-list integrity, alias collisions, eBay parsing, card_sync."""
import json
import pathlib
import sys

import pytest

from mowka_ingest import card_sync, gitstore
from mowka_ingest.cardcatalog import CardInfo
from mowka_ingest.models import Offer
from mowka_ingest.normalize import load_catalog, match
from mowka_ingest.sources import ebay

ROOT = pathlib.Path(__file__).resolve().parents[2]
CARDS = str(ROOT / "catalog" / "cards.yaml")
SEALED = str(ROOT / "catalog" / "skus.yaml")


def cards():
    return load_catalog(CARDS)


# --- chase list integrity ----------------------------------------------------

def test_chase_list_parses_all_card_kind():
    cs = cards()
    assert len(cs) >= 10
    assert all(c.kind == "card" for c in cs)
    assert all(c.catalog_ref and c.set_code and c.number for c in cs)
    ids = [c.id for c in cs]
    assert len(ids) == len(set(ids))


def test_card_aliases_do_not_collide_with_sealed_aliases():
    sealed_aliases = {a for s in load_catalog(SEALED) for a in s.aliases}
    card_aliases = {a for c in cards() for a in c.aliases}
    assert not sealed_aliases & card_aliases


# --- alias matching: same Pokémon across sets, punctuation, exclusions -------

def test_number_qualified_alias_matches_listing_title():
    sku = match("Pokemon TCG Umbreon ex - 161/131 - Prismatic Evolutions SIR NM", cards())
    assert sku and sku.id == "card-sv08.5-161"


def test_same_pokemon_different_set_number_does_not_cross_match():
    combined = cards()
    hit_151 = match("Pokemon 151 Charizard ex 199/165 Special Illustration Rare", combined)
    hit_fates = match("Paldean Fates Charizard ex 234/091 Shiny", combined)
    assert hit_151 and hit_151.id == "card-sv03.5-199"
    assert hit_fates and hit_fates.id == "card-sv04.5-234"
    assert match("Charizard ex 006/165", combined) is None  # base slot: not tracked


def test_graded_and_foreign_card_listings_never_match():
    assert match("Umbreon ex 161/131 Prismatic Evolutions PSA 10", cards()) is None
    assert match("Umbreon ex 161/131 Japanese Terastal Festival", cards()) is None


def test_combined_catalog_keeps_sealed_and_card_matching_separate():
    combined = load_catalog(SEALED) + cards()
    etb = match("POKEMON TCG: Prismatic Evolutions Elite Trainer Box", combined)
    single = match("Umbreon ex 161/131 Prismatic Evolutions", combined)
    assert etb and etb.kind == "sealed"
    assert single and single.kind == "card"


# --- eBay source --------------------------------------------------------------

class StubResp:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class StubSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(kwargs)
        return StubResp(self.payload)


EBAY_PAYLOAD = {"itemSummaries": [
    {"title": "Umbreon ex 161/131 Prismatic Evolutions PSA 10 GEM",  # graded: excluded
     "price": {"value": "700.00", "currency": "AUD"}, "itemWebUrl": "https://ebay/psa"},
    {"title": "Pokemon Umbreon ex 161/131 Prismatic Evolutions NM",
     "price": {"value": "1450.00", "currency": "AUD"}, "itemWebUrl": "https://ebay/a"},
    {"title": "Umbreon ex - 161/131 SV Prismatic Evolutions",
     "price": {"value": "1399.95", "currency": "AUD"}, "itemWebUrl": "https://ebay/b"},
    {"title": "Umbreon VMAX 215/203 Evolving Skies",                 # different card
     "price": {"value": "900.00", "currency": "AUD"}, "itemWebUrl": "https://ebay/c"},
]}


def umbreon():
    return next(c for c in cards() if c.id == "card-sv08.5-161")


def test_search_card_picks_cheapest_matching_ungraded():
    offer, count = ebay.search_card(umbreon(), "tok", session=StubSession(EBAY_PAYLOAD))
    assert count == 2
    assert offer.price_cents == 139995 and offer.url == "https://ebay/b"
    assert offer.source_type == "ebay_active" and offer.store == "eBay AU"


def test_search_card_no_matches_returns_none():
    offer, count = ebay.search_card(umbreon(), "tok",
                                    session=StubSession({"itemSummaries": []}))
    assert offer is None and count == 0


def test_fetch_cards_respects_call_budget(monkeypatch):
    monkeypatch.setattr(ebay, "get_token", lambda *a, **k: "tok")
    monkeypatch.setattr(ebay.time, "sleep", lambda _: None)
    searched_cards = []
    monkeypatch.setattr(ebay, "search_card",
                        lambda card, token, session=None: (searched_cards.append(card.id), (None, 0))[1])
    offers, counts, searched = ebay.fetch_cards(cards(), "id", "secret", max_calls=3)
    assert len(searched) == 3 and searched_cards == searched


# --- card_sync ----------------------------------------------------------------

FAKE_INFO = CardInfo(ref="x", name="N", set_name="S", set_code="sc", number="1",
                     image_url="https://img/x/low.webp", usd_market=123.45,
                     source_url="https://api/x")


class FakeAdapter:
    def card(self, ref):
        return CardInfo(ref=ref, name="N", set_name="S", set_code="sc", number="1",
                        image_url="https://img/x/low.webp", usd_market=123.45,
                        source_url="https://api/x")


def run_card_sync(tmp_path, monkeypatch, env_keys=False):
    monkeypatch.setattr(card_sync, "get_adapter", lambda name="tcgdex": FakeAdapter())
    monkeypatch.setattr(card_sync.time, "sleep", lambda _: None)
    if env_keys:
        monkeypatch.setenv("EBAY_CLIENT_ID", "k")
        monkeypatch.setenv("EBAY_CLIENT_SECRET", "k")
    else:
        monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
        monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(sys, "argv", ["card_sync", "--data-dir", str(tmp_path / "data"),
                                      "--site-out", str(tmp_path / "cards.json")])
    card_sync.main()
    return json.loads((tmp_path / "cards.json").read_text())


def test_card_sync_offline_builds_catalog_and_export(tmp_path, monkeypatch):
    payload = run_card_sync(tmp_path, monkeypatch)
    assert len(payload["cards"]) == len(cards())
    first = payload["cards"][0]
    assert first["usd_reference"] == 123.45
    assert first["image"] == "https://img/x/low.webp"
    assert first["best"] is None and first["offers"] == []
    cache = json.loads((tmp_path / "data" / "cards" / "catalog.json").read_text())
    assert len(cache) == len(cards())


def test_card_sync_surfaces_store_single_offers(tmp_path, monkeypatch):
    store_offer = Offer(sku_id="card-sv08.5-161", store="GD Games", url="https://x",
                        price_cents=140000, currency="AUD", in_stock=True,
                        observed_at="2026-07-09T10:00:00+00:00")
    latest, events = gitstore.apply_run({}, [store_offer])
    gitstore.save_run(tmp_path / "data", latest, events)
    payload = run_card_sync(tmp_path, monkeypatch)
    umb = next(c for c in payload["cards"] if c["id"] == "card-sv08.5-161")
    assert umb["best"]["store"] == "GD Games"
    assert umb["best"]["price_cents"] == 140000


def test_card_sync_prunes_only_researched_ebay_offers(tmp_path, monkeypatch):
    def seed(sku, price):
        return Offer(sku_id=sku, store="eBay AU", url="https://e", price_cents=price,
                     currency="AUD", in_stock=True,
                     observed_at="2026-07-09T09:00:00+00:00", source_type="ebay_active")
    latest, events = gitstore.apply_run({}, [seed("card-sv08.5-161", 100000),
                                             seed("card-sv03.5-199", 50000)])
    gitstore.save_run(tmp_path / "data", latest, events)
    # this run only re-searches umbreon and finds nothing -> its stale offer goes,
    # charizard (not searched: budget) keeps its offer
    monkeypatch.setattr(card_sync.ebay, "fetch_cards",
                        lambda *a, **k: ([], {"card-sv08.5-161": 0}, ["card-sv08.5-161"]))
    payload = run_card_sync(tmp_path, monkeypatch, env_keys=True)
    umb = next(c for c in payload["cards"] if c["id"] == "card-sv08.5-161")
    zard = next(c for c in payload["cards"] if c["id"] == "card-sv03.5-199")
    assert umb["best"] is None
    assert zard["best"]["price_cents"] == 50000
    assert umb["active_count"] == 0


# --- sealed lane untouched ----------------------------------------------------

def test_sealed_export_excludes_card_offers(tmp_path, monkeypatch):
    from mowka_ingest import snapshot
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"products": [
        {"title": "Pokemon Umbreon ex 161/131 Prismatic Evolutions NM",
         "handle": "umbreon", "variants": [{"price": "1400.00", "available": True}]},
        {"title": "Pokemon 151 ETB Elite Trainer Box",
         "handle": "151-etb", "variants": [{"price": "119.95", "available": True}]},
    ]}))
    monkeypatch.setattr(sys, "argv", ["snapshot", "--fixture", str(fixture),
                                      "--data-dir", str(tmp_path / "data"),
                                      "--site-out", str(tmp_path / "data.json")])
    snapshot.main()
    site = json.loads((tmp_path / "data.json").read_text())
    assert all(p["id"].startswith(("sv-", "me-")) for p in site["products"])
    # ...but the card offer IS captured in the shared data store for the card lane
    latest = gitstore.load_latest(tmp_path / "data")
    assert ("card-sv08.5-161", "Fixture Store") in latest


def test_card_restock_does_not_queue_sealed_alert(tmp_path, monkeypatch):
    from mowka_ingest import snapshot
    oos_card = Offer(sku_id="card-sv08.5-161", store="Fixture Store",
                     url="https://fixture.example/products/umbreon",
                     price_cents=140000, currency="AUD", in_stock=False,
                     observed_at="2026-07-08T10:00:00+00:00")
    latest, events = gitstore.apply_run({}, [oos_card])
    gitstore.save_run(tmp_path / "data", latest, events)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"products": [
        {"title": "Pokemon Umbreon ex 161/131 Prismatic Evolutions NM",
         "handle": "umbreon", "variants": [{"price": "1400.00", "available": True}]},
    ]}))
    monkeypatch.setattr(sys, "argv", ["snapshot", "--fixture", str(fixture),
                                      "--data-dir", str(tmp_path / "data"),
                                      "--site-out", str(tmp_path / "data.json")])
    snapshot.main()
    events_now = gitstore.load_events(tmp_path / "data")
    assert any(e["sku_id"] == "card-sv08.5-161" and gitstore.restocks([e]) for e in events_now)
    assert not (tmp_path / "data" / "alerts" / "outbox").exists()
