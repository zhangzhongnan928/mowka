"""Kill-gate dashboard: 500 weekly visitors OR 100 alert signups by week 4.

Queries GoatCounter (visitors) and Buttondown (subscribers) and writes a
one-page markdown dashboard. Both integrations are optional: without tokens
the script still writes the dashboard, marking the metric "not configured".

Env:
  GOATCOUNTER_SITE       e.g. "mowka" (-> mowka.goatcounter.com)
  GOATCOUNTER_API_TOKEN  GoatCounter Settings -> API tokens (read access)
  BUTTONDOWN_API_KEY     Buttondown Settings -> API

Usage: python scripts/kill_gate.py [output.md]
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

VISITOR_GATE = 500   # weekly visitors
SIGNUP_GATE = 100    # alert subscribers


def weekly_visitors() -> int | None:
    site = os.environ.get("GOATCOUNTER_SITE")
    token = os.environ.get("GOATCOUNTER_API_TOKEN")
    if not site or not token:
        return None
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    resp = requests.get(
        f"https://{site}.goatcounter.com/api/v0/stats/total",
        params={"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    for key in ("total_utc", "total"):  # API surface differs across versions
        if isinstance(payload.get(key), int):
            return payload[key]
    raise ValueError(f"unrecognized GoatCounter response keys: {sorted(payload)}")


def subscriber_count() -> int | None:
    key = os.environ.get("BUTTONDOWN_API_KEY")
    if not key:
        return None
    resp = requests.get(
        "https://api.buttondown.com/v1/subscribers",
        params={"type": "regular"},
        headers={"Authorization": f"Token {key}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("count")


def fmt(value: int | None, gate: int, label: str) -> str:
    if value is None:
        return f"| {label} | not configured | {gate} | — |"
    status = "✅ PASSED" if value >= gate else f"{value / gate:.0%} of gate"
    return f"| {label} | {value} | {gate} | {status} |"


def main() -> None:
    out_path = sys.argv[1] if len(sys.argv) > 1 else "KILLGATE.md"
    visitors = weekly_visitors()
    subscribers = subscriber_count()
    passed = (visitors is not None and visitors >= VISITOR_GATE) or (
        subscribers is not None and subscribers >= SIGNUP_GATE)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Mowka kill gate",
        "",
        f"Gate: **{VISITOR_GATE} weekly visitors OR {SIGNUP_GATE} alert signups by end of week 4 after launch.**",
        f"Status as of {now}: {'**GATE PASSED** 🎉' if passed else 'not yet passed'}",
        "",
        "| Metric | Current | Gate | Progress |",
        "|---|---|---|---|",
        fmt(visitors, VISITOR_GATE, "Weekly visitors (GoatCounter, last 7d)"),
        fmt(subscribers, SIGNUP_GATE, "Alert subscribers (Buttondown)"),
        "",
    ]
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
