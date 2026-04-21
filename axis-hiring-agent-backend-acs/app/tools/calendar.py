"""Calendar tools — thin wrappers around the active CalendarProvider.

These functions exist so the orchestrator can call `find_common_slots(...)`
without caring whether the backing provider is the in-memory mock or real
Graph. The provider is resolved once per call via
``app.providers.get_calendar_provider()``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from ..models import CalendarEventView, TimeSlot
from ..providers import get_calendar_provider


def get_free_busy(
    user_ids: List[str],
    window_start: datetime,
    window_end: datetime,
) -> Dict[str, List[TimeSlot]]:
    return get_calendar_provider().get_free_busy(user_ids, window_start, window_end)


def find_common_slots(
    user_ids: List[str],
    duration_min: int,
    window_start: datetime,
    window_end: datetime,
    working_hours: tuple = (9, 18),
    top_n: int = 3,
) -> List[TimeSlot]:
    return get_calendar_provider().find_common_slots(
        user_ids=user_ids,
        duration_min=duration_min,
        window_start=window_start,
        window_end=window_end,
        working_hours=working_hours,
        top_n=top_n,
    )


def create_teams_meeting(
    subject: str,
    start: datetime,
    end: datetime,
    organiser_id: str,
    attendees: List[str],
    body: str = "",
    application_id: Optional[str] = None,
) -> CalendarEventView:
    return get_calendar_provider().create_teams_meeting(
        subject=subject,
        start=start,
        end=end,
        organiser_id=organiser_id,
        attendees=attendees,
        body=body,
        application_id=application_id,
    )


def cancel_or_reschedule_meeting(
    event_id: str,
    new_start: Optional[datetime] = None,
    new_end: Optional[datetime] = None,
) -> CalendarEventView:
    return get_calendar_provider().cancel_or_reschedule_meeting(
        event_id=event_id,
        new_start=new_start,
        new_end=new_end,
    )


def list_calendar_events(application_id: Optional[str] = None) -> List[CalendarEventView]:
    return get_calendar_provider().list_events(application_id=application_id)
