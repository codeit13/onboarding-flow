"""Phase 7 — Recommendation consolidation tests."""

import pytest

from app.models import Application, FunnelStage, InterviewRecord
from app.store import STORE
from app.tools import consolidate_recommendation, update_application_status


def _seed_app(r1_score: float = 82.0) -> Application:
    app = Application(
        id="app-dec",
        candidate_id="EMP10234",
        job_id="job-590321",
        match_percent=88.0,
    )
    app.interviews.append(
        InterviewRecord(
            id="int-r1",
            application_id="app-dec",
            round="R1",
            score=r1_score,
            rationale="ok",
        )
    )
    STORE.add_application(app)
    return app


def _fb(submitted: dict) -> dict:
    return {"submitted": submitted, "pending": [], "complete": True}


class TestConsolidateRecommendation:
    def test_offer_when_majority_positive_and_scores_high(self):
        _seed_app(r1_score=85.0)
        panel = _fb({
            "hm@x.test": {"score": 88, "recommendation": "strong_hire", "strengths": "x", "concerns": ""},
            "int1@x.test": {"score": 82, "recommendation": "hire", "strengths": "x", "concerns": ""},
            "int2@x.test": {"score": 80, "recommendation": "hire", "strengths": "x", "concerns": ""},
        })
        rec = consolidate_recommendation("app-dec", panel)
        assert rec.verdict == "offer"
        assert rec.r1_score == 85.0
        assert rec.r2_avg_score >= 80

    def test_reject_on_two_no_hires(self):
        _seed_app()
        panel = _fb({
            "hm@x.test": {"score": 55, "recommendation": "no_hire", "strengths": "", "concerns": "x"},
            "int1@x.test": {"score": 60, "recommendation": "no_hire", "strengths": "", "concerns": "x"},
            "int2@x.test": {"score": 72, "recommendation": "hire", "strengths": "ok", "concerns": ""},
        })
        rec = consolidate_recommendation("app-dec", panel)
        assert rec.verdict == "reject"

    def test_hold_on_mixed_signals(self):
        _seed_app(r1_score=68.0)  # below 70 threshold
        panel = _fb({
            "hm@x.test": {"score": 72, "recommendation": "hire", "strengths": "ok", "concerns": ""},
            "int1@x.test": {"score": 65, "recommendation": "no_hire", "strengths": "", "concerns": "x"},
        })
        rec = consolidate_recommendation("app-dec", panel)
        assert rec.verdict == "hold"

    def test_hold_when_no_feedback_yet(self):
        _seed_app()
        rec = consolidate_recommendation("app-dec", {"submitted": {}, "pending": [], "complete": False})
        assert rec.verdict == "hold"


class TestUpdateApplicationStatus:
    def test_updates_stage_and_audits(self):
        _seed_app()
        update_application_status("app-dec", FunnelStage.OFFER, "Offer to be rolled out")
        app = STORE.get_application("app-dec")
        assert app.stage == FunnelStage.OFFER
        assert app.next_action == "Offer to be rolled out"
        assert any("applied → offer" in e.message for e in app.events)

    def test_missing_application_raises(self):
        with pytest.raises(LookupError):
            update_application_status("nope", FunnelStage.OFFER)
