import json
import pathlib

from mowka_ingest import db
from mowka_ingest.normalize import load_catalog, match
from mowka_ingest.sources.shopify import parse_products

ROOT = pathlib.Path(__file__).resolve().parents[2]
CATALOG = ROOT / "catalog" / "skus.yaml"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "shopify_products.json"


def test_alias_match_longest_wins():
    catalog = load_catalog(CATALOG)
    sku = match("POKEMON TCG: Prismatic Evolutions Elite Trainer Box (Sealed)", catalog)
    assert sku and sku.id == "sv-prismatic-evolutions-etb"


def test_no_match_returns_none():
    catalog = load_catalog(CATALOG)
    assert match("Dragon Shield Matte Sleeves - Black", catalog) is None


def test_parse_products_maps_stock_and_price():
    catalog = load_catalog(CATALOG)
    payload = json.loads(FIXTURE.read_text())
    offers = parse_products(payload, "Fixture Store", "https://fixture.example", catalog)
    by_sku = {o.sku_id: o for o in offers}
    assert len(offers) == 3  # sleeves ignored
    etb = by_sku["sv-prismatic-evolutions-etb"]
    assert etb.in_stock and etb.price_cents == 13495  # cheapest AVAILABLE variant
    ss = by_sku["sv-surging-sparks-booster-box"]
    assert not ss.in_stock and ss.price_cents == 28900


def test_end_to_end_db_roundtrip(tmp_path):
    catalog = load_catalog(CATALOG)
    conn = db.connect(str(tmp_path / "t.db"))
    db.upsert_products(conn, catalog)
    payload = json.loads(FIXTURE.read_text())
    db.insert_offers(conn, parse_products(payload, "Fixture Store", "https://fixture.example", catalog))
    latest = db.latest_offers(conn)
    assert len(latest) == 3
