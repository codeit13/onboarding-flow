"""Contract tests for the live AI-interview proxy endpoints in app.main.

These four endpoints are the bridge the candidate browser uses to talk
to the team's pre-built Virtual Interviewer sidecar without doing
cross-origin requests:

* GET  /applications/{id}/virtual-interview/welcome-audio
* GET  /applications/{id}/virtual-interview/full-question/{index}
* POST /applications/{id}/virtual-interview/transcribe
* POST /applications/{id}/virtual-interview/verify-face

We monkey-patch ``app.main.httpx.Client`` with a stub so the tests are
hermetic — the sidecar does NOT have to be running. That mirrors the
pattern in test_virtual_interviewer.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app as fastapi_app
from app.models import Application, InterviewRecord, TimeSlot
from app.store import STORE


# ---------------------------------------------------------------------------
# Stub httpx.Client
# ---------------------------------------------------------------------------


class _StubResponse:
    def __init__(self, status_code: int, body: Dict[str, Any]):
        self.status_code = status_code
        self._body = body
        self.text = str(body)
        self.headers = {"content-type": "application/json"}

    def json(self) -> Dict[str, Any]:
        return self._body


class _StubSidecar:
    """Stand-in for httpx.Client used by the proxy endpoints in main.py."""

    def __init__(self) -> None:
        self.calls: List[str] = []
        self.last_post_json: Dict[str, Any] = {}

    # context-manager protocol
    def __enter__(self) -> "_StubSidecar":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    # match the httpx.Client(...) constructor signature: ignore kwargs
    def __call__(self, *args: Any, **kwargs: Any) -> "_StubSidecar":
        return self

    # ----- HTTP verbs ------------------------------------------------------

    def get(self, url: str, **kwargs: Any) -> _StubResponse:
        self.calls.append(f"GET {url}")
        if url.endswith("/welcome_audio"):
            return _StubResponse(200, {"success": True, "audio": "AAA=", "text": "welcome"})
        if "/full_question/" in url:
            idx = int(url.rsplit("/", 1)[-1])
            if idx >= 5:
                return _StubResponse(400, {"success": False, "error": "no more questions"})
            return _StubResponse(
                200,
                {
                    "success": True,
                    "question_index": idx,
                    "question_text": f"Q{idx + 1}?",
                    "audio": "BBB=",
                },
            )
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url: str, **kwargs: Any) -> _StubResponse:
        self.calls.append(f"POST {url}")
        self.last_post_json = kwargs.get("json") or {}
        if url.endswith("/transcribe"):
            return _StubResponse(
                200,
                {"success": True, "transcript": "this is the candidate answer"},
            )
        if url.endswith("/verify_face"):
            return _StubResponse(
                200,
                {"success": True, "match": True, "name": "Rohan Mehta"},
            )
        raise AssertionError(f"unexpected POST {url}")


@pytest.fixture
def stub_sidecar(monkeypatch: pytest.MonkeyPatch) -> _StubSidecar:
    stub = _StubSidecar()
    # Replace httpx.Client in app.main's namespace so the proxy endpoints
    # use our stub. We return the stub itself when called like a constructor.
    monkeypatch.setattr(app_main.httpx, "Client", stub)
    return stub


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


# ---------------------------------------------------------------------------
# Seed an application with an R1 interview that already has a sidecar id
# ---------------------------------------------------------------------------


def _seed_application_with_session() -> Application:
    job = STORE.list_jobs()[0]
    candidate = next(iter(STORE.candidates.values()))
    application = Application(
        id=f"app-vi-proxy-{candidate.id}",
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
        virtual_interview_session_id="20260407200000",
        virtual_interview_state="in_progress",
    )
    application.interviews.append(interview)
    return application


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_welcome_audio_proxies_sidecar(client: TestClient, stub_sidecar: _StubSidecar):
    application = _seed_application_with_session()
    resp = client.get(f"/applications/{application.id}/virtual-interview/welcome-audio")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["audio"] == "AAA="
    assert any("/welcome_audio" in c and "GET" in c for c in stub_sidecar.calls)


def test_full_question_proxies_sidecar(client: TestClient, stub_sidecar: _StubSidecar):
    application = _seed_application_with_session()
    resp = client.get(
        f"/applications/{application.id}/virtual-interview/full-question/0"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["question_text"] == "Q1?"
    assert body["audio"] == "BBB="


def test_full_question_relays_400_when_index_past_end(
    client: TestClient, stub_sidecar: _StubSidecar
):
    application = _seed_application_with_session()
    resp = client.get(
        f"/applications/{application.id}/virtual-interview/full-question/9"
    )
    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_transcribe_proxies_audio_payload(client: TestClient, stub_sidecar: _StubSidecar):
    application = _seed_application_with_session()
    audio_data_url = "data:audio/webm;base64,QUJD"
    resp = client.post(
        f"/applications/{application.id}/virtual-interview/transcribe",
        json={"audio": audio_data_url},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transcript"] == "this is the candidate answer"
    # The proxy must forward the audio payload unchanged.
    assert stub_sidecar.last_post_json == {"audio": audio_data_url}


def test_verify_face_proxies_photo(client: TestClient, stub_sidecar: _StubSidecar):
    application = _seed_application_with_session()
    photo = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
    resp = client.post(
        f"/applications/{application.id}/virtual-interview/verify-face",
        json={"photo": photo},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["match"] is True
    assert body["name"] == "Rohan Mehta"
    assert stub_sidecar.last_post_json == {"photo": photo}


def test_endpoints_400_when_no_sidecar_session(
    client: TestClient, stub_sidecar: _StubSidecar
):
    """If the candidate hits a proxy before /start, we must surface a clean
    400 — not a crash and not a 502 — so the UI can prompt them to start."""
    job = STORE.list_jobs()[0]
    candidate = next(iter(STORE.candidates.values()))
    application = Application(
        id=f"app-vi-proxy-nostart-{candidate.id}",
        candidate_id=candidate.id,
        job_id=job.id,
        match_percent=80.0,
    )
    STORE.add_application(application)
    application.interviews.append(
        InterviewRecord(
            id=f"int-{application.id}",
            application_id=application.id,
            round="R1",
            meeting_slot=TimeSlot(
                start=datetime.utcnow(),
                end=datetime.utcnow() + timedelta(minutes=30),
            ),
        )
    )
    resp = client.get(
        f"/applications/{application.id}/virtual-interview/welcome-audio"
    )
    assert resp.status_code == 400
    assert "No live AI Interview Agent session" in resp.json()["detail"]
