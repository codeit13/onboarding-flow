"""Phase 2 — CV routing tests."""

import pytest

from app.models import Application, FunnelStage
from app.store import STORE
from app.tools import move_cv


def _make_app(app_id: str = "app-test") -> Application:
    app = Application(
        id=app_id,
        candidate_id="EMP10234",
        job_id="job-590321",
        match_percent=88.0,
    )
    STORE.add_application(app)
    return app


class TestMoveCv:
    def test_moves_to_shortlisted_folder(self):
        _make_app()
        move_cv("app-test", "/cvs/shortlisted/job-590321/")
        assert "app-test" in STORE.folder_contents("/cvs/shortlisted/job-590321/")

    def test_moves_to_rejected_folder(self):
        _make_app()
        move_cv("app-test", "/cvs/rejected/job-590321/")
        assert "app-test" in STORE.folder_contents("/cvs/rejected/job-590321/")

    def test_move_is_single_source_of_truth(self):
        _make_app()
        move_cv("app-test", "/cvs/shortlisted/job-590321/")
        move_cv("app-test", "/cvs/rejected/job-590321/")
        assert "app-test" not in STORE.folder_contents("/cvs/shortlisted/job-590321/")
        assert "app-test" in STORE.folder_contents("/cvs/rejected/job-590321/")

    def test_rejects_non_cvs_folder(self):
        _make_app()
        with pytest.raises(ValueError, match="/cvs/"):
            move_cv("app-test", "/tmp/misc/")

    def test_missing_application_raises(self):
        with pytest.raises(LookupError):
            move_cv("app-does-not-exist", "/cvs/shortlisted/job-590321/")
