"""Phase 5/6 — Interview tool tests."""

import pytest

from app.models import Application, InterviewRecord, TranscriptSegment
from app.store import STORE
from app.tools import collect_panel_feedback, run_virtual_interview
from app.tools.interview import submit_panel_feedback


def _seed_app() -> Application:
    app = Application(
        id="app-iv",
        candidate_id="EMP10234",
        job_id="job-590321",
        match_percent=88.0,
    )
    STORE.add_application(app)
    return app


def _seed_app_with_r2(app_id: str, interview_id: str) -> Application:
    """Seed a fresh application carrying a single empty R2 InterviewRecord
    so panel-feedback assertions have something to attach to."""
    app = Application(
        id=app_id,
        candidate_id="EMP10234",
        job_id="job-590321",
        match_percent=88.0,
    )
    app.interviews.append(
        InterviewRecord(id=interview_id, application_id=app_id, round="R2")
    )
    STORE.add_application(app)
    return app


class TestRunVirtualInterview:
    def test_appends_record_to_application(self):
        _seed_app()
        record = run_virtual_interview(
            application_id="app-iv",
            teams_meeting_id="evt-001",
            scripted_transcript=[
                TranscriptSegment(speaker="interviewer", text="Hi"),
                TranscriptSegment(speaker="candidate", text="Hello"),
            ],
        )
        assert record.round == "R1"
        assert record.teams_meeting_id == "evt-001"
        app = STORE.get_application("app-iv")
        assert len(app.interviews) == 1
        assert any("Virtual interview R1" in e.message for e in app.events)

    def test_missing_application_raises(self):
        with pytest.raises(LookupError):
            run_virtual_interview("nope", "evt-001", [])


class TestCollectPanelFeedback:
    def test_pending_when_nothing_submitted(self):
        fb = collect_panel_feedback("int-1", ["hm@x.test", "int@x.test"])
        assert fb["complete"] is False
        assert set(fb["pending"]) == {"hm@x.test", "int@x.test"}

    def test_partial_submission(self):
        _seed_app_with_r2("app-iv-2", "int-2")
        submit_panel_feedback(
            "int-2",
            "hm@x.test",
            score=80.0,
            strengths="Strong domain",
            concerns="Minor",
            recommendation="hire",
        )
        fb = collect_panel_feedback("int-2", ["hm@x.test", "int@x.test"])
        assert fb["complete"] is False
        assert fb["pending"] == ["int@x.test"]
        assert "hm@x.test" in fb["submitted"]

    def test_complete_when_all_submitted(self):
        _seed_app_with_r2("app-iv-3", "int-3")
        for pid in ["hm@x.test", "int@x.test"]:
            submit_panel_feedback(
                "int-3",
                pid,
                score=85.0,
                strengths="ok",
                concerns="",
                recommendation="strong_hire",
            )
        fb = collect_panel_feedback("int-3", ["hm@x.test", "int@x.test"])
        assert fb["complete"] is True
        assert fb["pending"] == []
