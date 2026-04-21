"""Tests for the intermediate Contact Review flow in bulk screening.

Covers the new endpoints:
  - PATCH /hr/bulk-intake/{pool_id}/contacts
  - POST  /hr/bulk-intake/{pool_id}/start-scoring

And the refactored upload flow:
  - POST  /hr/bulk-intake  now parses only (no scoring) and transitions
    the pool to ``pending_review``.

All Claude services are forced to deterministic so the suite stays
hermetic and never hits the live API.
"""

from __future__ import annotations

import io
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.store import STORE


@pytest.fixture(autouse=True)
def _force_deterministic(monkeypatch):
    monkeypatch.setenv("AXIS_RESUME_MATCHER", "deterministic")
    monkeypatch.setenv("AXIS_CV_SCREENER", "deterministic")
    monkeypatch.setenv("AXIS_JOB_SEARCHER", "deterministic")


@pytest.fixture
def client():
    return TestClient(fastapi_app)


SAMPLE_RESUME_TXT = b"""Priya Sharma
priya.sharma@example.com
+91 98765 43210
HDFC Bank, Branch Manager Mumbai
- Corporate salary acquisition, CASA cross-sell
- KYC compliance, relationship management
- Burgundy / HNI portfolio
Skills: Python, Data Analysis, SQL, Excel
Education: MBA Finance
"""

SAMPLE_RESUME_2 = b"""Rahul Verma
rahul.verma@test.com
Senior Developer, Axis Bank
- Full-stack development, microservices
- Cloud infrastructure, CI/CD
Skills: Java, Spring Boot, AWS
"""


def _upload_resumes(client, files_data=None, job_id=""):
    """Upload one or more resume files and return the response."""
    if files_data is None:
        files_data = [("resume1.txt", SAMPLE_RESUME_TXT)]
    files = [
        ("files", (fname, io.BytesIO(content), "text/plain"))
        for fname, content in files_data
    ]
    data = {"job_id": job_id}
    resp = client.post("/hr/bulk-intake", files=files, data=data)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _wait_for_status(client, pool_id, target_status, timeout=15):
    """Poll until the pool reaches the target status or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/hr/bulk-intake/{pool_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] == target_status:
            return body
        time.sleep(0.3)
    raise TimeoutError(
        f"Pool {pool_id} did not reach status '{target_status}' "
        f"within {timeout}s (last: {body['status']})"
    )


# ---------- Happy path tests ----------

def test_upload_creates_pending_review_pool(client):
    """Upload files -> pool transitions to pending_review after parsing."""
    # Pick a valid job_id from the seeded store
    jobs = STORE.list_jobs()
    assert len(jobs) > 0, "Seeded store should have at least one job"
    job_id = jobs[0].id

    result = _upload_resumes(client, job_id=job_id)
    pool_id = result["pool_id"]

    # Wait for parsing to complete
    status = _wait_for_status(client, pool_id, "pending_review")
    assert status["status"] == "pending_review"

    # All non-error rows should be in 'parsed' state
    for row in status["rows"]:
        assert row["status"] in ("parsed", "error"), (
            f"Row {row['row_id']} should be parsed or error, got {row['status']}"
        )

    # Parsed rows should have extracted candidate name
    parsed_rows = [r for r in status["rows"] if r["status"] == "parsed"]
    assert len(parsed_rows) > 0
    assert parsed_rows[0]["candidate_name"] is not None


def test_update_contacts_updates_row(client):
    """PATCH contacts -> row email/phone updated."""
    jobs = STORE.list_jobs()
    job_id = jobs[0].id
    result = _upload_resumes(client, job_id=job_id)
    pool_id = result["pool_id"]

    status = _wait_for_status(client, pool_id, "pending_review")
    row_id = status["rows"][0]["row_id"]

    resp = client.patch(
        f"/hr/bulk-intake/{pool_id}/contacts",
        json={
            "contacts": [
                {
                    "row_id": row_id,
                    "candidate_email": "updated@example.com",
                    "candidate_phone": "+91 11111 22222",
                    "candidate_name": "Updated Name",
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify the update persisted
    status2 = client.get(f"/hr/bulk-intake/{pool_id}").json()
    row = next(r for r in status2["rows"] if r["row_id"] == row_id)
    assert row["candidate_email"] == "updated@example.com"
    assert row["candidate_phone"] == "+91 11111 22222"
    assert row["candidate_name"] == "Updated Name"


def test_start_scoring_transitions_to_processing(client):
    """POST start-scoring -> pool status becomes processing."""
    jobs = STORE.list_jobs()
    job_id = jobs[0].id
    result = _upload_resumes(client, job_id=job_id)
    pool_id = result["pool_id"]

    _wait_for_status(client, pool_id, "pending_review")

    resp = client.post(f"/hr/bulk-intake/{pool_id}/start-scoring")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["pool_id"] == pool_id

    # Pool should now be processing or done (scoring might finish instantly)
    status = client.get(f"/hr/bulk-intake/{pool_id}").json()
    assert status["status"] in ("processing", "done")


def test_save_and_resume(client):
    """Update contacts, verify pool stays pending_review, can come back."""
    jobs = STORE.list_jobs()
    job_id = jobs[0].id
    result = _upload_resumes(client, job_id=job_id)
    pool_id = result["pool_id"]

    status = _wait_for_status(client, pool_id, "pending_review")
    row_id = status["rows"][0]["row_id"]

    # Save draft
    resp = client.patch(
        f"/hr/bulk-intake/{pool_id}/contacts",
        json={
            "contacts": [
                {"row_id": row_id, "candidate_email": "draft@example.com"}
            ]
        },
    )
    assert resp.status_code == 200

    # Pool should still be pending_review
    status2 = client.get(f"/hr/bulk-intake/{pool_id}").json()
    assert status2["status"] == "pending_review"

    # Data persisted
    row = next(r for r in status2["rows"] if r["row_id"] == row_id)
    assert row["candidate_email"] == "draft@example.com"


def test_scoring_produces_results(client):
    """After start-scoring, poll until done, verify match scores exist."""
    jobs = STORE.list_jobs()
    job_id = jobs[0].id
    result = _upload_resumes(client, job_id=job_id)
    pool_id = result["pool_id"]

    _wait_for_status(client, pool_id, "pending_review")

    client.post(f"/hr/bulk-intake/{pool_id}/start-scoring")

    # Wait for scoring to complete
    status = _wait_for_status(client, pool_id, "done")
    assert status["status"] == "done"

    # Check that scored rows have match_percent
    scored_rows = [r for r in status["rows"] if r["status"] == "done"]
    assert len(scored_rows) > 0
    for row in scored_rows:
        assert row["match_percent"] is not None
        assert row["recommendation"] is not None


def test_multiple_files_upload(client):
    """Upload multiple files, all should be parsed."""
    jobs = STORE.list_jobs()
    job_id = jobs[0].id
    result = _upload_resumes(
        client,
        files_data=[
            ("resume1.txt", SAMPLE_RESUME_TXT),
            ("resume2.txt", SAMPLE_RESUME_2),
        ],
        job_id=job_id,
    )
    pool_id = result["pool_id"]
    assert result["total_files"] == 2

    status = _wait_for_status(client, pool_id, "pending_review")
    parsed_rows = [r for r in status["rows"] if r["status"] == "parsed"]
    assert len(parsed_rows) == 2


# ---------- Negative path tests ----------

def test_update_contacts_wrong_status(client):
    """Cannot update contacts on a pool that is already processing."""
    jobs = STORE.list_jobs()
    job_id = jobs[0].id
    result = _upload_resumes(client, job_id=job_id)
    pool_id = result["pool_id"]

    _wait_for_status(client, pool_id, "pending_review")

    # Start scoring so pool transitions to processing
    client.post(f"/hr/bulk-intake/{pool_id}/start-scoring")

    # Wait for it to move past pending_review
    time.sleep(0.5)

    resp = client.patch(
        f"/hr/bulk-intake/{pool_id}/contacts",
        json={"contacts": [{"row_id": "fake", "candidate_email": "x@x.com"}]},
    )
    assert resp.status_code == 400


def test_start_scoring_wrong_status(client):
    """Cannot start scoring on a pool not in pending_review."""
    jobs = STORE.list_jobs()
    job_id = jobs[0].id
    result = _upload_resumes(client, job_id=job_id)
    pool_id = result["pool_id"]

    _wait_for_status(client, pool_id, "pending_review")

    # Start scoring first time
    resp = client.post(f"/hr/bulk-intake/{pool_id}/start-scoring")
    assert resp.status_code == 200

    # Try starting again — should fail
    resp2 = client.post(f"/hr/bulk-intake/{pool_id}/start-scoring")
    assert resp2.status_code == 400


def test_update_contacts_nonexistent_pool(client):
    """404 for nonexistent pool."""
    resp = client.patch(
        "/hr/bulk-intake/pool-nonexistent/contacts",
        json={"contacts": [{"row_id": "r1", "candidate_email": "x@x.com"}]},
    )
    assert resp.status_code == 404


def test_start_scoring_nonexistent_pool(client):
    """404 for nonexistent pool."""
    resp = client.post("/hr/bulk-intake/pool-nonexistent/start-scoring")
    assert resp.status_code == 404
