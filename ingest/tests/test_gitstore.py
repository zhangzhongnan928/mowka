import json

from mowka_ingest import gitstore
from mowka_ingest.models import Offer


def offer(sku="sv-151-etb", store="Store A", price=11995, in_stock=True,
          observed="2026-07-09T10:00:00+00:00"):
    return Offer(sku_id=sku, store=store, url=f"https://x/{sku}",
                 price_cents=price, currency="AUD", in_stock=in_stock,
                 observed_at=observed)


def event(sku="sv-151-etb", store="Store A", price=11995, in_stock=True,
          observed="2026-07-09T10:00:00+00:00", prev_price=None, prev_stock=None):
    return {"sku_id": sku, "store": store, "url": "u", "price_cents": price,
            "currency": "AUD", "in_stock": in_stock, "observed_at": observed,
            "prev_price_cents": prev_price, "prev_in_stock": prev_stock}


def test_first_run_emits_first_sighting_events():
    latest, events = gitstore.apply_run({}, [offer()])
    assert len(latest) == 1 and len(events) == 1
    assert events[0]["prev_price_cents"] is None
    assert events[0]["prev_in_stock"] is None


def test_unchanged_run_emits_no_events_but_refreshes_observation():
    first, _ = gitstore.apply_run({}, [offer(observed="2026-07-09T10:00:00+00:00")])
    latest, events = gitstore.apply_run(first, [offer(observed="2026-07-09T11:00:00+00:00")])
    assert events == []
    assert latest[("sv-151-etb", "Store A")]["observed_at"] == "2026-07-09T11:00:00+00:00"


def test_price_change_event_carries_previous_price():
    first, _ = gitstore.apply_run({}, [offer(price=11995)])
    _, events = gitstore.apply_run(first, [offer(price=10995)])
    assert len(events) == 1
    assert events[0]["prev_price_cents"] == 11995
    assert events[0]["price_cents"] == 10995


def test_stock_flip_event_and_restock_detection():
    first, _ = gitstore.apply_run({}, [offer(in_stock=False)])
    _, events = gitstore.apply_run(first, [offer(in_stock=True)])
    assert gitstore.restocks(events) == events
    # first sightings and price-only changes are not restocks
    _, first_events = gitstore.apply_run({}, [offer()])
    assert gitstore.restocks(first_events) == []


def test_missing_store_keeps_previous_observation():
    first, _ = gitstore.apply_run({}, [offer(store="Store A"), offer(store="Store B")])
    latest, events = gitstore.apply_run(first, [offer(store="Store A")])
    assert ("sv-151-etb", "Store B") in latest
    assert events == []


def test_dedupe_same_store_same_sku_keeps_ranked_best():
    dupes = [offer(price=12995, in_stock=True), offer(price=9995, in_stock=False)]
    latest, events = gitstore.apply_run({}, dupes)
    assert len(latest) == 1
    assert latest[("sv-151-etb", "Store A")]["price_cents"] == 12995  # in-stock wins


def test_save_and_load_roundtrip(tmp_path):
    latest, events = gitstore.apply_run({}, [offer()])
    gitstore.save_run(tmp_path, latest, events)
    assert gitstore.load_latest(tmp_path) == latest
    stored = gitstore.load_events(tmp_path)
    assert stored == events
    # events append across runs into the month file
    latest2, events2 = gitstore.apply_run(latest, [offer(price=9995)])
    gitstore.save_run(tmp_path, latest2, events2)
    assert len(gitstore.load_events(tmp_path)) == 2
    month_file = tmp_path / "events" / "2026-07.jsonl"
    assert len(month_file.read_text().splitlines()) == 2


def test_load_latest_missing_dir_is_empty(tmp_path):
    assert gitstore.load_latest(tmp_path / "nope") == {}
    assert gitstore.load_events(tmp_path / "nope") == []


def test_median_requires_seven_days_of_history():
    events = [event(observed="2026-07-07T10:00:00+00:00")]
    assert gitstore.median_30d(events, "sv-151-etb", "2026-07-09T10:00:00+00:00") is None


def test_median_carry_forward_daily_best():
    # price 10000 for 9 days, drops to 8000 on the last day -> median 10000
    events = [event(price=10000, observed="2026-06-30T10:00:00+00:00"),
              event(price=8000, observed="2026-07-09T09:00:00+00:00", prev_price=10000)]
    assert gitstore.median_30d(events, "sv-151-etb", "2026-07-09T10:00:00+00:00") == 10000


def test_median_ignores_out_of_stock_days():
    # in stock 5 days then OOS: only 5 daily samples -> below MIN_MEDIAN_DAYS
    events = [event(price=10000, observed="2026-07-01T10:00:00+00:00"),
              event(price=10000, in_stock=False, observed="2026-07-05T10:00:00+00:00",
                    prev_price=10000, prev_stock=True)]
    assert gitstore.median_30d(events, "sv-151-etb", "2026-07-20T10:00:00+00:00") is None


def test_median_uses_lowest_across_stores():
    events = [event(store="A", price=10000, observed="2026-07-01T10:00:00+00:00"),
              event(store="B", price=9000, observed="2026-07-01T11:00:00+00:00")]
    assert gitstore.median_30d(events, "sv-151-etb", "2026-07-09T10:00:00+00:00") == 9000


def test_median_only_counts_matching_sku():
    events = [event(sku="other", price=1000, observed="2026-07-01T10:00:00+00:00")]
    assert gitstore.median_30d(events, "sv-151-etb", "2026-07-09T10:00:00+00:00") is None


def test_latest_json_is_sorted_and_valid(tmp_path):
    latest, events = gitstore.apply_run({}, [offer(store="Zeta"), offer(store="Alpha")])
    gitstore.save_run(tmp_path, latest, events)
    payload = json.loads((tmp_path / "latest.json").read_text())
    stores = [o["store"] for o in payload["offers"]]
    assert stores == sorted(stores)
    assert "updated_at" in payload
