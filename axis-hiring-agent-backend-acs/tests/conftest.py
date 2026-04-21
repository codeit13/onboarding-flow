"""Shared pytest fixtures.

Every test gets a fresh seeded store, a clean messaging log, a fresh calendar,
and a fresh interview feedback store. Tests that want to assert on empty
baseline state can just import the reset helpers directly.

Tests always run against the in-memory Mock providers, even if the
operator's .env has flipped the runtime app to ``graph`` mode. Real Graph
calls are reserved for the live demo and the dedicated live smoke script —
the unit tests must be deterministic and offline.
"""

import os

# IMPORTANT: force mock providers BEFORE any `from app...` import below,
# because app/__init__.py auto-loads the runtime .env (which may set these
# to "graph" for the live demo).
os.environ["AXIS_CALENDAR_PROVIDER"] = "mock"
os.environ["AXIS_MESSAGING_PROVIDER"] = "mock"
# Skip the cosmetic "agent is interviewing" pause during tests so the
# orchestrator settles inside the 5s join window the e2e tests use.
os.environ["AXIS_R1_RUN_DELAY_SEC"] = "0"
os.environ["AXIS_R1_SCORE_DELAY_SEC"] = "0"
os.environ["AXIS_SCREEN_SCAN_DELAY_SEC"] = "0"
os.environ["AXIS_SCREEN_MATCH_DELAY_SEC"] = "0"
os.environ["AXIS_SCREEN_RUBRIC_DELAY_SEC"] = "0"
# ACS mock provider — drive the simulated Teams call instantly so tests
# can poll for the final state without sleeping.
os.environ["AXIS_ACS_PROVIDER"] = "mock"
os.environ["AXIS_ACS_MOCK_QUESTION_DELAY"] = "0"
# Disable real Claude calls in tests — every Claude-backed scorer
# (R1 transcript, resume matcher, panel recommender, salary extractor)
# must use its deterministic heuristic fallback so tests stay offline
# and complete inside the 5s orchestrator join window the e2e suite
# uses. Real Claude calls are reserved for the live demo path.
os.environ["AXIS_INTERVIEW_SCORER"] = "off"
os.environ["AXIS_RESUME_MATCHER"] = "off"
os.environ["AXIS_PANEL_RECOMMENDER"] = "off"
os.environ["AXIS_SALARY_EXTRACTOR"] = "off"
os.environ["AXIS_JOB_SEARCHER"] = "off"
# Make absolutely sure no real key leaks into the test process even
# if the operator has one exported in their shell — we never want a
# unit test to make a billable network call.
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest

from app.fixtures import seed_all
from app.providers import reset_providers
from app.services.virtual_interviewer import reset_virtual_interview_state
from app.tools import checklists
from app.tools.interview import _reset_interview


@pytest.fixture(autouse=True)
def _reset_all() -> None:
    seed_all()
    # Messaging + calendar state lives on the active provider — resetting the
    # provider singletons clears in-memory mock inboxes/calendars between tests.
    reset_providers()
    reset_virtual_interview_state()
    _reset_interview()
    checklists.reset_customisations()
    yield
