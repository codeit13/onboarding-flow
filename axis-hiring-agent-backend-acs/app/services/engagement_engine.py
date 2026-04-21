"""Engagement engine -- background worker that dispatches due WhatsApp touchpoints.

Mirrors the daemon-thread pattern in ``inbox_poller.py``. Periodically sweeps
all active engagement journeys and sends any touchpoint whose ``scheduled_at``
has arrived and whose ``status`` is still ``"pending"``.

Each touchpoint kind maps to a rich, warm, human message with deep links
back to the candidate portal — no bland template stubs.

Configuration
-------------
    AXIS_ENGAGEMENT_POLL_SEC  -- poll interval in seconds (default 30)
    AXIS_WHATSAPP_PROVIDER    -- "twilio" / "meta" / "mock" (default)
    AXIS_PORTAL_BASE_URL      -- candidate portal URL for deep links
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Dict, Optional

from ..models.engagement import ConversationMessage, EngagementJourney, EngagementTouchpoint
from ..providers import get_whatsapp_provider
from ..providers.whatsapp import WhatsAppSendResult
from ..store import STORE

log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = float(os.getenv("AXIS_ENGAGEMENT_POLL_SEC", "30"))
PORTAL_BASE = os.getenv("AXIS_PORTAL_BASE_URL", "http://localhost:3101")


# ---------------------------------------------------------------------------
# Rich message content builder
# ---------------------------------------------------------------------------
# Each touchpoint kind → a function that returns the full WhatsApp message
# text, personalised for this candidate. Messages are warm, human, and
# include deep links back to the portal for actions.


def _msg_welcome(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    join_str = (
        j.expected_joining_date.strftime("%d %B %Y")
        if j.expected_joining_date
        else "soon"
    )
    return (
        f"Hey {first}! 🎉\n\n"
        f"Welcome to the Axis Bank family! We're genuinely excited that you've "
        f"accepted the offer — your journey with us starts now.\n\n"
        f"Your joining date is *{join_str}*. Between now and then, we'll stay in "
        f"touch with everything you need — from documents to team introductions "
        f"to helpful tips for your first day.\n\n"
        f"You can track your entire onboarding journey here:\n"
        f"{PORTAL_BASE}/thrive\n\n"
        f"If you have any questions at all, just reply to this message. "
        f"We're here for you! 💜"
    )


def _msg_buddy_intro(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    buddy = j.buddy_name or "a team member"
    buddy_email = f" ({j.buddy_email})" if j.buddy_email else ""
    return (
        f"Hi {first}! 👋\n\n"
        f"We've paired you with *{buddy}*{buddy_email} as your onboarding buddy. "
        f"They'll be your go-to person for anything — from \"where's the best "
        f"coffee near the office?\" to \"how does the leave system work?\"\n\n"
        f"Feel free to reach out to them before your first day. They're looking "
        f"forward to meeting you!\n\n"
        f"Having a buddy made 87% of our new joiners feel more confident "
        f"on Day 1. 😊"
    )


def _msg_document_checklist(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    return (
        f"Hi {first}! 📋\n\n"
        f"Here's your joining document checklist — having these ready will make "
        f"your first day smooth:\n\n"
        f"✅ PAN Card (original + photocopy)\n"
        f"✅ Aadhaar Card\n"
        f"✅ Last 3 months' salary slips\n"
        f"✅ Relieving letter from current employer\n"
        f"✅ 4 passport-size photographs\n"
        f"✅ Cancelled cheque / bank details\n"
        f"✅ Educational certificates (originals for verification)\n\n"
        f"You can upload documents securely through your portal:\n"
        f"{PORTAL_BASE}/thrive\n\n"
        f"Don't worry if you're still waiting on your relieving letter — "
        f"just bring what you have on Day 1 and we'll work the rest out together."
    )


def _msg_culture_video(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    return (
        f"Hi {first}! 🎬\n\n"
        f"We thought you'd enjoy a peek at life inside Axis Bank before "
        f"you officially join!\n\n"
        f"🏢 *Our Culture* — At Axis, we believe in \"Dil Se Open\" — being "
        f"genuinely open to ideas, people, and possibilities. You'll find a "
        f"workplace that values curiosity and collaboration over hierarchy.\n\n"
        f"🎥 Watch our culture story: https://www.axisbank.com/about-us\n\n"
        f"🌟 *What makes us different:*\n"
        f"• Flat team structures — your ideas matter from Day 1\n"
        f"• Innovation labs where anyone can pitch\n"
        f"• 30+ employee resource groups to connect with\n"
        f"• Award-winning L&D programmes\n\n"
        f"What aspect of Axis Bank are you most curious about? "
        f"Reply and we'll connect you with the right people! 🙌"
    )


def _msg_employee_stories(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    return (
        f"Hi {first}! 💬\n\n"
        f"Here's what some of our recent joiners had to say about their "
        f"first few months at Axis Bank:\n\n"
        f"🗣️ *Priya, Product Manager (joined 6 months ago):*\n"
        f"\"I was nervous about switching from a startup, but the team made me "
        f"feel at home from literally Day 1. My manager actually asked ME what "
        f"tools I preferred.\"\n\n"
        f"🗣️ *Rahul, Tech Lead (joined 3 months ago):*\n"
        f"\"The tech stack surprised me — we're using cutting-edge tools and "
        f"the engineering culture is much more modern than I expected from a bank.\"\n\n"
        f"🗣️ *Ananya, Risk Analyst (joined 8 months ago):*\n"
        f"\"The learning opportunities are incredible. I've already done two "
        f"certifications sponsored by Axis.\"\n\n"
        f"We can't wait to hear your story a few months from now! 😊\n\n"
        f"Explore more about life at Axis: https://www.axisbank.com/careers"
    )


def _msg_benefits_overview(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    return (
        f"Hi {first}! 🎁\n\n"
        f"Here's a quick overview of the benefits waiting for you at Axis Bank "
        f"— beyond what's in your offer letter:\n\n"
        f"🏥 *Health & Wellness*\n"
        f"• Comprehensive medical insurance (family covered)\n"
        f"• Annual health check-ups\n"
        f"• Mental wellness programme & counselling\n\n"
        f"📚 *Growth & Learning*\n"
        f"• Certification reimbursements\n"
        f"• Internal mobility programme\n"
        f"• Leadership development tracks\n\n"
        f"🏖️ *Work-Life Balance*\n"
        f"• Flexible working arrangements\n"
        f"• Generous leave policy\n"
        f"• Employee assistance programme\n\n"
        f"💰 *Financial Perks*\n"
        f"• Preferential rates on Axis Bank products\n"
        f"• Employee stock options (eligible roles)\n"
        f"• Performance bonuses\n\n"
        f"Any questions about your benefits? Just reply here! 🙂"
    )


def _msg_weekly_checkin(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    days_left = None
    if j.expected_joining_date:
        days_left = (j.expected_joining_date - datetime.utcnow()).days
    days_str = f"{days_left} days" if days_left and days_left > 0 else "very soon"
    return (
        f"Hey {first}! 👋\n\n"
        f"Just checking in — how are you doing? Your joining date is "
        f"*{days_str}* away and we're getting everything ready for you.\n\n"
        f"Is there anything on your mind? Any questions about:\n"
        f"• Your role or team?\n"
        f"• The office location or commute?\n"
        f"• Documents or formalities?\n"
        f"• Anything else at all?\n\n"
        f"Simply reply to this message — we're here to help make this "
        f"transition as smooth as possible. 💜\n\n"
        f"Track your onboarding progress: {PORTAL_BASE}/thrive"
    )


def _msg_linkedin_connect(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    return (
        f"Hi {first}! 🔗\n\n"
        f"Want to start connecting with your future colleagues before Day 1?\n\n"
        f"Here are a few ways to get a head start:\n\n"
        f"1️⃣ Follow *Axis Bank* on LinkedIn for the latest news and culture posts\n"
        f"2️⃣ Join our internal communities (we'll send you the links on Day 1)\n"
        f"3️⃣ Feel free to update your LinkedIn with \"Joining Axis Bank\" — "
        f"our team loves welcoming new members!\n\n"
        f"Many new joiners tell us that connecting early helped them feel "
        f"like part of the team even before their first day. 🤝\n\n"
        f"Axis Bank LinkedIn: https://www.linkedin.com/company/axis-bank/"
    )


def _msg_it_setup(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    return (
        f"Hi {first}! 💻\n\n"
        f"We're getting your workstation and IT access ready! To make sure "
        f"everything is set up for Day 1, we need a few details:\n\n"
        f"1️⃣ *Laptop preference* — Windows or Mac? (where applicable)\n"
        f"2️⃣ *Preferred email format* — firstname.lastname or another style?\n"
        f"3️⃣ *Any special software* you'll need for your role?\n\n"
        f"Simply reply with your preferences and our IT team will have "
        f"everything configured before you walk in.\n\n"
        f"🔐 You'll receive your Axis Bank email credentials and VPN access "
        f"on your first day.\n\n"
        f"Complete your IT setup form: {PORTAL_BASE}/thrive"
    )


def _msg_team_intro_call(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    buddy = j.buddy_name or "your team"
    return (
        f"Hi {first}! 🤝\n\n"
        f"We'd love to set up a casual virtual coffee chat with {buddy} and "
        f"a few of your future teammates before your first day — no agenda, "
        f"just friendly faces!\n\n"
        f"This is a chance to:\n"
        f"• Put faces to names before Day 1\n"
        f"• Ask any informal questions\n"
        f"• Get tips about the team's working style\n"
        f"• Learn about your team's favourite lunch spots 😄\n\n"
        f"Would you be available for a 20-minute video call this week? "
        f"Reply with a couple of times that work for you and we'll set it up!\n\n"
        f"No pressure at all — if you'd rather wait until Day 1, that's "
        f"perfectly fine too. 🙂"
    )


def _msg_dress_code(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    return (
        f"Hi {first}! 👔\n\n"
        f"Your first day is coming up and we know the \"what do I wear?\" "
        f"question is real! Here's the quick guide:\n\n"
        f"👕 *Day-to-day:* Smart business casual. Think chinos/trousers + "
        f"a collared shirt or smart top. Jeans are fine on Fridays!\n\n"
        f"👟 *Shoes:* Clean, professional. Sneakers are okay on casual days.\n\n"
        f"🎒 *What to bring on Day 1:*\n"
        f"• Your joining documents (see the checklist we shared earlier)\n"
        f"• A government photo ID for security check-in\n"
        f"• A notebook — there's a lot of exciting stuff to take in!\n"
        f"• Your smile 😊\n\n"
        f"We'll have your welcome kit ready — laptop, ID card, and a few "
        f"Axis Bank surprises waiting at your desk. 🎁"
    )


def _msg_joining_reminder(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    join_str = (
        j.expected_joining_date.strftime("%A, %d %B %Y")
        if j.expected_joining_date
        else "your joining date"
    )
    return (
        f"Hi {first}! 📅\n\n"
        f"Just 3 days to go! Here's your Day 1 checklist for *{join_str}*:\n\n"
        f"⏰ *Arrival:* 9:00 AM at the main reception\n"
        f"📍 *Location:* Ask for the HR / People Team desk — they'll be "
        f"expecting you\n"
        f"📄 *Bring:* Your joining documents + government photo ID\n"
        f"🅿️ *Parking:* Available in the basement (mention you're a new joiner "
        f"at the gate)\n\n"
        f"*Your first day schedule:*\n"
        f"9:00 – Welcome & security badge\n"
        f"9:30 – HR orientation & paperwork\n"
        f"10:30 – IT setup & laptop handover\n"
        f"11:30 – Team introduction with your manager\n"
        f"12:30 – Lunch with your buddy! 🍽️\n\n"
        f"We've got everything ready for you. See you soon! 🎉\n\n"
        f"Any last-minute questions? Reply here anytime."
    )


def _msg_day_one_welcome(j: EngagementJourney, tp: EngagementTouchpoint) -> str:
    first = j.candidate_name.split()[0] if j.candidate_name else "there"
    return (
        f"Good morning {first}! 🌅\n\n"
        f"TODAY IS THE DAY! 🎉🎉🎉\n\n"
        f"Welcome to Axis Bank — officially! Your team is excited to meet you "
        f"and your desk is all set up.\n\n"
        f"A few friendly reminders:\n"
        f"📍 Head to the main reception and ask for the People Team\n"
        f"☕ Grab a coffee — it's going to be a great first day\n"
        f"😊 Relax — everyone remembers their first day and we'll make "
        f"yours special\n\n"
        f"Your buddy will meet you after orientation. If you need anything "
        f"at all today, reply here or find any team member — we're all here "
        f"to help.\n\n"
        f"Welcome to the family, {first}! 💜🏦"
    )


# ---------------------------------------------------------------------------
# Kind → message builder mapping
# ---------------------------------------------------------------------------

_MESSAGE_BUILDERS: Dict[str, callable] = {
    "welcome_whatsapp": _msg_welcome,
    "buddy_intro": _msg_buddy_intro,
    "document_checklist": _msg_document_checklist,
    "culture_video": _msg_culture_video,
    "employee_stories": _msg_employee_stories,
    "benefits_overview": _msg_benefits_overview,
    "weekly_checkin": _msg_weekly_checkin,
    "linkedin_connect": _msg_linkedin_connect,
    "it_setup_form": _msg_it_setup,
    "team_intro_call": _msg_team_intro_call,
    "dress_code_tips": _msg_dress_code,
    "joining_reminder": _msg_joining_reminder,
    "day_one_welcome": _msg_day_one_welcome,
}


def build_message(
    kind: str, journey: EngagementJourney, tp: EngagementTouchpoint
) -> str:
    """Build the full WhatsApp message text for a touchpoint."""
    builder = _MESSAGE_BUILDERS.get(kind)
    if builder:
        return builder(journey, tp)
    # Fallback for custom or unknown kinds
    first = journey.candidate_name.split()[0] if journey.candidate_name else "there"
    return (
        f"Hi {first}! 👋\n\n"
        f"This is a message from the Axis Bank onboarding team. "
        f"If you have any questions, just reply here!\n\n"
        f"{PORTAL_BASE}/thrive"
    )


# Keep _resolve_template for backward compat with routes/engagement.py
def _resolve_template(
    kind: str, journey: EngagementJourney, tp: EngagementTouchpoint
) -> tuple:
    """Legacy compat — returns (template_name, params). Routes use this."""
    first = journey.candidate_name.split()[0] if journey.candidate_name else "there"
    return (kind, {"1": first})


# ---------------------------------------------------------------------------
# Core tick
# ---------------------------------------------------------------------------


def _process_journey(journey: EngagementJourney, now: datetime) -> int:
    """Send all due touchpoints for a single journey. Returns count sent."""
    if not journey.whatsapp_opted_in:
        return 0

    wa = get_whatsapp_provider()
    sent_count = 0

    for tp in journey.touchpoints:
        if tp.status != "pending":
            continue
        if tp.scheduled_at > now:
            continue

        # Build the rich, personalised message
        message_text = build_message(tp.kind, journey, tp)

        # Send as a free-form text message (not a template)
        result: WhatsAppSendResult = wa.send_text_message(
            to_phone=journey.candidate_phone,
            text=message_text,
        )

        if result.success:
            tp.status = "sent"
            tp.sent_at = now
            tp.whatsapp_message_id = result.message_id
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
            log.info(
                "engagement: sent %s to %s (journey=%s, msg=%s)",
                tp.kind,
                journey.candidate_phone,
                journey.id,
                result.message_id,
            )
        else:
            tp.status = "failed"
            tp.error_message = result.error
            log.warning(
                "engagement: failed %s to %s (journey=%s): %s",
                tp.kind,
                journey.candidate_phone,
                journey.id,
                result.error,
            )

        sent_count += 1

    if sent_count > 0:
        journey.updated_at = now
        STORE.save_engagement_journey(journey)

    return sent_count


def tick() -> int:
    """One pass over all active journeys. Returns total touchpoints dispatched."""
    now = datetime.utcnow()
    total = 0
    active = [j for j in STORE.list_engagement_journeys() if j.status == "active"]
    for journey in active:
        try:
            total += _process_journey(journey, now)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "engagement: error processing journey %s: %r", journey.id, exc
            )
    return total


# ---------------------------------------------------------------------------
# Daemon thread (mirrors inbox_poller pattern)
# ---------------------------------------------------------------------------

_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def _loop() -> None:
    log.info("engagement engine: starting (interval=%ss)", POLL_INTERVAL_SEC)
    while not _stop_event.is_set():
        try:
            dispatched = tick()
            if dispatched:
                log.info("engagement engine: dispatched %d touchpoints", dispatched)
        except Exception as exc:  # noqa: BLE001
            log.warning("engagement engine: unhandled error in poll loop: %r", exc)
        _stop_event.wait(POLL_INTERVAL_SEC)


def start_engagement_engine() -> None:
    """Idempotent -- safe to call from FastAPI startup."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(
        target=_loop, name="engagement-engine", daemon=True
    )
    _thread.start()


def stop_engagement_engine() -> None:
    _stop_event.set()
