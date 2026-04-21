"""Candidate Engagement routes (post-offer, pre-joining).

Handles the entire lifecycle from offer acceptance through to joining day:
offer accept/decline, engagement journey CRUD, WhatsApp webhook
integration, and the onboarding dashboard.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..models.engagement import (
    ConversationMessage,
    EngagementJourney,
    build_engagement_timeline,
)
from ..providers import get_whatsapp_provider
from ..services.engagement_engine import build_message
from ..services.risk_engine import compute_risk_assessment, ReplyClassification
from ..store import STORE

log = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class OfferAcceptRequest(BaseModel):
    phone: str  # E.164 format (e.g. "+919988776655")
    whatsapp_consent: bool = True
    expected_joining_date: str  # ISO date string


class OfferDeclineRequest(BaseModel):
    reason: Optional[str] = None


class JourneyPatchRequest(BaseModel):
    buddy_name: Optional[str] = None
    buddy_email: Optional[str] = None
    expected_joining_date: Optional[str] = None
    risk_level: Optional[str] = None


# ---------------------------------------------------------------------------
# Offer Accept / Decline
# ---------------------------------------------------------------------------


@router.post("/applications/{app_id}/offer/accept")
def accept_offer(app_id: str, req: OfferAcceptRequest) -> dict:
    """Candidate accepts the offer -- kicks off the engagement journey."""
    app = STORE.get_application(app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    if app.stage.value != "offer":
        raise HTTPException(
            status_code=400,
            detail=f"Application is at stage '{app.stage.value}', expected 'offer'",
        )

    # Resolve candidate for name / email. Applications store candidate_id as
    # the employee_id (e.g. "EMP11023"), while the STORE indexes Candidate
    # objects by their internal id (e.g. "cand-004"). Look up by id first,
    # then fall back to a scan keyed on employee_id so the engagement journey
    # always shows the real person's name, not the literal string "Candidate".
    candidate = STORE.get_candidate(app.candidate_id)
    if candidate is None:
        for _c in STORE.list_candidates() if hasattr(STORE, "list_candidates") else STORE.candidates.values():
            if getattr(_c.profile, "employee_id", None) == app.candidate_id:
                candidate = _c
                break
    candidate_name = candidate.profile.name if candidate else "Candidate"
    candidate_email = candidate.profile.email if candidate else ""

    now = datetime.utcnow()
    joining_date = datetime.fromisoformat(req.expected_joining_date)

    # Build the engagement journey
    journey = EngagementJourney(
        id=f"ej-{uuid.uuid4().hex[:8]}",
        application_id=app_id,
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        candidate_phone=req.phone,
        whatsapp_opted_in=req.whatsapp_consent,
        offer_accepted_at=now,
        expected_joining_date=joining_date,
    )

    # Generate the touchpoint timeline
    touchpoints = build_engagement_timeline(journey)
    journey.touchpoints = touchpoints

    # Persist the journey
    STORE.add_engagement_journey(journey)

    # Update application stage and log the event
    from ..models.domain import FunnelStage, AgentStatus

    app.stage = FunnelStage.OFFER_ACCEPTED
    app.offer_accepted = True
    app.offer_accepted_at = now
    app.candidate_phone = req.phone
    app.expected_joining_date = joining_date
    app.engagement_journey_id = journey.id
    app.agent_status = AgentStatus.ENGAGING
    app.log("engagement", f"Offer accepted. Engagement journey {journey.id} created with {len(touchpoints)} touchpoints.")

    log.info(
        "Offer accepted for application %s -- journey %s with %d touchpoints",
        app_id,
        journey.id,
        len(touchpoints),
    )

    return journey.model_dump(mode="json")


@router.post("/applications/{app_id}/offer/decline")
def decline_offer(app_id: str, req: OfferDeclineRequest) -> dict:
    """Candidate declines the offer."""
    app = STORE.get_application(app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    if app.stage.value != "offer":
        raise HTTPException(
            status_code=400,
            detail=f"Application is at stage '{app.stage.value}', expected 'offer'",
        )

    from ..models.domain import FunnelStage, AgentStatus

    app.stage = FunnelStage.OFFER_DECLINED
    app.offer_declined = True
    app.offer_declined_reason = req.reason
    app.agent_status = AgentStatus.DONE
    reason_text = req.reason or "no reason given"
    app.log("engagement", f"Offer declined -- {reason_text}.")

    log.info("Offer declined for application %s: %s", app_id, reason_text)

    return app.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Engagement Journey CRUD
# ---------------------------------------------------------------------------


@router.get("/engagement/journeys")
def list_journeys() -> List[dict]:
    """List all engagement journeys (onboarding dashboard)."""
    journeys = STORE.list_engagement_journeys()
    return [j.model_dump(mode="json") for j in journeys]


@router.get("/engagement/journeys/{journey_id}")
def get_journey(journey_id: str) -> dict:
    """Get a single journey with all touchpoints."""
    journey = STORE.get_engagement_journey(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail=f"No journey {journey_id}")
    return journey.model_dump(mode="json")


@router.get("/engagement/by-application/{app_id}")
def get_journey_by_application(app_id: str) -> dict:
    """Get engagement journey for an application (candidate view)."""
    journey = STORE.get_engagement_journey_by_application(app_id)
    if not journey:
        raise HTTPException(
            status_code=404,
            detail=f"No engagement journey for application {app_id}",
        )
    return journey.model_dump(mode="json")


@router.patch("/engagement/journeys/{journey_id}")
def update_journey(journey_id: str, req: JourneyPatchRequest) -> dict:
    """Update mutable fields on a journey (buddy assignment, dates, risk)."""
    journey = STORE.get_engagement_journey(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail=f"No journey {journey_id}")

    if req.buddy_name is not None:
        journey.buddy_name = req.buddy_name
    if req.buddy_email is not None:
        journey.buddy_email = req.buddy_email
    if req.expected_joining_date is not None:
        journey.expected_joining_date = datetime.fromisoformat(req.expected_joining_date)
    if req.risk_level is not None:
        journey.risk_level = req.risk_level

    journey.updated_at = datetime.utcnow()
    STORE.save_engagement_journey(journey)

    log.info("Journey %s updated: %s", journey_id, req.model_dump(exclude_none=True))

    return journey.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Touchpoint actions
# ---------------------------------------------------------------------------


@router.post("/engagement/journeys/{journey_id}/touchpoints/{tp_id}/send")
def send_touchpoint(journey_id: str, tp_id: str) -> dict:
    """Manually trigger a specific touchpoint NOW (HR override)."""
    journey = STORE.get_engagement_journey(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail=f"No journey {journey_id}")

    tp = next((t for t in journey.touchpoints if t.id == tp_id), None)
    if not tp:
        raise HTTPException(
            status_code=404,
            detail=f"No touchpoint {tp_id} in journey {journey_id}",
        )

    if not journey.whatsapp_opted_in:
        raise HTTPException(
            status_code=400,
            detail="Candidate has not given WhatsApp consent",
        )

    # Resolve template + build the human-readable message
    from ..services.engagement_engine import _resolve_template, build_message

    template_name, params = _resolve_template(tp.kind, journey, tp)
    message_text = build_message(tp.kind, journey, tp)

    # Send via WhatsApp provider as a free-form text message so the
    # rich onboarding copy (welcome / buddy_intro / document_checklist /
    # culture / employee_stories / benefits / linkedin / it_setup / team_intro /
    # dress_code / joining_reminder / day_one / weekly_checkin) actually reaches
    # the candidate. Sending as `template_message` caused Twilio-sandbox to
    # wrap it as "[buddy_intro] Priya" — a placeholder, not a real message.
    # Matches the daemon (_process_journey) path which already uses text.
    provider = get_whatsapp_provider()
    try:
        result = provider.send_text_message(
            to_phone=journey.candidate_phone,
            text=message_text,
        )
        if not getattr(result, "success", True):
            raise RuntimeError(getattr(result, "error", "whatsapp send failed"))
        tp.status = "sent"
        tp.sent_at = datetime.utcnow()
        tp.whatsapp_message_id = result.message_id
        tp.template_id = template_name
        tp.template_params = params
        # Log outbound message in conversation history
        journey.conversations.append(ConversationMessage(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            journey_id=journey.id,
            direction="outbound",
            sender="system",
            body=message_text,
            channel="whatsapp",
            touchpoint_id=tp.id,
            whatsapp_message_id=result.message_id,
            status="sent",
        ))
    except Exception:
        log.exception(
            "Failed to send touchpoint %s for journey %s", tp_id, journey_id
        )
        tp.status = "failed"
        STORE.save_engagement_journey(journey)
        raise HTTPException(
            status_code=502,
            detail="WhatsApp delivery failed -- see server logs",
        )

    STORE.save_engagement_journey(journey)
    log.info("Touchpoint %s sent for journey %s", tp_id, journey_id)

    return tp.model_dump(mode="json")


@router.post("/engagement/journeys/{journey_id}/touchpoints/{tp_id}/skip")
def skip_touchpoint(journey_id: str, tp_id: str) -> dict:
    """Mark a touchpoint as skipped."""
    journey = STORE.get_engagement_journey(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail=f"No journey {journey_id}")

    tp = next((t for t in journey.touchpoints if t.id == tp_id), None)
    if not tp:
        raise HTTPException(
            status_code=404,
            detail=f"No touchpoint {tp_id} in journey {journey_id}",
        )

    tp.status = "skipped"
    STORE.save_engagement_journey(journey)

    log.info("Touchpoint %s skipped in journey %s", tp_id, journey_id)

    return tp.model_dump(mode="json")


# ---------------------------------------------------------------------------
# WhatsApp Webhook
# ---------------------------------------------------------------------------

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "axis-hiring-verify")


@router.get("/webhooks/whatsapp")
def whatsapp_verify(request: Request) -> Any:
    """Meta verification endpoint -- returns hub.challenge when token matches."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        log.info("WhatsApp webhook verified")
        return int(challenge) if challenge else ""

    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhooks/whatsapp")
def whatsapp_webhook(payload: Dict[str, Any]) -> dict:
    """Receive Meta webhook payloads -- status updates and inbound messages.

    Returns 200 immediately as Meta requires a fast response.
    """
    try:
        _process_whatsapp_payload(payload)
    except Exception:
        # Log but never return an error -- Meta will retry and we don't
        # want cascading failures.
        log.exception("Error processing WhatsApp webhook payload")

    return {"status": "ok"}


def _process_whatsapp_payload(payload: Dict[str, Any]) -> None:
    """Parse the Meta webhook payload and route to handlers."""
    entries = payload.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})

            # --- Status updates (delivered / read / failed) ---
            statuses = value.get("statuses", [])
            for status in statuses:
                _handle_status_update(status)

            # --- Inbound messages ---
            messages = value.get("messages", [])
            for message in messages:
                _handle_inbound_message(message)


def _handle_status_update(status: Dict[str, Any]) -> None:
    """Update touchpoint status based on WhatsApp delivery receipt."""
    wa_message_id = status.get("id")
    new_status = status.get("status")  # delivered, read, failed
    if not wa_message_id or not new_status:
        return

    # Search all journeys for the touchpoint with this message ID
    for journey in STORE.list_engagement_journeys():
        for tp in journey.touchpoints:
            if tp.whatsapp_message_id == wa_message_id:
                tp.status = new_status
                now = datetime.utcnow()
                if new_status == "delivered":
                    tp.delivered_at = now
                elif new_status == "read":
                    tp.read_at = now
                STORE.save_engagement_journey(journey)
                log.info(
                    "Touchpoint %s status -> %s (wa_id=%s)",
                    tp.id,
                    new_status,
                    wa_message_id,
                )
                return


def _handle_inbound_message(message: Dict[str, Any]) -> None:
    """Store candidate reply on the most recent sent touchpoint."""
    sender_phone = message.get("from", "")
    body = message.get("text", {}).get("body", "")
    if not sender_phone or not body:
        return

    # Normalise phone -- Meta sends without '+', our store has '+'
    if not sender_phone.startswith("+"):
        sender_phone = f"+{sender_phone}"

    # Find the journey by candidate phone (match on last 10 digits to be
    # resilient to '+' / country-code formatting differences).
    message_sid = message.get("id", "")
    sender_tail = "".join(ch for ch in sender_phone if ch.isdigit())[-10:]
    for journey in STORE.list_engagement_journeys():
        journey_tail = "".join(ch for ch in journey.candidate_phone if ch.isdigit())[-10:]
        if journey_tail != sender_tail:
            continue
        # Find sent touchpoints
        sent_tps = [
            tp
            for tp in journey.touchpoints
            if tp.status in ("sent", "delivered", "read")
        ]
        touchpoint_id: Optional[str] = None
        outbound_msg_id: Optional[str] = None
        if sent_tps:
            best = _match_reply_to_touchpoint(sent_tps, body)
            best.candidate_response = body
            outbound_msg_id = _find_outbound_msg_id(journey, best.id)
            touchpoint_id = best.id
        # Always persist the inbound message — even if no matching
        # touchpoint exists yet — so nothing the candidate says is lost.
        journey.conversations.append(ConversationMessage(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            journey_id=journey.id,
            direction="inbound",
            sender=sender_phone,
            body=body,
            channel="whatsapp",
            touchpoint_id=touchpoint_id,
            reply_to_id=outbound_msg_id,
            whatsapp_message_id=message_sid,
        ))
        _refresh_journey_risk(journey)
        STORE.save_engagement_journey(journey)
        log.info(
            "Inbound WhatsApp reply from %s stored (touchpoint=%s)",
            sender_phone, touchpoint_id or "none",
        )
        return
    log.warning(
        "Inbound WhatsApp reply from %s did not match any journey phone",
        sender_phone,
    )


# ---------------------------------------------------------------------------
# Twilio WhatsApp Webhook
# ---------------------------------------------------------------------------


@router.post("/webhooks/whatsapp/twilio")
async def twilio_whatsapp_webhook(request: Request) -> dict:
    """Receive Twilio WhatsApp webhooks (sandbox + production).

    Twilio posts ``application/x-www-form-urlencoded`` form data with fields
    like ``From``, ``Body``, ``MessageSid``, ``MessageStatus``.
    Returns 200 immediately as Twilio requires a fast response.
    """
    try:
        form = await request.form()
        form_data = dict(form)
        _process_twilio_whatsapp(form_data)
    except Exception:
        log.exception("Error processing Twilio WhatsApp webhook")

    return {"status": "ok"}


def _process_twilio_whatsapp(form_data: Dict[str, Any]) -> None:
    """Route Twilio form-data to the correct handler."""
    message_sid = str(form_data.get("MessageSid", ""))
    from_raw = str(form_data.get("From", ""))
    body = str(form_data.get("Body", ""))
    status = str(form_data.get("MessageStatus", ""))

    # Normalise phone — Twilio sends "whatsapp:+919988776655"
    sender_phone = from_raw.replace("whatsapp:", "").strip()
    if sender_phone and not sender_phone.startswith("+"):
        sender_phone = f"+{sender_phone}"

    log.info(
        "Twilio WhatsApp webhook: sid=%s from=%s status=%s body=%s",
        message_sid,
        sender_phone,
        status or "-",
        body[:80] if body else "-",
    )

    # Status callback (delivery receipts)
    if status and message_sid:
        _handle_twilio_status(message_sid, status)

    # Inbound candidate message
    if body and sender_phone:
        _handle_twilio_inbound(sender_phone, body, message_sid)


def _handle_twilio_status(message_sid: str, status: str) -> None:
    """Map Twilio status (sent/delivered/read/failed) to touchpoint status."""
    # Twilio statuses: queued, sent, delivered, read, failed, undelivered
    mapped = {
        "sent": "sent",
        "delivered": "delivered",
        "read": "read",
        "failed": "failed",
        "undelivered": "failed",
    }
    new_status = mapped.get(status)
    if not new_status:
        return

    for journey in STORE.list_engagement_journeys():
        for tp in journey.touchpoints:
            if tp.whatsapp_message_id == message_sid:
                tp.status = new_status
                now = datetime.utcnow()
                if new_status == "delivered":
                    tp.delivered_at = now
                elif new_status == "read":
                    tp.read_at = now
                STORE.save_engagement_journey(journey)
                log.info(
                    "Twilio status %s -> touchpoint %s", new_status, tp.id
                )
                return


def _handle_twilio_inbound(
    sender_phone: str, body: str, message_sid: str
) -> None:
    """Store candidate reply. Always persist — even if no sent touchpoint
    matches yet — so the message is never silently dropped."""
    sender_tail = "".join(ch for ch in sender_phone if ch.isdigit())[-10:]
    for journey in STORE.list_engagement_journeys():
        journey_tail = "".join(ch for ch in journey.candidate_phone if ch.isdigit())[-10:]
        if journey_tail != sender_tail:
            continue
        sent_tps = [
            tp
            for tp in journey.touchpoints
            if tp.status in ("sent", "delivered", "read")
        ]
        touchpoint_id: Optional[str] = None
        outbound_msg_id: Optional[str] = None
        if sent_tps:
            best = _match_reply_to_touchpoint(sent_tps, body)
            best.candidate_response = body
            outbound_msg_id = _find_outbound_msg_id(journey, best.id)
            touchpoint_id = best.id
        journey.conversations.append(ConversationMessage(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            journey_id=journey.id,
            direction="inbound",
            sender=sender_phone,
            body=body,
            channel="whatsapp",
            touchpoint_id=touchpoint_id,
            reply_to_id=outbound_msg_id,
            whatsapp_message_id=message_sid,
        ))
        _refresh_journey_risk(journey)
        STORE.save_engagement_journey(journey)
        log.info(
            "Twilio inbound from %s stored (touchpoint=%s, sid=%s)",
            sender_phone, touchpoint_id or "none", message_sid,
        )
        return
    log.warning(
        "Twilio inbound from %s did not match any journey (sid=%s)",
        sender_phone, message_sid,
    )


def _find_outbound_msg_id(journey: EngagementJourney, touchpoint_id: str) -> Optional[str]:
    """Find the outbound conversation message id linked to a touchpoint."""
    for msg in journey.conversations:
        if msg.direction == "outbound" and msg.touchpoint_id == touchpoint_id:
            return msg.id
    return None


def _refresh_journey_risk(journey: EngagementJourney) -> None:
    """Recompute and persist the risk level on a journey."""
    assessment = compute_risk_assessment(journey)
    journey.risk_level = assessment["risk_level"]
    journey.updated_at = datetime.utcnow()
    log.info(
        "Risk recalculated for %s (%s): %s (score %.1f)",
        journey.candidate_name,
        journey.id,
        assessment["risk_level"],
        assessment["overall_score"],
    )


# ---------------------------------------------------------------------------
# Risk Assessment API
# ---------------------------------------------------------------------------


@router.get("/engagement/journeys/{journey_id}/risk")
def get_journey_risk(journey_id: str) -> dict:
    """Get full multi-dimensional risk assessment for a journey."""
    journey = STORE.get_engagement_journey(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail=f"No journey {journey_id}")
    assessment = compute_risk_assessment(journey)
    # Also persist the latest risk level
    journey.risk_level = assessment["risk_level"]
    STORE.save_engagement_journey(journey)
    return assessment


@router.post("/engagement/refresh-risks")
def refresh_all_risks() -> dict:
    """Recalculate risk for all active journeys."""
    journeys = STORE.list_engagement_journeys()
    results = []
    for j in journeys:
        if j.status == "active":
            assessment = compute_risk_assessment(j)
            j.risk_level = assessment["risk_level"]
            STORE.save_engagement_journey(j)
            results.append({
                "journey_id": j.id,
                "candidate_name": j.candidate_name,
                "risk_level": assessment["risk_level"],
                "overall_score": assessment["overall_score"],
            })
    return {"refreshed": len(results), "journeys": results}


# ---------------------------------------------------------------------------
# Intent-based reply matching
# ---------------------------------------------------------------------------

# Keywords that signal a reply relates to a specific onboarding touchpoint.
# Each key is a touchpoint kind; the value is a set of lowercase keywords/
# phrases. The matcher scores each sent touchpoint by how many of its
# keywords appear in the candidate's reply, and picks the highest scorer.
# Ties fall back to the most recently sent touchpoint.
_TOUCHPOINT_KEYWORDS: Dict[str, List[str]] = {
    "welcome_whatsapp": [
        "welcome", "thank", "thanks", "excited", "looking forward",
        "joining", "happy", "offer", "accept",
        "role", "r&r", "roles and responsibilities", "designation",
        "job description", "jd", "thinking", "still thinking",
        "not decided", "come back to me",
    ],
    "buddy_intro": [
        "buddy", "mentor", "connect", "meet", "introduction",
        "guide", "assigned",
    ],
    "document_checklist": [
        "document", "documents", "upload", "pan", "aadhaar", "aadhar",
        "passport", "id proof", "address proof", "bank statement",
        "salary slip", "payslip", "certificate", "marksheet",
    ],
    "culture_video": [
        "culture", "video", "watched", "inspiring", "values",
        "mission", "life at axis", "workplace",
    ],
    "employee_stories": [
        "stories", "story", "employee", "experience", "journey",
        "testimonial", "read", "blog",
    ],
    "benefits_overview": [
        "benefits", "insurance", "health", "leave", "perks",
        "salary", "compensation", "ctc", "pf", "provident",
        "gratuity", "medical",
    ],
    "weekly_checkin": [
        "check in", "checkin", "check-in", "update", "how are",
        "doing well", "going good", "fine", "all good", "settled",
    ],
    "linkedin_connect": [
        "linkedin", "profile", "connected", "connection", "network",
        "social", "follow",
    ],
    "it_setup_form": [
        "laptop", "it setup", "system", "email id", "credentials",
        "login", "access", "id card", "equipment", "hardware",
        "software", "vpn", "device",
        # Direct answers to "Laptop preference — Windows or Mac?" prompt.
        # Without these, a reply like "Ofcourse Mac! Who wants windows now
        # days" scored zero across every category and fell back to the most
        # recent touchpoint (incorrectly tagged to welcome_whatsapp).
        "mac", "macbook", "windows", "linux", "ubuntu", "chromebook",
        "prefer", "preference", "firstname.lastname", "firstname",
        "lastname", "email format", "email style", "email prefer",
        "special software", "specific software", "special tool",
        "ide", "editor", "wfh", "work from home",
    ],
    "team_intro_call": [
        "team", "call", "meeting", "intro", "manager", "colleagues",
        "schedule", "calendar",
    ],
    "dress_code_tips": [
        "dress", "attire", "formal", "casual", "wear", "outfit",
        "clothes",
    ],
    "joining_reminder": [
        "joining", "date", "report", "office", "address", "location",
        "branch", "when", "time", "day one", "first day",
    ],
    "day_one_welcome": [
        "first day", "day one", "arrived", "reached", "reporting",
        "orientation", "induction",
    ],
}


def _match_reply_to_touchpoint(sent_tps: list, reply_body: str):
    """Pick the touchpoint that best matches the candidate's reply.

    Scores each sent touchpoint by counting keyword hits from the reply.
    If no touchpoint scores above zero (generic reply like "ok" or "👍"),
    falls back to the most recently sent touchpoint — the most likely
    target of a short acknowledgement.
    """
    reply_lower = reply_body.lower()
    best_tp = None
    best_score = 0

    for tp in sent_tps:
        keywords = _TOUCHPOINT_KEYWORDS.get(tp.kind, [])
        score = sum(1 for kw in keywords if kw in reply_lower)
        if score > best_score:
            best_score = score
            best_tp = tp

    if best_tp is not None:
        log.info(
            "Intent match: reply '%s' → %s (score %d)",
            reply_body[:60],
            best_tp.kind,
            best_score,
        )
        return best_tp

    # No keyword match — prefer the most recent touchpoint that doesn't
    # already have a candidate_response on it. A reply is almost always
    # answering a still-unanswered prompt, not adding a second reply to a
    # touchpoint that's already been answered.
    unanswered = [t for t in sent_tps if not getattr(t, "candidate_response", None)]
    if unanswered:
        fallback = max(unanswered, key=lambda t: t.sent_at or datetime.min)
        log.info(
            "No intent match for '%s' — falling back to most recent UNANSWERED: %s",
            reply_body[:60],
            fallback.kind,
        )
        return fallback

    # Every touchpoint already has a reply — fall back to overall most recent.
    fallback = max(sent_tps, key=lambda t: t.sent_at or datetime.min)
    log.info(
        "No intent match for '%s' — falling back to most recent: %s",
        reply_body[:60],
        fallback.kind,
    )
    return fallback


# ---------------------------------------------------------------------------
# Dashboard & risk
# ---------------------------------------------------------------------------


@router.get("/engagement/dashboard")
def engagement_dashboard() -> dict:
    """Summary stats for the onboarding dashboard."""
    journeys = STORE.list_engagement_journeys()
    now = datetime.utcnow()
    next_24h = now + timedelta(hours=24)

    active = [j for j in journeys if j.status == "active"]
    at_risk = [j for j in active if j.risk_level in ("medium", "high")]

    # Upcoming touchpoints in the next 24 hours
    upcoming: List[dict] = []
    for j in active:
        for tp in j.touchpoints:
            if tp.status == "pending" and tp.scheduled_at:
                if now <= tp.scheduled_at <= next_24h:
                    upcoming.append(
                        {
                            "journey_id": j.id,
                            "candidate_name": j.candidate_name,
                            "touchpoint_id": tp.id,
                            "kind": tp.kind,
                            "scheduled_at": tp.scheduled_at.isoformat(),
                        }
                    )

    # Completion rates
    total_tps = 0
    completed_tps = 0
    for j in active:
        for tp in j.touchpoints:
            total_tps += 1
            if tp.status in ("sent", "delivered", "read", "skipped"):
                completed_tps += 1

    completion_rate = (completed_tps / total_tps * 100) if total_tps > 0 else 0.0

    # Refresh risk levels + build risk details for each journey
    risk_assessments: Dict[str, Any] = {}
    for j in active:
        assessment = compute_risk_assessment(j)
        j.risk_level = assessment["risk_level"]
        STORE.save_engagement_journey(j)
        risk_assessments[j.id] = assessment

    at_risk = [j for j in active if j.risk_level in ("medium", "high")]

    return {
        "total_active_journeys": len(active),
        "at_risk_count": len(at_risk),
        "upcoming_touchpoints_24h": upcoming,
        "completion_rate_percent": round(completion_rate, 1),
        "journeys": [j.model_dump(mode="json") for j in active],
        "risk_assessments": risk_assessments,
    }


@router.get("/engagement/at-risk")
def at_risk_journeys() -> List[dict]:
    """Journeys flagged as medium or high risk."""
    journeys = STORE.list_engagement_journeys()
    at_risk = [
        j
        for j in journeys
        if j.risk_level in ("medium", "high") and j.status == "active"
    ]
    return [j.model_dump(mode="json") for j in at_risk]


# ---------------------------------------------------------------------------
# Conversation history & reply
# ---------------------------------------------------------------------------


class ReplyRequest(BaseModel):
    message: str
    reply_to_id: Optional[str] = None
    touchpoint_id: Optional[str] = None


@router.post("/engagement/journeys/{journey_id}/reply")
def reply_to_candidate(journey_id: str, req: ReplyRequest) -> dict:
    """Send a WhatsApp reply from the onboarding team to the candidate."""
    journey = STORE.get_engagement_journey(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail=f"No journey {journey_id}")

    provider = get_whatsapp_provider()
    result = provider.send_text_message(journey.candidate_phone, req.message)

    # If the caller referenced a touchpoint (inline reply from the timeline
    # panel) but not a specific inbound message, link to the most recent
    # inbound reply captured on that touchpoint so the chat-history view
    # renders the reply-quote context.
    resolved_reply_to_id = req.reply_to_id
    if not resolved_reply_to_id and req.touchpoint_id:
        for _m in reversed(journey.conversations):
            if (
                _m.touchpoint_id == req.touchpoint_id
                and _m.direction == "inbound"
            ):
                resolved_reply_to_id = _m.id
                break

    journey.conversations.append(ConversationMessage(
        id=f"msg-{uuid.uuid4().hex[:8]}",
        journey_id=journey.id,
        direction="outbound",
        sender="onboarding_team",
        body=req.message,
        channel="whatsapp",
        whatsapp_message_id=result.message_id if result.success else None,
        status="sent" if result.success else "failed",
        reply_to_id=resolved_reply_to_id,
        touchpoint_id=req.touchpoint_id,
    ))
    journey.updated_at = datetime.utcnow()
    STORE.save_engagement_journey(journey)

    if not result.success:
        raise HTTPException(status_code=502, detail=f"WhatsApp send failed: {result.error}")

    return {"status": "sent", "message_id": result.message_id}


@router.get("/engagement/journeys/{journey_id}/conversations")
def get_conversations(journey_id: str) -> dict:
    """Get full chronological conversation history for a journey."""
    journey = STORE.get_engagement_journey(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail=f"No journey {journey_id}")

    # Sort by timestamp chronologically
    sorted_msgs = sorted(journey.conversations, key=lambda m: m.timestamp)
    return {
        "journey_id": journey_id,
        "candidate_name": journey.candidate_name,
        "candidate_phone": journey.candidate_phone,
        "messages": [m.model_dump(mode="json") for m in sorted_msgs],
        "total": len(sorted_msgs),
    }


# ---------------------------------------------------------------------------
# Retag stale replies
# ---------------------------------------------------------------------------


@router.post("/engagement/retag-replies")
def retag_replies() -> dict:
    """Re-run intent matching on all candidate replies and backfill conversations."""
    retagged = 0
    backfilled = 0
    for journey in STORE.list_engagement_journeys():
        sent_tps = [tp for tp in journey.touchpoints if tp.status in ("sent", "delivered", "read")]
        # Track existing conversation touchpoint_ids to avoid duplicates
        existing_outbound_tp_ids = {
            m.touchpoint_id for m in journey.conversations if m.direction == "outbound"
        }
        existing_inbound_bodies = {
            m.body for m in journey.conversations if m.direction == "inbound"
        }

        # Remove old placeholder messages (e.g. "[welcome_whatsapp] Touchpoint sent")
        # and replace with real message content
        old_placeholder_ids = set()
        for msg in journey.conversations:
            if msg.direction == "outbound" and msg.body.endswith("] Touchpoint sent"):
                old_placeholder_ids.add(msg.id)
        if old_placeholder_ids:
            journey.conversations = [
                m for m in journey.conversations if m.id not in old_placeholder_ids
            ]
            # Reset outbound tracking so we re-backfill with real content
            existing_outbound_tp_ids = {
                m.touchpoint_id for m in journey.conversations if m.direction == "outbound"
            }

        for tp in journey.touchpoints:
            # Retag mismatched replies
            if tp.candidate_response and sent_tps:
                best = _match_reply_to_touchpoint(sent_tps, tp.candidate_response)
                if best.id != tp.id:
                    best.candidate_response = tp.candidate_response
                    tp.candidate_response = None
                    retagged += 1
                    log.info("Retagged reply from %s to %s", tp.kind, best.kind)

            # Backfill outbound messages for sent touchpoints with real content
            if tp.sent_at and tp.kind not in ("custom",) and tp.id not in existing_outbound_tp_ids:
                message_text = build_message(tp.kind, journey, tp)
                journey.conversations.append(ConversationMessage(
                    id=f"msg-{uuid.uuid4().hex[:8]}",
                    journey_id=journey.id,
                    direction="outbound",
                    sender="system",
                    body=message_text,
                    channel="whatsapp",
                    touchpoint_id=tp.id,
                    whatsapp_message_id=tp.whatsapp_message_id,
                    timestamp=tp.sent_at,
                    status=tp.status,
                ))
                existing_outbound_tp_ids.add(tp.id)
                backfilled += 1

            # Backfill inbound replies
            if tp.candidate_response and tp.candidate_response not in existing_inbound_bodies:
                # Use delivered_at + 1h as approximate reply time, or sent_at + 2h
                reply_time = tp.delivered_at or tp.sent_at or journey.created_at
                if reply_time and tp.sent_at:
                    from datetime import timedelta as _td
                    reply_time = reply_time + _td(hours=1)
                outbound_msg_id = _find_outbound_msg_id(journey, tp.id)
                journey.conversations.append(ConversationMessage(
                    id=f"msg-{uuid.uuid4().hex[:8]}",
                    journey_id=journey.id,
                    direction="inbound",
                    sender=journey.candidate_phone,
                    body=tp.candidate_response,
                    channel="whatsapp",
                    touchpoint_id=tp.id,
                    reply_to_id=outbound_msg_id,
                    timestamp=reply_time or journey.created_at,
                ))
                existing_inbound_bodies.add(tp.candidate_response)
                backfilled += 1

        # Fix up reply_to_id on inbound messages that are missing it
        for msg in journey.conversations:
            if msg.direction == "inbound" and not msg.reply_to_id and msg.touchpoint_id:
                outbound_id = _find_outbound_msg_id(journey, msg.touchpoint_id)
                if outbound_id:
                    msg.reply_to_id = outbound_id

        _refresh_journey_risk(journey)
        STORE.save_engagement_journey(journey)
    return {"retagged": retagged, "backfilled": backfilled}


# ---------------------------------------------------------------------------
# Candidate onboarding chatbot
# ---------------------------------------------------------------------------
#
# Visible on the candidate's Thrive status page once the offer is accepted.
# Lets the candidate ask free-text questions ("what's the travel policy?",
# "what's the culture?", "what does my role actually involve?") and get a
# Claude-grounded answer contextualised to the role they were hired for.
#
# Both the inbound question and the outbound reply are persisted on the
# EngagementJourney as ConversationMessage rows with channel="portal" so
# the onboarding team sees the entire chat in their existing Chat History
# view — no extra UI needed on the internal side.


class OnboardingChatRequest(BaseModel):
    message: str


@router.post("/applications/{app_id}/onboarding-chat")
def onboarding_chat(app_id: str, req: OnboardingChatRequest) -> dict:
    """Candidate → AI assistant chat, grounded in the role-specific KB."""
    from ..services import onboarding_assistant

    app = STORE.get_application(app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    if not app.offer_accepted:
        raise HTTPException(
            status_code=400,
            detail="Onboarding chat is available only after offer acceptance.",
        )

    journey = STORE.get_engagement_journey_by_application(app_id)
    if not journey:
        raise HTTPException(
            status_code=404,
            detail=f"No engagement journey for application {app_id}",
        )

    question = (req.message or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    if len(question) > 2000:
        raise HTTPException(status_code=400, detail="Message too long (max 2000 chars).")

    # Resolve job context for role-aware grounding
    job = STORE.get_job(app.job_id) if app.job_id else None
    job_title = job.title if job else "Axis Bank role"
    job_band = job.band if job else None
    joining = (
        app.expected_joining_date.strftime("%d %b %Y")
        if app.expected_joining_date
        else None
    )

    # Pull prior portal chat history so the assistant has context
    history = [
        {"direction": m.direction, "body": m.body}
        for m in journey.conversations
        if m.channel == "portal"
    ]

    # Persist inbound candidate message
    inbound = ConversationMessage(
        id=f"cm-{uuid.uuid4().hex[:8]}",
        journey_id=journey.id,
        direction="inbound",
        sender=journey.candidate_name or "Candidate",
        body=question,
        channel="portal",
        status="delivered",
    )
    journey.conversations.append(inbound)

    # Call the Claude-backed assistant
    reply = onboarding_assistant.ask(
        question=question,
        candidate_name=journey.candidate_name,
        job_title=job_title,
        job_band=job_band,
        expected_joining_date=joining,
        chat_history=history,
    )

    # Persist outbound assistant message. Citations are stored on the message
    # as internal metadata — the onboarding team sees them in the chat history
    # view, but they are NEVER rendered in the candidate-facing body.
    outbound = ConversationMessage(
        id=f"cm-{uuid.uuid4().hex[:8]}",
        journey_id=journey.id,
        direction="outbound",
        sender="Axis Onboarding Assistant",
        body=reply.answer,
        channel="portal",
        reply_to_id=inbound.id,
        status="delivered",
        citations=reply.citations or [],
    )
    journey.conversations.append(outbound)

    journey.updated_at = datetime.utcnow()
    STORE.save_engagement_journey(journey)

    app.log(
        "engagement",
        f"Onboarding chatbot answered via {reply.source} (role doc: {reply.role_file_used}).",
    )

    # Strip internal citations from the candidate-facing response. The
    # onboarding team sees them via the integrated chat-history view.
    outbound_public = outbound.model_dump(mode="json")
    outbound_public.pop("citations", None)
    return {
        "inbound": inbound.model_dump(mode="json"),
        "outbound": outbound_public,
        "source": reply.source,
        "role_file": reply.role_file_used,
    }


@router.get("/applications/{app_id}/onboarding-chat")
def get_onboarding_chat(app_id: str) -> dict:
    """Return the portal-channel chat transcript for a candidate."""
    app = STORE.get_application(app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    journey = STORE.get_engagement_journey_by_application(app_id)
    if not journey:
        return {"journey_id": None, "messages": []}
    # Candidate-facing endpoint: strip internal citations before returning.
    msgs = []
    for m in journey.conversations:
        if m.channel != "portal":
            continue
        d = m.model_dump(mode="json")
        d.pop("citations", None)
        msgs.append(d)
    msgs.sort(key=lambda m: m.get("timestamp", ""))
    return {"journey_id": journey.id, "messages": msgs, "total": len(msgs)}


# ---------------------------------------------------------------------------
# Dev-only: seed a ready-to-offer candidate so the demo can test the flow.
# Creates a Candidate + Application at stage=OFFER pointing at a real job.
# Idempotent per email — re-POSTing returns the existing app.
# ---------------------------------------------------------------------------


class SeedOfferReadyRequest(BaseModel):
    name: str = "Rohan Desai"
    email: str = "rohan.desai@xebia192.onmicrosoft.com"
    phone: str = "+919876543210"
    job_id: Optional[str] = None  # defaults to first Branch Manager job


@router.post("/dev/seed-offer-ready")
def seed_offer_ready(req: SeedOfferReadyRequest) -> dict:
    """Create (or reuse) a candidate + application sitting at stage=OFFER."""
    from ..models.domain import (
        AgentStatus,
        Application,
        Candidate,
        FunnelStage,
        Profile,
    )

    # Pick the job
    job = None
    if req.job_id:
        job = STORE.get_job(req.job_id)
    if not job:
        # default to first Branch Manager we find (Rohan Desai persona)
        for j in STORE.list_jobs():
            if "branch manager" in (j.title or "").lower():
                job = j
                break
    if not job:
        jobs = STORE.list_jobs()
        if not jobs:
            raise HTTPException(status_code=500, detail="No jobs in the store.")
        job = jobs[0]

    # Reuse existing app if one is already at OFFER for this email
    for a in STORE.list_applications():
        if (
            (STORE.get_candidate(a.candidate_id) or None)
            and STORE.get_candidate(a.candidate_id).profile.email.lower()
            == req.email.lower()
            and a.stage == FunnelStage.OFFER
        ):
            return {
                "reused": True,
                "application_id": a.id,
                "candidate_id": a.candidate_id,
                "job_id": a.job_id,
                "stage": a.stage.value,
            }

    # Build the Candidate
    cand_id = req.email.lower()
    profile = Profile(
        employee_id=cand_id,
        name=req.name,
        email=req.email,
        phone=req.phone,
        current_role="Branch Manager",
        current_location="Pune, India",
        tenure_years=9.0,
        skills=[
            "branch operations",
            "CASA cross-sell",
            "team leadership",
            "KYC compliance",
            "AML",
            "HNI management",
            "Finacle",
            "audit readiness",
            "customer experience",
        ],
    )
    candidate = Candidate(id=cand_id, profile=profile, kind="external")
    if not STORE.get_candidate(cand_id):
        STORE.add_candidate(candidate)

    # Build the Application at OFFER stage
    app_id = f"app-{uuid.uuid4().hex[:8]}"
    app = Application(
        id=app_id,
        candidate_id=cand_id,
        job_id=job.id,
        match_percent=82.0,
        match_rationale=(
            "10 years retail banking, strong CASA + compliance track record, "
            "Flagship-ready leadership profile."
        ),
        matched_skills=[
            "CASA cross-sell",
            "KYC compliance",
            "team leadership",
            "audit readiness",
        ],
        missing_skills=["HNI wealth products"],
        stage=FunnelStage.OFFER,
        agent_status=AgentStatus.WAITING_CANDIDATE_ACCEPTANCE,
        next_action="Awaiting candidate offer decision.",
        candidate_kind="external",
        source="organic",
        candidate_phone=req.phone,
        offer_sent=True,
        offer_sent_at=datetime.utcnow(),
    )
    STORE.add_application(app)
    app.log("system", "Seeded ready-to-offer application for demo testing.")

    return {
        "reused": False,
        "application_id": app.id,
        "candidate_id": cand_id,
        "job_id": job.id,
        "job_title": job.title,
        "stage": app.stage.value,
    }


@router.post("/dev/prune-orphan-journeys")
def prune_orphan_journeys() -> dict:
    """Remove engagement journeys whose application no longer exists."""
    journeys = STORE.list_engagement_journeys()
    removed: List[str] = []
    for j in journeys:
        if not STORE.get_application(j.application_id):
            try:
                STORE.delete_engagement_journey(j.id)
                removed.append(j.id)
            except Exception:
                # Fallback: mark dropped + save to clear from UI
                j.status = "dropped"
                j.drop_reason = "orphan (application missing)"
                STORE.save_engagement_journey(j)
                removed.append(j.id)
    return {"removed": removed, "count": len(removed)}
