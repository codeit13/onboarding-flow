"""Phase 2 — Scoring tests."""

from app.models import InterviewRecord, TranscriptSegment
from app.tools import get_employee_profile, get_jd, score_cv_against_jd, score_transcript


class TestScoreCvAgainstJd:
    def test_strong_candidate_scores_high(self):
        p = get_employee_profile("cand-004")  # Priya Nair — 6/6 skills, 7.1y tenure
        jd = get_jd("job-590321")
        r = score_cv_against_jd(p, jd)
        assert r.percent >= 95
        assert len(r.missing_skills) == 0
        # JD now sourced from the Axis JOB_ROLES taxonomy — assert against
        # one of the canonical BDM skill names from SKILL_MASTER.
        assert "bank sales" in r.matched_skills

    def test_borderline_candidate_scores_below_threshold(self):
        p = get_employee_profile("cand-003")  # Karthik — 3/6, 3.4y tenure, no boost
        jd = get_jd("job-590321")
        r = score_cv_against_jd(p, jd)
        assert r.percent < jd.shortlist_threshold
        assert len(r.missing_skills) > 0

    def test_weak_candidate_scores_very_low(self):
        p = get_employee_profile("cand-005")  # Vikram — 1/6, 1.5y tenure
        jd = get_jd("job-590321")
        r = score_cv_against_jd(p, jd)
        assert r.percent < 30

    def test_tenure_boost_applied(self):
        # Rohan has 5.2y tenure → +5 boost
        p = get_employee_profile("cand-001")
        jd = get_jd("job-590321")
        r = score_cv_against_jd(p, jd)
        # 5/6 skills = 83.3% + 5 = 88.3% (rounded)
        assert 85 <= r.percent <= 92

    def test_rationale_is_human_readable(self):
        p = get_employee_profile("cand-001")
        jd = get_jd("job-590321")
        r = score_cv_against_jd(p, jd)
        assert "Matched" in r.rationale
        assert "Missing" in r.rationale
        assert "Tenure" in r.rationale


class TestScoreTranscript:
    def test_strong_transcript_passes(self):
        jd = get_jd("job-590321")
        record = InterviewRecord(
            id="int-test",
            application_id="app-test",
            round="R1",
            transcript=[
                TranscriptSegment(
                    speaker="interviewer", text="Tell me about your experience."
                ),
                TranscriptSegment(
                    speaker="candidate",
                    text=(
                        "I led bank sales and business development across 1200 corporate "
                        "employees, owned end-to-end account development for the client, "
                        "and partnered closely with the commercial banking team to "
                        "underwrite employers liability cover. Business partnering with "
                        "stakeholders across HR and finance is my strongest suit."
                    ),
                ),
            ],
        )
        score, rationale = score_transcript(record, jd)
        # New scorer ceilings at 97 and rewards coverage + depth + evidence.
        # A rich substantive answer should clear the 'advance to panel' bar
        # cleanly but cannot saturate at 100.
        assert 75 <= score <= 97
        assert "covered" in rationale.lower()

    def test_weak_transcript_scores_low(self):
        jd = get_jd("job-590321")
        record = InterviewRecord(
            id="int-test",
            application_id="app-test",
            round="R1",
            transcript=[
                TranscriptSegment(speaker="interviewer", text="Tell me about yourself."),
                TranscriptSegment(speaker="candidate", text="I like working with people."),
            ],
        )
        score, _ = score_transcript(record, jd)
        # One shallow candidate turn with no JD skills → well below the bar.
        assert score < 30.0

    def test_empty_transcript_scores_zero(self):
        jd = get_jd("job-590321")
        record = InterviewRecord(id="int", application_id="app", round="R1", transcript=[])
        score, _ = score_transcript(record, jd)
        # No candidate turns at all → 0, not a free base score.
        assert score == 0.0
