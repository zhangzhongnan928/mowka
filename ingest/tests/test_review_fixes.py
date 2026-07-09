"""Regression tests for the adversarial-review findings."""
import json

import pytest

from mowka_ingest import db, gitstore, send_outbox
from mowka_ingest.export import build_payload
from mowka_ingest.models import Offer
from mowka_ingest.normalize import load_catalog, match
from mowka_ingest.sources.shopify import parse_products

CATALOG_PATH = str(gitstore.pathlib.Path(__file__).resolve().parents[2] / "catalog" / "skus.yaml")


def offer(sku="sv-151-etb", store="Store A", price=11995, in_stock=True,
          observed="2026-07-09T10:00:00+00:00"):
    return Offer(sku_id=sku, store=store, url=f"https://x/{sku}",
                 price_cents=price, currency="AUD", in_stock=in_stock,
                 observed_at=observed)


# --- finding 1: malformed variants must skip the variant, not kill the store

def test_null_price_available_variant_is_skipped_not_fatal():
    catalog = load_catalog(CATALOG_PATH)
    payload = {"products": [{
        "title": "Pokemon 151 ETB Elite Trainer Box",
        "handle": "151-etb",
        "variants": [{"price": None, "available": True},
                     {"price": "119.95", "available": True}],
    }]}
    offers = parse_products(payload, "S", "https://s.example", catalog)
    assert len(offers) == 1 and offers[0].price_cents == 11995


def test_missing_and_garbage_prices_are_skipped():
    catalog = load_catalog(CATALOG_PATH)
    payload = {"products": [{
        "title": "Pokemon 151 ETB Elite Trainer Box",
        "handle": "151-etb",
        "variants": [{"available": True}, {"price": "", "available": True},
                     {"price": "abc", "available": True}],
    }]}
    assert parse_products(payload, "S", "https://s.example", catalog) == []


# --- finding 8: graded singles / foreign variants must not match sealed SKUs

def test_graded_card_listing_is_excluded():
    catalog = load_catalog(CATALOG_PATH)
    # real Kollecter listing that polluted the first live run
    title = "2025 Pokemon Eevee Prismatic Evolutions Elite Trainer Box SVP-173 PSA 9"
    assert match(title, catalog) is None


def test_foreign_language_variants_are_excluded():
    catalog = load_catalog(CATALOG_PATH)
    assert match("Prismatic Evolutions Elite Trainer Box - Japanese Pokemon TCG", catalog) is None
    assert match("Surging Sparks Booster Box - Simplified Chinese", catalog) is None


def test_normal_sealed_listing_still_matches():
    catalog = load_catalog(CATALOG_PATH)
    sku = match("POKEMON TCG: Prismatic Evolutions Elite Trainer Box (Sealed)", catalog)
    assert sku and sku.id == "sv-prismatic-evolutions-etb"


# --- finding 3: takedown eviction

def test_store_removed_from_config_is_evicted():
    first, _ = gitstore.apply_run({}, [offer(store="Removed"), offer(store="Kept")])
    latest, _ = gitstore.apply_run(first, [offer(store="Kept")], active_stores={"Kept"})
    assert ("sv-151-etb", "Removed") not in latest
    assert ("sv-151-etb", "Kept") in latest


def test_configured_store_with_failed_fetch_is_retained():
    first, _ = gitstore.apply_run({}, [offer(store="Flaky"), offer(store="Kept")])
    latest, _ = gitstore.apply_run(first, [offer(store="Kept")],
                                   active_stores={"Kept", "Flaky"})
    assert ("sv-151-etb", "Flaky") in latest


# --- findings 2/5/15: sqlite path parity with the gitstore path

def test_sqlite_latest_offers_dedupes_and_uses_booleans(tmp_path):
    catalog = load_catalog(CATALOG_PATH)
    conn = db.connect(str(tmp_path / "t.db"))
    db.upsert_products(conn, catalog)
    same_second = [offer(price=12995, in_stock=True),
                   offer(price=9995, in_stock=False)]  # same (sku, store), same observed_at
    db.insert_offers(conn, same_second)
    latest = db.latest_offers(conn)
    assert len(latest) == 1
    assert latest[0]["price_cents"] == 12995  # ranked best: in stock wins
    assert latest[0]["in_stock"] is True


def test_both_paths_build_identical_payloads(tmp_path):
    catalog = load_catalog(CATALOG_PATH)
    offers = [offer(), offer(sku="sv-prismatic-evolutions-etb", store="B", price=13495)]
    conn = db.connect(str(tmp_path / "t.db"))
    db.upsert_products(conn, catalog)
    db.insert_offers(conn, offers)
    via_sqlite = build_payload(catalog, db.latest_offers(conn), generated_at="t")
    latest, _ = gitstore.apply_run({}, offers)
    via_gitstore = build_payload(catalog, list(latest.values()), generated_at="t")
    assert json.dumps(via_sqlite, sort_keys=True) == json.dumps(via_gitstore, sort_keys=True)


def test_stores_tracked_counts_distinct_stores():
    catalog = load_catalog(CATALOG_PATH)
    dupes = [{"sku_id": "sv-151-etb", "store": "A", "url": "u", "price_cents": 1,
              "currency": "AUD", "in_stock": True, "observed_at": "2026-07-09T10:00:00+00:00"}] * 2
    payload = build_payload(catalog, dupes, generated_at="t")
    etb = next(p for p in payload["products"] if p["id"] == "sv-151-etb")
    assert etb["stores_tracked"] == 1


# --- findings 10/12: queued sending

def test_send_outbox_without_key_leaves_queue(tmp_path, monkeypatch, capsys):
    outbox = tmp_path / "alerts" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "20990101T000000Z.json").write_text('{"subject": "s", "body": "b"}')
    monkeypatch.delenv("BUTTONDOWN_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["send_outbox", "--data-dir", str(tmp_path)])
    send_outbox.main()
    assert (outbox / "20990101T000000Z.json").exists()
    assert "leaving 1 queued" in capsys.readouterr().out


def test_send_outbox_sends_and_archives(tmp_path, monkeypatch):
    outbox = tmp_path / "alerts" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "20990101T000000Z.json").write_text('{"subject": "s", "body": "b"}')
    sent = []
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "k")
    monkeypatch.setattr(send_outbox.alerts, "deliver",
                        lambda email, data_dir, key: sent.append(email["subject"]))
    monkeypatch.setattr("sys.argv", ["send_outbox", "--data-dir", str(tmp_path)])
    send_outbox.main()
    assert sent == ["s"]
    assert not (outbox / "20990101T000000Z.json").exists()
    assert (outbox / "sent" / "20990101T000000Z.json").exists()


def test_send_outbox_retires_stale_alerts_unsent(tmp_path, monkeypatch):
    outbox = tmp_path / "alerts" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "20200101T000000Z.json").write_text('{"subject": "old", "body": "b"}')
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "k")
    monkeypatch.setattr(send_outbox.alerts, "deliver",
                        lambda *a: pytest.fail("stale alert must not send"))
    monkeypatch.setattr("sys.argv", ["send_outbox", "--data-dir", str(tmp_path)])
    send_outbox.main()
    assert (outbox / "sent" / "20200101T000000Z.stale.json").exists()
