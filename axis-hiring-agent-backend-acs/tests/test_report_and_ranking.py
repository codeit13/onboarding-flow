"""Tests for the new R1 InterviewReport + cross-candidate ranking module."""

from __future__ import annotations

import time

from app.models import AgentStatus, FunnelStage
from app.orchestrator import ORCHESTRATOR
from app.services import build_r1_report, rank_for_jd
from app.store import STORE
from app.tools.checklists import tick_checklist_item


def _join(application_id: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = ORCHESTRATOR._threads.get(application_id)  # noqa: SLF001
        if t is None or not t.is_alive():
            return
        t.join(timeout=deadline - time.time())
    raise TimeoutError(application_id)


def _drive_through_r1(employee_id: str, jd_id: str):
    from app.orchestrator import _strong_transcript, _weak_transcript
    from app.tools.intake import get_jd

    app = ORCHESTRATOR.start_application(employee_id, jd_id)
    _join(app.id)
    app = STORE.get_application(app.id)
    if app.agent_status == AgentStatus.WAITING_CANDIDATE and app.proposed_r1_slots:
        ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R1", 0)
        _join(app.id)
        app = STORE.get_application(app.id)
    if app.stage == FunnelStage.R1_SCHEDULED:
        ORCHESTRATOR.on_candidate_start_r1(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)
        # Post-fix: _do_run_r1 pauses until a real virtual-interview
        # transcript is folded in. Simulate the candidate completing
        # the AI interview by writing a canned transcript onto the
        # InterviewRecord and re-triggering — same code path the live
        # virtual_interviewer takes via _fold_transcript_into_interview.
        stub = next((i for i in app.interviews if i.round == "R1"), None)
        if stub is not None and not stub.transcript:
            jd = get_jd(app.job_id)
            stub.transcript = (
                _strong_transcript(jd) if app.match_percent >= 85 else _weak_transcript()
            )
            ORCHESTRATOR.trigger(app.id)
            _join(app.id)
            app = STORE.get_application(app.id)
    # New flow: _do_run_r1 hands control back to HR after R1 with no
    # pre-r2 checklist instantiated yet. Trigger one more loop pass so
    # _do_schedule_r2 instantiates the pre-r2 checklist and re-pauses at
    # the panel-composition gate (which is what the legacy tests expect
    # the WAITING_HR pause to look like).
    if (
        app.stage == FunnelStage.R1_DONE
        and app.agent_status == AgentStatus.WAITING_HR
        and not any(c.round == "R2" and c.phase == "pre" for c in app.checklists)
    ):
        ORCHESTRATOR.trigger(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)
    return app


class TestR1ReportAttachedToInterview:
    def test_report_built_after_r1_with_rubric_and_probes(self):
        app = _drive_through_r1("EMP10234", "job-590321")
        assert app.stage == FunnelStage.R1_DONE

        r1 = next(i for i in app.interviews if i.round == "R1")
        assert r1.report is not None
        report = r1.report
        assert report.application_id == app.id
        assert report.round == "R1"
        assert report.recommendation in ("advance", "borderline", "reject")
        assert 0.0 <= report.overall_score <= 100.0
        assert report.rubric_scores, "rubric should be populated per JD skill"
        assert all(0.0 <= v <= 100.0 for v in report.rubric_scores.values())
        assert report.headline
        assert report.recommended_probes, "probes should be populated"

    def test_report_carried_into_r2_panel_briefing(self):
        app = _drive_through_r1("EMP10234", "job-590321")
        STORE.get_application(app.id).selected_r2_panel_id = "panel-bdm-central"
        tick_checklist_item(app.id, "R2", "pre", "pre-r2-2", actor="hr_partner",
                            note="Approved")
        ORCHESTRATOR.on_hr_tick(app.id)
        _join(app.id)
        app = STORE.get_application(app.id)
        ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R2", 0)
        _join(app.id)
        app = STORE.get_application(app.id)

        from app.providers import get_calendar_provider
        events = [
            e for e in get_calendar_provider().list_events(application_id=app.id)
            if "Round 2" in e.subject and not e.cancelled
        ]
        assert events, "R2 calendar event should exist"
        body = events[0].body
        # Production-grade R2 invite body uses readable section headings
        # rather than ALL-CAPS markers; assert on the human-friendly anchors.
        assert "Round 2 Panel Interview" in body
        assert "Recommended panel probes" in body
        assert "AI headline" in body or "Round 1 score" in body


class TestRankingProjection:
    def test_ranking_orders_by_signal_tier_then_score(self):
        # Strong candidate progresses past R1.
        strong = _drive_through_r1("EMP10234", "job-590321")
        # Weak candidate is now parked at the HR screening review gate
        # (the orchestrator no longer auto-rejects at intake). HR clicks
        # Regret on the screening review to take them to REJECTED so the
        # ranking projection sees the same final tier the legacy flow did.
        weak_app = ORCHESTRATOR.start_application("EMP11544", "job-590321")
        _join(weak_app.id)
        weak_app = STORE.get_application(weak_app.id)
        weak_app.hr_screening_decision = "regret"
        ORCHESTRATOR.on_hr_tick(weak_app.id)
        _join(weak_app.id)

        ranking = rank_for_jd("job-590321")
        assert ranking.jd_id == "job-590321"
        assert ranking.total >= 2

        ranks_by_app = {r.application_id: r for r in ranking.candidates}
        assert strong.id in ranks_by_app
        assert weak_app.id in ranks_by_app

        strong_row = ranks_by_app[strong.id]
        weak_row = ranks_by_app[weak_app.id]

        # Strong candidate is in post_r1 tier (since R1 ran).
        assert strong_row.tier == "post_r1"
        assert strong_row.r1_score is not None
        # Weak rejected after HR screening review.
        assert weak_row.tier == "rejected"

        # Strong must be ranked higher than rejected.
        assert strong_row.rank < weak_row.rank
