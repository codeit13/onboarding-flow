"""End-to-end orchestrator test.

Drives candidates all the way through the funnel via the *autonomous*
``app.orchestrator.ORCHESTRATOR`` (not the legacy synchronous ``app.agent``)
and asserts the observable effects at every stage: store mutations,
checklists, calendar events on the active CalendarProvider, emails on
the active MessagingProvider, and audit events on the application.

Because the orchestrator runs each application in a daemon background
thread, every "drive" helper here joins the running thread (with a
generous timeout) so the asserts see a quiesced state machine.
"""

from __future__ import annotations

import time

from app.models import AgentStatus, FunnelStage
from app.orchestrator import ORCHESTRATOR
from app.providers import get_calendar_provider, get_messaging_provider
from app.store import STORE
from app.tools.checklists import tick_checklist_item
from app.tools.interview import submit_panel_feedback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _join(application_id: str, timeout: float = 5.0) -> None:
    """Wait until the orchestrator thread for this application has exited."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = ORCHESTRATOR._threads.get(application_id)  # noqa: SLF001 — test introspection
        if t is None or not t.is_alive():
            return
        t.join(timeout=deadline - time.time())
    raise TimeoutError(f"Orchestrator for {application_id} did not settle in {timeout}s")


def _drive_to_pause(employee_id: str, jd_id: str):
    """Start an application and wait for the orchestrator to pause/finish."""
    app = ORCHESTRATOR.start_application(employee_id, jd_id)
    _join(app.id)
    return STORE.get_application(app.id)


def _drive_through_r1_slot(employee_id: str, jd_id: str):
    """Drive an application all the way through Round 1.

    The orchestrator pauses three times before R1_DONE in the post-fix
    flow: first at WAITING_CANDIDATE for slot pick, then at
    WAITING_CANDIDATE for the candidate to click "Start interview", then
    *again* at WAITING_CANDIDATE because _do_run_r1 now refuses to score
    until the candidate has actually completed the AI interview (no
    more auto-rejection on a canned transcript). This helper walks all
    three gates by simulating the candidate finishing the AI interview
    via the same code path the live virtual_interviewer uses: writing a
    transcript onto the InterviewRecord and re-triggering the loop.
    """
    from app.orchestrator import _strong_transcript, _weak_transcript
    from app.tools.intake import get_jd

    app = _drive_to_pause(employee_id, jd_id)
    if app.agent_status == AgentStatus.WAITING_CANDIDATE and app.proposed_r1_slots:
        ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R1", 0)
        _join(app.id)
        app = STORE.get_application(app.id)
    if app.stage == FunnelStage.R1_SCHEDULED and not app.r1_started:
        ORCHESTRATOR.on_candidate_start_r1(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)
        # Simulate the candidate completing the AI interview: pick the
        # same canned strong/weak transcript the legacy auto-runner used,
        # write it onto the R1 InterviewRecord, then re-trigger the
        # orchestrator. This matches what
        # virtual_interviewer._fold_transcript_into_interview does in
        # production after the candidate's last typed answer.
        app = STORE.get_application(app.id)
        stub = next((i for i in app.interviews if i.round == "R1"), None)
        if stub is not None and not stub.transcript:
            jd = get_jd(app.job_id)
            stub.transcript = (
                _strong_transcript(jd) if app.match_percent >= 85 else _weak_transcript()
            )
            ORCHESTRATOR.trigger(app.id)
            _join(app.id)
            app = STORE.get_application(app.id)
    # New flow: _do_run_r1 now hands control back to HR after R1 (the
    # human-in-the-loop "AI is an aid, not a gate" rule) and pauses
    # WAITING_HR with no pending checklist items — only a free-text
    # next_action telling HR to review the transcript. The legacy tests
    # below expect the WAITING_HR pause to instead be the *panel
    # composition* gate (with pre-r2 checklist instantiated). Bridge the
    # two by triggering one more loop pass: _do_schedule_r2 will create
    # the pre-r2 checklist and re-pause at the panel-composition gate.
    if (
        app.stage == FunnelStage.R1_DONE
        and app.agent_status == AgentStatus.WAITING_HR
        and not any(c.round == "R2" and c.phase == "pre" for c in app.checklists)
    ):
        ORCHESTRATOR.trigger(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)
    return app


# ---------------------------------------------------------------------------
# Strong path: Rohan -> shortlist -> R1 (strong canned transcript) -> R2
# scheduled, paused at WAITING_PANEL. Panel votes hire -> OFFER.
# ---------------------------------------------------------------------------


class TestHappyPathOfferJourney:
    def test_full_funnel_to_offer(self):
        app = _drive_through_r1_slot("EMP10234", "job-590321")

        # Match was strong enough to shortlist (>=75%) and R1 ran with the
        # strong canned transcript. R2 scheduling needs HR sign-off on the
        # panel composition first, so the orchestrator pauses at WAITING_HR.
        assert app.match_percent >= 75
        assert app.stage == FunnelStage.R1_DONE
        assert app.agent_status == AgentStatus.WAITING_HR
        assert any("Scored profile" in e.message for e in app.events)

        # CV moved to shortlisted folder during screening.
        assert STORE.folders.get("/cvs/shortlisted/job-590321/") == [app.id]

        # Outreach email landed on the configured candidate inbox.
        sent = get_messaging_provider().list_emails(application_id=app.id)
        assert any("Round 1 Interview" in m.subject for m in sent if m.direction == "out")

        # Pre-R1 + post-R1 checklists fully satisfied at this point.
        for round_, phase in (("R1", "pre"), ("R1", "post")):
            inst = next(c for c in app.checklists if c.round == round_ and c.phase == phase)
            assert inst.is_satisfied(blocking_only=True), f"{round_}/{phase} not satisfied"

        # HR approves the R2 panel (DESIGN-001): selecting a panel id replaces
        # the legacy manual checklist tick; the endpoint auto-ticks pre-r2-2.
        STORE.get_application(app.id).selected_r2_panel_id = "panel-bdm-central"
        tick_checklist_item(app.id, "R2", "pre", "pre-r2-2", actor="hr_partner",
                            note="Panel approved")
        ORCHESTRATOR.on_hr_tick(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)
        assert app.stage == FunnelStage.R1_DONE
        assert app.agent_status == AgentStatus.WAITING_CANDIDATE
        assert len(app.proposed_r2_slots) == 3
        assert app.selected_r2_slot_index is None

        # The candidate now picks an R2 slot — agent books the panel meeting
        # and parks at WAITING_PANEL.
        ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R2", 0)
        _join(app.id)
        app = STORE.get_application(app.id)
        assert app.stage == FunnelStage.R2_SCHEDULED
        assert app.agent_status == AgentStatus.WAITING_PANEL

        pre_r2 = next(c for c in app.checklists if c.round == "R2" and c.phase == "pre")
        assert pre_r2.is_satisfied(blocking_only=True)

        # Two Teams meetings exist on the calendar provider (R1 + R2).
        cal_events = [
            e for e in get_calendar_provider().list_events(application_id=app.id)
            if not e.cancelled
        ]
        assert len(cal_events) == 2

        # R1 interview record was created and scored.
        r1 = next(i for i in app.interviews if i.round == "R1")
        assert r1.score is not None and r1.score >= 70

        # R2 stub waiting for panel feedback.
        r2 = next(i for i in app.interviews if i.round == "R2")

        # Panel submits 3 positive feedback items, then we resume.
        for pid, rec in [
            ("sk.hm@axisbank.test", "strong_hire"),
            ("rv.int@axisbank.test", "hire"),
            ("pm.int@axisbank.test", "hire"),
        ]:
            submit_panel_feedback(
                interview_id=r2.id,
                panellist_id=pid,
                score=85.0,
                strengths="Strong domain + calm under pressure",
                concerns="",
                recommendation=rec,
            )

        ORCHESTRATOR.on_panel_feedback(app.id)
        _join(app.id)

        # New flow: after every panellist has voted the orchestrator does
        # NOT auto-execute the offer. It parks the application at
        # R2_SCHEDULED / WAITING_HR so the HR partner can review panel
        # feedback (and optionally run the Claude AI review) before clicking
        # "Make offer" — which is what on_hr_r2_decision executes below.
        app = STORE.get_application(app.id)
        assert app.stage == FunnelStage.R2_SCHEDULED
        assert app.agent_status == AgentStatus.WAITING_HR

        ORCHESTRATOR.on_hr_r2_decision(app.id, "offer")

        # New flow (post-2026-04-07): HR's "offer" decision no longer rolls
        # out the formal offer email directly. The application enters
        # OFFER_NEGOTIATION and is paused waiting on the Offer Discussion
        # Team. They click "Roll out final offer" — which moves the stage
        # to OFFER and sends comms.final_offer_email.
        app = STORE.get_application(app.id)
        assert app.stage == FunnelStage.OFFER_NEGOTIATION
        assert app.agent_status == AgentStatus.WAITING_OFFER_TEAM

        post_r2 = next(c for c in app.checklists if c.round == "R2" and c.phase == "post")
        assert post_r2.is_satisfied(blocking_only=True)

        # Offer Discussion Team finalises the negotiated CTC and rolls out
        # the formal offer letter.
        ORCHESTRATOR.on_offer_team_rollout(
            app.id,
            final_ctc_lpa=2_200_000.0,
            notes="22% hike on current CTC, joining bonus of ₹1.5L",
            rolled_out_by="offer-team-lead",
        )

        app = STORE.get_application(app.id)
        assert app.stage == FunnelStage.OFFER
        assert app.agent_status == AgentStatus.DONE
        assert app.offer_rolled_out is True
        assert app.offer_proposed_ctc_lpa == 2_200_000.0

        # Final offer email was sent.
        sent = get_messaging_provider().list_emails(application_id=app.id)
        assert any("offer" in m.subject.lower() for m in sent if m.direction == "out")


# ---------------------------------------------------------------------------
# Below-threshold candidate -> rejected at intake with regret email
# ---------------------------------------------------------------------------


class TestRejectionOnBelowThreshold:
    def test_below_threshold_pauses_for_hr_review(self):
        # New flow (2026-04-07 human-in-the-loop rule): the orchestrator
        # never auto-rejects an internal candidate at intake. A
        # below-threshold AI screening match parks the application on
        # HR with the full report, waits for an explicit advance/regret.
        app = _drive_to_pause("EMP11544", "job-590321")

        assert app.match_percent < 75
        assert app.stage == FunnelStage.APPLIED
        assert app.agent_status == AgentStatus.WAITING_HR
        # CV must NOT have moved to /rejected/ — it's alive pending HR.
        assert STORE.folders.get("/cvs/rejected/job-590321/") in (None, [])
        # And no candidate-facing regret email was sent yet.
        sent_to_candidate = [
            m
            for m in get_messaging_provider().list_emails(application_id=app.id)
            if m.direction == "out" and "not to move forward" in m.body
        ]
        assert sent_to_candidate == []
        # HR partner DID receive the screening review summary.
        sent_to_hr = [
            m
            for m in get_messaging_provider().list_emails(application_id=app.id)
            if m.direction == "out" and "Screening review" in m.subject
        ]
        assert sent_to_hr, "HR partner should have received the screening review email"

    def test_hr_regret_after_screening_review_closes_application(self):
        # HR opens the screening review and clicks Regret → application
        # moves to REJECTED and the standard regret email goes out.
        app = _drive_to_pause("EMP11544", "job-590321")
        assert app.agent_status == AgentStatus.WAITING_HR

        app.hr_screening_decision = "regret"
        ORCHESTRATOR.on_hr_tick(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)

        assert app.stage == FunnelStage.REJECTED
        assert app.agent_status == AgentStatus.DONE
        assert STORE.folders.get("/cvs/rejected/job-590321/") == [app.id]
        sent = get_messaging_provider().list_emails(application_id=app.id)
        assert any(
            "not to move forward" in m.body for m in sent if m.direction == "out"
        )

    def test_hr_advance_after_screening_review_resumes_funnel(self):
        # HR opens the screening review and clicks Advance → orchestrator
        # overrides the threshold, shortlists the candidate, and proceeds
        # to Round 1 outreach (parks at WAITING_CANDIDATE for slot pick).
        app = _drive_to_pause("EMP11544", "job-590321")
        assert app.agent_status == AgentStatus.WAITING_HR

        app.hr_screening_decision = "advance"
        ORCHESTRATOR.on_hr_tick(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)

        assert app.stage == FunnelStage.SCREENED
        assert app.agent_status == AgentStatus.WAITING_CANDIDATE
        assert STORE.folders.get("/cvs/shortlisted/job-590321/") == [app.id]
        assert len(app.proposed_r1_slots) > 0


# ---------------------------------------------------------------------------
# Panel-reject path: candidate clears R1 strongly, but two no_hire votes
# at R2 panel cause finalise() to land on REJECTED.
# ---------------------------------------------------------------------------


class TestPanelRejectAtFinalise:
    def test_two_no_hires_trigger_reject(self):
        app = _drive_through_r1_slot("EMP10234", "job-590321")
        assert app.stage == FunnelStage.R1_DONE

        # HR approves the panel composition; agent proposes R2 slots and pauses.
        STORE.get_application(app.id).selected_r2_panel_id = "panel-bdm-central"
        tick_checklist_item(app.id, "R2", "pre", "pre-r2-2", actor="hr_partner",
                            note="Panel approved")
        ORCHESTRATOR.on_hr_tick(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)
        assert app.agent_status == AgentStatus.WAITING_CANDIDATE
        assert len(app.proposed_r2_slots) == 3

        # Candidate picks R2 slot 0 → R2 booked, parks at WAITING_PANEL.
        ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R2", 0)
        _join(app.id)
        app = STORE.get_application(app.id)
        assert app.stage == FunnelStage.R2_SCHEDULED

        r2 = next(i for i in app.interviews if i.round == "R2")
        for pid, rec in [
            ("sk.hm@axisbank.test", "no_hire"),
            ("rv.int@axisbank.test", "no_hire"),
            ("pm.int@axisbank.test", "hire"),
        ]:
            submit_panel_feedback(
                interview_id=r2.id,
                panellist_id=pid,
                score=55.0,
                strengths="",
                concerns="weak on numbers",
                recommendation=rec,
            )

        ORCHESTRATOR.on_panel_feedback(app.id)
        _join(app.id)

        # New flow: panel voting complete → parks at WAITING_HR. HR then
        # clicks Reject, which executes the rejection path.
        app = STORE.get_application(app.id)
        assert app.stage == FunnelStage.R2_SCHEDULED
        assert app.agent_status == AgentStatus.WAITING_HR

        ORCHESTRATOR.on_hr_r2_decision(app.id, "reject")

        app = STORE.get_application(app.id)
        assert app.stage == FunnelStage.REJECTED
        assert app.agent_status == AgentStatus.DONE
        assert STORE.folders.get("/cvs/rejected/job-590321/") == [app.id]


# ---------------------------------------------------------------------------
# HR-unblock path: agent pauses on a blocking checklist item, HR ticks it,
# orchestrator resumes via on_hr_tick().
# ---------------------------------------------------------------------------


class TestCandidateSlotConfirmation:
    """Plan §4.4 — conversational outreach: candidate must pick a slot."""

    def test_orchestrator_pauses_for_candidate_slot_then_resumes(self):
        app = _drive_to_pause("EMP10234", "job-590321")

        # Without confirming, the orchestrator must NOT have booked R1.
        assert app.agent_status == AgentStatus.WAITING_CANDIDATE
        assert app.stage == FunnelStage.SCREENED
        assert len(app.proposed_r1_slots) == 3
        assert app.selected_r1_slot_index is None
        assert not any(i.round == "R1" for i in app.interviews)

        # The outreach email exists with the proposed slots.
        sent = get_messaging_provider().list_emails(application_id=app.id)
        assert any("preferred slot" in m.body.lower() for m in sent if m.direction == "out")

        # Now the candidate confirms slot 1 — orchestrator resumes and books
        # R1, then pauses again at R1_SCHEDULED waiting for the candidate to
        # click "Start interview".
        ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R1", 1)
        _join(app.id)
        app = STORE.get_application(app.id)
        assert app.selected_r1_slot_index == 1
        assert app.stage == FunnelStage.R1_SCHEDULED
        assert app.agent_status == AgentStatus.WAITING_CANDIDATE
        assert not app.r1_started

        # Candidate clicks "Start interview". Post-fix the orchestrator
        # pauses again at WAITING_CANDIDATE because _do_run_r1 refuses to
        # score until a real virtual-interview transcript is folded in.
        ORCHESTRATOR.on_candidate_start_r1(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)
        assert app.r1_started
        assert app.stage == FunnelStage.R1_SCHEDULED
        assert app.agent_status == AgentStatus.WAITING_CANDIDATE

        # Simulate the candidate finishing the AI interview by folding a
        # canned transcript onto the R1 InterviewRecord and re-triggering
        # — same code path the live virtual_interviewer takes.
        from app.orchestrator import _strong_transcript
        from app.tools.intake import get_jd
        stub = next(i for i in app.interviews if i.round == "R1")
        stub.transcript = _strong_transcript(get_jd(app.job_id))
        ORCHESTRATOR.trigger(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)
        assert app.stage == FunnelStage.R1_DONE
        assert app.agent_status == AgentStatus.WAITING_HR

        # Calendar event uses the slot the candidate chose, not slot 0.
        chosen = app.proposed_r1_slots[1]
        cal = get_calendar_provider().list_events(application_id=app.id)
        r1_events = [e for e in cal if not e.cancelled and "Round 1" in e.subject]
        assert any(e.start == chosen.start for e in r1_events)

    def test_invalid_slot_index_raises(self):
        app = _drive_to_pause("EMP10234", "job-590321")
        assert app.agent_status == AgentStatus.WAITING_CANDIDATE
        try:
            ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R1", 99)
        except ValueError:
            return
        raise AssertionError("Expected ValueError for out-of-range slot")


class TestHrUnblockResumesAgent:
    def test_hr_tick_resumes_orchestrator(self):
        # Drive once so we have an application sitting at WAITING_HR for the
        # R2 panel-composition gate (after candidate slot confirmation + R1).
        app = _drive_through_r1_slot("EMP10234", "job-590321")
        assert app.agent_status == AgentStatus.WAITING_HR
        assert "Business Partner approved panel composition" in " ".join(
            app.pending_blocking_items
        )

        # HR ticks the blocking item; on_hr_tick should resume the agent
        # and drive it to the next gate (R2 slot pick by candidate).
        STORE.get_application(app.id).selected_r2_panel_id = "panel-bdm-central"
        tick_checklist_item(app.id, "R2", "pre", "pre-r2-2", actor="hr_partner",
                            note="Panel approved")
        ORCHESTRATOR.on_hr_tick(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)
        assert app.agent_status == AgentStatus.WAITING_CANDIDATE
        assert len(app.proposed_r2_slots) == 3

        # Candidate confirms R2 slot 0 → orchestrator books R2.
        ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R2", 0)
        _join(app.id)
        app = STORE.get_application(app.id)
        assert app.stage == FunnelStage.R2_SCHEDULED
        assert app.agent_status == AgentStatus.WAITING_PANEL
