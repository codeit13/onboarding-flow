"""Tests for the Claude semantic job searcher.

Force the deterministic provider via env so tests stay hermetic. The
deterministic path uses token-overlap with title/location bonuses and
shares the result shape with the live Claude path.
"""

from __future__ import annotations

import pytest

from app.services.claude_job_searcher import search_jobs, _tokens
from app.tools.external_intake import ExternalRecommendation


@pytest.fixture(autouse=True)
def _force_deterministic(monkeypatch):
    monkeypatch.setenv("AXIS_JOB_SEARCHER", "deterministic")


def test_search_jobs_empty_query_returns_nothing():
    matches, source = search_jobs("")
    assert matches == []
    assert source == "deterministic"


def test_search_jobs_returns_branch_manager_for_branch_manager_query():
    matches, source = search_jobs("Branch Manager in Mumbai")
    assert source == "deterministic"
    assert isinstance(matches, list)
    # At least one of the seeded JDs should match — and the top hit must be
    # a real ExternalRecommendation with a non-empty rationale.
    assert len(matches) >= 1
    top = matches[0]
    assert isinstance(top, ExternalRecommendation)
    assert top.match_percent >= 30.0
    assert top.rationale


def test_search_jobs_results_sorted_descending():
    matches, _ = search_jobs("relationship manager wealth Mumbai")
    scores = [m.match_percent for m in matches]
    assert scores == sorted(scores, reverse=True)


def test_search_jobs_drops_unrelated_queries():
    # Total nonsense — must not surface anything above the 30 threshold.
    matches, source = search_jobs("xyzzy plover frobnicate")
    assert source == "deterministic"
    assert matches == []


def test_tokens_filters_stopwords():
    toks = _tokens("I am looking for a Branch Manager in Mumbai")
    assert "looking" not in toks
    assert "manager" in toks
    assert "mumbai" in toks


def test_provider_env_override_to_claude_without_key_falls_back(monkeypatch):
    monkeypatch.setenv("AXIS_JOB_SEARCHER", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    matches, source = search_jobs("Branch Manager Mumbai")
    assert source == "deterministic"
