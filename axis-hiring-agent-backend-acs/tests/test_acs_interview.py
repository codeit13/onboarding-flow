"""Tests for the ACS Teams Interview Agent (mock provider).

The mock provider drives a complete simulated Teams call in a background
thread. With ``AXIS_ACS_MOCK_QUESTION_DELAY=0`` (set in conftest) the
simulation finishes essentially instantly, so we can poll for the final
``ended`` state with a short retry loop.
"""

from __future__ import annotations

import time

import pytest

from datetime import datetime, timedelta

from app.models import Application, InterviewRecord, TimeSlot
from app.providers import get_acs_provider
from app.services.acs_interview_bot import (
    build_question_list,
    finalise_acs_interview,
    get_acs_interview_status,
    start_acs_interview,
)
from app.store import STORE


def _wait_for_state(call_id: str, target: str, timeout_s: float = 3.0) -> None:
    provider = get_acs_provider()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        session = provider.get_session(call_id)
        if session and session.state == target:
            return
        time.sleep(0.02)
    raise AssertionError(
        f"ACS session {call_id} never reached state={target}; "
        f"got {provider.get_session(call_id) and provider.get_session(call_id).state}"
    )


def _seed_r1_interview() -> tuple:
    """Construct a stub Application + R1 InterviewRecord directly so the
    ACS service has something to dispatch against. Avoids depending on
    the full orchestrator state machine."""
    job = STORE.list_jobs()[0]
    candidate = next(iter(STORE.candidates.values()))
    application = Application(
        id=f"app-acs-{candidate.id}",
        candidate_id=candidate.id,
        job_id=job.id,
        match_percent=82.0,
    )
    STORE.add_application(application)
    interview = InterviewRecord(
        id=f"int-{application.id}",
        application_id=application.id,
        round="R1",
        teams_join_url="https://teams.microsoft.com/l/meetup-join/test",
        meeting_slot=TimeSlot(
            start=datetime.utcnow(),
            end=datetime.utcnow() + timedelta(minutes=30),
        ),
    )
    application.interviews.append(interview)
    return application, job, candidate, interview


def test_build_question_list_returns_fallback_when_claude_unavailable(monkeypatch):
    # Force the Claude path to fail so we exercise the deterministic fallback.
    import app.services.acs_interview_bot as bot_mod

    def boom(*_a, **_kw):
        raise RuntimeError("no claude in tests")

    monkeypatch.setattr(
        "app.services.claude_panel_recommender._call_anthropic",
        boom,
        raising=False,
    )

    job = STORE.list_jobs()[0]
    candidate = next(iter(STORE.candidates.values()))
    questions = build_question_list(job=job, profile=candidate.profile)
    assert 5 <= len(questions) <= 7
    assert all(isinstance(q, str) and q.strip() for q in questions)


def test_start_acs_interview_dispatches_and_completes():
    application, job, candidate, interview = _seed_r1_interview()

    session = start_acs_interview(
        application=application,
        job=job,
        profile=candidate.profile,
        interview=interview,
    )
    assert session.call_id.startswith("acs-mock-")
    assert interview.acs_call_id == session.call_id
    # state may be 'joining' or 'live' immediately after dispatch
    assert session.state in ("joining", "live", "ended")

    _wait_for_state(session.call_id, "ended")

    status = get_acs_interview_status(interview=interview)
    assert status is not None
    assert status["state"] == "ended"
    assert status["questions_asked"] == status["questions_total"]
    assert status["questions_total"] >= 5


def test_finalise_folds_transcript_into_interview_record():
    application, job, candidate, interview = _seed_r1_interview()

    session = start_acs_interview(
        application=application,
        job=job,
        profile=candidate.profile,
        interview=interview,
    )
    _wait_for_state(session.call_id, "ended")

    result = finalise_acs_interview(application=application, interview=interview)
    assert result is not None
    assert result["state"] == "ended"

    # Real captured transcript replaces any prior scripted content.
    assert len(interview.transcript) > 0
    speakers = {seg.speaker for seg in interview.transcript}
    assert speakers == {"interviewer", "candidate"}
    # Activity log records the dispatch + completion.
    messages = " ".join(e.message for e in application.events)
    assert "ACS Teams interview agent" in messages


def test_start_requires_teams_join_url():
    application, job, candidate, interview = _seed_r1_interview()
    interview.teams_join_url = None
    with pytest.raises(ValueError):
        start_acs_interview(
            application=application,
            job=job,
            profile=candidate.profile,
            interview=interview,
        )


def test_status_none_before_dispatch():
    interview = InterviewRecord(
        id="int-x",
        application_id="app-x",
        round="R1",
    )
    assert get_acs_interview_status(interview=interview) is None
