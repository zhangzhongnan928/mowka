import json

from mowka_ingest import alerts


def restock(sku="sv-151-etb", store="Store A", price=11995,
            observed="2026-07-09T10:00:00+00:00"):
    return {"sku_id": sku, "store": store, "url": f"https://x/{sku}",
            "price_cents": price, "currency": "AUD", "in_stock": True,
            "observed_at": observed, "prev_price_cents": price, "prev_in_stock": False}


def test_flap_guard_suppresses_within_window(tmp_path):
    first = alerts.filter_flapping([restock(observed="2026-07-09T10:00:00+00:00")], tmp_path)
    assert len(first) == 1
    again = alerts.filter_flapping([restock(observed="2026-07-09T13:00:00+00:00")], tmp_path)
    assert again == []


def test_flap_guard_allows_after_window(tmp_path):
    alerts.filter_flapping([restock(observed="2026-07-09T10:00:00+00:00")], tmp_path)
    later = alerts.filter_flapping([restock(observed="2026-07-10T11:00:00+00:00")], tmp_path)
    assert len(later) == 1


def test_flap_guard_is_per_sku_store_pair(tmp_path):
    alerts.filter_flapping([restock(store="Store A")], tmp_path)
    other = alerts.filter_flapping([restock(store="Store B")], tmp_path)
    assert len(other) == 1


def test_compose_single_restock_with_median():
    email = alerts.compose_email([restock(price=13495)], {"sv-151-etb": "151 Elite Trainer Box"},
                                 {"sv-151-etb": 14200}, "https://mowka.com")
    assert email["subject"] == "Restock: 151 Elite Trainer Box — A$134.95"
    assert "5% below its 30-day median (A$142.00)" in email["body"]
    assert "https://x/sv-151-etb" in email["body"]


def test_compose_without_history_says_so():
    email = alerts.compose_email([restock()], {}, {}, "https://mowka.com")
    assert "no 30-day history yet" in email["body"]


def test_compose_multiple_restocks_subject_counts():
    events = [restock(sku="a"), restock(sku="b")]
    email = alerts.compose_email(events, {}, {}, "https://mowka.com")
    assert email["subject"] == "Restocks: 2 tracked SKUs are back in stock"
    assert email["body"].count("back in stock at") == 2


def test_compose_above_median_direction():
    email = alerts.compose_email([restock(price=15000)], {}, {"sv-151-etb": 14200},
                                 "https://mowka.com")
    assert "above its 30-day median" in email["body"]


def test_deliver_without_key_writes_outbox(tmp_path):
    email = {"subject": "s", "body": "b"}
    result = alerts.deliver(email, tmp_path, api_key=None)
    outbox = list((tmp_path / "alerts" / "outbox").glob("*.json"))
    assert len(outbox) == 1 and str(outbox[0]) == result
    assert json.loads(outbox[0].read_text())["subject"] == "s"
