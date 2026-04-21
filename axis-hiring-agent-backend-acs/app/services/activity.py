"""Unified activity feed.

Merges four streams into one chronological list:
  1. AgentEvent audit entries written on each application
  2. Emails (sent + received) from the MessagingProvider
  3. Notifications from the MessagingProvider
  4. Calendar events from the CalendarProvider

The frontend polls ``/activity?application_id=...`` to render the "Agent
working" panel.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..models import ActivityItem
from ..providers import get_calendar_provider, get_messaging_provider
from ..store import STORE


def build_activity_feed(
    application_id: Optional[str] = None,
    limit: int = 200,
) -> List[ActivityItem]:
    items: List[ActivityItem] = []

    # ---- Agent events from application audit trails -----------------------
    apps = (
        [STORE.get_application(application_id)] if application_id
        else STORE.list_applications()
    )
    for app in apps:
        if not app:
            continue
        for i, ev in enumerate(app.events):
            kind = "checklist" if "Checklist" in ev.message else "agent"
            items.append(
                ActivityItem(
                    id=f"{app.id}-ev-{i}",
                    at=ev.at,
                    kind=kind,  # type: ignore[arg-type]
                    title=f"{ev.actor.replace('_', ' ').title()}",
                    detail=ev.message,
                    application_id=app.id,
                    meta={"level": ev.level},
                )
            )

    # ---- Emails -----------------------------------------------------------
    try:
        emails = get_messaging_provider().list_emails(application_id=application_id)
    except NotImplementedError:
        emails = []
    for e in emails:
        items.append(
            ActivityItem(
                id=f"email-{e.id}",
                at=e.at,
                kind="email_out" if e.direction == "out" else "email_in",
                title=e.subject,
                detail=_short(e.body, 280),
                application_id=e.application_id,
                meta={"to": e.to, "from": e.from_addr, "thread_id": e.thread_id},
            )
        )

    # ---- Notifications ----------------------------------------------------
    try:
        notes = get_messaging_provider().list_notifications()
    except NotImplementedError:
        notes = []
    for n in notes:
        if application_id and n.application_id != application_id:
            continue
        items.append(
            ActivityItem(
                id=f"note-{n.id}",
                at=n.at,
                kind="notification",
                title=f"Notification → {n.to}",
                detail=n.message,
                application_id=n.application_id,
                meta={"to": n.to, "jd_id": n.jd_id},
            )
        )

    # ---- Calendar events ---------------------------------------------------
    try:
        events = get_calendar_provider().list_events(application_id=application_id)
    except NotImplementedError:
        events = []
    for ev in events:
        items.append(
            ActivityItem(
                id=f"cal-{ev.id}",
                at=ev.start,
                kind="calendar",
                title=ev.subject,
                detail=(
                    f"{ev.start.strftime('%a %d %b %H:%M')} – "
                    f"{ev.end.strftime('%H:%M')} · "
                    f"{len(ev.attendees)} attendees"
                ),
                application_id=ev.application_id,
                meta={
                    "teams_join_url": ev.teams_join_url,
                    "organiser": ev.organiser_id,
                    "attendees": ev.attendees,
                    "cancelled": ev.cancelled,
                    "start": ev.start.isoformat(),
                    "end": ev.end.isoformat(),
                },
            )
        )

    items.sort(key=lambda x: x.at, reverse=True)
    return items[:limit]


def _short(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"
