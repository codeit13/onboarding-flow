"""External candidate flow — TDD spec.

Covers the new "Apply from outside Axis" intake path.

Distinguishing facts vs the internal path
-----------------------------------------
- The candidate has *no* Thrive profile and *no* Axis calendar.
- They land on the public landing page (4th persona tile), paste their
  resume, get a Claude-driven match against open JDs, and apply.
- The orchestrator MUST NOT try to read their calendar via Graph
  free/busy. It proposes slots from the HR partner's calendar alone and
  emails the candidate the proposed slots. The reply lands in Meera's
  inbox; a poller reads it, Claude extracts the chosen slot, the
  orchestrator resumes.
- The internal path (Rohan Desai etc.) MUST stay byte-for-byte identical.

Each test in this file is structured to pin one slice of behaviour. Tests
in other files (test_agent_e2e, test_intake) cover the internal path —
they MUST continue to pass after this feature lands. That's the
regression contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import (
    AgentStatus,
    Application,
    FunnelStage,
)
from app.store import STORE


# ---------------------------------------------------------------------------
# Sample resume text — kept inline so the test is self-contained
# ---------------------------------------------------------------------------

SAMPLE_RESUME = """
Siddharth Goyal External
siddharth.goyal@xebia.com · Bangalore, India · +91 98xxxxxxxx

PROFESSIONAL SUMMARY
Senior Relationship Manager with 9 years in retail and corporate banking,
specialising in corporate salary acquisition, CASA growth, and burgundy /
priority customer onboarding. Track record of growing branch books by
₹100+ crore and leading cross-functional teams of 8-12 RMs.

EXPERIENCE
HDFC Bank — Branch Manager, Indore (Jan 2021 - present)
- Led the corporate salary mandate for 3 mid-size IT firms; closed 1,400
  salary accounts with 58% CASA attachment.
- Owned the burgundy upgrade drive — converted 71 mass-affluent customers
  in 90 days, adding ₹84 crore in book value.
- Managed branch KYC compliance, brought non-compliance from 11% to 2%.

ICICI Bank — Relationship Manager, Bhopal (2017 - 2020)
- SME loan origination + working capital structuring.
- Handled a portfolio of 220 corporate salary accounts.

EDUCATION
MBA Finance, IIM Indore (2016)
BCom, DAVV Indore (2014)

SKILLS
Corporate salary acquisition, CASA growth, KYC compliance, portfolio
management, stakeholder management, MS Excel, Tableau.
"""


# ---------------------------------------------------------------------------
# 1. Resume parser — deterministic fallback so tests don't hit Claude
# ---------------------------------------------------------------------------


def test_resume_parser_returns_structured_external_profile() -> None:
    """parse_resume() must return an ExternalProfile with at least name,
    email, skills, and a free-text summary. The deterministic fallback is
    used in tests (no real Anthropic call)."""
    from app.tools.external_intake import parse_resume

    profile = parse_resume(SAMPLE_RESUME)
    assert profile.name
    assert "@" in profile.email
    assert len(profile.skills) >= 3
    # The parser must lift at least one skill that overlaps the seeded JDs.
    skills_lower = {s.lower() for s in profile.skills}
    assert any(
        kw in skills_lower or any(kw in s for s in skills_lower)
        for kw in ("casa", "salary", "kyc", "portfolio")
    )


def test_resume_parser_handles_minimal_input() -> None:
    """A near-empty resume must not crash; it should return a profile with
    placeholder name and an empty skill list."""
    from app.tools.external_intake import parse_resume

    profile = parse_resume("Jane Doe\njane@example.com\n")
    assert profile.email == "jane@example.com"
    assert profile.name  # any non-empty placeholder is fine


# ---------------------------------------------------------------------------
# 2. Job recommendation against the seeded JDs
# ---------------------------------------------------------------------------


def test_recommend_jobs_returns_ranked_matches() -> None:
    """Given a parsed external profile, recommend_jobs() returns the seeded
    JDs ranked highest-match first, each with a score in [0, 100]."""
    from app.tools.external_intake import parse_resume, recommend_jobs

    profile = parse_resume(SAMPLE_RESUME)
    matches = recommend_jobs(profile)
    assert matches, "expected at least one recommended job"
    # Sorted descending.
    scores = [m.match_percent for m in matches]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= m.match_percent <= 100 for m in matches)
    # Top match must be one of the BDM / branch-manager JDs because the
    # resume is heavy on corporate salary + branch management.
    top = matches[0]
    assert any(
        kw in top.job_title.lower()
        for kw in ("business development manager", "branch manager", "relationship")
    )


# ---------------------------------------------------------------------------
# 3. Apply path — creates Application with candidate_kind == "external"
# ---------------------------------------------------------------------------


def test_apply_external_creates_application_with_kind_external() -> None:
    from app.tools.external_intake import apply_external, parse_resume, recommend_jobs

    profile = parse_resume(SAMPLE_RESUME)
    target_job = recommend_jobs(profile)[0]
    app = apply_external(profile, target_job.job_id)

    assert isinstance(app, Application)
    assert app.candidate_kind == "external"
    assert app.stage == FunnelStage.APPLIED
    # The external candidate must be persisted under their email so the
    # frontend can re-fetch their applications next time they come back.
    cand = STORE.get_candidate(profile.email)
    assert cand is not None
    assert cand.kind == "external"
    assert cand.profile.email == profile.email


def test_internal_candidates_remain_kind_internal() -> None:
    """Regression: every fixture-seeded candidate must still report
    kind == 'internal'. We did NOT change them."""
    for cand in STORE.candidates.values():
        assert cand.kind == "internal"


# ---------------------------------------------------------------------------
# 4. Orchestrator branching — external skips candidate free/busy
# ---------------------------------------------------------------------------


def test_external_application_does_not_query_candidate_calendar(monkeypatch) -> None:
    """When the orchestrator schedules R1 for an external candidate, it
    must NOT pass the candidate's email into get_free_busy. The candidate
    has no Axis calendar and Graph would 404 in real life.

    We patch find_common_slots so we can assert which user_ids it was
    asked to intersect.
    """
    from app.tools.external_intake import apply_external, parse_resume, recommend_jobs
    from app import orchestrator as orch_mod
    from app.models import TimeSlot

    profile = parse_resume(SAMPLE_RESUME)
    target = recommend_jobs(profile)[0]
    app = apply_external(profile, target.job_id)

    captured_user_ids: list[list[str]] = []

    def fake_find(user_ids, duration_min, window_start, window_end, top_n=3):
        captured_user_ids.append(list(user_ids))
        # Return three deterministic slots starting tomorrow morning IST.
        base = window_start + timedelta(hours=4)
        return [
            TimeSlot(start=base + timedelta(hours=i * 2), end=base + timedelta(hours=i * 2 + 1))
            for i in range(3)
        ]

    monkeypatch.setattr(orch_mod, "find_common_slots", fake_find)

    orch = orch_mod.Orchestrator()
    orch.trigger(app.id)
    # Wait for the orchestrator thread to drain to its first WAITING state.
    _wait_for(orch, app.id, lambda a: a.agent_status != AgentStatus.RUNNING)

    refreshed = STORE.get_application(app.id)
    assert refreshed is not None
    assert refreshed.agent_status == AgentStatus.WAITING_CANDIDATE
    assert len(refreshed.proposed_r1_slots) == 3
    # The find_common_slots call MUST have excluded the external email.
    assert captured_user_ids, "find_common_slots was never called"
    last_call_users = captured_user_ids[-1]
    assert profile.email not in last_call_users, (
        f"external candidate email {profile.email!r} leaked into the "
        f"calendar intersection ({last_call_users}) — Graph would 404"
    )


# ---------------------------------------------------------------------------
# 5. Inbound mail — Claude extracts the chosen slot from a free-text reply
# ---------------------------------------------------------------------------


def test_extract_slot_choice_from_reply_text_picks_index() -> None:
    """Given a free-text reply that says 'Tuesday 11am works' and a list of
    proposed slots, the parser must pick the matching index. Deterministic
    fallback in tests."""
    from app.services.inbox_parser import extract_slot_choice
    from app.models import TimeSlot

    base = datetime(2026, 4, 14, 5, 30)  # Tue 11:00 IST = 05:30 UTC
    slots = [
        TimeSlot(start=base, end=base + timedelta(hours=1)),  # Tue 11:00
        TimeSlot(start=base + timedelta(days=1), end=base + timedelta(days=1, hours=1)),  # Wed 11:00
        TimeSlot(start=base + timedelta(days=2), end=base + timedelta(days=2, hours=1)),  # Thu 11:00
    ]
    reply = "Hi Meera, Tuesday 11am works perfectly for me. Thanks, Sid."
    idx = extract_slot_choice(reply, slots)
    assert idx == 0


def test_extract_slot_choice_picks_explicit_option_number() -> None:
    from app.services.inbox_parser import extract_slot_choice
    from app.models import TimeSlot

    base = datetime(2026, 4, 14, 5, 30)
    slots = [TimeSlot(start=base + timedelta(days=i), end=base + timedelta(days=i, hours=1)) for i in range(3)]
    assert extract_slot_choice("Option 2 please", slots) == 1
    assert extract_slot_choice("I'll take slot 3", slots) == 2


def test_extract_slot_choice_returns_none_when_unclear() -> None:
    from app.services.inbox_parser import extract_slot_choice
    from app.models import TimeSlot

    base = datetime(2026, 4, 14, 5, 30)
    slots = [TimeSlot(start=base + timedelta(days=i), end=base + timedelta(days=i, hours=1)) for i in range(3)]
    assert extract_slot_choice("Sounds good!", slots) is None


# ---------------------------------------------------------------------------
# 6. End-to-end: simulated email reply advances the orchestrator
# ---------------------------------------------------------------------------


def test_simulated_external_reply_books_meeting(monkeypatch) -> None:
    """Full external slice. We:
    1. apply_external as Siddharth
    2. let the orchestrator propose slots and email them
    3. simulate Meera's inbox receiving a reply that picks slot 1
    4. invoke the inbound handler
    5. assert the application moves to R1_SCHEDULED with a meeting record
    """
    from app.tools.external_intake import apply_external, parse_resume, recommend_jobs
    from app.services.inbox_parser import handle_external_reply
    from app import orchestrator as orch_mod

    profile = parse_resume(SAMPLE_RESUME)
    target = recommend_jobs(profile)[0]
    app = apply_external(profile, target.job_id)

    # Use the global orchestrator that the API uses, so on_candidate_confirm
    # routes through the same path the live HTTP handler hits.
    from app.orchestrator import ORCHESTRATOR
    ORCHESTRATOR.trigger(app.id)
    _wait_for(ORCHESTRATOR, app.id, lambda a: a.agent_status == AgentStatus.WAITING_CANDIDATE)

    refreshed = STORE.get_application(app.id)
    assert refreshed is not None
    assert refreshed.proposed_r1_slots, "orchestrator should have proposed slots"

    handled = handle_external_reply(
        sender_email=profile.email,
        body_text="Hi Meera, slot 2 please. Thanks!",
    )
    assert handled is True

    _wait_for(ORCHESTRATOR, app.id, lambda a: a.stage == FunnelStage.R1_SCHEDULED)
    after = STORE.get_application(app.id)
    assert after is not None
    assert after.stage == FunnelStage.R1_SCHEDULED
    assert after.selected_r1_slot_index == 1
    r1 = next((i for i in after.interviews if i.round == "R1"), None)
    assert r1 is not None and r1.meeting_slot is not None


def test_external_application_synthesises_r1_slots_when_calendar_empty(monkeypatch) -> None:
    """Round 1 is run by the AI Interview Agent — no human panellist
    actually has to be free for the candidate to take the call. So when
    Graph free/busy returns zero slots (HR partner fully booked, Graph
    503, whatever), the orchestrator MUST top up with deterministic
    business-hour slots so the candidate is never blocked.

    Regression for the screenshot bug where the candidate page sat on
    "AGENT · WAITING ON HR" forever because we'd parked the application
    instead of giving them three fallback AI-agent slots.
    """
    from app.tools.external_intake import apply_external, parse_resume, recommend_jobs
    from app import orchestrator as orch_mod

    profile = parse_resume(SAMPLE_RESUME)
    target = recommend_jobs(profile)[0]
    app = apply_external(profile, target.job_id)

    # Simulate the panel calendar being completely full for the next
    # 10 days — Graph returns zero common slots.
    monkeypatch.setattr(
        orch_mod,
        "find_common_slots",
        lambda **kwargs: [],
    )

    orch = orch_mod.Orchestrator()
    orch.trigger(app.id)
    _wait_for(orch, app.id, lambda a: a.agent_status != AgentStatus.RUNNING)

    refreshed = STORE.get_application(app.id)
    assert refreshed is not None
    # The candidate must have been advanced to slot picker, NOT parked on HR.
    assert refreshed.agent_status == AgentStatus.WAITING_CANDIDATE, (
        f"expected WAITING_CANDIDATE after synth top-up, got {refreshed.agent_status} "
        f"(next_action={refreshed.next_action!r})"
    )
    assert len(refreshed.proposed_r1_slots) == 3
    # Synthetic slots must be 30-min business-hour weekday slots in IST.
    for slot in refreshed.proposed_r1_slots:
        diff = (slot.end - slot.start).total_seconds()
        assert diff == 30 * 60
        assert slot.start.weekday() < 5  # Mon-Fri
    # Activity feed must explain that we topped up with synthetic slots.
    messages = [evt.message for evt in refreshed.events]
    assert any("synthetic" in m.lower() for m in messages), messages


def test_external_application_uses_real_calendar_slots_when_available(monkeypatch) -> None:
    """When Graph returns real slots, the orchestrator must use them
    verbatim and NOT mix in synthetic ones."""
    from app.tools.external_intake import apply_external, parse_resume, recommend_jobs
    from app import orchestrator as orch_mod
    from app.models import TimeSlot

    profile = parse_resume(SAMPLE_RESUME)
    target = recommend_jobs(profile)[0]
    app = apply_external(profile, target.job_id)

    real_slots = [
        TimeSlot(
            start=datetime.utcnow().replace(hour=4, minute=30, second=0, microsecond=0)
            + timedelta(days=1 + i),
            end=datetime.utcnow().replace(hour=5, minute=0, second=0, microsecond=0)
            + timedelta(days=1 + i),
        )
        for i in range(3)
    ]
    monkeypatch.setattr(
        orch_mod,
        "find_common_slots",
        lambda **kwargs: real_slots,
    )

    orch = orch_mod.Orchestrator()
    orch.trigger(app.id)
    _wait_for(orch, app.id, lambda a: a.agent_status != AgentStatus.RUNNING)

    refreshed = STORE.get_application(app.id)
    assert refreshed is not None
    assert refreshed.agent_status == AgentStatus.WAITING_CANDIDATE
    assert refreshed.proposed_r1_slots == real_slots
    messages = [evt.message for evt in refreshed.events]
    assert not any("synthetic" in m.lower() for m in messages), messages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_for(orch, app_id: str, predicate, timeout_sec: float = 5.0) -> None:
    """Spin until predicate(application) is True or we time out."""
    import time as _t
    deadline = _t.time() + timeout_sec
    while _t.time() < deadline:
        app = STORE.get_application(app_id)
        if app and predicate(app):
            return
        _t.sleep(0.05)
    raise AssertionError(
        f"timed out waiting for predicate on {app_id}; "
        f"final state = {STORE.get_application(app_id)}"
    )
