"""Tests for the per-panellist Claude recommender + endpoint.

These run with ``AXIS_LLM_PROVIDER=deterministic`` (set inside the test) so
no live API call is made — we just exercise the wiring, the fallback path,
and the per-panellist transcript routing.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.models import (
    AiPanelRecommendation,
    Application,
    FunnelStage,
    InterviewRecord,
    Job,
    PanelFeedback,
    PanelMember,
)
from app.services import recommend_for_panellist
from app.services.sample_r2_transcript import (
    SAMPLE_R2_TRANSCRIPT_VARIANTS,
    transcripts_for_panel,
)
from app.store import STORE


@pytest.fixture(autouse=True)
def _force_deterministic(monkeypatch):
    monkeypatch.setenv("AXIS_LLM_PROVIDER", "deterministic")


def _make_panellist(pid: str, name: str, rec="hire", score=72.0) -> PanelFeedback:
    return PanelFeedback(
        panellist_id=pid,
        panellist_name=name,
        score=score,
        strengths="solid ownership",
        concerns="will need ramp",
        recommendation=rec,
        submitted_at=datetime.utcnow(),
    )


def _seed_app_at_r2(app_id: str = "app-perpanel-1") -> Application:
    """Seed an application sitting at R2 with three panellist votes and
    three distinct per-panellist transcripts."""
    job = STORE.list_jobs()[0]  # any seeded job
    members = [
        PanelMember(user_id="pm1@axisbank.test", name="Panel One", role="hiring_manager"),
        PanelMember(user_id="pm2@axisbank.test", name="Panel Two", role="interviewer"),
        PanelMember(user_id="pm3@axisbank.test", name="Panel Three", role="interviewer"),
    ]
    panellist_ids = [m.user_id for m in members]

    r2 = InterviewRecord(
        id="int-perpanel-r2",
        application_id=app_id,
        round="R2",
        pasted_transcripts_by_panellist=transcripts_for_panel(panellist_ids),
        panel_feedback=[
            _make_panellist("pm1@axisbank.test", "Panel One", "hire", 78.0),
            _make_panellist("pm2@axisbank.test", "Panel Two", "no_hire", 58.0),
            _make_panellist("pm3@axisbank.test", "Panel Three", "strong_hire", 86.0),
        ],
    )
    application = Application(
        id=app_id,
        candidate_id="EMP10234",
        job_id=job.id,
        match_percent=82.0,
        stage=FunnelStage.R2_SCHEDULED,
    )
    application.interviews.append(r2)
    STORE.add_application(application)
    return application


def test_transcripts_for_panel_returns_distinct_variants():
    ids = ["a@x", "b@x", "c@x"]
    result = transcripts_for_panel(ids)
    assert set(result.keys()) == set(ids)
    # All three transcripts must be distinct so per-panellist AI runs see
    # different content (this is the whole point of the demo flow).
    values = list(result.values())
    assert len(set(values)) == 3
    # Cycling: a 4th panellist falls back to variant[0].
    result4 = transcripts_for_panel(ids + ["d@x"])
    assert result4["d@x"] == SAMPLE_R2_TRANSCRIPT_VARIANTS[0]


def test_recommend_for_panellist_returns_named_headline():
    app = _seed_app_at_r2()
    r2 = app.interviews[0]
    job = STORE.get_job(app.job_id)
    panellist = r2.panel_feedback[0]
    transcript = r2.pasted_transcripts_by_panellist[panellist.panellist_id]

    rec = recommend_for_panellist(
        interview=r2,
        transcript_text=transcript,
        job=job,
        r1_report=None,
        panellist=panellist,
    )
    assert isinstance(rec, AiPanelRecommendation)
    assert rec.application_id == app.id
    # Deterministic fallback tags the headline with the panellist's name so
    # HR can tell at a glance which card belongs to which interviewer.
    assert panellist.panellist_name in rec.headline


def test_endpoint_routes_per_panellist_transcript_and_caches():
    app = _seed_app_at_r2(app_id="app-perpanel-2")
    r2 = app.interviews[0]
    client = TestClient(fastapi_app)

    pid = r2.panel_feedback[1].panellist_id  # the no_hire vote
    expected_transcript = r2.pasted_transcripts_by_panellist[pid]

    # First call: no transcript_text in body → endpoint must use the
    # per-panellist transcript already on file.
    resp = client.post(
        f"/applications/{app.id}/analyse-panellist/{pid}",
        json={},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["application_id"] == app.id

    # The recommender must have been run against THIS panellist's transcript,
    # not a shared one — assert it's persisted under the right key.
    assert pid in r2.ai_recommendations_by_panellist
    assert r2.pasted_transcripts_by_panellist[pid] == expected_transcript

    # Second call without force returns the cached recommendation
    # (same generated_at) without re-running the recommender.
    cached = r2.ai_recommendations_by_panellist[pid]
    resp2 = client.post(
        f"/applications/{app.id}/analyse-panellist/{pid}",
        json={},
    )
    assert resp2.status_code == 200
    assert resp2.json()["generated_at"] == cached.generated_at.isoformat()


def test_endpoint_404_when_panellist_did_not_vote():
    app = _seed_app_at_r2(app_id="app-perpanel-3")
    client = TestClient(fastapi_app)
    resp = client.post(
        f"/applications/{app.id}/analyse-panellist/nobody@axisbank.test",
        json={},
    )
    assert resp.status_code == 404
