"""Hard-delete every event in all 5 demo tenant mailboxes.

This is a clean-slate operation: it lists every event in every mailbox
across the next 30 days, deletes them via Graph, and then prints a final
"events remaining" count per mailbox so we can see the cleanup landed.

Usage:
    .venv/bin/python scripts/wipe_tenant_calendars.py

Safe to re-run.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values  # noqa: E402
os.environ.update({k: v for k, v in dotenv_values(ROOT / ".env").items() if v})

import httpx  # noqa: E402

from app.providers.graph_auth import GRAPH_BASE_URL, get_auth  # noqa: E402

MAILBOXES = [
    "axis-hiring-agent@Xebia192.onmicrosoft.com",
    "meera.nair@Xebia192.onmicrosoft.com",
    "suresh.kumar@Xebia192.onmicrosoft.com",
    "SiddharthGoyal@Xebia192.onmicrosoft.com",
    "rohan.desai@Xebia192.onmicrosoft.com",
]


def list_events(client: httpx.Client, upn: str) -> list[dict]:
    """Return all events on this mailbox in the next 30 days."""
    start = datetime.utcnow().isoformat() + "Z"
    end = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
    r = client.get(
        f"/users/{upn}/calendarView",
        params={
            "startDateTime": start,
            "endDateTime": end,
            "$top": "200",
            "$select": "id,subject,start,end",
        },
    )
    if r.status_code >= 300:
        print(f"  ! list failed for {upn}: HTTP {r.status_code} {r.text[:200]}")
        return []
    return r.json().get("value", []) or []


def main() -> None:
    auth = get_auth()
    headers = {**auth.auth_header(), "Content-Type": "application/json"}
    deleted_total = 0
    with httpx.Client(base_url=GRAPH_BASE_URL, headers=headers, timeout=20.0) as client:
        for upn in MAILBOXES:
            events = list_events(client, upn)
            print(f"\n▶ {upn}: found {len(events)} event(s)")
            for ev in events:
                gid = ev.get("id")
                subject = ev.get("subject", "")
                r = client.delete(f"/users/{upn}/events/{gid}")
                if r.status_code in (200, 202, 204):
                    print(f"   ✓ deleted: {subject[:70]}")
                    deleted_total += 1
                else:
                    print(f"   ✗ delete failed ({r.status_code}): {subject[:70]}")
        print(f"\n▶ Total events deleted: {deleted_total}")
        print("\n▶ Post-cleanup state:")
        for upn in MAILBOXES:
            remaining = list_events(client, upn)
            print(f"   {upn}: {len(remaining)} event(s)")


if __name__ == "__main__":
    main()
