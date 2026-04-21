"""ACS Teams Interview Agent — high-level service.

Wraps the low-level ``AcsProvider`` (Azure Communication Services Call
Automation, or its offline mock) with the hiring-agent business logic:

  1. Build a JD-aware question list (Claude when available, deterministic
     fallback otherwise).
  2. Kick off the call (provider joins the Teams meeting via the join URL
     produced by the existing Graph calendar provider).
  3. Stash the live session id on the application's R1 InterviewRecord
     so the polling endpoints + frontend can read live status.
  4. After the call ends, fold the synthesised transcript back into
     ``InterviewRecord.transcript`` so the existing scoring + report
     pipeline (build_r1_report, score_interview_transcript) keeps
     working unchanged.

This is intentionally an ALTERNATE path to ``run_virtual_interview`` —
when the operator flips the candidate's R1 onto the ACS bot, the
scripted transcript path is bypassed and the real ACS bot runs the
conversation. Both paths land on the same downstream pipeline.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from ..models import (
    Application,
    InterviewRecord,
    Job,
    Profile,
    TranscriptSegment,
)
from ..providers import AcsCallSession, get_acs_provider

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------


_FALLBACK_QUESTIONS: List[str] = [
    "To start, walk me through your last 12 months in role — the two or "
    "three things you owned end-to-end and what the outcome was.",
    "Tell me about a time you had to push back on a senior stakeholder. "
    "What was at stake, and how did you make the case?",
    "How do you think about cross-sell so it doesn't become pushy? Give "
    "me a real example from your current branch or zone.",
    "What's the single biggest risk to your current book in the next 12 "
    "months, and what are you doing about it today?",
    "Tell me about a regulatory or compliance miss you caught — how did "
    "you handle it, and what changed in your process afterwards?",
    "What's a weakness you're actively working on right now?",
]


def build_question_list(*, job: Job, profile: Profile) -> List[str]:
    """Build the question list the bot will read out in the Teams call.

    Tries Claude first (so questions are JD- and profile-specific) and
    falls back to a strong default list if Claude is unavailable. Either
    way returns 5–7 questions.
    """
    try:
        from .claude_panel_recommender import _call_anthropic, _model  # type: ignore

        system = (
            "You are the Axis Bank AI Interview Agent. You will conduct a "
            "Round 1 interview with a real candidate over a Microsoft "
            "Teams call. Generate 5 to 7 open-ended interview questions "
            "tailored to the role and the candidate's background. Each "
            "question should be one or two sentences, conversational, and "
            "cover ownership, judgement, technical depth, regulatory "
            "awareness, and self-awareness. Return ONLY a JSON array of "
            "strings, no preamble."
        )
        user = (
            f"Role: {job.title}\n"
            f"Function: {job.function}\n"
            f"Required skills: {', '.join(job.required_skills) or 'n/a'}\n"
            f"Candidate name: {profile.name}\n"
            f"Current role: {profile.current_role}\n"
            f"Tenure: {profile.tenure_years} years\n"
            f"Skills: {', '.join(profile.skills) or 'n/a'}\n"
        )
        raw = _call_anthropic(system=system, user=user, model=_model())
        import json
        import re

        match = re.search(r"\[[\s\S]*\]", raw)
        if match:
            questions = json.loads(match.group(0))
            cleaned = [q.strip() for q in questions if isinstance(q, str) and q.strip()]
            if 3 <= len(cleaned) <= 12:
                return cleaned
    except Exception as exc:  # noqa: BLE001
        log.info("ACS question generator falling back to defaults (%s)", exc)
    return list(_FALLBACK_QUESTIONS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_acs_interview(
    *,
    application: Application,
    job: Job,
    profile: Profile,
    interview: InterviewRecord,
) -> AcsCallSession:
    """Kick off the ACS bot to join the Teams meeting on this R1."""
    if not interview.teams_join_url:
        raise ValueError(
            "InterviewRecord has no teams_join_url — schedule the meeting first"
        )
    questions = build_question_list(job=job, profile=profile)
    provider = get_acs_provider()
    session = provider.join_teams_meeting(
        application_id=application.id,
        teams_join_url=interview.teams_join_url,
        questions=questions,
    )
    interview.acs_call_id = session.call_id
    interview.acs_state = session.state
    application.log(
        "agent",
        f"ACS Teams interview agent dispatched — call {session.call_id}, "
        f"{len(questions)} questions queued",
    )
    return session


def get_acs_interview_status(
    *, interview: InterviewRecord
) -> Optional[Dict]:
    """Return the live session status for polling endpoints."""
    if not interview.acs_call_id:
        return None
    provider = get_acs_provider()
    session = provider.get_session(interview.acs_call_id)
    if session is None:
        return None
    interview.acs_state = session.state
    return session.to_public_dict()


def finalise_acs_interview(
    *, application: Application, interview: InterviewRecord
) -> Optional[Dict]:
    """When the bot finishes, fold the captured transcript back into the
    existing InterviewRecord.transcript so the downstream R1 scoring +
    report pipeline runs against real data."""
    if not interview.acs_call_id:
        return None
    provider = get_acs_provider()
    session = provider.get_session(interview.acs_call_id)
    if session is None:
        return None
    if session.state not in ("ended", "failed"):
        return session.to_public_dict()  # not ready yet

    # Replace any prior scripted transcript with the real captured lines.
    interview.transcript = [
        TranscriptSegment(
            speaker="interviewer" if line["speaker"] == "agent" else "candidate",
            text=line["text"],
            at=_parse_iso(line.get("at")),
        )
        for line in session.transcript_lines
    ]
    interview.acs_state = session.state
    application.log(
        "agent",
        f"ACS Teams interview agent finished — captured "
        f"{len(interview.transcript)} transcript segments",
    )
    return session.to_public_dict()


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "build_question_list",
    "start_acs_interview",
    "get_acs_interview_status",
    "finalise_acs_interview",
]
