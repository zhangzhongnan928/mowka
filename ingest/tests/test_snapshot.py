import json
import pathlib
import sys

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


class StubSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, timeout):
        class Resp:
            status_code = 404
            text = "{}"
        return Resp()


def test_fetch_injects_contact_into_user_agent():
    s = StubSession()
    shopify.fetch("Store", "https://x.example", [], session=s,
                  contact="zhangzhongnan928@gmail.com")
    assert s.headers["User-Agent"] == (
        "MowkaAU/0.1 (+contact: zhangzhongnan928@gmail.com) price index bot")


def test_fetch_without_contact_uses_placeholder():
    s = StubSession()
    shopify.fetch("Store", "https://x.example", [], session=s)
    assert "set-me-in-stores.yaml" in s.headers["User-Agent"]
