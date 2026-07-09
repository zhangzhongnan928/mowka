import argparse
import json
import pathlib
import sys

import pytest

from mowka_ingest import snapshot
from mowka_ingest.sources import shopify

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "shopify_products.json"


def run_snapshot(tmp_path, monkeypatch):
    argv = ["snapshot", "--fixture", str(FIXTURE),
            "--data-dir", str(tmp_path / "data"),
            "--site-out", str(tmp_path / "data.json")]
    monkeypatch.setattr(sys, "argv", argv)
    snapshot.main()


def test_fixture_end_to_end(tmp_path, monkeypatch):
    run_snapshot(tmp_path, monkeypatch)
    site = json.loads((tmp_path / "data.json").read_text())
    assert len(site["products"]) == 6  # full catalog, offers only where matched
    with_offers = [p for p in site["products"] if p["best"]]
    assert len(with_offers) == 3
    latest = json.loads((tmp_path / "data" / "latest.json").read_text())
    assert len(latest["offers"]) == 3
    events = (tmp_path / "data" / "events")
    assert sum(len(f.read_text().splitlines()) for f in events.glob("*.jsonl")) == 3


def test_second_run_is_quiet(tmp_path, monkeypatch):
    run_snapshot(tmp_path, monkeypatch)
    run_snapshot(tmp_path, monkeypatch)
    events = (tmp_path / "data" / "events")
    assert sum(len(f.read_text().splitlines()) for f in events.glob("*.jsonl")) == 3
    assert not (tmp_path / "data" / "alerts").exists()  # no restocks, no alerts


class StubResp:
    def __init__(self, status_code=404, text="{}", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class StubSession:
    def __init__(self, responses=None):
        self.headers = {}
        self.responses = list(responses or [])
        self.requests = []

    def get(self, url, timeout):
        self.requests.append(url)
        return self.responses.pop(0) if self.responses else StubResp()


def test_fetch_injects_contact_into_user_agent():
    s = StubSession()
    shopify.fetch("Store", "https://x.example", [], session=s,
                  contact="zhangzhongnan928@gmail.com")
    assert s.headers["User-Agent"] == (
        "MowkaAU/0.1 (+contact: zhangzhongnan928@gmail.com) price index bot")


def test_fetch_refuses_missing_or_placeholder_contact():
    for contact in (None, "", "you@example.com", "set-me-in-stores.yaml"):
        with pytest.raises(ValueError):
            shopify.fetch("Store", "https://x.example", [], session=StubSession(),
                          contact=contact)


def test_fetch_retries_429_once_honoring_retry_after(monkeypatch):
    sleeps = []
    monkeypatch.setattr(shopify.time, "sleep", sleeps.append)
    s = StubSession([StubResp(429, headers={"Retry-After": "3"}), StubResp(200, "{}")])
    shopify.fetch("Store", "https://x.example", [], session=s, contact="real@person.com")
    assert 3 in sleeps
    assert len(s.requests) == 2


def test_fetch_gives_up_on_second_429(monkeypatch):
    monkeypatch.setattr(shopify.time, "sleep", lambda _: None)
    s = StubSession([StubResp(429), StubResp(429)])
    offers = shopify.fetch("Store", "https://x.example", [], session=s,
                           contact="real@person.com")
    assert offers == [] and len(s.requests) == 2


def test_gather_offers_skips_malformed_store_entries(tmp_path, monkeypatch):
    stores = tmp_path / "stores.yaml"
    stores.write_text(
        'contact: "real@person.com"\n'
        "stores:\n"
        "  - base_url: \"https://nameless.example\"\n"       # no name: base_url stands in
        "    type: shopify\n"
        "  - name: \"No Type\"\n"                             # missing type: skipped
        "    base_url: \"https://notype.example\"\n"
        "  - name: \"No URL\"\n"                              # missing base_url: skipped
        "    type: shopify\n"
        "  - name: \"Good Store\"\n"
        "    type: shopify\n"
        "    base_url: \"https://good.example\"\n")
    fetched = []
    monkeypatch.setattr(shopify, "fetch",
                        lambda name, url, catalog, contact=None: fetched.append(name) or [])
    args = argparse.Namespace(fixture=None, stores=str(stores))
    offers, active = snapshot.gather_offers(args, [])
    assert offers == []
    assert fetched == ["https://nameless.example", "Good Store"]
    assert active == {"https://nameless.example", "Good Store"}
