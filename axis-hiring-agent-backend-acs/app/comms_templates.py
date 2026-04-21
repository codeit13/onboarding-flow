"""Production HR-grade copy for every outbound communication.

Centralising the templates here keeps the orchestrator readable and ensures
every email + calendar invite reads like a real Axis Bank HR communication —
not a demo. All copy is signed off by "Axis Bank Talent Acquisition" and
references a real reply-to mailbox so candidates and panellists know who is
on the other end.

If you need to rebrand, change the constants at the top of this file — every
email/invite in the system flows through these helpers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional

# ---------------------------------------------------------------------------
# Brand constants (single source of truth)
# ---------------------------------------------------------------------------

BRAND_NAME = "Axis Bank"
BRAND_TEAM = "Talent Acquisition · thrive HR"
BRAND_REPLY_TO = "axis-hiring-agent@Xebia192.onmicrosoft.com"
BRAND_PORTAL_NAME = "Thrive (Axis Bank's internal hiring portal)"
BRAND_TAGLINE = "Badhti ka naam zindagi."

SIGNATURE = (
    f"Warm regards,\n"
    f"{BRAND_TEAM}\n"
    f"{BRAND_NAME}\n"
    f"{BRAND_REPLY_TO}"
)

DISCLAIMER = (
    "This message was sent by the Axis Bank Talent Acquisition team via the "
    "Thrive hiring portal. If you believe you received it in error, please "
    "reply to this email and we will investigate."
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _fmt_slot(start: datetime, end: datetime) -> str:
    """e.g. 'Tuesday, 07 April 2026 · 10:30–11:00 IST'."""
    return (
        f"{start.strftime('%A, %d %B %Y')} · "
        f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')} IST"
    )


def _slot_options(slots: Iterable) -> str:
    lines = []
    for i, s in enumerate(slots, start=1):
        lines.append(
            f"  Option {i}.  {s.start.strftime('%A, %d %B %Y')}  ·  "
            f"{s.start.strftime('%H:%M')}–{s.end.strftime('%H:%M')} IST"
        )
    return "\n".join(lines)


def _hello(name: str) -> str:
    first = (name or "").split(" ")[0] or "there"
    return f"Dear {first},"


# ---------------------------------------------------------------------------
# Email templates — return (subject, body)
# ---------------------------------------------------------------------------


def post_screening_reject(name: str, jd_title: str, jd_location: str) -> tuple[str, str]:
    subject = f"Update on your application — {jd_title}, {jd_location}"
    body = (
        f"{_hello(name)}\n\n"
        f"Thank you for taking the time to apply for the position of "
        f"{jd_title} at our {jd_location} branch.\n\n"
        f"After a careful review of your profile against the requirements "
        f"of this role, we have decided not to move forward with your "
        f"candidature at this time. This decision is in no way a reflection "
        f"of your overall capabilities — Axis Bank receives a very large "
        f"number of strong internal applications for every opening.\n\n"
        f"Your profile remains active on {BRAND_PORTAL_NAME}, and we would "
        f"warmly encourage you to apply for other roles that match your "
        f"experience. We wish you the very best in your continued journey "
        f"with {BRAND_NAME}.\n\n"
        f"{SIGNATURE}\n\n"
        f"---\n{DISCLAIMER}"
    )
    return subject, body


def r1_outreach_with_slots(
    name: str,
    jd_title: str,
    jd_location: str,
    slots: list,
) -> tuple[str, str]:
    subject = f"Round 1 Interview Invitation — {jd_title}, {jd_location}"
    body = (
        f"{_hello(name)}\n\n"
        f"Congratulations! Following the initial screening of your "
        f"profile, we are pleased to invite you to Round 1 of the "
        f"selection process for the position of {jd_title} at our "
        f"{jd_location} branch.\n\n"
        f"Round 1 will be a 30-minute structured interview conducted "
        f"over Microsoft Teams. To make scheduling effortless, our "
        f"hiring assistant has already checked the calendars of the "
        f"interviewing team and identified the following slots:\n\n"
        f"{_slot_options(slots)}\n\n"
        f"Please confirm your preferred slot directly from your "
        f"application page on {BRAND_PORTAL_NAME}. As soon as you "
        f"confirm, you will receive a Microsoft Teams calendar invite "
        f"with the joining link and a short briefing on what to expect "
        f"in the conversation.\n\n"
        f"If none of the proposed slots work for you, simply reply to "
        f"this email and we will reach out with alternatives.\n\n"
        f"We are looking forward to meeting you.\n\n"
        f"{SIGNATURE}\n\n"
        f"---\n{DISCLAIMER}"
    )
    return subject, body


def r1_reject(name: str, jd_title: str) -> tuple[str, str]:
    subject = f"Update on your Round 1 interview — {jd_title}"
    body = (
        f"{_hello(name)}\n\n"
        f"Thank you for taking the time to speak with us in your Round 1 "
        f"interview for {jd_title}.\n\n"
        f"After carefully reviewing the conversation, we have decided not "
        f"to move forward with your candidature for this particular role. "
        f"We genuinely appreciated the perspectives you shared, and want "
        f"to be transparent that this decision was based on the specific "
        f"competency mix that this role requires today.\n\n"
        f"Your profile will remain active on {BRAND_PORTAL_NAME}, and we "
        f"would encourage you to apply for other roles where your strengths "
        f"align even better. Please do not hesitate to reach out if you "
        f"would like more detailed feedback.\n\n"
        f"{SIGNATURE}\n\n"
        f"---\n{DISCLAIMER}"
    )
    return subject, body


def screening_hr_review_summary(
    *,
    candidate_name: str,
    candidate_email: str,
    candidate_role: str,
    candidate_tenure: float,
    jd_title: str,
    jd_location: str,
    jd_threshold: float,
    match_percent: float,
    matched_skills: list,
    missing_skills: list,
    rationale: str,
    hr_review_url: str,
) -> tuple[str, str]:
    """Email sent to the Business Partner the moment intake screening finishes
    BELOW the shortlist threshold. The new product rule (2026-04-07) is
    that the agent NEVER auto-rejects an internal candidate — it always
    surfaces the AI screening report to HR and waits for an explicit
    advance/regret call. The body carries the full screening analysis so
    HR can decide without having to log in (though the link is included).
    """
    delta = match_percent - jd_threshold
    delta_line = (
        f"{delta:+.0f}pp vs the {jd_threshold:.0f}% shortlist threshold"
    )
    subject = (
        f"[Action] Screening review · {candidate_name} · "
        f"{jd_title} · {match_percent:.0f}% ({delta_line})"
    )

    matched_lines = "\n".join(f"  • {s}" for s in (matched_skills or [])) or "  • (none)"
    missing_lines = "\n".join(f"  • {s}" for s in (missing_skills or [])) or "  • (none)"

    body = (
        f"Hi,\n\n"
        f"The AI screening agent has just finished evaluating "
        f"{candidate_name} ({candidate_email}, currently "
        f"{candidate_role}, {candidate_tenure:.1f} yrs tenure) against "
        f"the JD rubric for {jd_title} ({jd_location}).\n\n"
        f"The candidate scored BELOW the shortlist threshold for this "
        f"role, but per the human-in-the-loop rule the agent has NOT "
        f"sent a regret email and has NOT closed the application. The "
        f"decision is yours: please review the screening summary below "
        f"and click Advance to push the candidate into Round 1, or "
        f"Regret to close the application with the standard regret "
        f"email.\n\n"
        f"=== AI SCREENING SUMMARY ===\n"
        f"  Match: {match_percent:.0f}% ({delta_line})\n"
        f"  Rationale: {rationale}\n\n"
        f"=== MATCHED SKILLS ===\n{matched_lines}\n\n"
        f"=== MISSING SKILLS ===\n{missing_lines}\n\n"
        f"---\n"
        f"Open the candidate in Business Partner queue: {hr_review_url}\n\n"
        f"This decision is yours, not the AI's. The AI score is an aid, "
        f"not a gate.\n\n"
        f"{SIGNATURE}\n\n---\n{DISCLAIMER}"
    )
    return subject, body


def r1_hr_review_summary(
    *,
    candidate_name: str,
    candidate_email: str,
    jd_title: str,
    jd_location: str,
    score: float,
    headline: str,
    recommendation: str,
    rubric_scores: dict,
    transcript_pairs: list,
    red_flags: list,
    recommended_probes: list,
    hr_review_url: str,
) -> tuple[str, str]:
    """Email sent to the Business Partner the moment the AI Interview Agent
    finishes Round 1. The Business Partner is the human-in-the-loop — they
    decide whether the candidate moves to R2 or is regretted, NOT the
    AI score threshold. The body carries the full AI analysis so HR
    can decide without having to log in (though the link is included).
    """
    subject = (
        f"[Action] R1 AI interview complete · {candidate_name} · "
        f"{jd_title} · {recommendation.upper()} ({score:.0f}/100)"
    )

    rubric_lines = "\n".join(
        f"  • {skill}: {pct:.0f}%" for skill, pct in (rubric_scores or {}).items()
    ) or "  • (no rubric scores produced)"

    transcript_lines = []
    for i, pair in enumerate(transcript_pairs, start=1):
        q = (pair.get("question") or "").strip()
        a = (pair.get("answer") or "").strip()
        transcript_lines.append(f"Q{i}. {q}\nA{i}. {a}\n")
    transcript_block = "\n".join(transcript_lines) or "(no transcript captured)"

    red_flag_lines = "\n".join(f"  • {rf}" for rf in (red_flags or [])) or "  • (none)"
    probe_lines = "\n".join(f"  • {p}" for p in (recommended_probes or [])) or "  • (none)"

    body = (
        f"Hi,\n\n"
        f"The AI Interview Agent has just finished Round 1 with "
        f"{candidate_name} ({candidate_email}) for {jd_title} "
        f"({jd_location}). Full structured analysis below — please "
        f"review and decide whether to advance the candidate to Round 2 "
        f"with the hiring manager panel, or to regret them.\n\n"
        f"=== AI RECOMMENDATION ===\n"
        f"  Headline: {headline}\n"
        f"  Overall score: {score:.0f}/100\n"
        f"  Recommendation: {recommendation.upper()}\n\n"
        f"=== RUBRIC BREAKDOWN ===\n{rubric_lines}\n\n"
        f"=== RED FLAGS ===\n{red_flag_lines}\n\n"
        f"=== RECOMMENDED PROBES FOR R2 ===\n{probe_lines}\n\n"
        f"=== FULL TRANSCRIPT (Q&A) ===\n{transcript_block}\n"
        f"---\n"
        f"Open the candidate in Business Partner queue: {hr_review_url}\n\n"
        f"This decision is yours, not the AI's. The AI score and "
        f"recommendation are an aid, not a gate.\n\n"
        f"{SIGNATURE}\n\n---\n{DISCLAIMER}"
    )
    return subject, body


def r2_outreach_with_slots(
    name: str,
    jd_title: str,
    jd_location: str,
    slots: list,
    r1_score: Optional[float],
    panel_size: int,
) -> tuple[str, str]:
    score_line = (
        f"Your Round 1 interview was scored {r1_score:.0f}/100 by our "
        f"AI Interview Agent, which is comfortably above the bar for "
        f"progression. "
        if r1_score is not None
        else ""
    )
    subject = f"Round 2 Panel Interview Invitation — {jd_title}, {jd_location}"
    body = (
        f"{_hello(name)}\n\n"
        f"Congratulations on clearing Round 1 of the selection process "
        f"for {jd_title} at our {jd_location} branch. {score_line}"
        f"We are now ready to invite you to Round 2 — a 45-minute panel "
        f"interview with {panel_size} senior leader{'s' if panel_size != 1 else ''} "
        f"from the hiring team.\n\n"
        f"Our hiring assistant has cross-checked the calendars of all the "
        f"panellists and identified the following common slots:\n\n"
        f"{_slot_options(slots)}\n\n"
        f"Please confirm your preferred slot from your application page "
        f"on {BRAND_PORTAL_NAME}. Once you confirm, you will receive a "
        f"Microsoft Teams calendar invite with the joining link, the panel "
        f"composition, and a short note on the focus areas the panel will "
        f"explore. The panel will already have read the AI interviewer's "
        f"Round 1 report ahead of the meeting, so the conversation can "
        f"start at depth.\n\n"
        f"If none of the proposed slots work for you, please reply to this "
        f"email and we will work with the panel to find an alternative.\n\n"
        f"We look forward to taking this conversation further.\n\n"
        f"{SIGNATURE}\n\n"
        f"---\n{DISCLAIMER}"
    )
    return subject, body


def offer_email(
    name: str,
    jd_title: str,
    jd_location: str,
    r1_score: float,
    r2_score: float,
) -> tuple[str, str]:
    subject = f"Offer of Employment — {jd_title}, {jd_location}"
    body = (
        f"{_hello(name)}\n\n"
        f"It gives us great pleasure to extend an offer for the position "
        f"of {jd_title} at our {jd_location} branch.\n\n"
        f"The hiring panel was unanimous in their recommendation. For "
        f"context, your Round 1 AI interview was scored {r1_score:.0f}/100 "
        f"and the Round 2 panel rated you {r2_score:.0f}/100, both well "
        f"above the bar for this role.\n\n"
        f"Your HR Business Partner will reach out to you within the next "
        f"two working days with the formal offer letter, the proposed "
        f"compensation structure, and the joining formalities. In the "
        f"meantime, please do reach out to us if you have any questions "
        f"about the role, the team, or the next steps.\n\n"
        f"On behalf of {BRAND_NAME} — welcome aboard. We are very excited "
        f"to have you join us on this journey.\n\n"
        f"{BRAND_TAGLINE}\n\n"
        f"{SIGNATURE}\n\n"
        f"---\n{DISCLAIMER}"
    )
    return subject, body


def final_offer_email(
    name: str,
    jd_title: str,
    jd_location: str,
    final_ctc: float,
    notes: str = "",
    r1_score: Optional[float] = None,
    r2_score: Optional[float] = None,
) -> tuple[str, str]:
    """Formal offer letter sent by the Offer Discussion Team.

    Differs from ``offer_email`` in that the CTC has already been
    negotiated against the candidate's salary scripts, so the email
    contains the *agreed* CTC, not a placeholder. Sent only when the
    Offer Discussion Team clicks "Roll out final offer" — never
    automatically as part of the R2 decision flow.
    """
    subject = f"Your formal offer from Axis Bank — {jd_title}, {jd_location}"
    score_line = ""
    if r1_score is not None and r2_score is not None:
        score_line = (
            f"For context, your Round 1 AI interview was scored "
            f"{r1_score:.0f}/100 and the Round 2 panel rated you "
            f"{r2_score:.0f}/100 — both well above the bar.\n\n"
        )
    notes_line = f"Negotiation notes from our Offer Discussion Team:\n{notes}\n\n" if notes else ""
    body = (
        f"{_hello(name)}\n\n"
        f"Following your panel interview and our subsequent compensation "
        f"discussion, we are delighted to formally extend you an offer for "
        f"the role of {jd_title} at our {jd_location} branch.\n\n"
        f"Agreed annual CTC: ₹{final_ctc:,.0f} per annum (gross).\n\n"
        f"{score_line}"
        f"{notes_line}"
        f"The detailed offer letter — covering the fixed/variable split, "
        f"joining bonus, leave policy and statutory benefits — has been "
        f"prepared by our Offer Discussion Team and will reach you on a "
        f"separate email within the next working day. Please review at your "
        f"convenience and revert with your acceptance via the link in that "
        f"email.\n\n"
        f"On behalf of {BRAND_NAME} — welcome aboard. We are very excited "
        f"to have you join us on this journey.\n\n"
        f"{BRAND_TAGLINE}\n\n"
        f"{SIGNATURE}\n\n"
        f"---\n{DISCLAIMER}"
    )
    return subject, body


def r2_reject(name: str, jd_title: str) -> tuple[str, str]:
    subject = f"Update on your Round 2 panel interview — {jd_title}"
    body = (
        f"{_hello(name)}\n\n"
        f"Thank you for the time you invested in the Round 2 panel "
        f"interview for {jd_title}. We genuinely enjoyed the conversation "
        f"and appreciated the depth you brought to the discussion.\n\n"
        f"After careful deliberation, the panel has decided not to move "
        f"forward with your candidature for this specific role. This was "
        f"a close decision and was driven by the very particular mix of "
        f"experience this role demands today.\n\n"
        f"Your profile will remain active on {BRAND_PORTAL_NAME}, and we "
        f"would warmly encourage you to consider other roles within "
        f"{BRAND_NAME}. We sincerely thank you for your interest in being "
        f"part of our team.\n\n"
        f"{SIGNATURE}\n\n"
        f"---\n{DISCLAIMER}"
    )
    return subject, body


# ---------------------------------------------------------------------------
# Calendar invite templates — return (subject, body)
# ---------------------------------------------------------------------------


def r1_calendar_invite(
    name: str,
    jd_title: str,
    jd_location: str,
    start: datetime,
    end: datetime,
    employee_id: str,
) -> tuple[str, str]:
    subject = f"Round 1 Interview · {jd_title} · {name}"
    body = (
        f"Round 1 Interview — {BRAND_NAME}\n"
        f"==================================\n\n"
        f"Candidate:        {name}  (Employee ID: {employee_id})\n"
        f"Position:         {jd_title}\n"
        f"Location:         {jd_location}\n"
        f"Round:            1 of 2  ·  AI-led structured interview\n"
        f"Duration:         30 minutes\n"
        f"When:             {_fmt_slot(start, end)}\n\n"
        f"Agenda\n"
        f"------\n"
        f"  1. Brief introductions and context-setting   (3 min)\n"
        f"  2. Role-relevant experience deep dive       (15 min)\n"
        f"  3. Scenario-based competency questions       (8 min)\n"
        f"  4. Candidate questions about the role        (4 min)\n\n"
        f"How this works\n"
        f"--------------\n"
        f"This is a structured interview led by Axis Bank's AI Interview "
        f"Agent. The conversation is recorded for quality and assessment "
        f"purposes only, and the transcript is reviewed by a member of "
        f"the {BRAND_TEAM} team within 24 hours of the interview.\n\n"
        f"What to bring\n"
        f"-------------\n"
        f"  • A quiet space with a stable internet connection\n"
        f"  • Headphones or a good-quality microphone\n"
        f"  • Two or three concrete examples from your recent work that "
        f"speak directly to this role\n\n"
        f"If you need to reschedule, please reply to this invite and we "
        f"will reach out with alternative slots.\n\n"
        f"{SIGNATURE}"
    )
    return subject, body


def r2_calendar_invite(
    name: str,
    jd_title: str,
    jd_location: str,
    start: datetime,
    end: datetime,
    employee_id: str,
    panel_names: List[str],
    r1_score: Optional[float],
    r1_headline: Optional[str],
    r1_recommendation: Optional[str],
    recommended_probes: Optional[List[str]],
) -> tuple[str, str]:
    subject = f"Round 2 Panel Interview · {jd_title} · {name}"

    panel_block = "\n".join(f"  • {p}" for p in panel_names) if panel_names else "  • (panel TBD)"
    score_line = (
        f"Round 1 score:    {r1_score:.0f}/100 — {r1_recommendation or 'progress'}"
        if r1_score is not None
        else "Round 1 score:    pending"
    )
    headline_line = f"AI headline:      {r1_headline}" if r1_headline else ""
    probes_block = (
        "\n".join(f"  • {p}" for p in (recommended_probes or []))
        if recommended_probes
        else "  • (no specific probes — open discussion)"
    )

    body = (
        f"Round 2 Panel Interview — {BRAND_NAME}\n"
        f"==========================================\n\n"
        f"Candidate:        {name}  (Employee ID: {employee_id})\n"
        f"Position:         {jd_title}\n"
        f"Location:         {jd_location}\n"
        f"Round:            2 of 2  ·  Hiring panel interview\n"
        f"Duration:         45 minutes\n"
        f"When:             {_fmt_slot(start, end)}\n"
        f"{score_line}\n"
        f"{headline_line}\n\n"
        f"Panel\n"
        f"-----\n"
        f"{panel_block}\n\n"
        f"Agenda\n"
        f"------\n"
        f"  1. Panel introductions                       (5 min)\n"
        f"  2. Candidate walk-through of recent work    (10 min)\n"
        f"  3. Panel deep-dive on probes (below)        (20 min)\n"
        f"  4. Candidate questions for the panel        (10 min)\n\n"
        f"Recommended panel probes (from the AI Round 1 report)\n"
        f"-----------------------------------------------------\n"
        f"{probes_block}\n\n"
        f"For the panel\n"
        f"-------------\n"
        f"The full AI Interview Agent report from Round 1 (transcript, "
        f"competency scores, strengths and risk areas) is attached to this "
        f"application on the panel dashboard in {BRAND_PORTAL_NAME}. Please "
        f"submit your structured feedback via the same dashboard within "
        f"24 hours of the interview — the orchestrator will not move the "
        f"candidate forward until every panellist has voted.\n\n"
        f"For the candidate\n"
        f"-----------------\n"
        f"Please join the Microsoft Teams meeting using the link in this "
        f"invite. If you need to reschedule, reply to this invite and we "
        f"will work with the panel to find an alternative.\n\n"
        f"{SIGNATURE}"
    )
    return subject, body
