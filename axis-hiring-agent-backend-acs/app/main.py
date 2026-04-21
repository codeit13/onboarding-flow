"""FastAPI entrypoint.

Run with: ``uvicorn app.main:app --reload``

Architecture note
-----------------
This module is a *thin* HTTP layer. It does NOT contain any hiring workflow
logic. Everything the agent does lives in ``app.orchestrator.ORCHESTRATOR``,
which is a thread-safe, idempotent state machine. The API's job is:

  * expose read endpoints for the three UIs (employee / HR / panel)
  * accept human inputs (apply, tick checklist, submit panel feedback)
  * call ``ORCHESTRATOR.trigger`` / ``on_hr_tick`` / ``on_panel_feedback``
  * return the current application snapshot — the UIs poll for updates

There is **no** ``/advance/*`` endpoint anymore. The agent drives itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx

from uuid import uuid4

from .fixtures import panels_for_job, seed_all
from .models import (
    ActivityItem,
    AgentStatus,
    AiPanelRecommendation,
    Application,
    ChecklistItem,
    FunnelStage,
    Job,
    Panel,
    PanelMember,
)
from .orchestrator import ORCHESTRATOR
from .providers import get_calendar_provider, get_messaging_provider, get_whatsapp_provider, reset_providers
from .services import (
    build_activity_feed,
    rank_for_jd,
    recommend_for_panellist,
    recommend_from_transcript,
)
from .services.acs_interview_bot import (
    finalise_acs_interview,
    get_acs_interview_status,
    start_acs_interview,
)
from .services.virtual_interviewer import (
    VIRTUAL_INTERVIEWER_URL,
    finalise_virtual_interview,
    get_virtual_interview,
    start_virtual_interview,
    submit_virtual_interview_answer,
)
from .services.ranking import JdRanking
from .store import STORE
from .tools import (
    get_checklist,
    tick_checklist_item,
    submit_panel_feedback,
)
from .tools.checklists import customise_checklist, reset_customisations

app = FastAPI(title="Axis Hiring Agent", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # POC on localhost — tighten before prod
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount engagement routes
from .routes.engagement import router as engagement_router
app.include_router(engagement_router, tags=["engagement"])


@app.on_event("startup")
def _startup() -> None:
    seed_all()
    # Start the inbound mail poller for the external candidate flow.
    # It reads the Business Partner's mailbox and feeds replies into the
    # inbox parser → orchestrator. Idempotent on repeated startup.
    from .services.inbox_poller import start_inbox_poller
    start_inbox_poller()

    # Start the engagement engine (post-offer WhatsApp touchpoints).
    from .services.engagement_engine import start_engagement_engine
    start_engagement_engine()

    # Recover stale bulk-screening pools stuck in "processing" from a previous
    # server life.  The background thread is gone and raw bytes aren't persisted,
    # so the only safe move is to mark unfinished rows as "failed".
    for pool in STORE.list_candidate_pools():
        if pool.status == "processing":
            stale = False
            for row in pool.rows:
                if row.status not in ("done", "error"):
                    row.status = "error"
                    row.error_message = "Server restarted — please re-upload this CV in a new batch."
                    stale = True
            if stale:
                pool.status = "failed"
                STORE.save_candidate_pool(pool)


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "jobs": len(STORE.jobs),
        "candidates": len(STORE.candidates),
        "applications": len(STORE.applications),
        "calendar_provider": type(get_calendar_provider()).__name__,
        "messaging_provider": type(get_messaging_provider()).__name__,
        "whatsapp_provider": type(get_whatsapp_provider()).__name__,
        "engagement_journeys": len(STORE.engagement_journeys),
    }


@app.get("/jobs", response_model=List[Job])
def list_jobs() -> List[Job]:
    return STORE.list_jobs()


@app.get("/taxonomy/stats")
def taxonomy_stats() -> dict:
    """Counts of roles/skills/departments loaded from the Axis taxonomy CSVs.
    Used by the frontend's about/health overlay so we can prove the demo is
    sourced from the official Axis Bank role + skill master."""
    from .services import taxonomy as tax
    return tax.stats()


@app.get("/taxonomy/roles")
def taxonomy_roles(q: str = "", limit: int = 25) -> list[dict]:
    """Search the Axis JOB_ROLES catalogue.

    Used by the JD edit / new-JD pages so HR can pick a role straight
    from the official taxonomy instead of free-typing a title.
    """
    from .services import taxonomy as tax
    rows = tax.search_roles(q, limit=limit)
    return [
        {
            "role_id": r.role_id,
            "title": r.title,
            "alias": r.alias,
            "department": r.department,
            "role_summary": r.role_summary,
            "skills": list(r.skills),
            "skill_categories": list(r.skill_categories),
            "responsibilities": list(r.responsibilities),
        }
        for r in rows
    ]


@app.get("/taxonomy/roles/{role_id}")
def taxonomy_role_detail(role_id: str) -> dict:
    from .services import taxonomy as tax
    r = tax.get_role_by_id(role_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"No role {role_id}")
    return {
        "role_id": r.role_id,
        "title": r.title,
        "alias": r.alias,
        "department": r.department,
        "role_summary": r.role_summary,
        "description": r.description,
        "skills": list(r.skills),
        "skill_ids": list(r.skill_ids),
        "skill_categories": list(r.skill_categories),
        "responsibilities": list(r.responsibilities),
        "works_with_internal": list(r.works_with_internal),
        "works_with_external": list(r.works_with_external),
    }


@app.get("/taxonomy/skills")
def taxonomy_skills(q: str = "", limit: int = 30) -> list[dict]:
    """Search the Axis SKILL_MASTER catalogue.

    Used by the JD editor's skill picker and by the candidate-facing
    "skill match" panel so every skill displayed in the demo is the
    canonical Axis term, not a free-text guess.
    """
    from .services import taxonomy as tax
    rows = tax.search_skills(q, limit=limit)
    return [
        {
            "skill_id": s.skill_id,
            "name": s.name,
            "category": s.category,
            "description": s.description,
        }
        for s in rows
    ]


@app.get("/taxonomy/skill-categories")
def taxonomy_skill_categories() -> list[str]:
    from .services import taxonomy as tax
    return tax.skill_categories()


@app.get("/taxonomy/departments")
def taxonomy_departments() -> list[str]:
    from .services import taxonomy as tax
    return tax.departments()


@app.get("/jobs/applicant-counts")
def jobs_applicant_counts() -> dict:
    """Real applicant count per JD — replaces the old hardcoded `3`."""
    counts: Dict[str, int] = {}
    for app_ in STORE.list_applications():
        counts[app_.job_id] = counts.get(app_.job_id, 0) + 1
    return counts


@app.get("/jobs/{jd_id}", response_model=Job)
def get_job(jd_id: str) -> Job:
    job = STORE.get_job(jd_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"No job {jd_id}")
    return job


@app.get("/candidates")
def list_candidates() -> list:
    return [
        {
            "id": c.id,
            "employee_id": c.profile.employee_id,
            "name": c.profile.name,
            "email": c.profile.email,
            "current_role": c.profile.current_role,
            "current_band": c.profile.current_band,
            "current_location": c.profile.current_location,
            "tenure_years": c.profile.tenure_years,
            "skills": c.profile.skills,
            "kras": c.profile.kras,
            "education": c.profile.education,
            "last_rating": c.profile.last_rating,
        }
        for c in STORE.candidates.values()
    ]


@app.get("/candidates/{cand_id}")
def get_candidate(cand_id: str) -> dict:
    # Accept either candidate id or employee id.
    for c in STORE.candidates.values():
        if c.id == cand_id or c.profile.employee_id == cand_id:
            return {
                "id": c.id,
                "employee_id": c.profile.employee_id,
                "name": c.profile.name,
                "email": c.profile.email,
                "current_role": c.profile.current_role,
                "current_band": c.profile.current_band,
                "current_location": c.profile.current_location,
                "tenure_years": c.profile.tenure_years,
                "skills": c.profile.skills,
                "kras": c.profile.kras,
                "education": c.profile.education,
                "last_rating": c.profile.last_rating,
                # External candidates may carry an extracted compensation
                # block from a salary slip uploaded at intake — surface it
                # so HR sees CTC + components on the candidate profile.
                "compensation": (
                    c.profile.compensation.model_dump(mode="json")
                    if c.profile.compensation is not None
                    else None
                ),
                "kind": c.kind,
            }
    raise HTTPException(status_code=404, detail=f"No candidate {cand_id}")


# Stages an application must reach before HR sees it in their queue.
# Per the live model: HR has nothing to do until the candidate has fully
# completed Round 1 — they only act on the R2 panel-composition gate.
_HR_VISIBLE_STAGES = {
    FunnelStage.R1_DONE,
    FunnelStage.R2_SCHEDULED,
    FunnelStage.OFFER_NEGOTIATION,
    FunnelStage.OFFER,
    FunnelStage.OFFER_ACCEPTED,
    FunnelStage.PRE_JOINING,
    FunnelStage.JOINED,
    FunnelStage.REJECTED,
}


@app.get("/applications", response_model=List[Application])
def list_applications(
    visible_to: Optional[str] = None,
    candidate_id: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Application]:
    """List applications.

    Optional filters, both backward-compatible:
    * ``visible_to=hr`` — only stages the HR command centre should see.
    * ``candidate_id=<employee_id>`` — just this candidate's applications.
      Powers the Thrive "My Applications" tray so a candidate can come
      back the next day and find everything they've applied to.

    No filter → every application in the store (unchanged behaviour).
    """
    apps = STORE.list_applications()
    if visible_to == "hr":
        apps = [a for a in apps if a.stage in _HR_VISIBLE_STAGES
            or (a.stage in {FunnelStage.SCREENED, FunnelStage.R1_SCHEDULED}
                and a.source == "bulk_screening")]
    if candidate_id:
        apps = [a for a in apps if a.candidate_id == candidate_id]
    if source:
        apps = [a for a in apps if a.source == source]
    return apps


@app.get("/applications/{app_id}", response_model=Application)
def get_application(app_id: str) -> Application:
    a = STORE.get_application(app_id)
    if not a:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    return a


@app.get("/applications/{app_id}/r1-report")
def get_r1_report(app_id: str) -> dict:
    """Structured AI Interview Agent report after Round 1.

    Read by the panel before R2 (so they walk in with a briefing) and by
    the candidate to see what the agent learned.
    """
    a = STORE.get_application(app_id)
    if not a:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    r1 = next((i for i in a.interviews if i.round == "R1"), None)
    if not r1 or r1.report is None:
        raise HTTPException(status_code=404, detail="No R1 report yet")
    return r1.report.model_dump()


@app.get("/jobs/{jd_id}/ranking", response_model=JdRanking)
def jd_ranking(jd_id: str) -> JdRanking:
    """Live cross-candidate ranking for one JD.

    Powers the HR JD Command Center leaderboard. Recomputed on every call
    so it always reflects the latest agent signal.
    """
    if STORE.get_job(jd_id) is None:
        raise HTTPException(status_code=404, detail=f"No job {jd_id}")
    return rank_for_jd(jd_id)


# ---------------------------------------------------------------------------
# Activity feed — unified timeline the "Agent working" panel polls
# ---------------------------------------------------------------------------


@app.get("/activity", response_model=List[ActivityItem])
def activity(
    application_id: Optional[str] = None,
    limit: int = 200,
) -> List[ActivityItem]:
    return build_activity_feed(application_id=application_id, limit=limit)


# ---------------------------------------------------------------------------
# Checklist endpoints (Business Partner view)
# ---------------------------------------------------------------------------


@app.get("/jobs/{jd_id}/checklist/{round_}/{phase}")
def get_checklist_endpoint(jd_id: str, round_: str, phase: str) -> dict:
    try:
        items = get_checklist(jd_id, round_, phase)  # type: ignore[arg-type]
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "jd_id": jd_id,
        "round": round_,
        "phase": phase,
        "items": [i.model_dump() for i in items],
    }


class ChecklistCustomiseRequest(BaseModel):
    extra_items: List[ChecklistItem]


@app.post("/jobs/{jd_id}/checklist/{round_}/{phase}/customise")
def customise_checklist_endpoint(
    jd_id: str, round_: str, phase: str, req: ChecklistCustomiseRequest
) -> dict:
    if STORE.get_job(jd_id) is None:
        raise HTTPException(status_code=404, detail=f"No job {jd_id}")
    customise_checklist(jd_id, round_, phase, req.extra_items)  # type: ignore[arg-type]
    return {"status": "ok", "items_added": len(req.extra_items)}


class ChecklistTickRequest(BaseModel):
    item_id: str
    actor: str = "hr_partner"
    note: str = ""


@app.post("/applications/{app_id}/checklist/{round_}/{phase}/tick")
def tick_item_endpoint(
    app_id: str, round_: str, phase: str, req: ChecklistTickRequest
) -> dict:
    try:
        inst = tick_checklist_item(
            app_id, round_, phase, req.item_id, actor=req.actor, note=req.note  # type: ignore[arg-type]
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # If this tick unblocked the agent, resume the state machine.
    ORCHESTRATOR.on_hr_tick(app_id)
    return inst.model_dump()


# ---------------------------------------------------------------------------
# Unblock — explicit resume after HR has satisfied blocking gates
# ---------------------------------------------------------------------------


@app.post("/applications/{app_id}/unblock", response_model=Application)
def unblock_application(app_id: str) -> Application:
    """Nudge the orchestrator. Safe to call any time — idempotent."""
    app = STORE.get_application(app_id)
    if not app:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    ORCHESTRATOR.on_hr_tick(app_id)
    return app


class ConfirmSlotRequest(BaseModel):
    round: Literal["R1", "R2"] = "R1"
    slot_index: int
    # Optional: ISO datetime when the candidate wants to run a CUSTOM slot
    # instead of one of the proposed slots. This supports the L1 "Start now"
    # and "Schedule for a custom date/time" affordances on the candidate
    # status page (R1 is an AI-driven interview, so the candidate may want
    # to run it immediately or at a specific time of their own choosing).
    # When present, the backend appends a 30-minute slot starting at this
    # datetime to the proposed_r1_slots list and selects it. slot_index
    # is ignored when custom_start_iso is provided.
    custom_start_iso: Optional[str] = None


@app.post("/applications/{app_id}/start-r1-interview", response_model=Application)
def start_r1_interview(app_id: str) -> Application:
    """Candidate clicked 'Start interview' on the live status page.

    This is the *real* gate at R1_SCHEDULED — in production it'd be the
    Virtual Interview Agent webhook firing when the Teams call actually
    starts. Until this is called, the orchestrator stays paused at
    WAITING_CANDIDATE and the application is invisible to HR.
    """
    try:
        return ORCHESTRATOR.on_candidate_start_r1(app_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# ACS Teams Interview Agent (R1 only)
# ---------------------------------------------------------------------------
#
# These endpoints dispatch / poll / finalise the live ACS bot that joins
# the candidate's R1 Microsoft Teams meeting, asks JD-aware questions,
# and captures the transcript. The mock provider simulates the call in a
# background thread so the demo runs offline; flip
# ``AXIS_ACS_PROVIDER=azure`` to use the real Azure Communication Services
# Call Automation SDK.


def _resolve_r1_interview(app_id: str):
    application = STORE.get_application(app_id)
    if not application:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    interview = next(
        (i for i in application.interviews if i.round == "R1"), None
    )
    if not interview:
        raise HTTPException(
            status_code=400,
            detail="No R1 interview record yet — schedule the meeting first",
        )
    return application, interview


@app.post("/applications/{app_id}/acs-interview/start")
def acs_interview_start(app_id: str) -> Dict[str, Any]:
    """Dispatch the ACS Teams Interview Agent into the candidate's R1 call."""
    application, interview = _resolve_r1_interview(app_id)
    job = STORE.get_job(application.job_id)
    candidate = STORE.get_candidate(application.candidate_id)
    if not job or not candidate:
        raise HTTPException(status_code=404, detail="Job or candidate missing")
    try:
        session = start_acs_interview(
            application=application,
            job=job,
            profile=candidate.profile,
            interview=interview,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return session.to_public_dict()


@app.get("/applications/{app_id}/acs-interview/status")
def acs_interview_status(app_id: str) -> Dict[str, Any]:
    """Poll live status of the ACS Teams interview bot."""
    _application, interview = _resolve_r1_interview(app_id)
    status = get_acs_interview_status(interview=interview)
    if status is None:
        return {"state": "not_started"}
    return status


@app.post("/applications/{app_id}/acs-interview/finalise")
def acs_interview_finalise(app_id: str) -> Dict[str, Any]:
    """Fold the captured ACS transcript back into InterviewRecord.transcript."""
    application, interview = _resolve_r1_interview(app_id)
    result = finalise_acs_interview(application=application, interview=interview)
    if result is None:
        raise HTTPException(status_code=400, detail="No ACS session for this R1")
    return result


# ---------------------------------------------------------------------------
# Virtual Interviewer (R1 only) — interactive turn-by-turn AI interview
# ---------------------------------------------------------------------------
#
# This is the *demo* path: instead of having a bot auto-join a Teams call,
# the candidate themselves runs through a browser-based AI interview that
# visually mirrors the existing Xebia virtual-interviewer UX. Questions
# come from Claude (with deterministic fallback), answers are submitted
# turn-by-turn via the candidate page, and on completion the (Q,A) pairs
# are folded into ``InterviewRecord.transcript`` so the existing R1
# scoring + report pipeline runs unchanged.


class VirtualInterviewAnswerRequest(BaseModel):
    answer_text: str


class VirtualInterviewStartRequest(BaseModel):
    """Frontend posts a base64 webcam snapshot here so the team's AI
    Interview Agent sidecar can run its face-detection gate before the
    interview begins.

    ``language`` is the candidate-selected interview language —
    "en" (English, default) or "hi" (Hindi). The sidecar generates the
    questions, the welcome message and the TTS audio in that language.
    """

    photo: str  # data:image/jpeg;base64,...
    language: Literal["en", "hi"] = "en"


@app.post("/applications/{app_id}/virtual-interview/start")
def virtual_interview_start(
    app_id: str, req: VirtualInterviewStartRequest
) -> Dict[str, Any]:
    """Spin up a fresh virtual interview session for this R1."""
    application, interview = _resolve_r1_interview(app_id)
    job = STORE.get_job(application.job_id)
    candidate = STORE.get_candidate(application.candidate_id)
    if not job or not candidate:
        raise HTTPException(status_code=404, detail="Job or candidate missing")
    # Idempotent — if a session is already active, return it instead of
    # rebuilding (avoids losing in-flight answers on accidental refresh).
    existing = get_virtual_interview(
        interview=interview, application_id=application.id
    )
    if existing is not None and existing.state == "in_progress":
        return existing.to_public_dict()
    # Persist the candidate's chosen language onto the InterviewRecord so
    # downstream code (R1 report builder, panel briefing, audit log) can
    # surface it without re-asking the sidecar.
    interview.language = req.language
    try:
        session = start_virtual_interview(
            application=application,
            job=job,
            profile=candidate.profile,
            interview=interview,
            photo_data_url=req.photo,
            language=req.language,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return session.to_public_dict()


@app.get("/applications/{app_id}/virtual-interview/status")
def virtual_interview_status(app_id: str) -> Dict[str, Any]:
    """Read the current state of the candidate's virtual interview session."""
    application, interview = _resolve_r1_interview(app_id)
    session = get_virtual_interview(
        interview=interview, application_id=application.id
    )
    if session is None:
        return {"state": "not_started"}
    return session.to_public_dict()


@app.post("/applications/{app_id}/virtual-interview/answer")
def virtual_interview_answer(
    app_id: str, req: VirtualInterviewAnswerRequest
) -> Dict[str, Any]:
    """Record the candidate's answer to the current question and advance."""
    application, interview = _resolve_r1_interview(app_id)
    try:
        session = submit_virtual_interview_answer(
            application=application,
            interview=interview,
            answer_text=req.answer_text,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return session.to_public_dict()


@app.post("/applications/{app_id}/virtual-interview/finalise")
def virtual_interview_finalise(app_id: str) -> Dict[str, Any]:
    """End the session early (or confirm it ended) and fold the transcript."""
    application, interview = _resolve_r1_interview(app_id)
    result = finalise_virtual_interview(
        application=application, interview=interview
    )
    if result is None:
        raise HTTPException(
            status_code=400, detail="No virtual interview session for this R1"
        )
    return result


# ---------------------------------------------------------------------------
# Live AI-interview proxy endpoints — TTS welcome / TTS question / STT / face
#
# These are thin pass-throughs to the team's Virtual Interviewer sidecar.
# The candidate page calls them directly (instead of hitting :8000 cross-origin)
# so the entire live interview UX (agent speaks, candidate replies by voice,
# face is verified live) runs against the team's exact code unmodified.
# ---------------------------------------------------------------------------


def _sidecar_session_id(app_id: str) -> str:
    """Resolve the sidecar interview_id stashed on the R1 InterviewRecord."""
    _, interview = _resolve_r1_interview(app_id)
    iid = interview.virtual_interview_session_id
    if not iid:
        raise HTTPException(
            status_code=400,
            detail="No live AI Interview Agent session — call /virtual-interview/start first",
        )
    return iid


def _clear_stale_sidecar_session(app_id: str) -> None:
    """When the sidecar returns 404 for our stored session ID it means the
    sidecar was restarted and the session is dead. Clear it so the next
    /virtual-interview/start creates a fresh one instead of reusing a
    zombie ID forever.
    """
    try:
        app_obj, interview = _resolve_r1_interview(app_id)
        interview.virtual_interview_session_id = None
        interview.virtual_interview_state = None
        app_obj.log(
            "system",
            "Sidecar returned 404 for stored session — cleared so a fresh /start can bind a new one.",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not clear stale sidecar session for %s: %s", app_id, exc)


@app.get("/applications/{app_id}/virtual-interview/welcome-audio")
def virtual_interview_welcome_audio(app_id: str) -> Dict[str, Any]:
    """Proxy GET /api/interview/{iid}/welcome_audio — TTS welcome message."""
    iid = _sidecar_session_id(app_id)
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)) as c:
            r = c.get(f"{VIRTUAL_INTERVIEWER_URL}/api/interview/{iid}/welcome_audio")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI Interview Agent unreachable: {exc}")
    if r.status_code == 404:
        _clear_stale_sidecar_session(app_id)
        raise HTTPException(status_code=410, detail="sidecar_session_expired")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"sidecar welcome_audio failed: {r.status_code} {r.text[:200]}")
    return r.json()


@app.get("/applications/{app_id}/virtual-interview/full-question/{index}")
def virtual_interview_full_question(app_id: str, index: int) -> Dict[str, Any]:
    """Proxy GET /api/interview/{iid}/full_question/{index} — question text + TTS audio."""
    iid = _sidecar_session_id(app_id)
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)) as c:
            r = c.get(f"{VIRTUAL_INTERVIEWER_URL}/api/interview/{iid}/full_question/{index}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI Interview Agent unreachable: {exc}")
    if r.status_code == 400:
        # sidecar says this index is past the last question — relay it
        return JSONResponse(status_code=400, content=r.json() if r.headers.get("content-type", "").startswith("application/json") else {"success": False})
    if r.status_code == 404:
        _clear_stale_sidecar_session(app_id)
        raise HTTPException(status_code=410, detail="sidecar_session_expired")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"sidecar full_question failed: {r.status_code} {r.text[:200]}")
    return r.json()


class TranscribeRequest(BaseModel):
    audio: str  # data:audio/...;base64,...


@app.post("/applications/{app_id}/virtual-interview/transcribe")
def virtual_interview_transcribe(app_id: str, req: TranscribeRequest) -> Dict[str, Any]:
    """Proxy POST /api/interview/transcribe — Deepgram STT for the candidate's recording."""
    _sidecar_session_id(app_id)  # validates session exists
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=120.0, write=60.0, pool=5.0)) as c:
            r = c.post(
                f"{VIRTUAL_INTERVIEWER_URL}/api/interview/transcribe",
                json={"audio": req.audio},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI Interview Agent unreachable: {exc}")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"sidecar transcribe failed: {r.status_code} {r.text[:200]}")
    return r.json()


class VerifyFaceRequest(BaseModel):
    photo: str  # data:image/jpeg;base64,...


@app.post("/applications/{app_id}/virtual-interview/verify-face")
def virtual_interview_verify_face(app_id: str, req: VerifyFaceRequest) -> Dict[str, Any]:
    """Proxy POST /api/interview/{iid}/verify_face — periodic identity check."""
    iid = _sidecar_session_id(app_id)
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)) as c:
            r = c.post(
                f"{VIRTUAL_INTERVIEWER_URL}/api/interview/{iid}/verify_face",
                json={"photo": req.photo},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI Interview Agent unreachable: {exc}")
    if r.status_code != 200:
        # Return the sidecar's body so the frontend can display the reason
        # without us masking it as a 502.
        try:
            return JSONResponse(status_code=200, content=r.json())
        except Exception:
            return {"success": False, "match": False, "message": r.text[:200]}
    return r.json()


@app.post("/applications/{app_id}/confirm-slot", response_model=Application)
def confirm_slot(app_id: str, req: ConfirmSlotRequest) -> Application:
    """Candidate picks one of the slots the agent proposed.

    This is the conversational outreach step from plan §4.4 — instead of
    parsing email replies via Graph (which we'll wire later), the candidate
    confirms directly from the live status page in the Thrive lookalike. The
    orchestrator resumes from WAITING_CANDIDATE and books the meeting.

    Special case: when ``custom_start_iso`` is provided on an R1 confirm,
    the candidate has chosen either "Start now" or a custom date/time
    outside the proposed tiles. We append a synthetic 30-minute slot to
    ``proposed_r1_slots`` at that start time and confirm its new index.
    R1 is an AI-driven virtual interview, so there is no panel calendar
    constraint to honour and any candidate-chosen start is valid. Custom
    slots are intentionally NOT supported for R2 because R2 requires a
    real intersection with every panellist's calendar.
    """
    try:
        # Handle custom R1 slot (Start now / custom date-time picker).
        if req.custom_start_iso and req.round == "R1":
            from datetime import datetime, timedelta, timezone as _tz
            from .models.domain import TimeSlot

            app_obj = STORE.get_application(app_id)
            if app_obj is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Application {app_id} not found",
                )
            raw = req.custom_start_iso.strip()
            # Accept "Z" suffix (JS toISOString) and plain ISO.
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                start_dt = datetime.fromisoformat(raw)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"custom_start_iso is not a valid ISO datetime: {e}",
                )
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=_tz.utc)
            end_dt = start_dt + timedelta(minutes=30)
            custom_slot = TimeSlot(start=start_dt, end=end_dt)
            # Append the custom slot and confirm its new index. STORE holds
            # references to the pydantic Application, so mutating the list
            # in place is enough — no explicit save call exists.
            app_obj.proposed_r1_slots = list(app_obj.proposed_r1_slots) + [custom_slot]
            new_idx = len(app_obj.proposed_r1_slots) - 1
            return ORCHESTRATOR.on_candidate_confirm_slot(app_id, req.round, new_idx)

        return ORCHESTRATOR.on_candidate_confirm_slot(app_id, req.round, req.slot_index)
    except HTTPException:
        raise
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/applications/{app_id}/reschedule/{round_}", response_model=Application)
def reschedule_meeting(app_id: str, round_: str) -> Application:
    """Candidate clicked 'Reschedule' on the live status page.

    Cancels the current Teams meeting on Graph, drops the local interview
    record + selected slot index, walks the application back one stage,
    and re-triggers the orchestrator so it proposes 3 fresh slots.

    Refuses (HTTP 400) if the meeting is within
    ``ORCHESTRATOR.RESCHEDULE_CUTOFF_HOURS`` of starting — the candidate
    must contact HR directly for late changes.
    """
    try:
        return ORCHESTRATOR.on_candidate_reschedule(app_id, round_.upper())
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Apply — the one entry point that kicks the orchestrator into life
# ---------------------------------------------------------------------------


class ApplyRequest(BaseModel):
    employee_id: str
    jd_id: str


@app.post("/apply", response_model=Application)
def apply(req: ApplyRequest) -> Application:
    """Employee clicked Apply on a Thrive card.

    This is the *only* way an application enters the system in production.
    The orchestrator takes over from here and drives the funnel autonomously.
    """
    try:
        return ORCHESTRATOR.start_application(req.employee_id, req.jd_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# External candidate endpoints (public-internet persona)
# ---------------------------------------------------------------------------


class ExternalParseRequest(BaseModel):
    resume_text: str


class ExternalApplyRequest(BaseModel):
    resume_text: str
    job_id: str
    # Optional identity override — the intake form lets the candidate type
    # the name + email they want HR to see, which can differ from whatever
    # the resume regex pulled out (e.g. they used a personal email for the
    # intake form but the resume header lists a work email). Without this
    # override, ``parse_resume`` re-runs in /external/apply and silently
    # discards the intake form values, so the candidate ends up keyed on
    # the wrong email and disappears from the tracker.
    name: Optional[str] = None
    email: Optional[str] = None
    # Optional intake provenance — present when the candidate came in
    # via the new natural-language intake page.
    search_query: Optional[str] = None
    recommendation_source: Optional[Literal["search", "ai"]] = None
    # Optional compensation snapshot — when the candidate uploaded a
    # salary slip during intake we ship the extracted breakdown along
    # with Apply so it lands on the candidate's profile in one round
    # trip.
    compensation: Optional[Dict[str, Any]] = None


class ExternalSearchRequest(BaseModel):
    query: str


@app.post("/external/parse-resume-file")
async def external_parse_resume_file(file: UploadFile = File(...)) -> dict:
    """Parse a PDF / DOCX / TXT resume upload into a profile + ranked jobs.

    Goes through ``claude_resume_matcher`` which calls the real Anthropic
    Messages API. The deterministic offline parser is only used as a
    fallback when the API key is missing or the call fails. The response
    includes ``source`` so the UI can prove the live LLM was hit.
    """
    from .services.claude_resume_matcher import match_resume
    from .tools.external_intake import extract_text_from_upload

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    try:
        resume_text = extract_text_from_upload(file.filename or "", data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"Could not read {file.filename!r}: {exc}",
        )
    if not resume_text.strip():
        raise HTTPException(
            status_code=400,
            detail="No text could be extracted from the file",
        )
    profile, matches, source = match_resume(resume_text)
    return {
        "resume_text": resume_text,
        "profile": profile.model_dump(),
        "matches": [m.__dict__ for m in matches],
        "source": source,
    }


@app.post("/external/parse-resume")
def external_parse_resume(req: ExternalParseRequest) -> dict:
    """Parse a pasted resume into a structured profile + ranked job matches.

    The frontend calls this once after the candidate pastes their resume,
    then renders the recommendations from the ``matches`` list.
    """
    from .tools.external_intake import parse_resume, recommend_jobs

    profile = parse_resume(req.resume_text)
    matches = recommend_jobs(profile)
    return {
        "profile": profile.model_dump(),
        "matches": [m.__dict__ for m in matches],
    }


@app.post("/external/apply", response_model=Application)
def external_apply(req: ExternalApplyRequest) -> Application:
    """External candidate clicked Apply on one of the recommended JDs.

    Re-parses the resume (cheap) so the candidate doesn't have to round-trip
    a Profile blob, then creates an external Application and triggers the
    orchestrator. The orchestrator branches on ``candidate_kind == 'external'``
    so it skips the candidate's calendar and emails them slot proposals.

    If the candidate uploaded a salary slip during intake, the extracted
    ``compensation`` block is attached to their profile here so HR can
    see CTC + components on the application card.
    """
    from .models import CompensationBreakdown
    from .tools.external_intake import apply_external, parse_resume

    profile = parse_resume(req.resume_text)
    # Honour the intake-form identity override (see ExternalApplyRequest).
    name_override = (req.name or "").strip()
    email_override = (req.email or "").strip()
    if name_override:
        profile.name = name_override
    if email_override:
        profile.email = email_override
        profile.employee_id = email_override
    if req.compensation:
        try:
            profile.compensation = CompensationBreakdown(**req.compensation)
        except Exception as exc:  # noqa: BLE001
            # Don't block apply if comp parsing fails — just log it.
            log_msg = f"Could not coerce compensation payload: {exc}"
            print(log_msg)  # noqa: T201
    try:
        app_record = apply_external(
            profile,
            req.job_id,
            search_query=req.search_query,
            recommendation_source=req.recommendation_source,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    ORCHESTRATOR.trigger(app_record.id)
    return app_record


# ---------------------------------------------------------------------------
# External candidate intake — new richer flow
# ---------------------------------------------------------------------------


@app.post("/external/parse-salary-slip")
async def external_parse_salary_slip(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Extract a structured CTC + components from an uploaded salary slip.

    Goes through ``claude_salary_extractor`` which calls the real
    Anthropic Messages API. The deterministic regex parser is only used
    when the API key is missing or the call fails — the ``source``
    field on the response surfaces which path was taken so the UI can
    show a "powered by Claude" badge for the live path.
    """
    from .services.claude_salary_extractor import extract_salary
    from .tools.external_intake import extract_text_from_upload

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    try:
        slip_text = extract_text_from_upload(file.filename or "", data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"Could not read {file.filename!r}: {exc}",
        )
    if not slip_text.strip():
        raise HTTPException(
            status_code=400,
            detail="No text could be extracted from the salary slip",
        )
    breakdown, source = extract_salary(
        slip_text, source_filename=file.filename
    )
    return {
        "compensation": breakdown.model_dump(mode="json"),
        "source": source,
    }


@app.post("/external/search-jobs")
def external_search_jobs(req: ExternalSearchRequest) -> Dict[str, Any]:
    """Run a natural-language semantic search against the open JDs.

    The candidate types something like "Branch Manager in any branch in
    Mumbai near Powai" on the intake page. This endpoint hands that to
    Claude which parses intent (role, city, locality) and ranks every
    open job by stated-preference fit. Falls back to a token-overlap
    scorer when Claude is unreachable.
    """
    from .services.claude_job_searcher import search_jobs

    matches, source = search_jobs(req.query)
    return {
        "query": req.query,
        "matches": [m.__dict__ for m in matches],
        "source": source,
    }


@app.post("/external/intake")
async def external_intake(
    resume: UploadFile = File(...),
    salary_slip: Optional[UploadFile] = File(None),
    name: str = Form(""),
    email: str = Form(""),
    search_query: str = Form(""),
) -> Dict[str, Any]:
    """One-shot external intake: NL query + resume + (optional) salary slip.

    The new external intake page sends all three inputs in a single
    multipart request. We:
      1. Extract resume text and run Claude resume matcher → AI-ranked
         job recommendations (Section B on the results page).
      2. Run Claude semantic search on the NL query against the open
         JDs → search-match recommendations (Section A on the results
         page). Empty list when no query was provided.
      3. If a salary slip was uploaded, run Claude salary extractor and
         attach the structured CompensationBreakdown to the returned
         profile so the candidate carries it into Apply.
      4. If the candidate typed a name/email on the intake form, those
         override anything Claude pulled out of the resume so HR sees
         the form-of-record values.

    Returns a single JSON blob the frontend stores in localStorage and
    feeds into the results page + the Apply call.
    """
    from .services.claude_job_searcher import search_jobs
    from .services.claude_resume_matcher import match_resume
    from .services.claude_salary_extractor import extract_salary
    from .tools.external_intake import extract_text_from_upload

    # ---- resume ----
    resume_bytes = await resume.read()
    if not resume_bytes:
        raise HTTPException(status_code=400, detail="Empty resume upload")
    try:
        resume_text = extract_text_from_upload(resume.filename or "", resume_bytes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"Could not read resume {resume.filename!r}: {exc}",
        )
    if not resume_text.strip():
        raise HTTPException(
            status_code=400, detail="No text extracted from resume"
        )

    profile, ai_matches, resume_source = match_resume(resume_text)

    # ---- name/email override from form ----
    name = (name or "").strip()
    email = (email or "").strip()
    if name:
        profile.name = name
    if email:
        profile.email = email
        profile.employee_id = email

    # ---- salary slip (optional) ----
    salary_source: Optional[str] = None
    if salary_slip is not None and salary_slip.filename:
        slip_bytes = await salary_slip.read()
        if slip_bytes:
            try:
                slip_text = extract_text_from_upload(
                    salary_slip.filename or "", slip_bytes
                )
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not read salary slip "
                    f"{salary_slip.filename!r}: {exc}",
                )
            if slip_text.strip():
                breakdown, salary_source = extract_salary(
                    slip_text, source_filename=salary_slip.filename
                )
                profile.compensation = breakdown

    # ---- semantic NL search (optional) ----
    search_matches: list = []
    search_source: Optional[str] = None
    sq = (search_query or "").strip()
    if sq:
        m, search_source = search_jobs(sq)
        search_matches = [item.__dict__ for item in m]

    return {
        "resume_text": resume_text,
        "profile": profile.model_dump(mode="json"),
        "search_query": sq,
        "search_matches": search_matches,
        "search_source": search_source,
        "ai_recommendations": [m.__dict__ for m in ai_matches],
        "ai_source": resume_source,
        "salary_source": salary_source,
    }


class ExternalReplyRequest(BaseModel):
    sender_email: str
    body_text: str


@app.post("/external/simulate-reply")
def external_simulate_reply(req: ExternalReplyRequest) -> dict:
    """Demo helper: pretend an inbound reply landed in the Business Partner's
    inbox. Calls ``handle_external_reply`` directly so the orchestrator
    advances without waiting for the next poller tick. Use this from the
    live status page when running a scripted demo on the same laptop.
    """
    from .services.inbox_parser import handle_external_reply

    advanced = handle_external_reply(
        sender_email=req.sender_email,
        body_text=req.body_text,
    )
    return {"advanced": advanced}


@app.post("/external/poll-inbox")
def external_poll_inbox() -> dict:
    """Force one immediate pass over the Business Partner's mailbox. Useful when
    a tester wants to trigger the poller manually instead of waiting for
    the periodic interval to fire."""
    from .services.inbox_poller import _poll_once

    dispatched = _poll_once()
    return {"dispatched": dispatched}


@app.get("/external/applications")
def external_applications(email: str) -> List[Application]:
    """All applications belonging to one external candidate (by email).

    Used by the live status page so a returning external candidate can
    see every JD they've applied to in one place.
    """
    sender = email.strip().lower()
    return [
        a
        for a in STORE.list_applications()
        if a.candidate_kind == "external" and a.candidate_id.lower() == sender
    ]


class WithdrawRequest(BaseModel):
    reason: str


@app.post("/applications/{app_id}/withdraw")
def withdraw_application(app_id: str, req: WithdrawRequest):
    """Candidate withdraws their application, with a reason."""
    application = STORE.get_application(app_id)
    if not application:
        raise HTTPException(404, "Application not found")
    terminal = {"offer_declined", "withdrawn", "rejected", "joined"}
    if application.stage.value in terminal:
        raise HTTPException(400, f"Cannot withdraw — application is already {application.stage.value}")
    from datetime import datetime
    from .models.domain import _now_ist, FunnelStage
    application.stage = FunnelStage.WITHDRAWN
    application.withdrawn = True
    application.withdrawn_reason = req.reason.strip()
    application.withdrawn_at = _now_ist()
    application.agent_status = AgentStatus.IDLE
    application.next_action = ""
    STORE.save_application(application)
    return {"status": "withdrawn", "message": "Your application has been withdrawn. We wish you the best."}


# ---------------------------------------------------------------------------
# Panel endpoints (Panel persona)
# ---------------------------------------------------------------------------


@app.get("/panel/pending")
def panel_pending(user_id: str) -> list:
    """Return R2 interviews where this panellist still owes feedback."""
    pending = []
    for app in STORE.list_applications():
        if app.stage != FunnelStage.R2_SCHEDULED:
            continue
        job = STORE.get_job(app.job_id)
        if not job:
            continue
        # BUG-012: source the panel members from the panel HR actually
        # picked at R2 approval time, not from the JD's legacy hardcoded
        # `jd.panel`. Fall back to the JD panel only when no R2 panel was
        # selected (e.g. legacy applications created before DESIGN-001).
        selected_panel = (
            STORE.get_panel(app.selected_r2_panel_id)
            if app.selected_r2_panel_id
            else None
        )
        if selected_panel is not None:
            panel_ids = {m.user_id for m in selected_panel.members}
        else:
            panel_ids = {p.user_id for p in job.panel if p.role != "hr_partner"}
        if user_id not in panel_ids:
            continue
        r2 = next((i for i in app.interviews if i.round == "R2"), None)
        if not r2:
            continue
        # Already submitted?
        if any(fb.panellist_id == user_id for fb in r2.panel_feedback):
            continue

        cand_name = "Unknown"
        for c in STORE.candidates.values():
            if c.id == app.candidate_id or c.profile.employee_id == app.candidate_id:
                cand_name = c.profile.name
                break
        pending.append(
            {
                "application_id": app.id,
                "interview_id": r2.id,
                "job_id": job.id,
                "job_title": job.title,
                "job_location": job.location,
                "candidate_name": cand_name,
                "slot_start": r2.meeting_slot.start.isoformat() if r2.meeting_slot else None,
                "slot_end": r2.meeting_slot.end.isoformat() if r2.meeting_slot else None,
                "teams_join_url": None,  # filled in by frontend from /activity if needed
            }
        )
    return pending


@app.get("/panel/history")
def panel_history(user_id: str) -> list:
    """Return R2 interviews this panellist has already submitted feedback on.

    Mirror image of /panel/pending — gives the panellist a read-only view of
    every vote they've cast, with the score / strengths / concerns / verdict
    and the final consolidated outcome (offer / rejected / still pending peer
    votes). The panellist cannot edit a submitted vote, but they need a way
    to look it up later.
    """
    history = []
    for app in STORE.list_applications():
        for iv in app.interviews:
            if iv.round != "R2":
                continue
            mine = next(
                (fb for fb in iv.panel_feedback if fb.panellist_id == user_id),
                None,
            )
            if mine is None:
                continue
            job = STORE.get_job(app.job_id)
            if not job:
                continue
            cand_name = "Unknown"
            for c in STORE.candidates.values():
                if c.id == app.candidate_id or c.profile.employee_id == app.candidate_id:
                    cand_name = c.profile.name
                    break
            # Outcome rollup: how many panel members were expected vs voted,
            # plus the funnel stage so the UI can show offer / rejected / etc.
            selected_panel = (
                STORE.get_panel(app.selected_r2_panel_id)
                if app.selected_r2_panel_id
                else None
            )
            if selected_panel is not None:
                expected_panel_ids = {m.user_id for m in selected_panel.members}
            else:
                expected_panel_ids = {
                    p.user_id for p in job.panel if p.role != "hr_partner"
                }
            history.append(
                {
                    "application_id": app.id,
                    "interview_id": iv.id,
                    "job_id": job.id,
                    "job_title": job.title,
                    "job_location": job.location,
                    "candidate_name": cand_name,
                    "slot_start": iv.meeting_slot.start.isoformat() if iv.meeting_slot else None,
                    "slot_end": iv.meeting_slot.end.isoformat() if iv.meeting_slot else None,
                    "stage": app.stage.value if hasattr(app.stage, "value") else str(app.stage),
                    "my_score": mine.score,
                    "my_strengths": mine.strengths,
                    "my_concerns": mine.concerns,
                    "my_recommendation": mine.recommendation,
                    "submitted_at": mine.submitted_at.isoformat()
                    if hasattr(mine.submitted_at, "isoformat")
                    else str(mine.submitted_at),
                    "votes_in": len(iv.panel_feedback),
                    "votes_expected": len(expected_panel_ids),
                }
            )
    # Most recent first.
    history.sort(key=lambda h: h["submitted_at"], reverse=True)
    return history


class PanelFeedbackRequest(BaseModel):
    interview_id: str
    panellist_id: str
    score: float
    strengths: str
    concerns: str
    recommendation: Literal["strong_hire", "hire", "no_hire"]


@app.post("/panel/feedback")
def submit_panel_feedback_endpoint(req: PanelFeedbackRequest) -> dict:
    try:
        submit_panel_feedback(
            req.interview_id,
            req.panellist_id,
            score=req.score,
            strengths=req.strengths,
            concerns=req.concerns,
            recommendation=req.recommendation,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Resolve which application owns this R2 interview, then nudge the
    # orchestrator. It will check if all panel feedback is in and transition
    # into finalisation if so.
    owning_app_id: Optional[str] = None
    for application in STORE.list_applications():
        for iv in application.interviews:
            if iv.id == req.interview_id and iv.round == "R2":
                owning_app_id = application.id
                break
        if owning_app_id:
            break

    if owning_app_id:
        ORCHESTRATOR.on_panel_feedback(owning_app_id)
    return {"status": "ok", "application_id": owning_app_id}


@app.get("/panel/members")
def panel_members() -> list:
    """All distinct panel members across every JD AND every configured Panel
    object, for the Panel persona dropdown.

    Historically this only iterated ``job.panel`` (the legacy inline panel on
    the JD), which left out stub panellists that live only on Panel objects
    like ``panel-bdm-central``. That meant that after HR approved a modern
    Panel for an R2, the persona dropdown couldn't surface every panellist
    the orchestrator was waiting on — so votes would get stuck at 1-of-3 with
    no way for the demo user to log in as the remaining panellists.

    We now union both sources: ``job.panel`` (for JD-specific listings) plus
    every member of every ``Panel`` in the panel registry.
    """
    seen: dict = {}

    def _record(member, *, job=None, panel=None):
        if member.role == "hr_partner":
            return
        if member.user_id not in seen:
            seen[member.user_id] = {
                "user_id": member.user_id,
                "name": member.name,
                "role": member.role,
                "jobs": [],
                "panels": [],
            }
        if job is not None:
            seen[member.user_id]["jobs"].append(
                {"id": job.id, "title": job.title, "location": job.location}
            )
        if panel is not None and not any(
            p["id"] == panel.id for p in seen[member.user_id]["panels"]
        ):
            seen[member.user_id]["panels"].append(
                {"id": panel.id, "name": panel.name}
            )

    for job in STORE.list_jobs():
        for p in job.panel:
            _record(p, job=job)
    for panel in STORE.list_panels():
        for m in panel.members:
            _record(m, panel=panel)

    return list(seen.values())


# ---------------------------------------------------------------------------
# Panel configuration (DESIGN-001 chunks 1 + 2)
# ---------------------------------------------------------------------------


class PanelCreateRequest(BaseModel):
    name: str
    members: List[PanelMember]
    role_scopes: List[str] = []
    location: Optional[str] = None
    default_size: int = 1
    active: bool = True


class PanelUpdateRequest(BaseModel):
    name: Optional[str] = None
    members: Optional[List[PanelMember]] = None
    role_scopes: Optional[List[str]] = None
    location: Optional[str] = None
    default_size: Optional[int] = None
    active: Optional[bool] = None


@app.get("/panels", response_model=List[Panel])
def list_panels() -> List[Panel]:
    return STORE.list_panels()


@app.get("/panels/for-job/{jd_id}", response_model=List[Panel])
def list_panels_for_job(jd_id: str) -> List[Panel]:
    job = STORE.get_job(jd_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {jd_id}")
    return panels_for_job(job)


@app.get("/applications/{app_id}/r2-slots-by-panel")
def r2_slots_by_panel(app_id: str) -> List[Dict[str, Any]]:
    """Per-panel candidate slot preview for the HR R2 approval card.

    For each panel that matches the JD's function/band, intersects the
    candidate + Business Partner + panel-member calendars over the same look-ahead
    window the orchestrator uses, and returns up to 3 candidate slots so HR
    can compare panels by availability *before* clicking Approve.
    """
    from .tools.calendar import find_common_slots
    from .tools.intake import get_employee_profile

    application = STORE.get_application(app_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    job = STORE.get_job(application.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {application.job_id}")
    profile = get_employee_profile(application.candidate_id)

    window_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2)
    window_end = window_start + timedelta(days=5)

    out: List[Dict[str, Any]] = []
    for panel in panels_for_job(job):
        if not panel.active or not panel.members:
            continue
        panel_ids = [m.user_id for m in panel.members]
        attendees = list({job.hr_partner_id, profile.email, *panel_ids})
        try:
            slots = find_common_slots(
                user_ids=attendees,
                duration_min=45,
                window_start=window_start,
                window_end=window_end,
                top_n=3,
            )
        except Exception as exc:  # noqa: BLE001
            slots = []
            error = repr(exc)
        else:
            error = None
        out.append({
            "panel_id": panel.id,
            "panel_name": panel.name,
            "members": [
                {"user_id": m.user_id, "name": m.name, "role": m.role}
                for m in panel.members
            ],
            "location": panel.location,
            "slots": [
                {"start": s.start.isoformat(), "end": s.end.isoformat()}
                for s in slots
            ],
            "error": error,
        })
    return out


@app.post("/panels", response_model=Panel)
def create_panel(req: PanelCreateRequest) -> Panel:
    panel = Panel(
        id=f"panel-{uuid4().hex[:8]}",
        name=req.name.strip(),
        members=list(req.members),
        role_scopes=list(req.role_scopes),
        location=req.location,
        default_size=req.default_size,
        active=req.active,
    )
    STORE.add_panel(panel)
    return panel


@app.patch("/panels/{panel_id}", response_model=Panel)
def update_panel(panel_id: str, req: PanelUpdateRequest) -> Panel:
    panel = STORE.get_panel(panel_id)
    if panel is None:
        raise HTTPException(status_code=404, detail=f"No panel {panel_id}")
    if req.name is not None:
        panel.name = req.name.strip()
    if req.members is not None:
        panel.members = list(req.members)
    if req.role_scopes is not None:
        panel.role_scopes = list(req.role_scopes)
    if req.location is not None:
        panel.location = req.location
    if req.default_size is not None:
        panel.default_size = req.default_size
    if req.active is not None:
        panel.active = req.active
    panel.updated_at = datetime.utcnow()
    return panel


@app.delete("/panels/{panel_id}")
def delete_panel(panel_id: str) -> dict:
    ok = STORE.delete_panel(panel_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No panel {panel_id}")
    return {"status": "deleted", "id": panel_id}


# ---------------------------------------------------------------------------
# R2 approval + transcript analysis (DESIGN-001 chunks 4 + 6)
# ---------------------------------------------------------------------------


class R2ApprovalRequest(BaseModel):
    panel_id: str


@app.post("/applications/{app_id}/approve-r2", response_model=Application)
def approve_r2(app_id: str, req: R2ApprovalRequest) -> Application:
    """HR approves an R1-cleared application for R2 and picks the panel.

    Replaces the legacy manual checklist tick at ``pre-r2-2``. The old
    item is auto-ticked here so the audit trail still records the HR
    approval, then the orchestrator is re-triggered and proceeds through
    the multi-user free/busy intersection, Teams invite, and pause at
    WAITING_PANEL.
    """
    application = STORE.get_application(app_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    if application.stage != FunnelStage.R1_DONE:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve R2 from stage {application.stage.value}",
        )

    panel = STORE.get_panel(req.panel_id)
    if panel is None:
        raise HTTPException(status_code=404, detail=f"No panel {req.panel_id}")
    if not panel.active:
        raise HTTPException(status_code=400, detail="Panel is inactive")
    if not panel.members:
        raise HTTPException(status_code=400, detail="Panel has no members")

    application.selected_r2_panel_id = panel.id
    application.log(
        "hr_partner",
        f"Approved R2 with panel '{panel.name}' ({len(panel.members)} members)",
    )

    # Auto-tick the legacy blocking checklist item so the existing gate
    # in the orchestrator's state machine (and the audit display) sees
    # the approval event. Ignore LookupError — checklist may not be
    # instantiated yet.
    try:
        tick_checklist_item(
            app_id,
            "R2",
            "pre",
            "pre-r2-2",
            actor="hr_partner",
            note=f"Approved via /approve-r2 with panel {panel.name}",
        )
    except LookupError:
        pass

    ORCHESTRATOR.on_hr_tick(app_id)
    return application


class HrRegretRequest(BaseModel):
    reason: str = ""


@app.post("/applications/{app_id}/hr-regret-r1", response_model=Application)
def hr_regret_r1(app_id: str, req: HrRegretRequest) -> Application:
    """Business Partner rejects a candidate AFTER R1 AI interview review.

    The orchestrator no longer auto-rejects on AI score — every R1 lands
    in the HR queue with the transcript + AI report attached. HR clicks
    Advance (→ /approve-r2) or Regret (→ this endpoint).
    """
    from .comms_templates import r1_reject as _r1_reject
    from .tools.intake import get_employee_profile, get_jd
    from .services.messaging import send_email

    application = STORE.get_application(app_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    if application.stage != FunnelStage.R1_DONE:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot regret R1 from stage {application.stage.value}",
        )

    reason = (req.reason or "HR regretted after R1 review").strip()
    application.log(
        "hr_partner",
        f"Regretted candidate after R1 AI interview review: {reason}",
    )
    update_application_status(app_id, FunnelStage.REJECTED, reason)

    # Candidate-facing regret email — same template the orchestrator
    # used to send on auto-reject, only now it's HR-driven.
    job = STORE.get_job(application.job_id)
    candidate = STORE.get_candidate(application.candidate_id)
    if job and candidate:
        try:
            profile = get_employee_profile(application.candidate_id)
            subject, body = _r1_reject(profile.name, job.title)
            send_email(
                to=profile.email,
                subject=subject,
                body=body,
                application_id=app_id,
            )
        except Exception as exc:  # noqa: BLE001
            application.log(
                "agent",
                f"Failed to send regret email: {exc!r}",
                level="warn",
            )

    application.agent_status = AgentStatus.DONE
    application.next_action = "Closed — HR regretted candidate after R1 review"
    return application


class HrScreeningDecisionRequest(BaseModel):
    decision: Literal["advance", "regret"]
    reason: str = ""


@app.post(
    "/applications/{app_id}/hr-screening-decision", response_model=Application
)
def hr_screening_decision(
    app_id: str, req: HrScreeningDecisionRequest
) -> Application:
    """Business Partner reviews the AI screening report and decides.

    Per the human-in-the-loop rule (2026-04-07), the orchestrator never
    auto-rejects an internal candidate on the JD-rubric screening score.
    Instead, when the score is below the shortlist threshold the
    orchestrator emails the full screening report to HR and pauses
    WAITING_HR. HR then calls this endpoint with either:

      - decision="advance" → the orchestrator overrides the threshold,
        shortlists the candidate, and resumes the funnel into Round 1
        outreach. The candidate is never told the AI flagged them.
      - decision="regret" → the orchestrator moves the application to
        REJECTED and sends the standard post-screening regret email.
    """
    application = STORE.get_application(app_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    if application.stage != FunnelStage.APPLIED:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot decide screening from stage "
                f"{application.stage.value} — this gate only fires while "
                f"the application is still at intake screening."
            ),
        )
    if application.agent_status != AgentStatus.WAITING_HR:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot decide screening — orchestrator is not currently "
                "waiting for HR. Refresh the HR queue and retry."
            ),
        )

    application.hr_screening_decision = req.decision
    reason = (
        req.reason
        or (
            "Business Partner overrode the screening threshold"
            if req.decision == "advance"
            else "Business Partner closed the application after screening review"
        )
    ).strip()
    application.log(
        "hr_partner",
        f"Screening review · {req.decision.upper()} — {reason}",
    )
    ORCHESTRATOR.on_hr_tick(app_id)
    return application


class AnalyseTranscriptRequest(BaseModel):
    transcript_text: str
    force: bool = False  # if True, re-run even when a cached recommendation exists


@app.post("/applications/{app_id}/analyse-transcript", response_model=AiPanelRecommendation)
def analyse_transcript(app_id: str, req: AnalyseTranscriptRequest) -> AiPanelRecommendation:
    """Panellist pastes an R2 transcript; Claude returns a recommendation.

    Cached on the ``InterviewRecord`` so re-renders do not re-bill the API.
    """
    application = STORE.get_application(app_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")

    r2 = next((i for i in application.interviews if i.round == "R2"), None)
    if r2 is None:
        raise HTTPException(status_code=400, detail="No R2 interview on file yet")

    if not req.transcript_text or not req.transcript_text.strip():
        raise HTTPException(status_code=400, detail="transcript_text is required")

    # Cache hit — return the prior recommendation unless the caller forced a refresh.
    if (
        not req.force
        and r2.ai_recommendation is not None
        and r2.pasted_transcript == req.transcript_text
    ):
        return r2.ai_recommendation

    job = STORE.get_job(application.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {application.job_id}")

    r1 = next((i for i in application.interviews if i.round == "R1"), None)
    r1_report = getattr(r1, "report", None) if r1 else None

    try:
        rec = recommend_from_transcript(
            interview=r2,
            transcript_text=req.transcript_text,
            job=job,
            r1_report=r1_report,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Recommender failed: {exc!r}")

    r2.pasted_transcript = req.transcript_text
    r2.ai_recommendation = rec
    application.log(
        "agent",
        f"Claude R2 recommendation: {rec.suggested_recommendation} "
        f"({rec.suggested_score:.0f}/100) — {rec.headline}",
    )
    return rec


class AnalysePanellistRequest(BaseModel):
    # Optional — if omitted, the endpoint uses the per-panellist transcript
    # already on file (``r2.pasted_transcripts_by_panellist[panellist_id]``).
    # HR can override by sending a different string (e.g. an edited paste).
    transcript_text: Optional[str] = None
    force: bool = False


@app.post(
    "/applications/{app_id}/analyse-panellist/{panellist_id}",
    response_model=AiPanelRecommendation,
)
def analyse_panellist(
    app_id: str, panellist_id: str, req: AnalysePanellistRequest
) -> AiPanelRecommendation:
    """Per-panellist Claude review.

    HR runs this once per panel vote on the R2 review screen — Claude is
    asked to corroborate or challenge THAT specific panellist's verdict
    against THAT panellist's own 1-on-1 transcript. Each panellist meets
    the candidate separately, so the transcript is per-panellist, not
    shared. Cached on
    ``InterviewRecord.ai_recommendations_by_panellist[panellist_id]`` so
    re-renders do not re-bill the API.
    """
    application = STORE.get_application(app_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")

    r2 = next((i for i in application.interviews if i.round == "R2"), None)
    if r2 is None:
        raise HTTPException(status_code=400, detail="No R2 interview on file yet")

    panellist = next(
        (fb for fb in r2.panel_feedback if fb.panellist_id == panellist_id),
        None,
    )
    if panellist is None:
        raise HTTPException(
            status_code=404,
            detail=f"No panel feedback from {panellist_id} on this R2",
        )

    # Resolve the transcript: explicit override → per-panellist on file →
    # legacy shared transcript. Whichever we end up using is the cache key
    # for this panellist's recommendation.
    transcript_text = (req.transcript_text or "").strip()
    if not transcript_text:
        transcript_text = (
            r2.pasted_transcripts_by_panellist.get(panellist_id)
            or r2.pasted_transcript
            or ""
        )
    if not transcript_text or not transcript_text.strip():
        raise HTTPException(
            status_code=400,
            detail=f"No transcript on file for panellist {panellist_id}",
        )

    cached = r2.ai_recommendations_by_panellist.get(panellist_id)
    cached_transcript = r2.pasted_transcripts_by_panellist.get(panellist_id)
    if (
        not req.force
        and cached is not None
        and cached_transcript == transcript_text
    ):
        return cached

    job = STORE.get_job(application.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {application.job_id}")

    r1 = next((i for i in application.interviews if i.round == "R1"), None)
    r1_report = getattr(r1, "report", None) if r1 else None

    try:
        rec = recommend_for_panellist(
            interview=r2,
            transcript_text=transcript_text,
            job=job,
            r1_report=r1_report,
            panellist=panellist,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Per-panellist recommender failed: {exc!r}"
        )

    r2.pasted_transcripts_by_panellist[panellist_id] = transcript_text
    r2.ai_recommendations_by_panellist[panellist_id] = rec
    application.log(
        "agent",
        f"Claude per-panellist review for {panellist.panellist_name or panellist_id}: "
        f"{rec.suggested_recommendation} ({rec.suggested_score:.0f}/100) — {rec.headline}",
    )
    return rec


class HrR2DecisionRequest(BaseModel):
    decision: Literal["offer", "reject"]


@app.post("/applications/{app_id}/hr-r2-decision", response_model=Application)
def hr_r2_decision(app_id: str, req: HrR2DecisionRequest) -> Application:
    """HR finalises the R2 verdict after reviewing panel feedback.

    This is the explicit HR-gated replacement for the old auto-finalise
    path. The panel submits feedback → orchestrator routes to HR →
    HR (optionally) runs the AI review for comparison → HR clicks
    "Make offer" or "Reject" which calls this endpoint.
    """
    try:
        return ORCHESTRATOR.on_hr_r2_decision(app_id, req.decision)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Offer Discussion Team — post-R2, pre final-offer human-gated stage
# ---------------------------------------------------------------------------


class OfferTeamRolloutRequest(BaseModel):
    final_ctc_lpa: float
    notes: str = ""
    rolled_out_by: str = "offer_team"


@app.get("/offer-team/queue")
def offer_team_queue() -> list:
    """All applications currently sitting with the Offer Discussion Team.

    Each entry carries enough context for the queue card on the
    /offer-team page: candidate name, role, location, R1/R2 scores, and
    the AI-extracted CompensationBreakdown if a salary slip was uploaded
    at intake.
    """
    from .tools.intake import get_employee_profile
    rows: list = []
    for app in ORCHESTRATOR.list_offer_team_queue():
        try:
            job = STORE.get_job(app.job_id)
            profile = get_employee_profile(app.candidate_id)
        except Exception:
            continue
        r1 = next((i for i in app.interviews if i.round == "R1"), None)
        r2 = next((i for i in app.interviews if i.round == "R2"), None)

        # R2 score: prefer the interview-level score, otherwise compute the
        # average of every recorded panel vote so the Offer Discussion Team
        # actually sees a number on the queue card (the field was rendering
        # as "—" because the orchestrator never aggregates panel votes onto
        # the InterviewRecord — the source of truth is panel_feedback).
        r2_avg_score = None
        if r2 is not None:
            if r2.score is not None:
                r2_avg_score = r2.score
            elif r2.panel_feedback:
                r2_avg_score = sum(f.score for f in r2.panel_feedback) / len(r2.panel_feedback)

        # R1 AI summary — pull the structured Claude/heuristic report so the
        # Offer Discussion Team can negotiate with full context (headline,
        # recommendation, strongest signals, red flags).
        r1_summary = None
        if r1 is not None and r1.report is not None:
            rep = r1.report
            r1_summary = {
                "headline": rep.headline,
                "overall_score": rep.overall_score,
                "recommendation": rep.recommendation,
                "red_flags": list(rep.red_flags or [])[:3],
                "top_highlights": [
                    {"quote": h.quote, "why": h.why_it_matters}
                    for h in (rep.transcript_highlights or [])[:2]
                ],
            }

        # R2 AI summary — every panellist's vote (name, score, recommendation,
        # one-line strengths, one-line concerns) so the Offer Discussion Team
        # knows exactly how strong the panel signal was before negotiating.
        r2_summary = None
        if r2 is not None and r2.panel_feedback:
            votes = []
            for f in r2.panel_feedback:
                votes.append({
                    "panellist_name": f.panellist_name,
                    "score": f.score,
                    "recommendation": f.recommendation,
                    "strengths": (f.strengths or "").strip()[:280],
                    "concerns": (f.concerns or "").strip()[:280],
                })
            strong = sum(1 for f in r2.panel_feedback if f.recommendation == "strong_hire")
            hire = sum(1 for f in r2.panel_feedback if f.recommendation == "hire")
            no_hire = sum(1 for f in r2.panel_feedback if f.recommendation == "no_hire")
            r2_summary = {
                "votes": votes,
                "tally": {"strong_hire": strong, "hire": hire, "no_hire": no_hire},
                "average_score": r2_avg_score,
            }

        rows.append({
            "application_id": app.id,
            "candidate_name": profile.name,
            "candidate_email": profile.email,
            "candidate_current_role": profile.current_role,
            "job_id": job.id if job else app.job_id,
            "job_title": job.title if job else "",
            "job_location": job.location if job else "",
            "r1_score": r1.score if r1 else None,
            "r2_score": r2_avg_score,
            "r1_summary": r1_summary,
            "r2_summary": r2_summary,
            "current_ctc_lpa": (
                profile.compensation.current_ctc
                if getattr(profile, "compensation", None) else None
            ),
            "proposed_ctc_lpa": app.offer_proposed_ctc_lpa,
            "negotiation_notes": app.offer_negotiation_notes,
            "rolled_out": app.offer_rolled_out,
            "next_action": app.next_action,
            "updated_at": app.updated_at.isoformat(),
        })
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows


@app.post("/applications/{app_id}/offer-team/rollout", response_model=Application)
def offer_team_rollout(app_id: str, req: OfferTeamRolloutRequest) -> Application:
    """Offer Discussion Team finalises the negotiated CTC and rolls
    out the formal offer letter — moves the application from
    OFFER_NEGOTIATION → OFFER and sends comms.final_offer_email."""
    try:
        return ORCHESTRATOR.on_offer_team_rollout(
            app_id,
            final_ctc_lpa=req.final_ctc_lpa,
            notes=req.notes,
            rolled_out_by=req.rolled_out_by,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail=f"No application {app_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/hr/partners")
def hr_partners() -> list:
    """Every Business Partner across JDs, for the HR persona dropdown."""
    seen: dict = {}
    for job in STORE.list_jobs():
        for p in job.panel:
            if p.role != "hr_partner":
                continue
            if p.user_id not in seen:
                seen[p.user_id] = {"user_id": p.user_id, "name": p.name, "jobs": []}
            seen[p.user_id]["jobs"].append(
                {"id": job.id, "title": job.title, "location": job.location}
            )
    return list(seen.values())


# ---------------------------------------------------------------------------
# Bulk CV Screening — HR dashboard feature
# ---------------------------------------------------------------------------
#
# Endpoints for the new dashboarding solution where HR partners upload
# bulk CVs and the AI engine evaluates and ranks profiles against a JD.
# These are entirely ADDITIVE — they don't modify any existing code path.


@app.post("/hr/bulk-intake")
async def hr_bulk_intake(
    files: List[UploadFile] = File(...),
    job_id: str = Form(default=""),
    custom_criteria: str = Form(default=""),
) -> dict:
    """Upload N CVs, optionally target a JD, and kick off batch screening.

    - **With job_id** (single-JD mode): scores all CVs against that one JD.
    - **Without job_id** (auto-map mode): scores every CV against ALL open
      roles and maps each to the best-fitting job automatically.

    Returns immediately with a ``pool_id`` + initial row stubs. The actual
    AI evaluation runs in background tasks. Poll ``GET /hr/bulk-intake/{pool_id}``
    for live progress.
    """
    from .models import BulkCandidateRow, CandidatePool

    # Determine mode — empty string or missing = auto-map
    job_id = job_id.strip() if job_id else ""
    auto_map = not job_id
    job = None
    if job_id:
        job = STORE.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"No job {job_id}")

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    pool_id = f"pool-{uuid4().hex[:8]}"
    rows: List[BulkCandidateRow] = []
    file_data: List[tuple] = []  # (row_id, filename, bytes)

    for f in files:
        row_id = f"row-{uuid4().hex[:8]}"
        raw = await f.read()
        rows.append(BulkCandidateRow(row_id=row_id, file_name=f.filename or "unknown"))
        file_data.append((row_id, f.filename or "unknown", raw))

    pool = CandidatePool(
        id=pool_id,
        job_id=job_id if job_id else None,
        job_title=job.title if job else "All open roles (auto-mapped)",
        mode="single_jd" if job_id else "auto_map",
        rows=rows,
        custom_criteria=(custom_criteria.strip() or None),
    )
    STORE.add_candidate_pool(pool)

    # Phase 1: Parse resumes in background, then set pool to pending_review
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _parse_single_row(row_id: str, filename: str, raw_bytes: bytes):
        """Parse one CV (text extraction + resume matching) — runs inside a thread-pool worker."""
        from .tools.external_intake import extract_text_from_upload
        from .services.claude_resume_matcher import match_resume

        row = next(r for r in pool.rows if r.row_id == row_id)
        try:
            row.status = "parsing"
            STORE.save_candidate_pool(pool)
            resume_text = extract_text_from_upload(filename, raw_bytes)
            if not resume_text.strip():
                row.status = "error"
                row.error_message = f"No text extracted from {filename}"
                STORE.save_candidate_pool(pool)
                return

            row.resume_text = resume_text
            profile, _, _ = match_resume(resume_text)
            row.profile = profile
            row.candidate_name = profile.name
            row.candidate_email = profile.email
            row.candidate_phone = getattr(profile, "phone", None)

            row.status = "parsed"
            STORE.save_candidate_pool(pool)

        except Exception as exc:
            row.status = "error"
            row.error_message = str(exc)[:500]
            STORE.save_candidate_pool(pool)

    def _parse_pool():
        """Run parsing with 3 concurrent workers, then set pool to pending_review."""
        max_workers = min(3, len(file_data))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_parse_single_row, rid, fn, rb): rid
                for rid, fn, rb in file_data
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass  # already handled inside _parse_single_row

        # All rows parsed — move pool to pending_review so HR can review contacts
        pool.status = "pending_review"
        STORE.save_candidate_pool(pool)

    thread = threading.Thread(target=_parse_pool, daemon=True)
    thread.start()

    return {
        "pool_id": pool_id,
        "job_id": pool.job_id,
        "job_title": pool.job_title,
        "mode": pool.mode,
        "total_files": len(files),
        "status": "processing",
    }


# ---------------------------------------------------------------------------
# Bulk intake — contact review & scoring endpoints
# ---------------------------------------------------------------------------

class UpdateContactsRequest(BaseModel):
    contacts: List[Dict[str, Any]]  # [{row_id, candidate_email?, candidate_phone?, candidate_name?}]


@app.patch("/hr/bulk-intake/{pool_id}/contacts")
def update_pool_contacts(pool_id: str, req: UpdateContactsRequest):
    """Batch update contact details for rows in a pool that is pending review."""
    pool = STORE.get_candidate_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail=f"No pool {pool_id}")
    if pool.status not in ("pending_review",):
        raise HTTPException(status_code=400, detail="Pool not in review state")
    for contact in req.contacts:
        row = next((r for r in pool.rows if r.row_id == contact.get("row_id")), None)
        if not row:
            continue
        if "candidate_email" in contact:
            row.candidate_email = contact["candidate_email"]
        if "candidate_phone" in contact:
            row.candidate_phone = contact["candidate_phone"]
        if "candidate_name" in contact:
            row.candidate_name = contact["candidate_name"]
        # Also update the parsed profile if it exists
        if row.profile:
            if "candidate_email" in contact:
                row.profile.email = contact["candidate_email"] or row.profile.email
            if "candidate_phone" in contact:
                row.profile.phone = contact["candidate_phone"]
            if "candidate_name" in contact:
                row.profile.name = contact["candidate_name"] or row.profile.name
    STORE.save_candidate_pool(pool)
    return {"ok": True}


@app.post("/hr/bulk-intake/{pool_id}/start-scoring")
def start_pool_scoring(pool_id: str):
    """Start the AI scoring phase after HR has reviewed contacts."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from uuid import uuid4

    pool = STORE.get_candidate_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail=f"No pool {pool_id}")
    if pool.status != "pending_review":
        raise HTTPException(status_code=400, detail="Pool must be in pending_review state")

    pool.status = "processing"
    STORE.save_candidate_pool(pool)

    # Determine mode
    auto_map = pool.mode == "auto_map"
    job = STORE.get_job(pool.job_id) if pool.job_id else None
    all_jobs = STORE.list_jobs() if auto_map else []

    def _score_single_row(row):
        """Score one already-parsed CV."""
        from .services.claude_cv_screener import screen_cv

        if row.status != "parsed":
            return  # skip error / queued rows

        try:
            row.status = "scoring"
            STORE.save_candidate_pool(pool)

            resume_text = row.resume_text
            profile = row.profile

            if auto_map and all_jobs:
                best_score = -1.0
                best_result = None
                best_job_ref = None
                job_scores = []

                # PERFORMANCE: fan out Claude calls across all open roles in
                # parallel — serial for-loop adds ~30-40s per CV for 8 jobs.
                def _score_job(cand_job):
                    try:
                        r = screen_cv(
                            resume_text, profile, cand_job,
                            custom_criteria=pool.custom_criteria,
                        )
                        return (cand_job, r)
                    except Exception:
                        return None

                with ThreadPoolExecutor(
                    max_workers=min(8, len(all_jobs))
                ) as _ex:
                    results = list(_ex.map(_score_job, all_jobs))

                for _pair in results:
                    if _pair is None:
                        continue
                    candidate_job, result = _pair
                    job_scores.append({
                        "job_id": candidate_job.id,
                        "job_title": candidate_job.title,
                        "location": getattr(candidate_job, "location", ""),
                        "band": getattr(candidate_job, "band", ""),
                        "match_percent": round(result.match_percent, 1),
                        "recommendation": result.recommendation,
                    })
                    if result.match_percent > best_score:
                        best_score = result.match_percent
                        best_result = result
                        best_job_ref = candidate_job

                row.all_job_scores = sorted(
                    job_scores, key=lambda x: x["match_percent"], reverse=True
                )
                if best_result and best_job_ref:
                    row.best_job_id = best_job_ref.id
                    row.best_job_title = best_job_ref.title
                    row.match_percent = best_result.match_percent
                    row.recommendation = best_result.recommendation
                    row.headline = best_result.headline
                    row.summary = best_result.summary
                    row.strengths = list(best_result.strengths)
                    row.concerns = list(best_result.concerns)
                    row.evidence_quotes = list(best_result.evidence_quotes)
                    row.matched_skills = list(best_result.matched_skills)
                    row.missing_skills = list(best_result.missing_skills)
                    row.criteria_assessment = list(best_result.criteria_assessment)
            else:
                result = screen_cv(resume_text, profile, job, custom_criteria=pool.custom_criteria)
                row.match_percent = result.match_percent
                row.recommendation = result.recommendation
                row.headline = result.headline
                row.summary = result.summary
                row.strengths = list(result.strengths)
                row.concerns = list(result.concerns)
                row.evidence_quotes = list(result.evidence_quotes)
                row.matched_skills = list(result.matched_skills)
                row.missing_skills = list(result.missing_skills)
                row.criteria_assessment = list(result.criteria_assessment)

                # ── Cross-JD enrichment: score against other open roles ──
                # PERFORMANCE: fan out the N other-JD Claude calls in parallel
                # instead of iterating sequentially. Each screen_cv call is
                # ~3–6s against the Claude API; for 7 other jobs the serial
                # version adds ~30–40s per CV. Parallelising collapses that
                # to the single-slowest call (~5s) per CV.
                other_jobs = [j for j in STORE.list_jobs() if j.id != job.id]
                if other_jobs:
                    cross_scores = [{
                        "job_id": job.id,
                        "job_title": job.title,
                        "location": getattr(job, "location", ""),
                        "band": getattr(job, "band", ""),
                        "match_percent": round(result.match_percent, 1),
                        "recommendation": result.recommendation,
                    }]

                    def _score_other(other_job):
                        try:
                            r = screen_cv(
                                resume_text, profile, other_job,
                                custom_criteria=pool.custom_criteria,
                            )
                            return {
                                "job_id": other_job.id,
                                "job_title": other_job.title,
                                "location": getattr(other_job, "location", ""),
                                "band": getattr(other_job, "band", ""),
                                "match_percent": round(r.match_percent, 1),
                                "recommendation": r.recommendation,
                            }
                        except Exception:
                            return None

                    # Cap fan-out so we don't overwhelm the Claude API.
                    with ThreadPoolExecutor(
                        max_workers=min(8, len(other_jobs))
                    ) as _ex:
                        for _res in _ex.map(_score_other, other_jobs):
                            if _res is not None:
                                cross_scores.append(_res)

                    row.all_job_scores = sorted(
                        cross_scores, key=lambda x: x["match_percent"], reverse=True
                    )
                    if row.all_job_scores:
                        top = row.all_job_scores[0]
                        row.best_job_id = top["job_id"]
                        row.best_job_title = top["job_title"]

            row.status = "done"
            STORE.save_candidate_pool(pool)

        except Exception as exc:
            row.status = "error"
            row.error_message = str(exc)[:500]
            STORE.save_candidate_pool(pool)

    def _auto_create_shortlist_apps():
        """After scoring completes, create placeholder Applications at
        the SCREENED stage for every system-shortlisted row that doesn't
        already have one, so they show up in the HR Funnel even before
        HR formally routes them to L1/L2.

        Source is stamped as ``bulk_screening`` for provenance.
        The HR ``route`` action later reuses this application.
        """
        from .tools.intake import get_jd

        for row in pool.rows:
            # Only auto-create for system shortlists with no app yet
            if row.status != "done":
                continue
            if row.application_id:
                continue
            if (row.recommendation or "").lower() != "shortlist":
                continue
            if not row.profile:
                continue

            # Resolve target job — auto-map uses best_job_id, single-jd uses pool.job_id
            target_job_id = (
                row.best_job_id if pool.mode == "auto_map" else pool.job_id
            )
            if not target_job_id:
                continue
            try:
                target_jd = get_jd(target_job_id)
            except Exception:
                continue
            if not target_jd:
                continue

            # Ensure profile carries identity from the row (HR-edited fields win)
            if row.candidate_email:
                row.profile.email = row.candidate_email
                row.profile.employee_id = row.candidate_email
            if row.candidate_name:
                row.profile.name = row.candidate_name
            if row.candidate_phone:
                row.profile.phone = row.candidate_phone

            # Upsert the external candidate
            from .models import Application, Candidate, FunnelStage
            cand_id = row.profile.email or f"ext-{row.row_id}"
            cand = STORE.get_candidate(cand_id)
            if cand is None:
                cand = Candidate(id=cand_id, profile=row.profile, kind="external")
                STORE.add_candidate(cand)

            app = Application(
                id=f"app-{uuid4().hex[:8]}",
                candidate_id=cand_id,
                job_id=target_job_id,
                match_percent=row.match_percent or 0.0,
                match_rationale=row.headline or "System shortlisted from bulk screening",
                matched_skills=list(row.matched_skills or []),
                missing_skills=list(row.missing_skills or []),
                stage=FunnelStage.SCREENED,
                candidate_kind="external",
                source="bulk_screening",
                source_pool_id=pool.id,
                source_row_id=row.row_id,
            )
            STORE.add_application(app)
            app.log(
                "agent",
                f"System shortlisted from bulk screening batch {pool.id} "
                f"(match {row.match_percent:.0f}%) — awaiting HR decision on L1/L2",
            )
            row.application_id = app.id

    def _score_pool():
        """Run batch scoring with 3 concurrent workers."""
        scoreable = [r for r in pool.rows if r.status == "parsed"]
        if not scoreable:
            pool.status = "done"
            STORE.save_candidate_pool(pool)
            return
        max_workers = min(3, len(scoreable))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_score_single_row, row): row.row_id
                for row in scoreable
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass

        # Auto-create Apps for shortlisted rows so they show in the funnel
        try:
            _auto_create_shortlist_apps()
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Auto-creating shortlist apps failed for pool %s: %r", pool.id, exc
            )

        all_done = all(r.status in ("done", "error") for r in pool.rows)
        pool.status = "done" if all_done else "failed"
        STORE.save_candidate_pool(pool)

    thread = threading.Thread(target=_score_pool, daemon=True)
    thread.start()

    return {"ok": True, "pool_id": pool_id}


@app.get("/hr/bulk-intake/{pool_id}")
def hr_bulk_intake_status(pool_id: str) -> dict:
    """Poll batch status — live progress + per-row state."""
    pool = STORE.get_candidate_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail=f"No pool {pool_id}")

    return {
        "pool_id": pool.id,
        "job_id": pool.job_id,
        "job_title": pool.job_title,
        "mode": pool.mode,
        "created_by": pool.created_by,
        "created_at": pool.created_at.isoformat(),
        "status": pool.status,
        "total": pool.total,
        "done_count": pool.done_count,
        "progress_pct": round(pool.progress_pct, 1),
        "custom_criteria": pool.custom_criteria,
        "rows": [r.model_dump(mode="json", exclude={"resume_text"}) for r in pool.rows],
    }


@app.get("/hr/bulk-intake/{pool_id}/results")
def hr_bulk_intake_results(pool_id: str) -> dict:
    """Ranked leaderboard — scored candidates sorted by match_percent."""
    pool = STORE.get_candidate_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail=f"No pool {pool_id}")

    ranked = pool.ranked_rows()
    return {
        "pool_id": pool.id,
        "job_id": pool.job_id,
        "job_title": pool.job_title,
        "mode": pool.mode,
        "status": pool.status,
        "total": pool.total,
        "leaderboard": [
            {
                "rank": i + 1,
                "row_id": r.row_id,
                "file_name": r.file_name,
                "candidate_name": r.candidate_name,
                "candidate_email": r.candidate_email,
                "candidate_phone": r.candidate_phone,
                "match_percent": r.match_percent,
                "recommendation": r.recommendation,
                "headline": r.headline,
                "matched_skills": r.matched_skills,
                "missing_skills": r.missing_skills,
                "status": r.status,
                "routed_to": r.routed_to,
                "application_id": r.application_id,
                # Auto-map fields
                "best_job_id": r.best_job_id,
                "best_job_title": r.best_job_title,
                "all_job_scores": r.all_job_scores,
            }
            for i, r in enumerate(ranked)
        ],
    }


@app.get("/hr/bulk-intake/{pool_id}/row/{row_id}")
def hr_bulk_intake_row_detail(pool_id: str, row_id: str) -> dict:
    """Drill-in for one CV — full AI rationale, strengths, evidence."""
    pool = STORE.get_candidate_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail=f"No pool {pool_id}")
    row = next((r for r in pool.rows if r.row_id == row_id), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"No row {row_id}")

    return {
        "pool_id": pool.id,
        "job_id": pool.job_id,
        "job_title": pool.job_title,
        "pool_custom_criteria": pool.custom_criteria,
        **row.model_dump(mode="json"),
    }


@app.get("/hr/bulk-intake/{pool_id}/export")
def hr_bulk_intake_export(pool_id: str) -> JSONResponse:
    """CSV export of the leaderboard for offline sharing."""
    pool = STORE.get_candidate_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail=f"No pool {pool_id}")

    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Rank", "Candidate", "Email", "File", "Match %",
        "Recommendation", "Headline", "Matched Skills", "Missing Skills",
        "Strengths", "Concerns",
    ])
    for i, r in enumerate(pool.ranked_rows()):
        writer.writerow([
            i + 1,
            r.candidate_name or "",
            r.candidate_email or "",
            r.file_name,
            f"{r.match_percent:.0f}" if r.match_percent is not None else "",
            r.recommendation or "",
            r.headline or "",
            "; ".join(r.matched_skills),
            "; ".join(r.missing_skills),
            "; ".join(r.strengths),
            "; ".join(r.concerns),
        ])

    from fastapi.responses import Response

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="bulk-screening-{pool_id}.csv"',
        },
    )


@app.get("/hr/candidate-pools")
def hr_candidate_pools() -> list:
    """List all bulk screening batches for the HR dashboard."""
    pools = STORE.list_candidate_pools()
    return [
        {
            "pool_id": p.id,
            "job_id": p.job_id,
            "job_title": p.job_title,
            "mode": p.mode,
            "created_by": p.created_by,
            "created_at": p.created_at.isoformat(),
            "status": p.status,
            "total": p.total,
            "done_count": p.done_count,
            "progress_pct": round(p.progress_pct, 1),
            "shortlisted": sum(
                1 for r in p.rows if r.recommendation == "shortlist"
            ),
            "candidate_names": [r.candidate_name for r in p.rows if r.candidate_name],
        }
        for p in sorted(pools, key=lambda x: x.created_at.replace(tzinfo=None), reverse=True)
    ]


# ---------------------------------------------------------------------------
# Bulk screening → interview routing
# ---------------------------------------------------------------------------


class RouteRequest(BaseModel):
    round: Literal["L1", "L2"]
    job_id: Optional[str] = None          # override target requisition (auto-map)
    action: Literal["route", "notify"] = "route"  # "notify" = invite candidate to apply


@app.post("/hr/bulk-intake/{pool_id}/row/{row_id}/route")
def route_candidate(pool_id: str, row_id: str, req: RouteRequest):
    """Route a bulk-screened candidate directly to L1 (R1) or L2 (R2),
    or send them a notification inviting them to apply for a requisition.

    Creates a Candidate + Application from the pool row data, sets the
    appropriate stage, and kicks the orchestrator so the candidate gets
    notified with interview slot proposals.
    """
    from uuid import uuid4
    from .models import (
        Application, Candidate, FunnelStage, AgentStatus,
    )
    from .tools.decision import update_application_status
    from .tools.external_intake import apply_external

    pool = STORE.get_candidate_pool(pool_id)
    if not pool:
        raise HTTPException(404, f"Pool {pool_id} not found")

    row = next((r for r in pool.rows if r.row_id == row_id), None)
    if not row:
        raise HTTPException(404, f"Row {row_id} not found in pool {pool_id}")

    if row.status != "done":
        raise HTTPException(400, "Cannot route a row that hasn't been scored yet")

    if row.routed_to:
        raise HTTPException(
            409,
            f"Already routed to {row.routed_to} (application {row.application_id})",
        )

    if not row.profile:
        raise HTTPException(400, "Row has no parsed profile — cannot create application")

    # Resolve the target job — explicit override > auto-map best > pool job
    target_job_id = req.job_id or (row.best_job_id if pool.mode == "auto_map" else pool.job_id)
    if not target_job_id:
        raise HTTPException(400, "No target job resolved for this candidate")

    job = STORE.get_job(target_job_id)
    if not job:
        raise HTTPException(404, f"Job {target_job_id} not found")

    # --- Create Candidate + Application via the existing external flow ---
    profile = row.profile
    # Ensure profile has identity from the row
    if row.candidate_email:
        profile.email = row.candidate_email
        profile.employee_id = row.candidate_email
    if row.candidate_name:
        profile.name = row.candidate_name

    # ── NOTIFY mode: invite candidate to apply themselves ──
    if req.action == "notify":
        from .providers import get_messaging_provider, get_whatsapp_provider
        mp = get_messaging_provider()

        candidate_name = row.candidate_name or "there"
        first_name = candidate_name.split()[0] if candidate_name != "there" else "there"
        apply_url = f"http://localhost:3101/apply?job={target_job_id}&name={row.candidate_name or ''}&email={row.candidate_email or ''}"

        notify_msg = (
            f"Hi {first_name}, we came across your profile and believe you could be a great fit for "
            f"{job.title}{(' in ' + job.location) if getattr(job, 'location', '') else ''} at Axis Bank. "
            f"We'd love for you to explore this opportunity and apply through our Thrive portal: {apply_url}"
        )

        # 1. In-app notification (always)
        mp.notify(
            to=row.candidate_email or "",
            message=notify_msg,
            jd_id=target_job_id,
        )

        # 2. Real email via Graph (or mock) — fire-and-forget with error capture
        email_sent = False
        email_error = None
        if row.candidate_email:
            try:
                email_subject = f"Opportunity at Axis Bank — {job.title}"
                email_body = (
                    f"Dear {first_name},\n\n"
                    f"We came across your profile and believe you could be a great fit for "
                    f"the role of {job.title}"
                    f"{(' in ' + job.location) if getattr(job, 'location', '') else ''} "
                    f"at Axis Bank.\n\n"
                    f"We'd love for you to explore this opportunity and apply through "
                    f"our Thrive portal:\n{apply_url}\n\n"
                    f"Looking forward to hearing from you.\n\n"
                    f"Warm regards,\nAxis Bank Talent Acquisition"
                )
                mp.send_email(
                    to=row.candidate_email,
                    subject=email_subject,
                    body=email_body,
                )
                email_sent = True
                import logging as _logging
                _logging.getLogger(__name__).info(
                    "Notify email sent to %s for job %s", row.candidate_email, job.title
                )
            except Exception as exc:
                email_error = str(exc)
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "Notify email to %s failed: %r", row.candidate_email, exc
                )

        # 3. WhatsApp via Twilio (or mock) — only if phone available
        whatsapp_sent = False
        whatsapp_error = None
        if row.candidate_phone:
            import logging as _logging
            _log = _logging.getLogger(__name__)

            # Normalize to strict E.164 format that Twilio requires:
            # strip spaces/dashes/parens, and prepend +91 for bare 10-digit
            # Indian mobile numbers.
            import re as _re
            raw_phone = row.candidate_phone.strip()
            digits = _re.sub(r"[^\d+]", "", raw_phone)
            if digits.startswith("+"):
                normalized_phone = digits
            elif digits.startswith("91") and len(digits) == 12:
                normalized_phone = "+" + digits
            elif len(digits) == 10 and digits[0] in "6789":
                normalized_phone = "+91" + digits
            else:
                normalized_phone = "+" + digits if not digits.startswith("+") else digits

            _log.info(
                "Notify WhatsApp: raw=%r normalized=%r", raw_phone, normalized_phone
            )

            try:
                wp = get_whatsapp_provider()
                wa_result = wp.send_text_message(
                    to_phone=normalized_phone,
                    text=notify_msg,
                )
                whatsapp_sent = wa_result.success
                if not wa_result.success:
                    whatsapp_error = wa_result.error
                    _log.warning(
                        "Notify WhatsApp to %s failed at provider: %s",
                        normalized_phone, wa_result.error,
                    )
                else:
                    _log.info(
                        "Notify WhatsApp to %s: success (message_id=%s)",
                        normalized_phone, wa_result.message_id,
                    )
            except Exception as exc:
                whatsapp_error = str(exc)
                _log.warning(
                    "Notify WhatsApp to %s raised: %r", normalized_phone, exc
                )

        # Mark row
        row.routed_to = f"notified-{req.round}"
        row.routed_job_id = target_job_id
        row.routed_job_title = job.title
        STORE.save_candidate_pool(pool)

        # Build a human-readable delivery summary
        channels: list[str] = ["in-app"]
        if email_sent:
            channels.append("email")
        if whatsapp_sent:
            channels.append("WhatsApp")
        channel_str = ", ".join(channels)

        return {
            "ok": True,
            "application_id": None,
            "candidate_name": row.candidate_name,
            "routed_to": f"notified-{req.round}",
            "stage": "notified",
            "message": (
                f"Notification sent to {row.candidate_name} via {channel_str} "
                f"inviting them to apply for {job.title}."
            ),
            "delivery": {
                "email_sent": email_sent,
                "email_error": email_error,
                "whatsapp_sent": whatsapp_sent,
                "whatsapp_error": whatsapp_error,
            },
        }

    # ── ROUTE mode: create application directly (or reuse an existing
    # auto-created app for this shortlisted row) ──
    existing_app = (
        STORE.get_application(row.application_id) if row.application_id else None
    )
    if existing_app and existing_app.job_id == target_job_id:
        # Reuse the pre-created SCREENED app from the auto-shortlist step
        app_record = existing_app
    else:
        app_record = apply_external(
            profile,
            target_job_id,
            search_query=None,
            recommendation_source="ai",
        )

    # --- Stamp bulk-screening source so HR funnel shows the provenance ---
    app_record.source = "bulk_screening"
    # Applications are stored by reference in STORE.applications — no explicit save needed

    # --- Override the match data with our bulk-screening scores ---
    app_record.match_percent = row.match_percent or app_record.match_percent
    app_record.matched_skills = row.matched_skills or app_record.matched_skills
    app_record.missing_skills = row.missing_skills or app_record.missing_skills
    app_record.match_rationale = row.headline or app_record.match_rationale

    # --- Set the appropriate stage based on routing target ---
    if req.round == "L1":
        update_application_status(
            app_record.id,
            FunnelStage.SCREENED,
            "Routed to L1 from Bulk CV Screening dashboard — proposing R1 slots",
        )
        app_record.log(
            "hr_partner",
            f"Routed directly to L1 (R1 interview) from bulk screening batch {pool_id}",
        )
    else:
        update_application_status(
            app_record.id,
            FunnelStage.SCREENED,
            "Routed to L2 — skipping R1",
        )
        update_application_status(
            app_record.id,
            FunnelStage.R1_DONE,
            "Routed to L2 from Bulk CV Screening dashboard — HR to approve R2 panel",
        )
        app_record.log(
            "hr_partner",
            f"Routed directly to L2 (R2 panel interview) from bulk screening batch {pool_id} — R1 skipped",
        )

    # --- Mark the row as routed ---
    row.routed_to = req.round
    row.application_id = app_record.id
    row.routed_job_id = target_job_id
    row.routed_job_title = job.title
    STORE.save_candidate_pool(pool)

    # --- Kick the orchestrator ---
    ORCHESTRATOR.trigger(app_record.id)

    return {
        "ok": True,
        "application_id": app_record.id,
        "candidate_name": row.candidate_name,
        "routed_to": req.round,
        "stage": app_record.stage.value,
        "message": (
            f"{row.candidate_name} routed to {req.round} for {job.title}. "
            + ("R1 interview slots being proposed."
               if req.round == "L1"
               else "Awaiting HR panel selection for R2.")
        ),
    }


# ---------------------------------------------------------------------------
# Debug / observability endpoints — provider-backed so they work with mock OR graph
# ---------------------------------------------------------------------------


@app.get("/debug/emails")
def debug_emails(application_id: Optional[str] = None) -> list:
    try:
        emails = get_messaging_provider().list_emails(application_id=application_id)
    except NotImplementedError:
        return []
    return [
        {
            "id": m.id,
            "thread_id": m.thread_id,
            "to": m.to,
            "from": m.from_addr,
            "subject": m.subject,
            "body": m.body,
            "at": m.at.isoformat(),
            "direction": m.direction,
            "application_id": m.application_id,
        }
        for m in emails
    ]


@app.get("/debug/notifications")
def debug_notifications() -> list:
    try:
        notes = get_messaging_provider().list_notifications()
    except NotImplementedError:
        return []
    return [
        {
            "id": n.id,
            "to": n.to,
            "message": n.message,
            "at": n.at.isoformat(),
            "application_id": n.application_id,
            "jd_id": n.jd_id,
        }
        for n in notes
    ]


@app.get("/debug/calendar")
def debug_calendar(application_id: Optional[str] = None) -> list:
    try:
        events = get_calendar_provider().list_events(application_id=application_id)
    except NotImplementedError:
        return []
    return [
        {
            "id": e.id,
            "subject": e.subject,
            "organiser_id": e.organiser_id,
            "attendees": e.attendees,
            "start": e.start.isoformat(),
            "end": e.end.isoformat(),
            "teams_join_url": e.teams_join_url,
            "cancelled": e.cancelled,
            "application_id": e.application_id,
            "body": getattr(e, "body", ""),
        }
        for e in events
    ]


# ---------------------------------------------------------------------------
# Demo reset + pre-seed
# ---------------------------------------------------------------------------


@app.post("/demo/reset")
def demo_reset() -> dict:
    seed_all()
    reset_providers()
    reset_customisations()
    return {
        "status": "reseeded",
        "jobs": len(STORE.jobs),
        "candidates": len(STORE.candidates),
    }


@app.post("/demo/seed-flow")
def demo_seed_flow() -> dict:
    """Pre-seed a spread of applications across every funnel stage so the
    HR kanban, employee status, and panel dashboard all have rich demo data.

    Drives the *orchestrator* — not manual advance calls — so the resulting
    state is indistinguishable from a live run. Most seeded applications
    auto-confirm the first proposed R1 slot so the demo lands them in the
    "interesting" downstream stages; one is left at WAITING_CANDIDATE so the
    employee can experience the slot-picker UX themselves.
    """
    import time as _time
    import threading as _threading

    # Start clean.
    seed_all()
    reset_providers()
    reset_customisations()

    created: List[str] = []

    def _settle(app_id: str, timeout_s: float = 30.0) -> None:
        # Real Microsoft Graph calls (Outlook send + Teams meeting create) can
        # each take 1-3 seconds, and a full R1/R2 cycle stacks several. Give
        # the orchestrator thread up to 30s to settle before we move on.
        deadline = _time.time() + timeout_s
        while _time.time() < deadline:
            t = ORCHESTRATOR._threads.get(app_id)  # type: ignore[attr-defined]
            if t is None or not t.is_alive():
                return
            t.join(timeout=min(1.0, deadline - _time.time()))

    def _drive_through_r1(app_id: str) -> None:
        """Confirm slot, then start the R1 interview, settling between gates."""
        _settle(app_id)
        application = STORE.get_application(app_id)
        if application and application.agent_status.value == "waiting_candidate" and application.proposed_r1_slots:
            ORCHESTRATOR.on_candidate_confirm_slot(app_id, "R1", 0)
            _settle(app_id)
        application = STORE.get_application(app_id)
        if application and application.stage == FunnelStage.R1_SCHEDULED:
            ORCHESTRATOR.on_candidate_start_r1(app_id)
            _settle(app_id)

    # 1) Priya — strong, auto-confirms slot, will land at R1_DONE / WAITING_HR.
    a = ORCHESTRATOR.start_application("cand-004", "job-590321")
    _drive_through_r1(a.id)
    created.append(a.id)

    # 2) Rohan — strong, drives all the way through R2 panel feedback so the
    #    application is parked at R2_SCHEDULED / WAITING_HR. This is the seat
    #    where the Business Partner sees the new "Action needed — final R2 decision"
    #    block (panel votes summary + Run AI review + Make offer / Reject).
    b = ORCHESTRATOR.start_application("cand-001", "job-590321")
    _drive_through_r1(b.id)

    # HR approves R2 panel composition.
    application = STORE.get_application(b.id)
    if application is not None and application.stage == FunnelStage.R1_DONE:
        application.selected_r2_panel_id = "panel-bdm-central"
        try:
            from .tools.checklists import tick_checklist_item as _tick
            _tick(b.id, "R2", "pre", "pre-r2-2", actor="hr_partner",
                  note="[seed] Panel approved")
        except Exception:
            pass
        ORCHESTRATOR.on_hr_tick(b.id)
        _settle(b.id)

    # Candidate picks R2 slot 0.
    application = STORE.get_application(b.id)
    if (application is not None
            and application.agent_status.value == "waiting_candidate"
            and application.proposed_r2_slots):
        ORCHESTRATOR.on_candidate_confirm_slot(b.id, "R2", 0)
        _settle(b.id)

    # All panellists submit positive votes — orchestrator parks at
    # R2_SCHEDULED / WAITING_HR for the Business Partner's final decision.
    # IMPORTANT: we must use the *actual* panellist user_ids from the
    # selected panel object — _do_finalise checks completeness against
    # those exact IDs. Hardcoding fake emails leaves the app stuck at
    # WAITING_PANEL because the real panellists haven't voted.
    application = STORE.get_application(b.id)
    if application is not None and application.stage == FunnelStage.R2_SCHEDULED:
        try:
            from .tools.interview import submit_panel_feedback as _submit
            r2_iv = next((iv for iv in application.interviews if iv.round == "R2"), None)
            selected_panel = STORE.get_panel("panel-bdm-central")
            if r2_iv is not None and selected_panel is not None:
                _votes = ["strong_hire", "hire", "hire", "hire", "strong_hire"]
                _scores = [92.0, 88.0, 86.0, 90.0, 91.0]
                for _idx, _member in enumerate(selected_panel.members):
                    _submit(
                        interview_id=r2_iv.id,
                        panellist_id=_member.user_id,
                        panellist_name=_member.name,
                        score=_scores[_idx % len(_scores)],
                        strengths="Strong domain depth on Burgundy upgrade + CASA "
                                  "push. Calm under pressure, clear regulatory "
                                  "instincts on KYC compliance.",
                        concerns="Could delegate analytics work more aggressively.",
                        recommendation=_votes[_idx % len(_votes)],
                    )
                ORCHESTRATOR.on_panel_feedback(b.id)
                _settle(b.id)
        except Exception as _seed_exc:
            import traceback as _tb
            print(f"[seed] R2 panel submit failed for {b.id}: {_seed_exc}")
            _tb.print_exc()

    created.append(b.id)

    # 3) Ananya — different JD, auto-confirms.
    c = ORCHESTRATOR.start_application("cand-002", "job-592808")
    _drive_through_r1(c.id)
    created.append(c.id)

    # 4) Karthik — weak match, auto-rejected at intake (no slot confirmation needed).
    d = ORCHESTRATOR.start_application("cand-003", "job-590321")
    created.append(d.id)

    # 5) Vikram — very weak match, auto-rejected at intake.
    e = ORCHESTRATOR.start_application("cand-005", "job-595396")
    created.append(e.id)

    return {"status": "ok", "applications": created}


@app.post("/demo/wipe-plus-offer")
def demo_wipe_plus_offer() -> dict:
    """Wipe all in-memory state (same as ``/demo/reset``) and additionally
    seed a SINGLE application parked at FunnelStage.OFFER — i.e. the
    final offer has been rolled out and we are waiting for the candidate
    to click Accept / Decline.

    Purpose: lets the user demo the post-offer engagement journey
    (onboarding chat, WhatsApp warm-keep touchpoints, pre-joining
    checklist) without first having to drive a fresh candidate through
    screening → R1 → R2 → HR decision → offer rollout.

    The seeded candidate is intentionally DIFFERENT from cand-001
    (Rohan Verma) because Rohan is the canonical demo candidate for the
    screening → R1 path and using the same person in both stages looks
    inconsistent. We use cand-004 (Priya Nair) — the strong-fit BDM
    reference candidate — on job-590321 (Sr BM Flagship, Pune West).
    """
    import time as _time

    # --- Phase 1: wipe exactly like /demo/reset ---
    seed_all()
    reset_providers()
    reset_customisations()

    def _settle(app_id: str, timeout_s: float = 120.0) -> None:
        deadline = _time.time() + timeout_s
        while _time.time() < deadline:
            t = ORCHESTRATOR._threads.get(app_id)  # type: ignore[attr-defined]
            if t is None or not t.is_alive():
                return
            t.join(timeout=min(1.0, deadline - _time.time()))

    def _wait_for_stage(app_id: str, target, timeout_s: float = 120.0) -> bool:
        deadline = _time.time() + timeout_s
        while _time.time() < deadline:
            _settle(app_id, timeout_s=1.0)
            ap = STORE.get_application(app_id)
            if ap is None:
                return False
            if isinstance(target, (list, tuple, set)):
                if ap.stage in target:
                    return True
            else:
                if ap.stage == target:
                    return True
            _time.sleep(0.5)
        return False

    # --- Phase 2: drive one application to OFFER stage ---
    seed_candidate_id = "cand-004"  # Priya Nair — NOT Rohan (cand-001)
    seed_job_id = "job-590321"       # RB-LS: BDM Corporate Salary, Bhopal (Priya matches strongly here — same as seed-flow)
    app = ORCHESTRATOR.start_application(seed_candidate_id, seed_job_id)
    _settle(app.id)

    # HR advances past the AI screening review gate (2026-04-07 human-in-the-loop
    # rule parks every new application at APPLIED/WAITING_HR until HR decides).
    a = STORE.get_application(app.id)
    if a and a.stage == FunnelStage.APPLIED and a.agent_status == AgentStatus.WAITING_HR:
        a.hr_screening_decision = "advance"
        a.log("hr_partner", "[seed] Screening advanced for offer-ready demo")
        STORE.save_application(a)
        ORCHESTRATOR.trigger(app.id)
        _settle(app.id)

    # Confirm R1 slot + start R1
    a = STORE.get_application(app.id)
    if a and a.agent_status.value == "waiting_candidate" and a.proposed_r1_slots:
        ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R1", 0)
        _settle(app.id)
    a = STORE.get_application(app.id)
    if a and a.stage == FunnelStage.R1_SCHEDULED:
        ORCHESTRATOR.on_candidate_start_r1(app.id)
        _settle(app.id)

    # Inject a canned R1 transcript so _do_run_r1 can score and advance
    # to R1_DONE without needing a live Virtual Interviewer session.
    a = STORE.get_application(app.id)
    if a and a.stage == FunnelStage.R1_SCHEDULED:
        try:
            from datetime import datetime as _dt
            from .models import TranscriptSegment as _TS
            r1_stub = next((iv for iv in a.interviews if iv.round == "R1"), None)
            if r1_stub is not None and not r1_stub.transcript:
                _now = _dt.utcnow()
                _canned = [
                    ("Walk me through how you would grow CASA and HNI relationships "
                     "in a flagship branch in Pune West.",
                     "I would anchor growth on three pillars: first, segmenting the "
                     "existing book by wallet-share potential and running a 60-day "
                     "Burgundy upgrade sprint; second, activating the corporate "
                     "salary tie-ups already in the catchment for family accounts; "
                     "third, tightening KYC-compliant onboarding turnaround to "
                     "under 30 minutes so referrals convert before the weekend."),
                    ("Tell me about a difficult regulatory or compliance call you "
                     "made at your previous branch.",
                     "When RBI tightened beneficial-ownership norms in 2024 we had "
                     "14 HNI files with gaps. I paused disbursement on two and "
                     "re-ran KYC walk-throughs with the clients personally. Lost "
                     "one relationship short-term but the audit closed clean and "
                     "the same client came back six months later."),
                    ("How do you coach a relationship manager whose CASA numbers "
                     "are slipping?",
                     "I pull the activity log first — calls made, meetings booked, "
                     "mandates offered — before touching numbers. Usually the "
                     "pipeline is leaking at the discovery step, not at close. "
                     "We co-run three live client meetings, I demo the mandate "
                     "framing, and then set a 2-week activity-first target with "
                     "a daily 10-minute standup."),
                ]
                segs = []
                for q, ans in _canned:
                    segs.append(_TS(speaker="interviewer", text=q, at=_now))
                    segs.append(_TS(speaker="candidate", text=ans, at=_now))
                r1_stub.transcript = segs
                r1_stub.virtual_interview_state = "completed"
                a.log("agent", "[seed] Canned R1 transcript injected for offer-ready demo")
                STORE.save_application(a)
                ORCHESTRATOR.trigger(app.id)
                _wait_for_stage(app.id, FunnelStage.R1_DONE, timeout_s=120.0)
        except Exception as _inject_exc:
            import traceback as _tb
            print(f"[seed-offer] transcript inject failed: {_inject_exc}")
            _tb.print_exc()

    # HR approves R2 panel
    a = STORE.get_application(app.id)
    if a and a.stage == FunnelStage.R1_DONE:
        a.selected_r2_panel_id = "panel-bdm-central"
        try:
            from .tools.checklists import tick_checklist_item as _tick
            _tick(app.id, "R2", "pre", "pre-r2-2", actor="hr_partner",
                  note="[seed] Panel approved for offer-ready demo")
        except Exception:
            pass
        ORCHESTRATOR.on_hr_tick(app.id)
        _settle(app.id)

    # Candidate confirms R2 slot 0
    a = STORE.get_application(app.id)
    if (a and a.agent_status.value == "waiting_candidate"
            and a.proposed_r2_slots):
        ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R2", 0)
        _settle(app.id)

    # All panellists submit strong positive feedback
    a = STORE.get_application(app.id)
    if a and a.stage == FunnelStage.R2_SCHEDULED:
        try:
            from .tools.interview import submit_panel_feedback as _submit
            r2_iv = next((iv for iv in a.interviews if iv.round == "R2"), None)
            panel = STORE.get_panel("panel-bdm-central")
            if r2_iv is not None and panel is not None:
                _votes = ["strong_hire", "hire", "strong_hire"]
                _scores = [92.0, 89.0, 93.0]
                for _idx, _m in enumerate(panel.members):
                    _submit(
                        interview_id=r2_iv.id,
                        panellist_id=_m.user_id,
                        panellist_name=_m.name,
                        score=_scores[_idx % len(_scores)],
                        strengths="Deep wealth / HNI relationships in west India, "
                                  "clean regulatory record, calm presence.",
                        concerns="Minor — could stretch on CASA analytics depth.",
                        recommendation=_votes[_idx % len(_votes)],
                    )
                ORCHESTRATOR.on_panel_feedback(app.id)
                _settle(app.id)
        except Exception as _seed_exc:
            import traceback as _tb
            print(f"[seed-offer] panel submit failed: {_seed_exc}")
            _tb.print_exc()

    # HR takes the final R2 decision → "offer" (moves to OFFER_NEGOTIATION)
    a = STORE.get_application(app.id)
    if a and a.stage == FunnelStage.R2_SCHEDULED:
        try:
            ORCHESTRATOR.on_hr_r2_decision(app.id, "offer")
            _settle(app.id)
        except Exception as _hr_exc:
            print(f"[seed-offer] hr_r2_decision failed: {_hr_exc}")

    # Offer team rolls out final offer → moves to OFFER (waiting for candidate)
    a = STORE.get_application(app.id)
    if a and a.stage == FunnelStage.OFFER_NEGOTIATION:
        try:
            ORCHESTRATOR.on_offer_team_rollout(
                app.id,
                final_ctc_lpa=42.0,
                notes="[seed] CTC negotiated at ₹42 LPA fixed + 15% variable + joining bonus",
                rolled_out_by="offer_team@axisbank.test",
            )
            _settle(app.id)
        except Exception as _rollout_exc:
            print(f"[seed-offer] rollout failed: {_rollout_exc}")

    final = STORE.get_application(app.id)
    return {
        "status": "ok",
        "application_id": app.id,
        "stage": final.stage.value if final else None,
        "agent_status": final.agent_status.value if final else None,
        "candidate": seed_candidate_id,
        "job": seed_job_id,
        "note": "One application parked at OFFER — waiting for candidate to accept/decline.",
    }
