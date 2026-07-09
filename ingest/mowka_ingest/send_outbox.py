"""Send queued restock alerts. Runs AFTER the data commit is pushed, so the
flap-guard state suppressing a duplicate is durable before any email leaves.

    BUTTONDOWN_API_KEY=... python -m mowka_ingest.send_outbox --data-dir ../data

Without the key this is a no-op (queue stays for the next run). Restocks are
time-sensitive: queued emails older than MAX_AGE_HOURS are retired unsent
rather than delivered stale. Sent and retired emails move to outbox/sent/.
"""
import argparse
import os
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import requests

from . import alerts

MAX_AGE_HOURS = 6


def _queued_at(path: pathlib.Path) -> datetime | None:
    try:
        return datetime.strptime(path.stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    outbox = pathlib.Path(args.data_dir) / "alerts" / "outbox"
    queue = sorted(p for p in outbox.glob("*.json")) if outbox.exists() else []
    if not queue:
        print("outbox empty")
        return
    api_key = os.environ.get("BUTTONDOWN_API_KEY")
    if not api_key:
        print(f"BUTTONDOWN_API_KEY not set; leaving {len(queue)} queued email(s)")
        return
    sent_dir = outbox / "sent"
    sent_dir.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    for path in queue:
        queued_at = _queued_at(path)
        if queued_at and now - queued_at > timedelta(hours=MAX_AGE_HOURS):
            path.rename(sent_dir / f"{path.stem}.stale.json")
            print(f"retired stale alert unsent: {path.name}")
            continue
        try:
            alerts.deliver(json.loads(path.read_text()), args.data_dir, api_key)
        except requests.RequestException as exc:
            # Buttondown outage: leave the queue intact, next run retries
            print(f"WARN delivery failed, will retry next run: {exc}", file=sys.stderr)
            break
        path.rename(sent_dir / path.name)
        print(f"sent {path.name}")


if __name__ == "__main__":
    main()
