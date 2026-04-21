"""Integration tests for the Virtual Interviewer proxy.

The Virtual Interviewer is now a thin proxy to the team's pre-built
FastAPI sidecar (``virtual-interviewer/`` shipped in the project root).
The wrapper exposes the same public surface as the previous in-process
mock, but every state transition goes over HTTP to the sidecar.

These tests pin the *contract* of the wrapper without requiring the
sidecar to be running: ``httpx.Client`` is monkey-patched so each test
returns canned sidecar responses. The previous unit tests (which
called the deleted in-process mock) have been removed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

from app.models import Application, InterviewRecord, TimeSlot
from app.services import virtual_interviewer as vi
from app.store import STORE


# ---------------------------------------------------------------------------
# Stub HTTP transport
# ---------------------------------------------------------------------------


class _StubResponse:
    def __init__(self, status_code: int, json_body: Dict[str, Any]):
        self.status_code = status_code
        self._json = json_body
        self.text = str(json_body)

    def json(self) -> Dict[str, Any]:
        return self._json


class _StubClient:
    """Pretends to be the sidecar. Tracks calls and serves a fake session
    JSON whose ``current_question_index`` advances with each ``/answer``."""

    INTERVIEW_ID = "20260407200000"

    def __init__(self) -> None:
        self.questions: List[Dict[str, Any]] = [
            {"id": i + 1, "question": f"Q{i+1}?", "answer": None, "is_mandatory": True}
            for i in range(5)
        ]
        self.calls: List[str] = []

    # context-manager protocol so it slots in for httpx.Client()
    def __enter__(self) -> "_StubClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _StubResponse:
        self.calls.append(f"POST {url}")
        if url.endswith("/api/interview/start"):
            return _StubResponse(
                200,
                {
                    "success": True,
                    "interview_id": self.INTERVIEW_ID,
                    "message": "ok",
                    "welcome_message": "welcome",
                },
            )
        if url.endswith("/answer"):
            ans = (kwargs.get("json") or {}).get("answer", "")
            for q in self.questions:
                if q["answer"] is None:
                    q["answer"] = ans
                    break
            return _StubResponse(200, {"success": True, "message": "saved"})
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url: str, **kwargs: Any) -> _StubResponse:
        self.calls.append(f"GET {url}")
        if url.endswith(f"/api/interview/{self.INTERVIEW_ID}"):
            answered = sum(1 for q in self.questions if q["answer"] is not None)
            payload = {
                "id": self.INTERVIEW_ID,
                "name": "Rohan Mehta",
                "email": "rohan@example.com",
                "questions": self.questions,
                "current_question_index": answered,
                "start_time": datetime.utcnow().isoformat(),
                "end_time": (
                    datetime.utcnow().isoformat()
                    if answered >= len(self.questions)
                    else None
                ),
            }
            return _StubResponse(200, {"success": True, "interview": payload})
        raise AssertionError(f"unexpected GET {url}")


@pytest.fixture
def stub_sidecar(monkeypatch: pytest.MonkeyPatch) -> _StubClient:
    stub = _StubClient()
    monkeypatch.setattr(vi, "_client", lambda: stub)
    return stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_r1_interview() -> tuple:
    job = STORE.list_jobs()[0]
    candidate = next(iter(STORE.candidates.values()))
    application = Application(
        id=f"app-vi-{candidate.id}",
        candidate_id=candidate.id,
        job_id=job.id,
        match_percent=80.0,
    )
    STORE.add_application(application)
    interview = InterviewRecord(
        id=f"int-{application.id}",
        application_id=application.id,
        round="R1",
        meeting_slot=TimeSlot(
            start=datetime.utcnow(),
            end=datetime.utcnow() + timedelta(minutes=30),
        ),
    )
    application.interviews.append(interview)
    return application, job, candidate, interview


_FAKE_PHOTO = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_start_creates_session_with_questions(stub_sidecar: _StubClient):
    application, job, candidate, interview = _seed_r1_interview()
    session = vi.start_virtual_interview(
        application=application,
        job=job,
        profile=candidate.profile,
        interview=interview,
        photo_data_url=_FAKE_PHOTO,
    )
    assert session.session_id == _StubClient.INTERVIEW_ID
    assert session.state == "in_progress"
    assert len(session.questions) == 5
    assert interview.virtual_interview_session_id == session.session_id
    assert interview.virtual_interview_state == "in_progress"
    # Sidecar was actually called for /start and full session GET
    assert any("POST" in c and "/start" in c for c in stub_sidecar.calls)
    assert any("GET" in c and _StubClient.INTERVIEW_ID in c for c in stub_sidecar.calls)


def test_start_requires_photo(stub_sidecar: _StubClient):
    application, job, candidate, interview = _seed_r1_interview()
    with pytest.raises(ValueError):
        vi.start_virtual_interview(
            application=application,
            job=job,
            profile=candidate.profile,
            interview=interview,
            photo_data_url="",
        )


def test_submit_answer_advances_index_and_completes(stub_sidecar: _StubClient):
    application, job, candidate, interview = _seed_r1_interview()
    vi.start_virtual_interview(
        application=application,
        job=job,
        profile=candidate.profile,
        interview=interview,
        photo_data_url=_FAKE_PHOTO,
    )
    last = None
    for i in range(5):
        last = vi.submit_virtual_interview_answer(
            application=application,
            interview=interview,
            answer_text=f"Answer to question {i + 1} with concrete examples.",
        )
    assert last is not None
    assert last.state == "completed"
    assert last.current_index == 5
    assert len(last.answers) == 5
    # Transcript folded into the InterviewRecord (Q + A per pair)
    assert len(interview.transcript) == 5 * 2
    speakers = {seg.speaker for seg in interview.transcript}
    assert speakers == {"interviewer", "candidate"}


def test_submit_empty_answer_rejected(stub_sidecar: _StubClient):
    application, job, candidate, interview = _seed_r1_interview()
    vi.start_virtual_interview(
        application=application,
        job=job,
        profile=candidate.profile,
        interview=interview,
        photo_data_url=_FAKE_PHOTO,
    )
    with pytest.raises(ValueError):
        vi.submit_virtual_interview_answer(
            application=application, interview=interview, answer_text="   "
        )


def test_finalise_early_folds_partial_transcript(stub_sidecar: _StubClient):
    application, job, candidate, interview = _seed_r1_interview()
    vi.start_virtual_interview(
        application=application,
        job=job,
        profile=candidate.profile,
        interview=interview,
        photo_data_url=_FAKE_PHOTO,
    )
    vi.submit_virtual_interview_answer(
        application=application, interview=interview, answer_text="Partial answer one."
    )
    vi.submit_virtual_interview_answer(
        application=application, interview=interview, answer_text="Partial answer two."
    )
    out = vi.finalise_virtual_interview(application=application, interview=interview)
    assert out is not None
    assert out["state"] == "completed"
    # 2 Q/A pairs folded → 4 transcript segments
    assert len(interview.transcript) == 4


def test_get_returns_none_before_start():
    interview = InterviewRecord(id="x", application_id="x", round="R1")
    assert vi.get_virtual_interview(interview=interview) is None


def test_start_endpoint_is_idempotent_when_in_progress(stub_sidecar: _StubClient):
    """Refreshing the candidate page must NOT lose answers — calling
    ``get_virtual_interview`` after start should return the same session id
    with the existing index/answers preserved by the sidecar."""
    application, job, candidate, interview = _seed_r1_interview()
    s1 = vi.start_virtual_interview(
        application=application,
        job=job,
        profile=candidate.profile,
        interview=interview,
        photo_data_url=_FAKE_PHOTO,
    )
    vi.submit_virtual_interview_answer(
        application=application, interview=interview, answer_text="answer one"
    )
    s2 = vi.get_virtual_interview(
        interview=interview, application_id=application.id
    )
    assert s2 is not None
    assert s2.session_id == s1.session_id
    assert s2.current_index == 1
