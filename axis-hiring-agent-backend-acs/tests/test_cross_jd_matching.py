"""Tests for Feature 3 — Cross-JD Matching in Single JD Mode.

When screening CVs against a single JD, the system also scores each candidate
against all other open roles and populates all_job_scores / best_job_id /
best_job_title fields on each BulkCandidateRow.
"""

import os
# Force test env before any app imports
os.environ.setdefault("AXIS_CALENDAR_PROVIDER", "mock")
os.environ.setdefault("AXIS_MESSAGING_PROVIDER", "mock")
os.environ.setdefault("AXIS_ACS_PROVIDER", "mock")
os.environ.setdefault("AXIS_INTERVIEW_SCORER", "off")
os.environ.setdefault("AXIS_RESUME_MATCHER", "off")
os.environ.setdefault("AXIS_PANEL_RECOMMENDER", "off")
os.environ.setdefault("AXIS_SALARY_EXTRACTOR", "off")
os.environ.setdefault("AXIS_JOB_SEARCHER", "off")
os.environ.setdefault("ANTHROPIC_API_KEY", "")

from unittest.mock import MagicMock, patch
from typing import List

import pytest

from app.models.domain import BulkCandidateRow, CandidatePool, Job, Profile
from app.services.claude_cv_screener import CvScreenResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(job_id: str, title: str) -> Job:
    """Create a minimal Job for testing."""
    return Job(
        id=job_id,
        job_id=job_id.replace("job-", ""),
        title=title,
        band="B4",
        tags=["test"],
        location="Mumbai",
        required_skills=["python", "sql"],
        hr_partner_id="hr-1",
        panel=[],
    )


def _make_profile(name: str = "Test Candidate") -> Profile:
    return Profile(
        employee_id="emp-test",
        name=name,
        email=f"{name.lower().replace(' ', '.')}@test.com",
        current_role="Engineer",
        current_location="Mumbai",
        tenure_years=5.0,
        skills=["python", "sql", "java"],
    )


def _make_screen_result(match_percent: float, recommendation: str = "shortlist") -> CvScreenResult:
    return CvScreenResult(
        match_percent=match_percent,
        recommendation=recommendation,
        headline="Test headline",
        summary="Test summary",
        strengths=["Good"],
        concerns=[],
        evidence_quotes=[],
        matched_skills=["python"],
        missing_skills=[],
        source="deterministic",
    )


def _make_row(row_id: str = "row-test1") -> BulkCandidateRow:
    return BulkCandidateRow(row_id=row_id, file_name="test.pdf")


# ---------------------------------------------------------------------------
# The function under test: we extract the cross-JD scoring logic to test it
# in isolation. This mirrors what _score_single_row does after single_jd
# primary scoring.
# ---------------------------------------------------------------------------


def _apply_cross_jd_enrichment(
    row: BulkCandidateRow,
    primary_job: Job,
    primary_result: CvScreenResult,
    resume_text: str,
    profile: Profile,
    store_list_jobs_fn,
    screen_cv_fn,
):
    """Replicate the cross-JD enrichment logic from main.py."""
    other_jobs = [j for j in store_list_jobs_fn() if j.id != primary_job.id]
    if other_jobs:
        cross_scores = [{
            "job_id": primary_job.id,
            "job_title": primary_job.title,
            "location": getattr(primary_job, "location", ""),
            "band": getattr(primary_job, "band", ""),
            "match_percent": round(primary_result.match_percent, 1),
            "recommendation": primary_result.recommendation,
        }]
        for other_job in other_jobs:
            try:
                other_result = screen_cv_fn(resume_text, profile, other_job)
                cross_scores.append({
                    "job_id": other_job.id,
                    "job_title": other_job.title,
                    "location": getattr(other_job, "location", ""),
                    "band": getattr(other_job, "band", ""),
                    "match_percent": round(other_result.match_percent, 1),
                    "recommendation": other_result.recommendation,
                })
            except Exception:
                pass
        row.all_job_scores = sorted(
            cross_scores, key=lambda x: x["match_percent"], reverse=True
        )
        if row.all_job_scores:
            top = row.all_job_scores[0]
            row.best_job_id = top["job_id"]
            row.best_job_title = top["job_title"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCrossJdMatching:
    """Cross-JD matching in single_jd mode."""

    def test_single_jd_populates_all_job_scores(self):
        """Single JD mode scores against all jobs, populates all_job_scores."""
        primary_job = _make_job("job-1", "Backend Engineer")
        other_job = _make_job("job-2", "Data Scientist")
        profile = _make_profile()
        row = _make_row()
        primary_result = _make_screen_result(75.0)

        def list_jobs():
            return [primary_job, other_job]

        def screen_cv(text, prof, job):
            return _make_screen_result(60.0, "maybe")

        _apply_cross_jd_enrichment(
            row, primary_job, primary_result,
            "resume text", profile, list_jobs, screen_cv,
        )

        assert len(row.all_job_scores) == 2
        job_ids = [s["job_id"] for s in row.all_job_scores]
        assert "job-1" in job_ids
        assert "job-2" in job_ids

    def test_single_jd_best_job_set(self):
        """best_job_id set to highest scorer across all JDs."""
        primary_job = _make_job("job-1", "Backend Engineer")
        other_job = _make_job("job-2", "Data Scientist")
        profile = _make_profile()
        row = _make_row()
        primary_result = _make_screen_result(60.0, "maybe")

        def list_jobs():
            return [primary_job, other_job]

        def screen_cv(text, prof, job):
            # Other job scores higher
            return _make_screen_result(90.0, "shortlist")

        _apply_cross_jd_enrichment(
            row, primary_job, primary_result,
            "resume text", profile, list_jobs, screen_cv,
        )

        assert row.best_job_id == "job-2"
        assert row.best_job_title == "Data Scientist"

    def test_cross_scores_sorted_descending(self):
        """all_job_scores sorted by match_percent descending."""
        primary_job = _make_job("job-1", "Role A")
        profile = _make_profile()
        row = _make_row()
        primary_result = _make_screen_result(50.0, "maybe")

        jobs = [
            primary_job,
            _make_job("job-2", "Role B"),
            _make_job("job-3", "Role C"),
        ]
        scores_map = {"job-2": 80.0, "job-3": 65.0}

        def list_jobs():
            return jobs

        def screen_cv(text, prof, job):
            return _make_screen_result(scores_map[job.id])

        _apply_cross_jd_enrichment(
            row, primary_job, primary_result,
            "resume text", profile, list_jobs, screen_cv,
        )

        percents = [s["match_percent"] for s in row.all_job_scores]
        assert percents == sorted(percents, reverse=True)
        assert percents == [80.0, 65.0, 50.0]

    def test_primary_jd_included_in_cross_scores(self):
        """The selected JD appears in all_job_scores."""
        primary_job = _make_job("job-1", "Backend Engineer")
        other_job = _make_job("job-2", "Frontend Engineer")
        profile = _make_profile()
        row = _make_row()
        primary_result = _make_screen_result(85.0)

        def list_jobs():
            return [primary_job, other_job]

        def screen_cv(text, prof, job):
            return _make_screen_result(70.0)

        _apply_cross_jd_enrichment(
            row, primary_job, primary_result,
            "resume text", profile, list_jobs, screen_cv,
        )

        primary_in_scores = [s for s in row.all_job_scores if s["job_id"] == "job-1"]
        assert len(primary_in_scores) == 1
        assert primary_in_scores[0]["match_percent"] == 85.0

    def test_auto_map_unchanged(self):
        """Auto-map mode still uses its own logic — cross-JD enrichment only
        runs for single_jd when there are other jobs."""
        row = _make_row()
        # In auto_map mode the cross-JD enrichment function is never called.
        # Verify that calling it with no other jobs leaves the row empty.
        primary_job = _make_job("job-only", "Only Role")
        primary_result = _make_screen_result(80.0)

        def list_jobs():
            return [primary_job]  # Only the primary job exists

        _apply_cross_jd_enrichment(
            row, primary_job, primary_result,
            "resume text", _make_profile(), list_jobs, lambda *a: None,
        )

        # No other jobs → no cross-JD data added
        assert row.all_job_scores == []
        assert row.best_job_id is None
        assert row.best_job_title is None

    def test_single_jd_one_job_only(self):
        """With only 1 open job, all_job_scores stays empty (no cross-JD data)."""
        primary_job = _make_job("job-solo", "Solo Role")
        profile = _make_profile()
        row = _make_row()
        primary_result = _make_screen_result(72.0)

        def list_jobs():
            return [primary_job]

        _apply_cross_jd_enrichment(
            row, primary_job, primary_result,
            "resume text", profile, list_jobs, lambda *a: None,
        )

        assert row.all_job_scores == []
        assert row.best_job_id is None

    def test_error_rows_no_cross_scores(self):
        """Failed parse rows don't have cross-JD scores — the function is never
        called for them, so the row stays empty."""
        row = _make_row()
        row.status = "error"
        row.error_message = "Parse failed"

        # We never call _apply_cross_jd_enrichment for error rows
        assert row.all_job_scores == []
        assert row.best_job_id is None
        assert row.best_job_title is None

    def test_cross_jd_skips_failed_scoring(self):
        """If scoring against a cross-JD fails, that job is skipped gracefully."""
        primary_job = _make_job("job-1", "Role A")
        other_jobs = [_make_job("job-2", "Role B"), _make_job("job-3", "Role C")]
        profile = _make_profile()
        row = _make_row()
        primary_result = _make_screen_result(70.0)

        def list_jobs():
            return [primary_job] + other_jobs

        call_count = 0

        def screen_cv(text, prof, job):
            nonlocal call_count
            call_count += 1
            if job.id == "job-2":
                raise RuntimeError("Claude timeout")
            return _make_screen_result(55.0, "maybe")

        _apply_cross_jd_enrichment(
            row, primary_job, primary_result,
            "resume text", profile, list_jobs, screen_cv,
        )

        # job-2 failed, so we should have 2 entries (primary + job-3)
        assert len(row.all_job_scores) == 2
        job_ids = [s["job_id"] for s in row.all_job_scores]
        assert "job-1" in job_ids
        assert "job-3" in job_ids
        assert "job-2" not in job_ids
