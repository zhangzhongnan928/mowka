"""Git-as-database storage (the TCGdex price-history pattern).

The private data repo holds:
  data/latest.json          current best-known offer per (sku, store)
  data/events/YYYY-MM.jsonl append-only log: one line per observed CHANGE
                            (first sighting, price change, stock change)
  data/alerts/history.jsonl restock alerts already sent (flap guard)

Committing only changes keeps hourly commits tiny while preserving the full
price history. State at any moment is reconstructed by replaying events.

Retention: a (sku, store) pair absent from a run keeps its previous entry in
latest.json — a failed store fetch must not erase real observations. The site
shows observation age, so staleness is visible rather than silently dropped.
"""
import json
import pathlib
import statistics
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .models import Offer
from .ranking import rank

MIN_MEDIAN_DAYS = 7

Key = tuple[str, str]  # (sku_id, store)


def _key(o: dict) -> Key:
    return (o["sku_id"], o["store"])


def load_latest(data_dir: str | pathlib.Path) -> dict[Key, dict]:
    path = pathlib.Path(data_dir) / "latest.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    return {_key(o): o for o in payload["offers"]}


def dedupe_run(offers: list[Offer]) -> dict[Key, dict]:
    """Several listings at one store can match the same SKU (e.g. an ETB and a
    bundled variant). Keep the best per (sku, store), by the ranking rule."""
    grouped: dict[Key, list[dict]] = {}
    for offer in offers:
        o = asdict(offer)
        grouped.setdefault(_key(o), []).append(o)
    return {k: rank(v) for k, v in grouped.items()}


def apply_run(prev: dict[Key, dict], offers: list[Offer],
              active_stores: set[str] | None = None) -> tuple[dict[Key, dict], list[dict]]:
    """Merge a run's offers into the previous state.

    Returns (new_latest, events). An event records the offer plus what it
    changed from; prev_* are None on first sighting.

    active_stores: the set of store names currently configured. Shopify-store
    entries no longer configured are evicted — this is how a same-day takedown
    actually leaves the site. Scoped to source_type == "store_shopify" so the
    sealed cron never evicts marketplace offers it doesn't manage (the card
    sync prunes its own stale eBay entries before calling). None (dev paths)
    keeps everything: a transient fetch failure must never erase real
    observations.
    """
    current = dedupe_run(offers)
    latest: dict[Key, dict] = {}
    for k, v in prev.items():
        source = v.get("source_type", "store_shopify")
        if (active_stores is not None and source == "store_shopify"
                and k[1] not in active_stores):
            continue
        latest[k] = v
    events: list[dict] = []
    for key, offer in sorted(current.items()):
        old = prev.get(key)
        latest[key] = offer
        if old is None:
            events.append({**offer, "prev_price_cents": None, "prev_in_stock": None})
        elif old["price_cents"] != offer["price_cents"] or bool(old["in_stock"]) != bool(offer["in_stock"]):
            events.append({**offer,
                           "prev_price_cents": old["price_cents"],
                           "prev_in_stock": bool(old["in_stock"])})
    return latest, events


def save_run(data_dir: str | pathlib.Path, latest: dict[Key, dict], events: list[dict]) -> None:
    root = pathlib.Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    offers = [latest[k] for k in sorted(latest)]
    updated_at = max((o["observed_at"] for o in offers), default=_now_iso())
    (root / "latest.json").write_text(
        json.dumps({"updated_at": updated_at, "offers": offers}, indent=1) + "\n")
    by_month: dict[str, list[dict]] = {}
    for e in events:
        by_month.setdefault(e["observed_at"][:7], []).append(e)
    events_dir = root / "events"
    events_dir.mkdir(exist_ok=True)
    for month, batch in sorted(by_month.items()):
        with open(events_dir / f"{month}.jsonl", "a") as f:
            for e in batch:
                f.write(json.dumps(e) + "\n")


def load_events(data_dir: str | pathlib.Path) -> list[dict]:
    events_dir = pathlib.Path(data_dir) / "events"
    if not events_dir.exists():
        return []
    events: list[dict] = []
    for path in sorted(events_dir.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def restocks(events: list[dict]) -> list[dict]:
    """Alertable transitions: was out of stock, now in stock."""
    return [e for e in events if e["prev_in_stock"] is False and e["in_stock"]]


def median_30d(events: list[dict], sku_id: str, until: str) -> int | None:
    """Median of the SKU's daily best in-stock price over the 30 days ending
    at `until` (ISO 8601 UTC). Carry-forward replay: each day's value is the
    lowest in-stock price prevailing across stores at that day's cutoff.
    Returns None with fewer than MIN_MEDIAN_DAYS days of in-stock data —
    'when history allows', per spec.
    """
    sku_events = sorted((e for e in events if e["sku_id"] == sku_id),
                        key=lambda e: e["observed_at"])
    if not sku_events:
        return None
    end = datetime.fromisoformat(until)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start_day = (end - timedelta(days=29)).date()
    state: dict[str, dict] = {}
    idx = 0
    daily_best: list[int] = []
    for day_offset in range(30):
        day = start_day + timedelta(days=day_offset)
        cutoff = min(datetime.combine(day, datetime.max.time(), tzinfo=timezone.utc), end)
        while idx < len(sku_events):
            e = sku_events[idx]
            observed = datetime.fromisoformat(e["observed_at"])
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            if observed > cutoff:
                break
            state[e["store"]] = e
            idx += 1
        in_stock = [s["price_cents"] for s in state.values() if s["in_stock"]]
        if in_stock:
            daily_best.append(min(in_stock))
    if len(daily_best) < MIN_MEDIAN_DAYS:
        return None
    return round(statistics.median(daily_best))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
