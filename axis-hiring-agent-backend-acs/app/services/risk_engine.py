"""Multi-dimensional risk scoring engine for candidate engagement journeys.

Evaluates candidates on four risk dimensions:
  1. Responsiveness — are they replying to messages?
  2. Sentiment — do their replies sound positive and committed?
  3. Compliance — are overdue touchpoints (documents, IT form) still pending?
  4. Timeline — how close is the joining date with gaps in engagement?

Each dimension yields a score 0-100 (100 = high risk). The overall risk
level is derived from the weighted composite:
  ≤ 30  → "low"
  ≤ 60  → "medium"
  > 60  → "high"

Also classifies candidate replies as queries/concerns that need attention.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

from ..models.engagement import EngagementJourney, EngagementTouchpoint

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reply classification — detect queries, concerns, and sentiment
# ---------------------------------------------------------------------------

_QUERY_SIGNALS = [
    "?", "when", "how", "what", "where", "who", "which", "why",
    "can you", "could you", "will i", "do i", "is there",
    "please clarify", "clarify", "confused", "not sure",
    "i want to ask", "i want to know", "query", "question",
    "help me", "need help",
]

_CONCERN_SIGNALS = [
    "worried", "concern", "anxious", "nervous", "unsure",
    "reconsider", "rethink", "second thoughts", "not sure",
    "still thinking", "thinking about", "not decided", "undecided",
    "need time", "give me time", "let me think", "haven't decided",
    "hesitant", "doubtful", "doubt",
    "delay", "postpone", "extend", "push back",
    "other offer", "another offer", "competing offer",
    "not happy", "disappointed", "issue", "problem",
    "cannot", "can't", "unable", "difficult",
    "notice period", "not able to join", "won't be able",
    "come back to me", "get back to me", "waiting for",
    "exact r&r", "roles and responsibilities", "job description",
    "clarity", "unclear", "confused",
]

_POSITIVE_SIGNALS = [
    "excited", "looking forward", "thank", "thanks", "great",
    "wonderful", "happy", "glad", "awesome", "perfect",
    "ready", "prepared", "can't wait", "love",
    "done", "completed", "uploaded", "submitted", "sent",
    "yes", "sure", "absolutely", "definitely", "of course",
]

_NEGATIVE_SIGNALS = [
    "not interested", "decline", "withdraw", "cancel",
    "regret", "sorry but", "unfortunately", "bad experience",
    "rude", "unprofessional", "no response", "ghosting",
    "competitor", "better offer", "higher salary",
]


class ReplyClassification:
    """Classification of a single candidate reply."""

    def __init__(
        self,
        touchpoint_id: str,
        touchpoint_kind: str,
        reply_text: str,
    ):
        self.touchpoint_id = touchpoint_id
        self.touchpoint_kind = touchpoint_kind
        self.reply_text = reply_text

        lower = reply_text.lower()
        self.is_query = any(sig in lower for sig in _QUERY_SIGNALS)
        self.is_concern = any(sig in lower for sig in _CONCERN_SIGNALS)
        self.positive_count = sum(1 for sig in _POSITIVE_SIGNALS if sig in lower)
        self.negative_count = sum(1 for sig in _NEGATIVE_SIGNALS if sig in lower)

        if self.is_concern or self.negative_count > 0:
            self.sentiment = "negative"
        elif self.positive_count >= 2:
            self.sentiment = "positive"
        elif self.positive_count >= 1 and self.negative_count == 0:
            self.sentiment = "positive"
        else:
            self.sentiment = "neutral"

        self.needs_attention = self.is_query or self.is_concern or self.sentiment == "negative"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "touchpoint_id": self.touchpoint_id,
            "touchpoint_kind": self.touchpoint_kind,
            "reply_text": self.reply_text,
            "is_query": self.is_query,
            "is_concern": self.is_concern,
            "sentiment": self.sentiment,
            "needs_attention": self.needs_attention,
        }


# ---------------------------------------------------------------------------
# Risk dimension scorers (each returns 0-100, 100 = highest risk)
# ---------------------------------------------------------------------------

def _score_responsiveness(journey: EngagementJourney) -> Dict[str, Any]:
    """How responsive is the candidate to sent messages?

    Risk rises when messages go unanswered — especially recent ones.
    """
    sent_tps = [
        tp for tp in journey.touchpoints
        if tp.status in ("sent", "delivered", "read")
    ]
    if not sent_tps:
        return {"score": 0, "detail": "No messages sent yet", "signals": []}

    total_sent = len(sent_tps)
    replied = sum(1 for tp in sent_tps if tp.candidate_response)
    reply_rate = replied / total_sent if total_sent else 1.0

    signals: List[str] = []

    # Check for recent unanswered messages (sent > 24h ago with no reply)
    now = datetime.utcnow()
    stale_count = 0
    for tp in sent_tps:
        if tp.sent_at and not tp.candidate_response:
            hours_since = (now - tp.sent_at).total_seconds() / 3600
            if hours_since > 48:
                stale_count += 1

    if stale_count > 0:
        signals.append(f"{stale_count} message{'s' if stale_count > 1 else ''} unanswered for 48h+")

    if reply_rate == 0 and total_sent >= 2:
        signals.append("Zero replies to any message")
        score = 90
    elif reply_rate < 0.3:
        signals.append(f"Low reply rate: {replied}/{total_sent}")
        score = 70
    elif reply_rate < 0.5:
        score = 40
    else:
        score = max(0, 20 - int(reply_rate * 20))

    # Boost risk if recent messages are unanswered
    score = min(100, score + stale_count * 10)

    detail = f"{replied}/{total_sent} messages answered ({reply_rate:.0%} reply rate)"
    return {"score": score, "detail": detail, "signals": signals}


def _score_sentiment(journey: EngagementJourney) -> Dict[str, Any]:
    """Overall sentiment derived from candidate replies."""
    replies: List[ReplyClassification] = []
    for tp in journey.touchpoints:
        if tp.candidate_response:
            replies.append(
                ReplyClassification(tp.id, tp.kind, tp.candidate_response)
            )

    if not replies:
        return {"score": 20, "detail": "No replies to analyse", "signals": []}

    signals: List[str] = []
    negative_count = sum(1 for r in replies if r.sentiment == "negative")
    concern_count = sum(1 for r in replies if r.is_concern)
    query_count = sum(1 for r in replies if r.is_query)
    positive_count = sum(1 for r in replies if r.sentiment == "positive")

    if concern_count > 0:
        signals.append(f"{concern_count} reply{'s' if concern_count > 1 else ''} with concerns")
    if query_count > 0:
        signals.append(f"{query_count} unanswered query{'s' if query_count > 1 else ''}")
    if negative_count > 0:
        signals.append(f"{negative_count} negative-sentiment reply{'s' if negative_count > 1 else ''}")

    # Score: more negatives/concerns → higher risk
    if negative_count >= 2 or concern_count >= 2:
        score = 80
    elif negative_count >= 1 or concern_count >= 1:
        score = 55
    elif positive_count == len(replies):
        score = 5
    elif positive_count > negative_count:
        score = 15
    else:
        score = 30

    sentiments = [r.sentiment for r in replies]
    detail = f"{len(replies)} replies: {positive_count} positive, {negative_count} negative, {len(replies) - positive_count - negative_count} neutral"
    return {"score": score, "detail": detail, "signals": signals}


def _score_compliance(journey: EngagementJourney) -> Dict[str, Any]:
    """Are critical onboarding steps still pending past their schedule?

    Document submission, IT setup, and team intro are high-priority.
    """
    now = datetime.utcnow()
    critical_kinds = {"document_checklist", "it_setup_form", "team_intro_call"}
    signals: List[str] = []
    overdue_count = 0

    for tp in journey.touchpoints:
        if tp.kind in critical_kinds and tp.status == "pending":
            if tp.scheduled_at and tp.scheduled_at < now:
                days_overdue = (now - tp.scheduled_at).days
                signals.append(
                    f"{tp.kind.replace('_', ' ').title()} overdue by {days_overdue} day{'s' if days_overdue != 1 else ''}"
                )
                overdue_count += 1

    if overdue_count == 0:
        return {"score": 0, "detail": "All critical steps on track", "signals": []}
    elif overdue_count == 1:
        score = 40
    elif overdue_count == 2:
        score = 65
    else:
        score = 85

    detail = f"{overdue_count} critical onboarding step{'s' if overdue_count != 1 else ''} overdue"
    return {"score": score, "detail": detail, "signals": signals}


def _score_timeline(journey: EngagementJourney) -> Dict[str, Any]:
    """Is the joining date approaching with incomplete engagement?"""
    if not journey.expected_joining_date:
        return {"score": 10, "detail": "No joining date set", "signals": []}

    now = datetime.utcnow()
    days_left = (journey.expected_joining_date - now).days
    total_tp = len(journey.touchpoints)
    completed_tp = sum(
        1 for tp in journey.touchpoints
        if tp.status in ("sent", "delivered", "read", "skipped")
    )
    completion_pct = completed_tp / total_tp if total_tp else 1.0

    signals: List[str] = []

    if days_left < 0:
        signals.append(f"Joining date was {abs(days_left)} days ago")
        score = 90
    elif days_left <= 3 and completion_pct < 0.7:
        signals.append(f"Only {days_left} days to joining, {completion_pct:.0%} journey complete")
        score = 80
    elif days_left <= 7 and completion_pct < 0.5:
        signals.append(f"{days_left} days to joining, only {completion_pct:.0%} complete")
        score = 60
    elif days_left <= 14 and completion_pct < 0.3:
        signals.append(f"Low engagement with {days_left} days remaining")
        score = 45
    else:
        score = max(0, 20 - int(completion_pct * 20))

    detail = f"{days_left} days to joining, {completion_pct:.0%} journey complete"
    return {"score": score, "detail": detail, "signals": signals}


# ---------------------------------------------------------------------------
# Suggested actions based on risk signals
# ---------------------------------------------------------------------------

_SUGGESTED_ACTIONS: Dict[str, List[str]] = {
    "zero_replies": [
        "Call the candidate directly to confirm their interest",
        "Ask their buddy or referrer to reach out personally",
        "Send a personalized WhatsApp message (not template)",
    ],
    "low_reply_rate": [
        "Switch to phone calls for critical touchpoints",
        "Assign a buddy and schedule a warm introduction call",
    ],
    "negative_sentiment": [
        "Schedule an immediate 1-on-1 call with HR to address concerns",
        "Review the offer terms — candidate may be comparing with competitors",
        "Connect with the hiring manager for a personal outreach",
    ],
    "has_concerns": [
        "Respond to candidate's concerns within 24 hours",
        "Loop in the hiring manager for a reassurance call",
        "Share relevant success stories from recent joiners",
    ],
    "has_queries": [
        "Respond to candidate's questions within 4 hours",
        "Share FAQ document or onboarding guide link",
    ],
    "overdue_documents": [
        "Send a gentle reminder about pending documents",
        "Offer help — call to walk them through the upload process",
        "Extend the deadline if candidate has valid reasons",
    ],
    "overdue_it_setup": [
        "Escalate to IT team to expedite equipment provisioning",
        "Confirm laptop preference and delivery timeline",
    ],
    "approaching_joining": [
        "Send a personal welcome note from the team lead",
        "Confirm logistics: reporting time, location, parking, dress code",
        "Schedule a pre-joining video call for any last questions",
    ],
    "past_joining_date": [
        "URGENT: Call the candidate immediately",
        "Escalate to the hiring manager and HRBP",
        "Prepare for possible offer rescission if no response in 48h",
    ],
}


def _build_suggested_actions(risk_result: Dict[str, Any]) -> List[str]:
    """Pick the most relevant actions based on active risk signals."""
    actions: List[str] = []
    signals_flat = []
    for dim in risk_result.get("dimensions", {}).values():
        signals_flat.extend(dim.get("signals", []))

    signals_text = " ".join(s.lower() for s in signals_flat)

    if "zero replies" in signals_text:
        actions.extend(_SUGGESTED_ACTIONS["zero_replies"])
    elif "low reply rate" in signals_text or "unanswered" in signals_text:
        actions.extend(_SUGGESTED_ACTIONS["low_reply_rate"])

    if risk_result.get("flagged_replies"):
        has_concern = any(r["is_concern"] for r in risk_result["flagged_replies"])
        has_query = any(r["is_query"] for r in risk_result["flagged_replies"])
        if has_concern:
            actions.extend(_SUGGESTED_ACTIONS["has_concerns"])
        if has_query:
            actions.extend(_SUGGESTED_ACTIONS["has_queries"])

    if "negative-sentiment" in signals_text:
        actions.extend(_SUGGESTED_ACTIONS["negative_sentiment"])

    if "document" in signals_text and "overdue" in signals_text:
        actions.extend(_SUGGESTED_ACTIONS["overdue_documents"])
    if "it setup" in signals_text and "overdue" in signals_text:
        actions.extend(_SUGGESTED_ACTIONS["overdue_it_setup"])

    if "joining date was" in signals_text:
        actions.extend(_SUGGESTED_ACTIONS["past_joining_date"])
    elif "days to joining" in signals_text:
        actions.extend(_SUGGESTED_ACTIONS["approaching_joining"])

    # Deduplicate while preserving order
    seen = set()
    unique_actions = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            unique_actions.append(a)

    return unique_actions[:5]  # Cap at 5 most relevant


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "responsiveness": 0.30,
    "sentiment": 0.25,
    "compliance": 0.25,
    "timeline": 0.20,
}


def compute_risk_assessment(journey: EngagementJourney) -> Dict[str, Any]:
    """Compute full multi-dimensional risk assessment for a journey.

    Returns:
        {
            "overall_score": 0-100,
            "risk_level": "low" | "medium" | "high",
            "dimensions": {
                "responsiveness": {"score": N, "detail": "...", "signals": [...]},
                "sentiment": {...},
                "compliance": {...},
                "timeline": {...},
            },
            "flagged_replies": [
                {"touchpoint_id": "...", "reply_text": "...", "is_query": true, ...},
            ],
            "suggested_actions": ["...", "..."],
        }
    """
    dimensions = {
        "responsiveness": _score_responsiveness(journey),
        "sentiment": _score_sentiment(journey),
        "compliance": _score_compliance(journey),
        "timeline": _score_timeline(journey),
    }

    # Weighted composite
    overall = sum(
        dimensions[dim]["score"] * weight
        for dim, weight in _WEIGHTS.items()
    )

    if overall <= 30:
        risk_level = "low"
    elif overall <= 60:
        risk_level = "medium"
    else:
        risk_level = "high"

    # Classify replies that need attention
    flagged: List[Dict[str, Any]] = []
    for tp in journey.touchpoints:
        if tp.candidate_response:
            rc = ReplyClassification(tp.id, tp.kind, tp.candidate_response)
            if rc.needs_attention:
                flagged.append(rc.to_dict())

    result = {
        "overall_score": round(overall, 1),
        "risk_level": risk_level,
        "dimensions": dimensions,
        "flagged_replies": flagged,
    }

    # Build suggested actions
    result["suggested_actions"] = _build_suggested_actions(result)

    return result
