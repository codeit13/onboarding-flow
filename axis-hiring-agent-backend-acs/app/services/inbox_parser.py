"""Inbound mail parser for the external candidate flow.

When an external candidate replies to the slot-proposal email, the reply
lands in the Business Partner's mailbox (Meera Nair on Xebia192). A background
poller (``app.services.inbox_poller``) reads new messages from her inbox
via Microsoft Graph and hands each one to ``handle_external_reply`` here.

The flow:
  1. Look up which Application this sender is associated with (by email).
  2. Use Claude (or the deterministic fallback) to extract which slot the
     candidate is choosing — by option number, weekday, or date.
  3. Call the orchestrator's standard ``on_candidate_confirm_slot`` so the
     same code path the internal UI confirm uses fires for external too.

Why this is its own service
---------------------------
- ``parse_resume`` and ``extract_slot_choice`` are pure functions; they
  must be unit-testable without spinning up Graph or threading.
- ``handle_external_reply`` is the seam the poller calls. Tests inject
  fake reply text into it directly to drive the orchestrator end-to-end
  without touching the network.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from ..models import Application, AgentStatus, FunnelStage, TimeSlot
from ..store import STORE


# ---------------------------------------------------------------------------
# Slot extraction
# ---------------------------------------------------------------------------


_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def extract_slot_choice(reply_text: str, slots: List[TimeSlot]) -> Optional[int]:
    """Return the index into ``slots`` the candidate picked, or None.

    Resolution order (most reliable first):
      1. Explicit option/slot number — "option 2", "slot 3", "#2".
      2. Weekday match — "Tuesday works".
      3. Hour-of-day match — "11am", "2 pm", "14:00" — picks the slot
         whose start hour (in IST) matches.
      4. Give up → None.

    The orchestrator treats None as "still waiting" and the poller marks
    the email as needing HR review.

    Real implementation will replace this with a Claude call that takes
    the slot list and the reply text and returns a JSON {chosen_index}.
    The deterministic version below is what unit tests use, and it's
    also a robust fallback when the API key is missing.
    """
    if not reply_text or not slots:
        return None
    text = reply_text.lower()

    # 1. Option / slot / # number.
    m = re.search(r"(?:option|slot|choice|#)\s*([1-9])", text)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(slots):
            return idx

    # 2. Weekday — convert each slot's start to weekday and match.
    for word, dow in _WEEKDAYS.items():
        if re.search(rf"\b{word}\b", text):
            for i, slot in enumerate(slots):
                # IST = UTC+5:30; convert by adding 330 minutes when the
                # slot is in UTC. We use start.weekday() which is fine
                # for naive datetimes (the seeded slots are timezone-naive
                # IST already in tests).
                if slot.start.weekday() == dow:
                    return i

    # 3. Hour of day — "11am", "2 pm", "14:00".
    hour = _parse_hour(text)
    if hour is not None:
        for i, slot in enumerate(slots):
            # IST hour. Slots may be UTC or IST depending on caller; the
            # orchestrator stores naive IST in the live demo, so prefer
            # the bare hour. Fall back to UTC+5:30 for safety.
            if slot.start.hour == hour:
                return i
            ist_hour = (slot.start.hour + 5) % 24
            if ist_hour == hour:
                return i

    return None


def _parse_hour(text: str) -> Optional[int]:
    """Best-effort hour-of-day extraction from a free-text reply."""
    # 11am / 11 am / 11AM
    m = re.search(r"\b([0-1]?\d)\s*(am|pm)\b", text)
    if m:
        h = int(m.group(1)) % 12
        if m.group(2) == "pm":
            h += 12
        return h
    # 14:00 / 09:30
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if m:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Application lookup by sender
# ---------------------------------------------------------------------------


def find_application_by_sender(sender_email: str) -> Optional[Application]:
    """Return the most recent active external Application for this sender.

    "Most recent" because a candidate can have applied to multiple JDs;
    we resolve to the one currently waiting on a slot confirmation. If
    none is waiting, we fall back to the most recently updated.
    """
    if not sender_email:
        return None
    sender = sender_email.strip().lower()
    matches = [
        a
        for a in STORE.list_applications()
        if a.candidate_kind == "external"
        and a.candidate_id.lower() == sender
    ]
    if not matches:
        return None
    waiting = [
        a
        for a in matches
        if a.agent_status == AgentStatus.WAITING_CANDIDATE
        and a.stage in (FunnelStage.SCREENED, FunnelStage.R1_DONE)
    ]
    pool = waiting or matches
    pool.sort(key=lambda a: a.updated_at, reverse=True)
    return pool[0]


# ---------------------------------------------------------------------------
# Public entrypoint — the poller calls this
# ---------------------------------------------------------------------------


def handle_external_reply(
    sender_email: str,
    body_text: str,
    received_at: Optional[datetime] = None,
) -> bool:
    """Process one inbound reply. Returns True if it advanced an
    application, False if we couldn't make sense of it (the poller will
    log + leave the message untouched so HR can intervene).
    """
    app = find_application_by_sender(sender_email)
    if app is None:
        return False

    # Choose which round we're confirming. External candidates use the
    # same proposed_r1_slots / proposed_r2_slots fields as internal.
    if app.stage == FunnelStage.SCREENED and app.proposed_r1_slots:
        slots = app.proposed_r1_slots
        round_ = "R1"
    elif app.stage == FunnelStage.R1_DONE and app.proposed_r2_slots:
        slots = app.proposed_r2_slots
        round_ = "R2"
    else:
        return False

    chosen = extract_slot_choice(body_text, slots)
    if chosen is None:
        app.log(
            "agent",
            f"Inbound reply from {sender_email} did not match any proposed slot — leaving for HR review",
            level="warn",
        )
        return False

    app.log(
        "candidate",
        f"Replied via email and chose {round_} slot #{chosen + 1}",
    )
    # Use the same orchestrator method the UI uses so internal and
    # external paths converge.
    from ..orchestrator import ORCHESTRATOR
    ORCHESTRATOR.on_candidate_confirm_slot(app.id, round_, chosen)
    return True
