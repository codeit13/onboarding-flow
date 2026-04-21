"""Tests for the unified /external/intake multipart endpoint and the
new salary-slip + semantic-search endpoints.

These run with all Claude services forced to deterministic so the
test suite stays hermetic and never hits the live API. The endpoint
contract (response shape, fields, status codes) is identical between
the Claude path and the deterministic path — the only difference is
the ``source`` field on the response.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.store import STORE


@pytest.fixture(autouse=True)
def _force_all_deterministic(monkeypatch):
    monkeypatch.setenv("AXIS_RESUME_MATCHER", "deterministic")
    monkeypatch.setenv("AXIS_SALARY_EXTRACTOR", "deterministic")
    monkeypatch.setenv("AXIS_JOB_SEARCHER", "deterministic")


@pytest.fixture
def client():
    return TestClient(fastapi_app)


SAMPLE_RESUME = b"""Priya Sharma
priya.sharma@example.com
HDFC Bank, Branch Manager Mumbai
- Corporate salary acquisition, CASA cross-sell
- KYC compliance, relationship management
- Burgundy / HNI portfolio
"""

SAMPLE_SLIP = b"""HDFC Bank Ltd.
Payslip for Mar 2026
Basic 62,000
HRA 24,800
Special Allowance 37,000
Annual variable pay 2,22,000
"""


def test_search_jobs_endpoint_returns_matches(client):
    resp = client.post(
        "/external/search-jobs",
        json={"query": "Branch Manager in Mumbai"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "Branch Manager in Mumbai"
    assert body["source"] == "deterministic"
    assert isinstance(body["matches"], list)


def test_parse_salary_slip_endpoint_returns_compensation(client):
    resp = client.post(
        "/external/parse-salary-slip",
        files={"file": ("march.txt", SAMPLE_SLIP, "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "deterministic"
    comp = body["compensation"]
    assert comp["basic"] == 62000 * 12
    assert comp["hra"] == 24800 * 12
    assert comp["variable"] == 222000
    assert comp["current_ctc"] is not None and comp["current_ctc"] > 0


def test_parse_salary_slip_endpoint_rejects_empty(client):
    resp = client.post(
        "/external/parse-salary-slip",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp.status_code == 400


def test_intake_endpoint_returns_full_payload(client):
    resp = client.post(
        "/external/intake",
        files={
            "resume": ("resume.txt", SAMPLE_RESUME, "text/plain"),
            "salary_slip": ("slip.txt", SAMPLE_SLIP, "text/plain"),
        },
        data={
            "name": "Priya Sharma",
            "email": "priya.sharma@example.com",
            "search_query": "Branch Manager in Mumbai",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resume_text"]
    assert body["search_query"] == "Branch Manager in Mumbai"
    assert body["search_source"] == "deterministic"
    assert isinstance(body["search_matches"], list)
    assert isinstance(body["ai_recommendations"], list)
    assert body["salary_source"] == "deterministic"
    profile = body["profile"]
    assert profile["name"] == "Priya Sharma"
    assert profile["email"] == "priya.sharma@example.com"
    # Compensation got merged into the profile.
    assert profile["compensation"] is not None
    assert profile["compensation"]["current_ctc"] is not None


def test_intake_endpoint_works_without_optional_inputs(client):
    resp = client.post(
        "/external/intake",
        files={"resume": ("r.txt", SAMPLE_RESUME, "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["search_matches"] == []
    assert body["search_source"] is None
    assert body["salary_source"] is None
    assert body["profile"]["compensation"] is None


def test_apply_endpoint_threads_search_provenance(client):
    # First parse a resume so we have a profile + recommendations.
    resp = client.post(
        "/external/parse-resume",
        json={"resume_text": SAMPLE_RESUME.decode()},
    )
    assert resp.status_code == 200
    matches = resp.json()["matches"]
    assert matches, "expected at least one recommendation"
    job_id = matches[0]["job_id"]

    # Now apply with provenance + a synthetic compensation block.
    resp2 = client.post(
        "/external/apply",
        json={
            "resume_text": SAMPLE_RESUME.decode(),
            "job_id": job_id,
            "search_query": "Branch Manager in Mumbai",
            "recommendation_source": "search",
            "compensation": {
                "current_ctc": 1850000,
                "basic": 740000,
                "hra": 296000,
                "variable": 222000,
                "extraction_source": "deterministic",
            },
        },
    )
    assert resp2.status_code == 200, resp2.text
    app_body = resp2.json()
    assert app_body["candidate_kind"] == "external"
    assert app_body["search_query"] == "Branch Manager in Mumbai"
    assert app_body["recommendation_source"] == "search"
    # Candidate persisted with compensation on profile.
    cand = STORE.get_candidate(app_body["candidate_id"])
    assert cand is not None
    assert cand.profile.compensation is not None
    assert cand.profile.compensation.current_ctc == 1850000
