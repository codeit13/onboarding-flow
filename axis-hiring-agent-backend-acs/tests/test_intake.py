"""Phase 1 — Intake tests."""

import pytest

from app.tools import get_employee_profile, get_jd, list_open_jds


class TestGetEmployeeProfile:
    def test_resolves_by_employee_id(self):
        p = get_employee_profile("EMP10234")
        assert p.name == "Rohan Verma"
        # Skills are sourced from the Axis SKILL_MASTER taxonomy.
        assert "Bank Sales" in p.skills

    def test_resolves_by_candidate_id(self):
        p = get_employee_profile("cand-001")
        assert p.employee_id == "EMP10234"

    def test_missing_raises(self):
        with pytest.raises(LookupError, match="No employee"):
            get_employee_profile("DOES-NOT-EXIST")


class TestListOpenJds:
    def test_returns_all_seeded_jds(self):
        jds = list_open_jds()
        # Production-grade demo dataset: 8 jobs across multiple functions.
        assert len(jds) == 8
        # The three BDM postings from the original Thrive screenshot are
        # always present.
        assert {"Bhopal", "Vadodara", "Mysuru"}.issubset({j.location for j in jds})

    def test_every_jd_has_panel_with_at_least_hr_and_hm(self):
        for jd in list_open_jds():
            roles = [p.role for p in jd.panel]
            assert "hr_partner" in roles
            assert "hiring_manager" in roles


class TestGetJd:
    def test_returns_full_jd(self):
        jd = get_jd("job-590321")
        assert jd.location == "Bhopal"
        assert jd.shortlist_threshold == 75.0
        assert len(jd.required_skills) > 0

    def test_missing_raises(self):
        with pytest.raises(LookupError):
            get_jd("nope")
