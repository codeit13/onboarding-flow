"""Engagement domain models for the post-offer, pre-joining candidate journey.

Pure Pydantic models + one helper function. No side effects, no DB calls, no IO.
Used by the engagement engine, WhatsApp provider, and the FastAPI routes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Touchpoint (a single scheduled communication event)
# ---------------------------------------------------------------------------


class EngagementTouchpoint(BaseModel):
    id: str
    kind: Literal[
        "welcome_whatsapp",
        "buddy_intro",
        "document_checklist",
        "culture_video",
        "employee_stories",
        "benefits_overview",
        "weekly_checkin",
        "linkedin_connect",
        "it_setup_form",
        "team_intro_call",
        "dress_code_tips",
        "joining_reminder",
        "day_one_welcome",
        "custom",
    ]
    channel: Literal["whatsapp", "email", "portal", "calendar"]
    scheduled_at: datetime
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    candidate_response: Optional[str] = None
    status: Literal["pending", "sent", "delivered", "read", "failed", "skipped"] = (
        "pending"
    )
    template_id: Optional[str] = None  # WhatsApp Business template name
    template_params: Dict[str, str] = Field(default_factory=dict)
    whatsapp_message_id: Optional[str] = None  # Meta message ID for status tracking
    error_message: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Conversation message (full chat history for a journey)
# ---------------------------------------------------------------------------


class ConversationMessage(BaseModel):
    id: str
    journey_id: str
    direction: Literal["inbound", "outbound"]  # inbound = candidate, outbound = system/team
    sender: str  # phone number or "system" or team member name
    body: str
    channel: Literal["whatsapp", "email", "portal"] = "whatsapp"
    touchpoint_id: Optional[str] = None  # linked touchpoint if applicable
    reply_to_id: Optional[str] = None  # id of the message this is a reply to (WhatsApp context)
    whatsapp_message_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: Optional[str] = None  # sent, delivered, read, failed
    # Internal-only grounding citations (KB doc + section). Shown to the
    # onboarding team in the chat history view; NEVER rendered to the candidate.
    citations: List[Dict[str, str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Journey (end-to-end engagement for one accepted candidate)
# ---------------------------------------------------------------------------


class EngagementJourney(BaseModel):
    id: str
    application_id: str
    candidate_name: str
    candidate_email: str
    candidate_phone: str  # E.164 format for WhatsApp
    whatsapp_opted_in: bool = False
    offer_accepted_at: Optional[datetime] = None
    expected_joining_date: Optional[datetime] = None
    buddy_name: Optional[str] = None
    buddy_email: Optional[str] = None
    touchpoints: List[EngagementTouchpoint] = Field(default_factory=list)
    conversations: List[ConversationMessage] = Field(default_factory=list)
    sentiment_score: Optional[float] = None  # 0-100, AI-derived
    risk_level: Literal["low", "medium", "high"] = "low"
    status: Literal["active", "completed", "dropped"] = "active"
    dropped_at: Optional[datetime] = None
    drop_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Timeline builder
# ---------------------------------------------------------------------------

# Standard touchpoint schedule: (offset_type, days, kind, channel)
# offset_type: "accept" = days after offer acceptance, "join" = days before joining
_STANDARD_TIMELINE: List[tuple] = [
    # --- Immediate warmth (days 0-3 after acceptance) ---
    ("accept", 0, "welcome_whatsapp", "whatsapp"),
    ("accept", 1, "buddy_intro", "whatsapp"),
    ("accept", 3, "document_checklist", "whatsapp"),
    # --- Culture & connection (first 2 weeks) ---
    ("accept", 5, "culture_video", "whatsapp"),
    ("accept", 8, "employee_stories", "whatsapp"),
    ("accept", 10, "benefits_overview", "whatsapp"),
    ("accept", 14, "weekly_checkin", "whatsapp"),
    ("accept", 17, "linkedin_connect", "whatsapp"),
    ("accept", 21, "weekly_checkin", "whatsapp"),
    # --- Practical prep (counting down to Day 1) ---
    ("join", -14, "it_setup_form", "whatsapp"),
    ("join", -7, "team_intro_call", "whatsapp"),
    ("join", -5, "dress_code_tips", "whatsapp"),
    ("join", -3, "joining_reminder", "whatsapp"),
    ("join", 0, "day_one_welcome", "whatsapp"),
]


def _tp_id() -> str:
    return f"tp-{uuid.uuid4().hex[:8]}"


def build_engagement_timeline(
    journey: EngagementJourney,
) -> List[EngagementTouchpoint]:
    """Generate the standard touchpoint schedule for an accepted candidate.

    Requires ``offer_accepted_at`` and ``expected_joining_date`` to be set on
    the journey. Returns a list of ``EngagementTouchpoint`` objects with
    ``scheduled_at`` computed from the two anchor dates, sorted chronologically.

    If a join-relative touchpoint would fall before the acceptance date (e.g.
    the joining date is only a week away), its ``scheduled_at`` is clamped to
    the acceptance date so it is dispatched immediately on the next engine tick.
    """
    if journey.offer_accepted_at is None:
        raise ValueError("offer_accepted_at is required to build the timeline")
    if journey.expected_joining_date is None:
        raise ValueError("expected_joining_date is required to build the timeline")

    accept = journey.offer_accepted_at
    join = journey.expected_joining_date
    touchpoints: List[EngagementTouchpoint] = []

    for offset_type, days, kind, channel in _STANDARD_TIMELINE:
        if offset_type == "accept":
            scheduled = accept + timedelta(days=days)
        else:
            # "join" offsets: negative means *before* joining, 0 means joining day
            scheduled = join + timedelta(days=days)

        # Clamp: don't schedule anything before the acceptance moment
        if scheduled < accept:
            scheduled = accept

        touchpoints.append(
            EngagementTouchpoint(
                id=_tp_id(),
                kind=kind,
                channel=channel,
                scheduled_at=scheduled,
            )
        )

    # Sort chronologically so the engine processes them in order
    touchpoints.sort(key=lambda tp: tp.scheduled_at)
    return touchpoints
