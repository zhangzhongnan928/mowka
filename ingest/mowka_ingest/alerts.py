"""Restock alerts.

Trigger: a tracked SKU transitions out-of-stock -> in-stock (gitstore.restocks).
Each alert includes price vs the SKU's 30-day median when history allows.

Delivery is Buttondown (subscribers, double-opt-in, and one-click unsubscribe
all live provider-side). Without BUTTONDOWN_API_KEY the email is written to
data/alerts/outbox/ instead, so the pipeline is fully testable offline and
nothing is lost before the provider is wired.

Flap guard: a (sku, store) pair that restocks repeatedly (stock flapping,
inventory glitches) alerts at most once per FLAP_WINDOW_HOURS. Sent alerts
are recorded in data/alerts/history.jsonl.
"""
import json
import pathlib
from datetime import datetime, timedelta, timezone

import requests

FLAP_WINDOW_HOURS = 24
BUTTONDOWN_EMAILS_URL = "https://api.buttondown.com/v1/emails"


def _parse(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def filter_flapping(restock_events: list[dict], data_dir: str | pathlib.Path) -> list[dict]:
    """Drop restocks already alerted within FLAP_WINDOW_HOURS; record survivors."""
    history_path = pathlib.Path(data_dir) / "alerts" / "history.jsonl"
    history: dict[tuple[str, str], datetime] = {}
    if history_path.exists():
        for line in history_path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                history[(rec["sku_id"], rec["store"])] = _parse(rec["alerted_at"])
    window = timedelta(hours=FLAP_WINDOW_HOURS)
    kept: list[dict] = []
    for e in restock_events:
        last = history.get((e["sku_id"], e["store"]))
        if last is None or _parse(e["observed_at"]) - last >= window:
            kept.append(e)
    if kept:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(history_path, "a") as f:
            for e in kept:
                f.write(json.dumps({"sku_id": e["sku_id"], "store": e["store"],
                                    "alerted_at": e["observed_at"]}) + "\n")
    return kept


def _aud(cents: int) -> str:
    return f"A${cents / 100:,.2f}"


def _median_line(price_cents: int, median_cents: int | None) -> str:
    if median_cents is None:
        return "no 30-day history yet"
    if median_cents == 0:
        return f"30-day median {_aud(median_cents)}"
    delta = (price_cents - median_cents) / median_cents * 100
    if abs(delta) < 0.5:
        return f"at its 30-day median ({_aud(median_cents)})"
    direction = "below" if delta < 0 else "above"
    return f"{abs(delta):.0f}% {direction} its 30-day median ({_aud(median_cents)})"


def compose_email(restock_events: list[dict], names: dict[str, str],
                  medians: dict[str, int | None], site_url: str) -> dict:
    """Build {subject, body} markdown for one run's restocks."""
    lines = []
    for e in restock_events:
        name = names.get(e["sku_id"], e["sku_id"])
        lines.append(f"- **{name}** is back in stock at [{e['store']}]({e['url']}) — "
                     f"{_aud(e['price_cents'])}, {_median_line(e['price_cents'], medians.get(e['sku_id']))}")
    first_name = names.get(restock_events[0]["sku_id"], restock_events[0]["sku_id"])
    subject = (f"Restock: {first_name} — {_aud(restock_events[0]['price_cents'])}"
               if len(restock_events) == 1
               else f"Restocks: {len(restock_events)} tracked SKUs are back in stock")
    body = ("Tracked sealed product just came back in stock:\n\n"
            + "\n".join(lines)
            + f"\n\nFull index: {site_url}\n\n"
            "Prices belong to the stores that set them; every offer links to its source.\n")
    return {"subject": subject, "body": body}


def deliver(email: dict, data_dir: str | pathlib.Path, api_key: str | None) -> str:
    """Send via Buttondown when a key is present; otherwise write to the outbox.
    Returns 'sent' or the outbox path."""
    if api_key:
        resp = requests.post(
            BUTTONDOWN_EMAILS_URL,
            headers={"Authorization": f"Token {api_key}"},
            json={"subject": email["subject"], "body": email["body"],
                  "status": "about_to_send"},
            timeout=30,
        )
        resp.raise_for_status()
        return "sent"
    outbox = pathlib.Path(data_dir) / "alerts" / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = outbox / f"{stamp}.json"
    path.write_text(json.dumps(email, indent=1) + "\n")
    return str(path)
