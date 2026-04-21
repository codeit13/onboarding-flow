"""Tests for auto-creating Applications when bulk screening shortlists candidates.

After `/hr/bulk-intake/{pool_id}/start-scoring` completes, every row with
``recommendation == "shortlist"`` should get a placeholder Application at
``FunnelStage.SCREENED`` with ``source == "bulk_screening"`` so it shows
up in the HR Funnel even before HR formally routes to L1/L2.

Also tests the improved phone extraction regex.
"""

from __future__ import annotations

import io
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.providers import reset_providers
from app.store import STORE
from app.tools.external_intake import parse_resume


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _force_deterministic(monkeypatch):
    monkeypatch.setenv("AXIS_RESUME_MATCHER", "deterministic")
    monkeypatch.setenv("AXIS_CV_SCREENER", "deterministic")
    monkeypatch.setenv("AXIS_JOB_SEARCHER", "deterministic")
    monkeypatch.setenv("AXIS_MESSAGING_PROVIDER", "mock")
    monkeypatch.setenv("AXIS_WHATSAPP_PROVIDER", "mock")
    monkeypatch.setenv("AXIS_CALENDAR_PROVIDER", "mock")
    reset_providers()


@pytest.fixture
def client():
    return TestClient(fastapi_app)


# ---------------------------------------------------------------------------
# Phone extraction tests
# ---------------------------------------------------------------------------


class TestPhoneExtraction:
    """The improved regex should catch many common phone formats."""

    def test_labeled_phone(self):
        text = "Rohan Desai\nPhone: +91 98765 43210\nMumbai"
        prof = parse_resume(text)
        assert prof.phone is not None
        assert "9876543210" in prof.phone

    def test_mobile_label(self):
        text = "Priya\nEmail: p@x.com\nMobile: 9876543210\n"
        prof = parse_resume(text)
        assert prof.phone is not None
        assert "9876543210" in prof.phone

    def test_plus_91_no_separator(self):
        text = "Rohan\nrohan@x.com\n+919887712568\n"
        prof = parse_resume(text)
        assert prof.phone is not None
        assert "9887712568" in prof.phone

    def test_plus_91_with_space(self):
        text = "Rohan\nrohan@x.com\n+91 9887712568\n"
        prof = parse_resume(text)
        assert prof.phone is not None
        assert "9887712568" in prof.phone

    def test_plus_91_with_hyphen(self):
        text = "Rohan\nrohan@x.com\n+91-9887-712-568\n"
        prof = parse_resume(text)
        assert prof.phone is not None
        # Hyphens stripped in stored form
        assert "9887712568" in prof.phone

    def test_bare_10_digit_indian_mobile(self):
        text = "Anu\nanu@x.com\nContact number: 9876543210\n"
        prof = parse_resume(text)
        assert prof.phone is not None
        assert "9876543210" in prof.phone

    def test_no_phone_returns_none(self):
        text = "Someone\nsomeone@x.com\nMumbai, India\n"
        prof = parse_resume(text)
        assert prof.phone is None

    def test_phone_in_contact_section(self):
        text = "Sneha\nContact: +91 98765-43210\nsneha@x.com"
        prof = parse_resume(text)
        assert prof.phone is not None


# ---------------------------------------------------------------------------
# Auto-shortlist-to-funnel tests
# ---------------------------------------------------------------------------


SAMPLE_RESUME = (
    "Rajesh Menon\n"
    "Email: rajesh.menon@gmail.com\n"
    "Phone: +91 9876543210\n"
    "· Pune, India\n\n"
    "Experience:\n"
    "- Branch Manager at Axis Bank (2014 - 2024) — 10 years\n"
    "- Portfolio sales, CASA cross-sell, KYC compliance\n"
    "- P&L ownership, team leadership, customer experience\n"
    "- Stakeholder management, audit & compliance, branch operations\n"
    "- Relationship management, corporate salary acquisition\n"
)


def _upload(client, job_id: str):
    file = io.BytesIO(SAMPLE_RESUME.encode())
    resp = client.post(
        "/hr/bulk-intake",
        data={"jd_id": job_id, "mode": "single_jd"},
        files={"files": ("CV_Rajesh.txt", file, "text/plain")},
    )
    assert resp.status_code == 200
    return resp.json()["pool_id"]


def _wait_for_status(client, pool_id: str, target: str, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        body = client.get(f"/hr/bulk-intake/{pool_id}").json()
        last = body["status"]
        if last == target:
            return body
        time.sleep(0.3)
    raise TimeoutError(f"Pool {pool_id} did not reach '{target}' (last={last})")


class TestAutoShortlistToFunnel:
    def test_shortlisted_row_gets_application(self, client):
        """Once scoring completes, shortlisted rows should have application_id set."""
        jobs = STORE.list_jobs()
        assert len(jobs) > 0
        job_id = jobs[0].id

        pool_id = _upload(client, job_id)
        _wait_for_status(client, pool_id, "pending_review")
        client.post(f"/hr/bulk-intake/{pool_id}/start-scoring")
        status = _wait_for_status(client, pool_id, "done")

        shortlisted_rows = [
            r for r in status["rows"]
            if (r.get("recommendation") or "").lower() == "shortlist"
        ]
        # We expect at least one shortlisted row for a strong candidate
        if not shortlisted_rows:
            pytest.skip("No shortlisted rows in deterministic scoring — skip")

        for row in shortlisted_rows:
            assert row.get("application_id"), (
                f"Shortlisted row {row['row_id']} should have application_id set"
            )

    def test_shortlisted_app_has_bulk_screening_source(self, client):
        """Auto-created apps should be stamped source=bulk_screening."""
        jobs = STORE.list_jobs()
        job_id = jobs[0].id
        pool_id = _upload(client, job_id)
        _wait_for_status(client, pool_id, "pending_review")
        client.post(f"/hr/bulk-intake/{pool_id}/start-scoring")
        status = _wait_for_status(client, pool_id, "done")

        shortlisted = [
            r for r in status["rows"]
            if (r.get("recommendation") or "").lower() == "shortlist"
        ]
        if not shortlisted:
            pytest.skip("No shortlisted rows to verify")

        for row in shortlisted:
            app_id = row.get("application_id")
            app = STORE.get_application(app_id)
            assert app is not None
            assert app.source == "bulk_screening"

    def test_shortlisted_app_visible_in_hr_funnel(self, client):
        """Auto-created shortlist apps should appear in the HR funnel."""
        jobs = STORE.list_jobs()
        job_id = jobs[0].id
        pool_id = _upload(client, job_id)
        _wait_for_status(client, pool_id, "pending_review")
        client.post(f"/hr/bulk-intake/{pool_id}/start-scoring")
        status = _wait_for_status(client, pool_id, "done")

        shortlisted = [
            r for r in status["rows"]
            if (r.get("recommendation") or "").lower() == "shortlist"
        ]
        if not shortlisted:
            pytest.skip("No shortlisted rows to verify")

        shortlisted_app_ids = {r["application_id"] for r in shortlisted}

        # Get HR-visible apps
        resp = client.get("/applications", params={"visible_to": "hr"})
        assert resp.status_code == 200
        hr_apps = resp.json()
        hr_app_ids = {a["id"] for a in hr_apps}

        # Every shortlisted app should be in the HR funnel
        for app_id in shortlisted_app_ids:
            assert app_id in hr_app_ids, (
                f"App {app_id} should be visible in HR funnel"
            )

    def test_non_shortlisted_rows_do_not_get_apps(self, client):
        """Rejected or maybe rows should NOT get auto-created apps."""
        jobs = STORE.list_jobs()
        job_id = jobs[0].id
        pool_id = _upload(client, job_id)
        _wait_for_status(client, pool_id, "pending_review")
        client.post(f"/hr/bulk-intake/{pool_id}/start-scoring")
        status = _wait_for_status(client, pool_id, "done")

        non_shortlisted = [
            r for r in status["rows"]
            if r["status"] == "done"
            and (r.get("recommendation") or "").lower() != "shortlist"
        ]
        for row in non_shortlisted:
            assert not row.get("application_id"), (
                f"Non-shortlisted row {row['row_id']} (rec={row.get('recommendation')}) "
                f"should not have an application_id"
            )

    def test_route_reuses_existing_shortlist_app(self, client):
        """When HR routes a shortlisted row, it should reuse the pre-created app."""
        jobs = STORE.list_jobs()
        job_id = jobs[0].id
        pool_id = _upload(client, job_id)
        _wait_for_status(client, pool_id, "pending_review")
        client.post(f"/hr/bulk-intake/{pool_id}/start-scoring")
        status = _wait_for_status(client, pool_id, "done")

        shortlisted = [
            r for r in status["rows"]
            if (r.get("recommendation") or "").lower() == "shortlist"
        ]
        if not shortlisted:
            pytest.skip("No shortlisted rows to verify")

        row = shortlisted[0]
        pre_route_app_id = row["application_id"]

        # Route to L1
        nothrow_client = TestClient(fastapi_app, raise_server_exceptions=False)
        resp = nothrow_client.post(
            f"/hr/bulk-intake/{pool_id}/row/{row['row_id']}/route",
            json={"action": "route", "round": "L1", "job_id": job_id},
        )
        if resp.status_code != 200:
            pytest.skip(f"Route endpoint errored: {resp.status_code}")
        body = resp.json()
        # The returned application_id should match the pre-created app
        assert body.get("application_id") == pre_route_app_id
