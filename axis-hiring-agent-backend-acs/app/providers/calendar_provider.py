"""CalendarProvider — abstract contract + in-memory mock.

Every calendar operation the agent needs goes through this interface. The
mock implementation is a faithful simulation of the Microsoft Graph calendar
surface:
  * per-user busy blocks with working-hours + weekend skipping
  * free/busy intersection across multiple attendees
  * creating Teams meetings with a joinWebUrl
  * cancelling / rescheduling a meeting and fanning busy-block updates

The real GraphCalendarProvider (see graph_calendar_provider.py) implements the
same Protocol against the live Graph API. Callers never check the concrete
type — they always use ``app.providers.get_calendar_provider()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Protocol
from uuid import uuid4

from ..models import CalendarEventView, TimeSlot


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


class CalendarProvider(Protocol):
    """The surface every calendar backend must implement."""

    def get_free_busy(
        self,
        user_ids: List[str],
        window_start: datetime,
        window_end: datetime,
    ) -> Dict[str, List[TimeSlot]]:
        """Return per-user busy blocks inside the window."""

    def find_common_slots(
        self,
        user_ids: List[str],
        duration_min: int,
        window_start: datetime,
        window_end: datetime,
        working_hours: tuple = (9, 18),
        top_n: int = 3,
    ) -> List[TimeSlot]:
        """Intersect everyone's free time, return top-N slots of required length."""

    def create_teams_meeting(
        self,
        subject: str,
        start: datetime,
        end: datetime,
        organiser_id: str,
        attendees: List[str],
        body: str = "",
        application_id: Optional[str] = None,
    ) -> CalendarEventView:
        """Book a real Teams meeting and block everyone's calendar."""

    def cancel_or_reschedule_meeting(
        self,
        event_id: str,
        new_start: Optional[datetime] = None,
        new_end: Optional[datetime] = None,
    ) -> CalendarEventView:
        """Cancel the event (new_start==None) or move it to a new slot."""

    def list_events(
        self,
        application_id: Optional[str] = None,
    ) -> List[CalendarEventView]:
        """Return every event we've created, optionally filtered by application."""

    def seed_busy(self, user_id: str, slots: List[TimeSlot]) -> None:
        """Test helper — populate busy blocks. Real provider is a no-op."""

    def reset(self) -> None:
        """Test helper — wipe state."""


# ---------------------------------------------------------------------------
# Mock implementation
# ---------------------------------------------------------------------------


@dataclass
class _MockEvent:
    id: str
    organiser_id: str
    attendees: List[str]
    subject: str
    slot: TimeSlot
    teams_join_url: Optional[str]
    body: str
    cancelled: bool = False
    application_id: Optional[str] = None

    def to_view(self) -> CalendarEventView:
        return CalendarEventView(
            id=self.id,
            organiser_id=self.organiser_id,
            attendees=list(self.attendees),
            subject=self.subject,
            start=self.slot.start,
            end=self.slot.end,
            teams_join_url=self.teams_join_url,
            body=self.body,
            cancelled=self.cancelled,
            application_id=self.application_id,
        )


# Module-level state so every MockCalendarProvider instance shares the same
# world (simulates a single tenant's Exchange Online). Reset via reset().
_CALENDARS: Dict[str, List[TimeSlot]] = {}
_EVENTS: Dict[str, _MockEvent] = {}


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


def _intersect(a: List[TimeSlot], b: List[TimeSlot]) -> List[TimeSlot]:
    out: List[TimeSlot] = []
    for x in a:
        for y in b:
            start = max(x.start, y.start)
            end = min(x.end, y.end)
            if end > start:
                out.append(TimeSlot(start=start, end=end))
    return out


class MockCalendarProvider:
    """In-memory calendar, fully deterministic, suitable for demo + tests."""

    def get_free_busy(
        self,
        user_ids: List[str],
        window_start: datetime,
        window_end: datetime,
    ) -> Dict[str, List[TimeSlot]]:
        if window_end <= window_start:
            raise ValueError("window_end must be after window_start")
        out: Dict[str, List[TimeSlot]] = {}
        window = TimeSlot(start=window_start, end=window_end)
        for uid in user_ids:
            out[uid] = [s for s in _CALENDARS.get(uid, []) if s.overlaps(window)]
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

        day = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
        days: List[datetime] = []
        while day < window_end:
            days.append(day)
            day += timedelta(days=1)

        free_by_user: List[List[TimeSlot]] = []
        for uid in user_ids:
            user_free: List[TimeSlot] = []
            busy = _CALENDARS.get(uid, [])
            for d in days:
                if d.weekday() >= 5:  # skip Sat/Sun
                    continue
                win = _working_window(d, *working_hours)
                user_free.extend(_subtract(busy, win))
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
        organiser_id: str,
        attendees: List[str],
        body: str = "",
        application_id: Optional[str] = None,
    ) -> CalendarEventView:
        if end <= start:
            raise ValueError("meeting end must be after start")
        evt = _MockEvent(
            id=f"evt-{uuid4().hex[:8]}",
            organiser_id=organiser_id,
            attendees=list(attendees),
            subject=subject,
            slot=TimeSlot(start=start, end=end),
            teams_join_url=f"https://teams.microsoft.com/l/meetup-join/{uuid4().hex}",
            body=body,
            application_id=application_id,
        )
        _EVENTS[evt.id] = evt
        for uid in {organiser_id, *attendees}:
            _CALENDARS.setdefault(uid, []).append(evt.slot)
        return evt.to_view()

    def cancel_or_reschedule_meeting(
        self,
        event_id: str,
        new_start: Optional[datetime] = None,
        new_end: Optional[datetime] = None,
    ) -> CalendarEventView:
        evt = _EVENTS.get(event_id)
        if not evt:
            raise LookupError(f"No meeting for id={event_id!r}")

        old_slot = evt.slot
        for uid in {evt.organiser_id, *evt.attendees}:
            cal = _CALENDARS.get(uid, [])
            _CALENDARS[uid] = [
                s for s in cal
                if not (s.start == old_slot.start and s.end == old_slot.end)
            ]

        if new_start is None or new_end is None:
            evt.cancelled = True
            return evt.to_view()

        if new_end <= new_start:
            raise ValueError("new_end must be after new_start")
        evt.slot = TimeSlot(start=new_start, end=new_end)
        for uid in {evt.organiser_id, *evt.attendees}:
            _CALENDARS.setdefault(uid, []).append(evt.slot)
        return evt.to_view()

    def list_events(
        self,
        application_id: Optional[str] = None,
    ) -> List[CalendarEventView]:
        events = list(_EVENTS.values())
        if application_id:
            events = [e for e in events if e.application_id == application_id]
        events.sort(key=lambda e: e.slot.start)
        return [e.to_view() for e in events]

    def seed_busy(self, user_id: str, slots: List[TimeSlot]) -> None:
        _CALENDARS.setdefault(user_id, []).extend(slots)

    def reset(self) -> None:
        _CALENDARS.clear()
        _EVENTS.clear()

    # ---- class-level helpers for tests / providers factory -----------------

    @classmethod
    def reset_global_state(cls) -> None:
        _CALENDARS.clear()
        _EVENTS.clear()
