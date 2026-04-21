"""Feature 1 — Funnel Integration for Bulk Screening.

Validates that:
- Bulk-routed applications get source='bulk_screening'
- External-intake applications get source='external_intake'
- Organic applications default to source='organic'
- The HR-visible filter includes bulk-screened apps at SCREENED / R1_SCHEDULED
- Organic apps at SCREENED are NOT visible to HR
- The ?source= query parameter filters correctly
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.models import Application, FunnelStage
from app.store import STORE


@pytest.fixture
def client():
    return TestClient(fastapi_app)


def _make_app(
    app_id: str = "app-test",
    stage: FunnelStage = FunnelStage.APPLIED,
    source: str = "organic",
) -> Application:
    app = Application(
        id=app_id,
        candidate_id="EMP10234",
        job_id="job-590321",
        match_percent=88.0,
        stage=stage,
        source=source,
    )
    STORE.add_application(app)
    return app


class TestSourceField:
    def test_organic_app_source_defaults_organic(self):
        """Normal apply -> source is 'organic' by default."""
        app = Application(
            id="app-organic",
            candidate_id="EMP10234",
            job_id="job-590321",
            match_percent=75.0,
        )
        assert app.source == "organic"

    def test_bulk_routed_app_has_source_bulk_screening(self):
        """Explicitly setting source='bulk_screening' works."""
        app = _make_app(app_id="app-bulk", source="bulk_screening")
        assert app.source == "bulk_screening"

    def test_external_intake_source(self):
        """External intake apps get source='external_intake'."""
        app = _make_app(app_id="app-ext", source="external_intake")
        assert app.source == "external_intake"


class TestHrFunnelVisibility:
    def test_bulk_routed_app_visible_in_hr_funnel(self, client):
        """Bulk-screened app at SCREENED stage IS visible to HR."""
        _make_app(
            app_id="app-bulk-screened",
            stage=FunnelStage.SCREENED,
            source="bulk_screening",
        )
        resp = client.get("/applications", params={"visible_to": "hr"})
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()]
        assert "app-bulk-screened" in ids

    def test_bulk_routed_r1_scheduled_visible_in_hr_funnel(self, client):
        """Bulk-screened app at R1_SCHEDULED stage IS visible to HR."""
        _make_app(
            app_id="app-bulk-r1",
            stage=FunnelStage.R1_SCHEDULED,
            source="bulk_screening",
        )
        resp = client.get("/applications", params={"visible_to": "hr"})
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()]
        assert "app-bulk-r1" in ids

    def test_screened_organic_not_in_hr_funnel(self, client):
        """Organic app at SCREENED stage is NOT visible to HR."""
        _make_app(
            app_id="app-organic-screened",
            stage=FunnelStage.SCREENED,
            source="organic",
        )
        resp = client.get("/applications", params={"visible_to": "hr"})
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()]
        assert "app-organic-screened" not in ids

    def test_r1_done_always_visible(self, client):
        """Any app at R1_DONE is visible to HR regardless of source."""
        _make_app(
            app_id="app-r1done",
            stage=FunnelStage.R1_DONE,
            source="organic",
        )
        resp = client.get("/applications", params={"visible_to": "hr"})
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()]
        assert "app-r1done" in ids


class TestSourceFilter:
    def test_source_filter_returns_only_matching(self, client):
        """GET /applications?source=bulk_screening returns only bulk apps."""
        _make_app(app_id="app-b1", source="bulk_screening", stage=FunnelStage.R1_DONE)
        _make_app(app_id="app-o1", source="organic", stage=FunnelStage.R1_DONE)
        _make_app(app_id="app-e1", source="external_intake", stage=FunnelStage.R1_DONE)

        resp = client.get("/applications", params={"source": "bulk_screening"})
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()]
        assert "app-b1" in ids
        assert "app-o1" not in ids
        assert "app-e1" not in ids

    def test_source_filter_combined_with_visible_to(self, client):
        """Source filter works together with visible_to=hr."""
        _make_app(
            app_id="app-combo",
            source="bulk_screening",
            stage=FunnelStage.SCREENED,
        )
        _make_app(
            app_id="app-combo-org",
            source="organic",
            stage=FunnelStage.R1_DONE,
        )

        resp = client.get(
            "/applications",
            params={"visible_to": "hr", "source": "bulk_screening"},
        )
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()]
        assert "app-combo" in ids
        assert "app-combo-org" not in ids
