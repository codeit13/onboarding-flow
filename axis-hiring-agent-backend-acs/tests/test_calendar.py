"""Calendar provider tests — exercise free/busy + meeting creation against
the active CalendarProvider (the in-memory mock during tests).

The conftest swaps to fresh provider singletons before each test, so the
busy maps and event store are isolated between tests.
"""

from datetime import datetime, timedelta

import pytest

from app.models import TimeSlot
from app.providers import get_calendar_provider
from app.tools import (
    cancel_or_reschedule_meeting,
    create_teams_meeting,
    find_common_slots,
    get_free_busy,
)


# A clean Monday 9am baseline so tests don't trip on weekends.
# 2026-04-06 is a Monday.
MON = datetime(2026, 4, 6, 9, 0)


def _seed_busy(user_id: str, slots: list[TimeSlot]) -> None:
    get_calendar_provider().seed_busy(user_id, slots)


class TestGetFreeBusy:
    def test_returns_only_blocks_in_window(self):
        _seed_busy(
            "hr.bhopal@axisbank.test",
            [
                TimeSlot(start=MON + timedelta(hours=1), end=MON + timedelta(hours=2)),
                TimeSlot(start=MON + timedelta(days=10), end=MON + timedelta(days=10, hours=1)),
            ],
        )
        fb = get_free_busy(
            ["hr.bhopal@axisbank.test"],
            window_start=MON,
            window_end=MON + timedelta(days=5),
        )
        assert len(fb["hr.bhopal@axisbank.test"]) == 1

    def test_invalid_window_raises(self):
        with pytest.raises(ValueError):
            get_free_busy(["x"], window_start=MON, window_end=MON)


class TestFindCommonSlots:
    def test_returns_slots_when_all_users_free(self):
        slots = find_common_slots(
            user_ids=["a@x.test", "b@x.test"],
            duration_min=30,
            window_start=MON,
            window_end=MON + timedelta(days=2),
            top_n=3,
        )
        assert len(slots) == 3
        assert slots[0].start.hour == 9
        assert (slots[0].end - slots[0].start) == timedelta(minutes=30)

    def test_busy_blocks_are_avoided(self):
        _seed_busy(
            "hr@x.test",
            [TimeSlot(start=MON, end=MON + timedelta(hours=2))],  # busy 9-11 Monday
        )
        slots = find_common_slots(
            user_ids=["hr@x.test", "cand@x.test"],
            duration_min=30,
            window_start=MON,
            window_end=MON + timedelta(days=2),
            top_n=1,
        )
        assert slots[0].start >= MON + timedelta(hours=2)

    def test_weekends_are_skipped(self):
        sat = datetime(2026, 4, 11, 9, 0)  # Saturday
        sun_end = datetime(2026, 4, 13, 0, 0)
        slots = find_common_slots(
            user_ids=["a@x.test"],
            duration_min=30,
            window_start=sat,
            window_end=sun_end,
            top_n=1,
        )
        assert slots == []

    def test_working_hours_respected(self):
        slots = find_common_slots(
            user_ids=["a@x.test"],
            duration_min=30,
            window_start=MON,
            window_end=MON + timedelta(days=1),
            working_hours=(9, 18),
            top_n=10,
        )
        for s in slots:
            assert 9 <= s.start.hour < 18

    def test_empty_user_ids_raises(self):
        with pytest.raises(ValueError):
            find_common_slots(
                user_ids=[],
                duration_min=30,
                window_start=MON,
                window_end=MON + timedelta(days=1),
            )


class TestCreateAndReschedule:
    def test_create_meeting_blocks_everyones_calendar(self):
        start = MON + timedelta(hours=3)
        end = start + timedelta(minutes=30)
        evt = create_teams_meeting(
            subject="R1", start=start, end=end,
            organiser_id="hr@x.test", attendees=["cand@x.test"],
        )
        assert evt.teams_join_url.startswith("https://teams.microsoft.com/")
        fb = get_free_busy(["hr@x.test", "cand@x.test"], MON, MON + timedelta(days=1))
        assert len(fb["hr@x.test"]) == 1
        assert len(fb["cand@x.test"]) == 1

    def test_create_rejects_bad_slot(self):
        with pytest.raises(ValueError):
            create_teams_meeting(
                subject="x", start=MON, end=MON,
                organiser_id="hr@x.test", attendees=[],
            )

    def test_reschedule_moves_busy_blocks(self):
        start = MON + timedelta(hours=3)
        end = start + timedelta(minutes=30)
        evt = create_teams_meeting(
            subject="R1", start=start, end=end,
            organiser_id="hr@x.test", attendees=["cand@x.test"],
        )
        new_start = MON + timedelta(days=1, hours=4)
        new_end = new_start + timedelta(minutes=30)
        updated = cancel_or_reschedule_meeting(evt.id, new_start, new_end)
        assert updated.start == new_start
        assert updated.end == new_end

    def test_cancel_marks_event(self):
        evt = create_teams_meeting(
            subject="R1",
            start=MON + timedelta(hours=4),
            end=MON + timedelta(hours=4, minutes=30),
            organiser_id="hr@x.test",
            attendees=["cand@x.test"],
        )
        cancelled = cancel_or_reschedule_meeting(evt.id)
        assert cancelled.cancelled is True

    def test_reschedule_missing_raises(self):
        with pytest.raises(LookupError):
            cancel_or_reschedule_meeting("evt-nope")
