"""Real Microsoft Graph CalendarProvider.

Activated by:

    AXIS_CALENDAR_PROVIDER=graph
    AXIS_GRAPH_TENANT_ID=<tenant uuid>
    AXIS_GRAPH_CLIENT_ID=<app registration client id>
    AXIS_GRAPH_CLIENT_SECRET=<client secret value>
    AXIS_GRAPH_ORGANISER_UPN=<upn of the mailbox that hosts meetings>
    AXIS_GRAPH_TIMEZONE=Asia/Kolkata   # optional, default Asia/Kolkata

Endpoints used:

    POST   /v1.0/users/{upn}/calendar/getSchedule    — free/busy
    POST   /v1.0/users/{upn}/onlineMeetings          — create Teams link
    POST   /v1.0/users/{upn}/events                  — book calendar event
    GET    /v1.0/users/{upn}/events                  — list events
    PATCH  /v1.0/users/{upn}/events/{id}             — reschedule
    DELETE /v1.0/users/{upn}/events/{id}             — cancel

Application permissions required (already granted for this tenant):
    Calendars.ReadWrite, OnlineMeetings.ReadWrite.All, User.Read.All,
    MailboxSettings.Read

Notes on "organiser" semantics
------------------------------
With application permissions, the hiring agent books every meeting as the
service mailbox (``AXIS_GRAPH_ORGANISER_UPN``) regardless of which
``organiser_id`` the caller passes. The ``organiser_id`` argument is kept
in the Protocol for compatibility but is only used as a hint — the actual
organiser on Graph is always the service mailbox. Attendees are passed
through as-is.

Free/busy intersection
----------------------
Graph's ``getSchedule`` returns per-user busy blocks. We do the intersection
locally using the same working-hours + weekend-skipping logic as the mock,
so the behaviour is identical across both providers.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
from uuid import uuid4

import httpx

from ..models import CalendarEventView, TimeSlot
from .graph_auth import GRAPH_BASE_URL, get_auth

log = logging.getLogger(__name__)


class GraphCalendarError(RuntimeError):
    """Any non-2xx response from Graph during a calendar operation."""


# ---------------------------------------------------------------------------
# Local free/busy helpers (identical semantics to the mock)
# ---------------------------------------------------------------------------


def _working_window(day: datetime, start_hour: int, end_hour: int) -> TimeSlot:
    day_start = datetime.combine(day.date(), time(start_hour))
    day_end = datetime.combine(day.date(), time(end_hour))
    return TimeSlot(start=day_start, end=day_end)


def _subtract(busy: List[TimeSlot], window: TimeSlot) -> List[TimeSlot]:
    free = [window]
    for b in sorted(busy, key=lambda s: s.start):
        new_free: List[TimeSlot] = []
        for f in free:
            if not f.overlaps(b):
                new_free.append(f)
                continue
            if b.start > f.start:
                new_free.append(TimeSlot(start=f.start, end=min(b.start, f.end)))
            if b.end < f.end:
                new_free.append(TimeSlot(start=max(b.end, f.start), end=f.end))
        free = [s for s in new_free if s.end > s.start]
    return free


def _stub_busy_blocks(
    upn: str,
    window_start: datetime,
    window_end: datetime,
) -> List[TimeSlot]:
    """Deterministic synthetic busy blocks for a `@stub.local` mailbox.

    BUG-013 fix: stubs used to return an empty busy list ("always free"),
    which meant every panel composition produced the *same* slot preview
    on the HR R2 approval card — masking the fact that real Graph
    free/busy was happening on the real attendees. We now seed each stub
    with two deterministic weekday busy windows derived from the UPN, so
    different panel rosters produce *visibly different* candidate slots
    while still being completely offline.

    The pattern is intentionally simple: hash the UPN to pick a "morning
    busy hour" in [09, 13) and an "afternoon busy hour" in [13, 17), and
    block 60 minutes in each on every weekday in the window.
    """
    import hashlib

    h = int(hashlib.sha1(upn.encode("utf-8")).hexdigest(), 16)
    morning_hour = 9 + (h % 4)              # 09, 10, 11, 12
    afternoon_hour = 13 + ((h >> 4) % 4)    # 13, 14, 15, 16

    blocks: List[TimeSlot] = []
    day = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < window_end:
        if day.weekday() < 5:  # Mon–Fri
            m_start = day.replace(hour=morning_hour)
            blocks.append(TimeSlot(start=m_start, end=m_start + timedelta(hours=1)))
            a_start = day.replace(hour=afternoon_hour)
            blocks.append(TimeSlot(start=a_start, end=a_start + timedelta(hours=1)))
        day += timedelta(days=1)
    return blocks


def _intersect(a: List[TimeSlot], b: List[TimeSlot]) -> List[TimeSlot]:
    out: List[TimeSlot] = []
    for x in a:
        for y in b:
            start = max(x.start, y.start)
            end = min(x.end, y.end)
            if end > start:
                out.append(TimeSlot(start=start, end=end))
    return out


# ---------------------------------------------------------------------------
# Graph wire-format helpers
# ---------------------------------------------------------------------------


def _to_graph_dt(dt: datetime, tz: str) -> dict:
    """Graph wants ``{'dateTime': '2026-04-06T15:00:00', 'timeZone': 'Asia/Kolkata'}``."""
    return {"dateTime": dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz}


def _from_graph_dt(block: dict) -> datetime:
    """Graph returns ``{'dateTime': '2026-04-06T15:00:00.0000000', 'timeZone': 'UTC'}``."""
    raw = (block or {}).get("dateTime") or ""
    # Trim fractional seconds beyond microsecond precision that Python can't parse.
    if "." in raw:
        head, frac = raw.split(".", 1)
        raw = f"{head}.{frac[:6]}"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.utcnow()


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


class GraphCalendarProvider:
    """CalendarProvider implemented against live Microsoft Graph."""

    def __init__(self) -> None:
        self.organiser_upn = os.getenv("AXIS_GRAPH_ORGANISER_UPN", "").strip()
        self.timezone = os.getenv("AXIS_GRAPH_TIMEZONE", "Asia/Kolkata")
        if not self.organiser_upn:
            raise RuntimeError(
                "GraphCalendarProvider requires AXIS_GRAPH_ORGANISER_UPN — the UPN of "
                "the mailbox that hosts meetings (e.g. axis-hiring-agent@tenant.onmicrosoft.com)."
            )
        # Touch the auth helper so config problems surface at construction time.
        get_auth()
        # Track events we have created so list_events can return them directly
        # (faster than GET /events on every call, and already filtered to our app).
        self._known_event_ids: Dict[str, str] = {}  # graph_event_id -> application_id

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    def _client(self, prefer_timezone: bool = False) -> httpx.Client:
        headers = {
            **get_auth().auth_header(),
            "Content-Type": "application/json",
        }
        if prefer_timezone:
            # Ask Graph to render every dateTime in the response in our
            # configured timezone instead of UTC. Used by getSchedule so the
            # busy-block intersection lines up with the IST working hours.
            headers["Prefer"] = f'outlook.timezone="{self.timezone}"'
        return httpx.Client(
            base_url=GRAPH_BASE_URL,
            headers=headers,
            timeout=20.0,
        )

    @staticmethod
    def _raise_for_status(r: httpx.Response, op: str) -> None:
        if r.status_code >= 300:
            raise GraphCalendarError(
                f"Graph {op} failed: HTTP {r.status_code} — {r.text[:600]}"
            )

    # ------------------------------------------------------------------
    # Public API — CalendarProvider Protocol
    # ------------------------------------------------------------------

    def get_free_busy(
        self,
        user_ids: List[str],
        window_start: datetime,
        window_end: datetime,
    ) -> Dict[str, List[TimeSlot]]:
        if window_end <= window_start:
            raise ValueError("window_end must be after window_start")
        if not user_ids:
            return {}

        # Synthetic ("stub") panel members live alongside the real tenant
        # mailboxes in graph mode (see fixtures.GRAPH_STUB_*). They have
        # plausible names but `@stub.local` UPNs and obviously do not exist
        # on the real tenant — sending them to Graph either errors or
        # returns nothing useful. Treat them as "always free" by initialising
        # an empty busy list locally and skipping the Graph call for them.
        real_user_ids = [u for u in user_ids if not u.lower().endswith("@stub.local")]
        stub_user_ids = [u for u in user_ids if u.lower().endswith("@stub.local")]
        out: Dict[str, List[TimeSlot]] = {
            uid: _stub_busy_blocks(uid, window_start, window_end)
            for uid in stub_user_ids
        }
        if not real_user_ids:
            return out

        # Graph getSchedule is mailbox-scoped — we call it against the organiser
        # mailbox but can look up any attendee's free/busy across the tenant.
        #
        # IMPORTANT: by default Graph returns scheduleItems in UTC, while the
        # rest of our orchestrator builds working-hours windows as naive IST
        # datetimes. If we don't align them, busy blocks at "09:00 IST" come
        # back as "03:30 UTC", never overlap with the [09:00, 18:00] window,
        # and the agent happily proposes slots that collide with existing
        # tentative meetings on the candidate's calendar. The
        # `Prefer: outlook.timezone` header tells Graph to render dateTimes
        # in the requested zone, so we get busy blocks back as "09:00 IST"
        # (naive) and the intersection works.
        url = f"/users/{self.organiser_upn}/calendar/getSchedule"
        body = {
            "schedules": real_user_ids,
            "startTime": _to_graph_dt(window_start, self.timezone),
            "endTime": _to_graph_dt(window_end, self.timezone),
            "availabilityViewInterval": 30,
        }
        with self._client(prefer_timezone=True) as client:
            r = client.post(url, json=body)
        self._raise_for_status(r, "getSchedule")

        for uid in real_user_ids:
            out[uid] = []
        for sched in r.json().get("value", []):
            uid = sched.get("scheduleId")
            if uid not in out:
                # Graph may return the canonical-cased UPN — try case-insensitive match.
                match = next((u for u in real_user_ids if u.lower() == (uid or "").lower()), None)
                if match is None:
                    continue
                uid = match
            for item in sched.get("scheduleItems", []) or []:
                # Busy states we treat as blocked: "busy", "oof", "tentative"
                status = (item.get("status") or "").lower()
                if status == "free":
                    continue
                start = _from_graph_dt(item.get("start") or {})
                end = _from_graph_dt(item.get("end") or {})
                if end > start:
                    out[uid].append(TimeSlot(start=start, end=end))
        return out

    def find_common_slots(
        self,
        user_ids: List[str],
        duration_min: int,
        window_start: datetime,
        window_end: datetime,
        working_hours: tuple = (9, 18),
        top_n: int = 3,
    ) -> List[TimeSlot]:
        if not user_ids:
            raise ValueError("user_ids required")

        busy = self.get_free_busy(user_ids, window_start, window_end)

        day = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
        days: List[datetime] = []
        while day < window_end:
            days.append(day)
            day += timedelta(days=1)

        free_by_user: List[List[TimeSlot]] = []
        for uid in user_ids:
            user_free: List[TimeSlot] = []
            user_busy = busy.get(uid, [])
            for d in days:
                if d.weekday() >= 5:  # skip Sat/Sun
                    continue
                win = _working_window(d, *working_hours)
                user_free.extend(_subtract(user_busy, win))
            free_by_user.append(user_free)

        common = free_by_user[0]
        for nxt in free_by_user[1:]:
            common = _intersect(common, nxt)

        chosen: List[TimeSlot] = []
        for slot in sorted(common, key=lambda s: s.start):
            if (slot.end - slot.start).total_seconds() / 60 >= duration_min:
                chosen.append(
                    TimeSlot(start=slot.start, end=slot.start + timedelta(minutes=duration_min))
                )
                if len(chosen) >= top_n:
                    break
        return chosen

    def create_teams_meeting(
        self,
        subject: str,
        start: datetime,
        end: datetime,
        organiser_id: str,  # noqa: ARG002 — kept for Protocol compatibility
        attendees: List[str],
        body: str = "",
        application_id: Optional[str] = None,
    ) -> CalendarEventView:
        if end <= start:
            raise ValueError("meeting end must be after start")

        # Filter out placeholder / non-routable attendee addresses before
        # handing the list to Graph. Fixture panellists live under
        # ``@stub.local`` (and similar unreachable domains) because they
        # don't have real mailboxes in the Xebia192 tenant. Microsoft Graph
        # will either reject the whole event or, worse, silently skip
        # sending invitations to the VALID attendees (the candidate, HR)
        # when any invalid address is in the list. We keep the stubs in our
        # audit log for demo fidelity but strip them here so real
        # attendees always receive their calendar invite.
        def _is_routable(addr: str) -> bool:
            a = (addr or "").strip().lower()
            if "@" not in a:
                return False
            domain = a.split("@", 1)[1]
            # Reject obvious placeholders: .local, .test, .example, localhost
            if domain.endswith(".local") or domain.endswith(".test") or domain.endswith(".example") or domain == "localhost":
                return False
            if domain.startswith("stub.") or domain.startswith("example."):
                return False
            return True

        routable_attendees = [a for a in attendees if _is_routable(a)]
        dropped = [a for a in attendees if not _is_routable(a)]
        if dropped:
            log.info(
                "create_teams_meeting: dropping %d non-routable attendee(s) from Graph invite: %s",
                len(dropped),
                dropped,
            )

        # Create the calendar event with isOnlineMeeting=true so Graph
        # auto-provisions the Teams meeting as part of event creation.
        # This avoids the separate POST /onlineMeetings call which requires
        # an Application Access Policy configured via PowerShell.
        event_body = {
            "subject": subject,
            "start": _to_graph_dt(start, self.timezone),
            "end": _to_graph_dt(end, self.timezone),
            "body": {
                "contentType": "HTML",
                "content": (body or "").replace("\n", "<br>"),
            },
            "organizer": {
                "emailAddress": {
                    "address": self.organiser_upn,
                    "name": self.organiser_upn.split("@")[0],
                }
            },
            "attendees": [
                {
                    "emailAddress": {"address": addr, "name": addr.split("@")[0]},
                    "type": "required",
                }
                for addr in routable_attendees
            ],
            "isOnlineMeeting": True,
            "onlineMeetingProvider": "teamsForBusiness",
            # Stash our application id in the singleValueExtendedProperties
            # so we can filter events back to the application later.
            **(
                {
                    "singleValueExtendedProperties": [
                        {
                            "id": "String {00020329-0000-0000-C000-000000000046} Name AxisAppId",
                            "value": application_id,
                        }
                    ]
                }
                if application_id
                else {}
            ),
        }
        with self._client() as client:
            r = client.post(
                f"/users/{self.organiser_upn}/events",
                json=event_body,
            )
            self._raise_for_status(r, "create event")
            event = r.json()

            # Graph populates event.onlineMeeting.joinUrl after creation. Two
            # well-known quirks force us to do a follow-up GET in some cases:
            #
            #   1. The POST response occasionally omits the onlineMeeting block
            #      even when the meeting was provisioned correctly.
            #   2. Teams provisioning is sometimes async and the joinUrl shows
            #      up a few seconds *after* the event row exists.
            #
            # Strategy: try the POST response first; if no joinUrl, re-GET with
            # an explicit $select up to 3 times with a 1s sleep between tries.
            online_meeting = event.get("onlineMeeting") or {}
            join_url = (
                online_meeting.get("joinUrl")
                or event.get("onlineMeetingUrl")
                or ""
            )
            graph_id = event.get("id", f"evt-{uuid4().hex[:8]}")

            if not join_url and graph_id and not graph_id.startswith("evt-"):
                import time as _time
                for _ in range(3):
                    _time.sleep(1.0)
                    rg = client.get(
                        f"/users/{self.organiser_upn}/events/{graph_id}",
                        params={
                            "$select": "id,isOnlineMeeting,onlineMeeting,onlineMeetingUrl"
                        },
                    )
                    if rg.status_code >= 300:
                        log.warning(
                            "Graph re-fetch event for joinUrl failed: HTTP %s",
                            rg.status_code,
                        )
                        break
                    refreshed = rg.json()
                    online_meeting = refreshed.get("onlineMeeting") or {}
                    join_url = (
                        online_meeting.get("joinUrl")
                        or refreshed.get("onlineMeetingUrl")
                        or ""
                    )
                    if join_url:
                        log.info("Graph joinUrl populated on retry")
                        break
        if application_id:
            self._known_event_ids[graph_id] = application_id

        return CalendarEventView(
            id=graph_id,
            organiser_id=self.organiser_upn,
            attendees=list(attendees),
            subject=subject,
            start=start,
            end=end,
            teams_join_url=join_url or None,
            body=body,
            cancelled=False,
            application_id=application_id,
        )

    def cancel_or_reschedule_meeting(
        self,
        event_id: str,
        new_start: Optional[datetime] = None,
        new_end: Optional[datetime] = None,
    ) -> CalendarEventView:
        with self._client() as client:
            if new_start is None or new_end is None:
                r = client.delete(f"/users/{self.organiser_upn}/events/{event_id}")
                self._raise_for_status(r, "delete event")
                return CalendarEventView(
                    id=event_id,
                    organiser_id=self.organiser_upn,
                    attendees=[],
                    subject="(cancelled)",
                    start=datetime.utcnow(),
                    end=datetime.utcnow(),
                    teams_join_url=None,
                    body="",
                    cancelled=True,
                    application_id=self._known_event_ids.get(event_id),
                )

            if new_end <= new_start:
                raise ValueError("new_end must be after new_start")
            patch_body = {
                "start": _to_graph_dt(new_start, self.timezone),
                "end": _to_graph_dt(new_end, self.timezone),
            }
            r = client.patch(
                f"/users/{self.organiser_upn}/events/{event_id}",
                json=patch_body,
            )
            self._raise_for_status(r, "reschedule event")
            event = r.json()

        return CalendarEventView(
            id=event_id,
            organiser_id=self.organiser_upn,
            attendees=[
                (a.get("emailAddress") or {}).get("address", "")
                for a in event.get("attendees", []) or []
            ],
            subject=event.get("subject", ""),
            start=new_start,
            end=new_end,
            teams_join_url=(event.get("onlineMeeting") or {}).get("joinUrl"),
            body=(event.get("body") or {}).get("content", ""),
            cancelled=False,
            application_id=self._known_event_ids.get(event_id),
        )

    def list_events(
        self,
        application_id: Optional[str] = None,
    ) -> List[CalendarEventView]:
        # Use the "known ids" map as the authoritative filter, then fetch each
        # event. This avoids the cost (and paging complexity) of listing every
        # event on the service mailbox.
        ids = [
            gid
            for gid, app_id in self._known_event_ids.items()
            if (application_id is None or app_id == application_id)
        ]
        out: List[CalendarEventView] = []
        with self._client() as client:
            for gid in ids:
                r = client.get(f"/users/{self.organiser_upn}/events/{gid}")
                if r.status_code == 404:
                    continue
                if r.status_code >= 300:
                    log.warning("Graph get event %s: HTTP %s", gid, r.status_code)
                    continue
                event = r.json()
                start = _from_graph_dt(event.get("start") or {})
                end = _from_graph_dt(event.get("end") or {})
                out.append(
                    CalendarEventView(
                        id=gid,
                        organiser_id=self.organiser_upn,
                        attendees=[
                            (a.get("emailAddress") or {}).get("address", "")
                            for a in event.get("attendees", []) or []
                        ],
                        subject=event.get("subject", ""),
                        start=start,
                        end=end,
                        teams_join_url=(event.get("onlineMeeting") or {}).get("joinUrl"),
                        body=(event.get("body") or {}).get("content", ""),
                        cancelled=event.get("isCancelled", False),
                        application_id=self._known_event_ids.get(gid),
                    )
                )
        out.sort(key=lambda e: e.start)
        return out

    def seed_busy(self, user_id: str, slots: List[TimeSlot]) -> None:
        # No-op: we can't (and shouldn't) seed busy blocks on real mailboxes.
        return None

    def reset(self) -> None:
        self._known_event_ids.clear()

    @classmethod
    def reset_global_state(cls) -> None:
        """Protocol parity with MockCalendarProvider."""
        return None
