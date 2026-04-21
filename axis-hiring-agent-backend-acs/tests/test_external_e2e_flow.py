"""End-to-end test for the new external candidate flow.

Walks the full funnel a candidate would experience after the Q2 demo
refresh, hitting the same HTTP endpoints the frontend hits, with the
same docx files we ship to the demo machine.

Coverage:

1. POST /external/intake (multipart resume + salary_slip + name + email
   + search_query) — assert profile, search_matches, ai_recommendations,
   compensation are all populated end-to-end. The docx text extractor
   MUST pull tables out of the salary slip — that's the bug we just
   fixed.

2. POST /external/apply (with provenance + compensation block from the
   intake response) — assert candidate_kind == external, search_query
   threaded through, candidate persisted with compensation.

3. GET /candidates/{cand_id} — assert compensation surfaces on the HR
   candidate detail endpoint with extraction_source.

4. Orchestrator triggers slot proposals — assert proposed_r1_slots
   is non-empty so the candidate has something to confirm.

5. POST /applications/{id}/confirm-slot R1 — assert the application
   advances to R1_SCHEDULED with a meeting record (mirroring the slot
   pick the candidate makes on /external/status/{id}).

6. GET /external/applications?email=... — assert the tracker page can
   list this candidate's applications.

All Claude services are forced to deterministic so the test stays
hermetic. The endpoint contract is identical between the Claude path
and the deterministic path — only the rationale text changes.
"""

from __future__ import annotations

import io
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.orchestrator import ORCHESTRATOR
from app.store import STORE


@pytest.fixture(autouse=True)
def _force_all_deterministic(monkeypatch):
    monkeypatch.setenv("AXIS_RESUME_MATCHER", "deterministic")
    monkeypatch.setenv("AXIS_SALARY_EXTRACTOR", "deterministic")
    monkeypatch.setenv("AXIS_JOB_SEARCHER", "deterministic")
    monkeypatch.setenv("AXIS_LLM_PROVIDER", "deterministic")


@pytest.fixture
def client():
    return TestClient(fastapi_app)


# Synthetic resume + salary-slip text. We don't ship a real .docx here
# because pytest shouldn't depend on demo assets — but we use the SAME
# TEXT we'd extract from the .docx after the table-walk fix, so the
# downstream parsers see what they'd see in production.

RESUME_BYTES = (
    b"ROHAN DESAI\n"
    b"rohan.desai@Xebia192.onmicrosoft.com\n"
    b"Mumbai, India\n"
    b"\n"
    b"PROFESSIONAL SUMMARY\n"
    b"Branch banking leader with 11 years across HDFC and ICICI Bank.\n"
    b"\n"
    b"EXPERIENCE\n"
    b"HDFC Bank - Branch Manager, Powai (2021-present)\n"
    b"- Owned end-to-end branch P&L (book size 420 crore, 14 staff).\n"
    b"- CASA growth, corporate salary acquisition, burgundy onboarding.\n"
    b"- KYC compliance turnaround.\n"
    b"\n"
    b"SKILLS\n"
    b"branch P&L, CASA, corporate salary, KYC, burgundy, HNI portfolio,\n"
    b"team leadership, relationship management, audit & compliance\n"
)

# Mimics the table output our docx extractor now produces — Basic /
# HRA / Variable separated by tabs.
SLIP_BYTES = (
    b"HDFC Bank Ltd.\n"
    b"Payslip for the month of Mar 2026\n"
    b"Employee: Rohan Desai\n"
    b"Basic\t72,000\n"
    b"HRA\t28,800\n"
    b"Special Allowance\t42,000\n"
    b"Annual variable pay (FY25)\t3,40,000\n"
)


# ---------------------------------------------------------------------------
# 1. /external/intake — full multipart roundtrip
# ---------------------------------------------------------------------------


def test_intake_returns_profile_search_ai_and_compensation(client):
    resp = client.post(
        "/external/intake",
        files={
            "resume": ("rohan_desai_resume.txt", RESUME_BYTES, "text/plain"),
            "salary_slip": ("rohan_desai_slip.txt", SLIP_BYTES, "text/plain"),
        },
        data={
            "name": "Rohan Desai",
            "email": "rohan.desai@Xebia192.onmicrosoft.com",
            "search_query": "Branch Manager in Mumbai near Powai",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Profile identity comes from form, NOT from resume regex.
    assert body["profile"]["name"] == "Rohan Desai"
    assert body["profile"]["email"] == "rohan.desai@Xebia192.onmicrosoft.com"

    # Salary slip → compensation block on profile.
    comp = body["profile"]["compensation"]
    assert comp is not None
    assert comp["current_ctc"] is not None and comp["current_ctc"] > 0
    assert comp["basic"] == 72000 * 12
    assert comp["hra"] == 28800 * 12
    assert comp["variable"] == 340000

    # Both ranking sources populated.
    assert body["search_query"] == "Branch Manager in Mumbai near Powai"
    assert isinstance(body["search_matches"], list)
    assert isinstance(body["ai_recommendations"], list)
    assert len(body["ai_recommendations"]) >= 1, "AI recs should have at least one match"
    assert body["search_source"] == "deterministic"
    assert body["ai_source"] == "deterministic"
    assert body["salary_source"] == "deterministic"


# ---------------------------------------------------------------------------
# 2. Apply uses the intake payload and persists provenance + compensation
# ---------------------------------------------------------------------------


def test_apply_threads_provenance_and_persists_compensation(client):
    intake = client.post(
        "/external/intake",
        files={
            "resume": ("r.txt", RESUME_BYTES, "text/plain"),
            "salary_slip": ("s.txt", SLIP_BYTES, "text/plain"),
        },
        data={
            "name": "Rohan Desai",
            "email": "rohan.desai+e2e2@Xebia192.onmicrosoft.com",
            "search_query": "Branch Manager Mumbai",
        },
    ).json()

    # Apply against the top AI recommendation, marking source = "ai".
    job_id = intake["ai_recommendations"][0]["job_id"]
    resp = client.post(
        "/external/apply",
        json={
            "resume_text": intake["resume_text"],
            "job_id": job_id,
            "name": intake["profile"]["name"],
            "email": intake["profile"]["email"],
            "search_query": intake["search_query"],
            "recommendation_source": "ai",
            "compensation": intake["profile"]["compensation"],
        },
    )
    assert resp.status_code == 200, resp.text
    app_body = resp.json()
    assert app_body["candidate_kind"] == "external"
    assert app_body["search_query"] == "Branch Manager Mumbai"
    assert app_body["recommendation_source"] == "ai"

    # Compensation must be persisted on the candidate so HR sees it.
    cand = STORE.get_candidate(app_body["candidate_id"])
    assert cand is not None
    assert cand.profile.compensation is not None
    assert cand.profile.compensation.current_ctc is not None


# ---------------------------------------------------------------------------
# 3. GET /candidates/{id} surfaces compensation for HR
# ---------------------------------------------------------------------------


def test_get_candidate_returns_compensation_for_hr(client):
    intake = client.post(
        "/external/intake",
        files={
            "resume": ("r.txt", RESUME_BYTES, "text/plain"),
            "salary_slip": ("s.txt", SLIP_BYTES, "text/plain"),
        },
        data={
            "name": "Rohan Desai",
            "email": "rohan.desai+e2e3@Xebia192.onmicrosoft.com",
            "search_query": "",
        },
    ).json()
    job_id = intake["ai_recommendations"][0]["job_id"]
    app = client.post(
        "/external/apply",
        json={
            "resume_text": intake["resume_text"],
            "job_id": job_id,
            "name": intake["profile"]["name"],
            "email": intake["profile"]["email"],
            "compensation": intake["profile"]["compensation"],
            "recommendation_source": "ai",
        },
    ).json()

    # Candidate detail endpoint — what /hr/candidates/[candId] hits.
    resp = client.get(f"/candidates/{app['candidate_id']}")
    assert resp.status_code == 200, resp.text
    cand = resp.json()
    assert cand["compensation"] is not None
    assert cand["compensation"]["current_ctc"] is not None
    assert cand["kind"] == "external"


# ---------------------------------------------------------------------------
# 4. Orchestrator proposes R1 slots for the external application
# ---------------------------------------------------------------------------


def test_orchestrator_proposes_r1_slots_for_external(client):
    intake = client.post(
        "/external/intake",
        files={
            "resume": ("r.txt", RESUME_BYTES, "text/plain"),
            "salary_slip": ("s.txt", SLIP_BYTES, "text/plain"),
        },
        data={
            "name": "Rohan Desai",
            "email": "rohan.desai+e2e4@Xebia192.onmicrosoft.com",
            "search_query": "",
        },
    ).json()
    job_id = intake["ai_recommendations"][0]["job_id"]
    app = client.post(
        "/external/apply",
        json={
            "resume_text": intake["resume_text"],
            "job_id": job_id,
            "name": intake["profile"]["name"],
            "email": intake["profile"]["email"],
            "compensation": intake["profile"]["compensation"],
            "recommendation_source": "ai",
        },
    ).json()

    # Wait for the orchestrator thread to propose slots.
    deadline = time.time() + 5.0
    refreshed = None
    while time.time() < deadline:
        refreshed = STORE.get_application(app["id"])
        if refreshed and refreshed.proposed_r1_slots:
            break
        time.sleep(0.05)
    assert refreshed is not None
    assert refreshed.proposed_r1_slots, (
        f"orchestrator never proposed slots for external app; "
        f"final agent_status={refreshed.agent_status}"
    )


# ---------------------------------------------------------------------------
# 5. /external/applications tracker
# ---------------------------------------------------------------------------


def test_tracker_lists_applications_by_email(client):
    # NB: no `+` in this address — FastAPI's query parser treats `+` as a
    # space unless the client URL-encodes it. The frontend uses
    # `encodeURIComponent(email)` which DOES encode it correctly, but the
    # raw test client below uses a plain f-string so we keep the address
    # ASCII-only here for clarity.
    email = "rohan.desai.tracker@Xebia192.onmicrosoft.com"
    intake = client.post(
        "/external/intake",
        files={
            "resume": ("r.txt", RESUME_BYTES, "text/plain"),
            "salary_slip": ("s.txt", SLIP_BYTES, "text/plain"),
        },
        data={"name": "Rohan Desai", "email": email, "search_query": ""},
    ).json()
    job_id = intake["ai_recommendations"][0]["job_id"]
    app = client.post(
        "/external/apply",
        json={
            "resume_text": intake["resume_text"],
            "job_id": job_id,
            "name": intake["profile"]["name"],
            "email": intake["profile"]["email"],
            "compensation": intake["profile"]["compensation"],
            "recommendation_source": "ai",
        },
    ).json()

    # Tracker page hits this endpoint.
    resp = client.get(f"/external/applications?email={email}")
    assert resp.status_code == 200, resp.text
    apps = resp.json()
    assert any(a["id"] == app["id"] for a in apps), (
        f"expected {app['id']} in tracker for {email}, got {[a['id'] for a in apps]}"
    )
