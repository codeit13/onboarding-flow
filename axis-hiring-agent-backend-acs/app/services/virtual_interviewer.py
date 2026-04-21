"""Virtual Interviewer — thin proxy to the team's pre-built FastAPI service.

The Axis hiring-agent backend used to ship its own in-process mock for
the candidate-facing R1 AI interview. That mock has been replaced with
a proxy to the team's production Virtual Interviewer service (the one
shipped in ``virtual-interviewer/``), which lives on its own FastAPI
sidecar at ``$VIRTUAL_INTERVIEWER_URL`` (default ``http://127.0.0.1:8000``).

We do **not** rewrite or fork the team's logic. We simply forward:

    POST /api/interview/start              ← session create + face check
    GET  /api/interview/{id}               ← full session JSON (questions, answers)
    GET  /api/interview/{id}/question      ← current question
    POST /api/interview/{id}/answer        ← submit current answer + advance
    POST /api/interview/{id}/evaluate      ← end interview, generate evaluation

The wrapper exposes the same public surface our backend (and frontend)
already calls — ``start_virtual_interview``, ``get_virtual_interview``,
``submit_virtual_interview_answer``, ``finalise_virtual_interview`` — so
the rest of the codebase needs no changes apart from passing the
candidate's webcam photo through.

Threading
---------
There are no background threads here. Every state transition is driven
by an explicit HTTP call from the candidate page. State (questions,
answers, evaluation) lives inside the team's sidecar — we keep only the
sidecar's ``interview_id`` on ``InterviewRecord.virtual_interview_session_id``.

When the candidate submits their final answer the sidecar marks the
session ``completed`` (its `current_question_index` >= len(questions)).
At that point we fetch the full session, fold the captured (Q,A) pairs
into ``InterviewRecord.transcript`` as TranscriptSegment objects, and
re-trigger the orchestrator so its R1 scoring loop wakes up and runs
against the *real* candidate answers — no canned fallback transcripts,
no auto-rejection.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from ..models import (
    Application,
    InterviewRecord,
    Job,
    Profile,
    TranscriptSegment,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sidecar config
# ---------------------------------------------------------------------------

VIRTUAL_INTERVIEWER_URL = os.environ.get(
    "VIRTUAL_INTERVIEWER_URL", "http://127.0.0.1:8000"
).rstrip("/")
_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0)


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT)


# ---------------------------------------------------------------------------
# Public dataclass — what main.py + the frontend already consume
# ---------------------------------------------------------------------------


@dataclass
class VirtualInterviewSession:
    """Adapter between the sidecar's session JSON and the shape our
    frontend (``app/thrive/virtual-interview/[appId]/page.tsx``) expects.
    """

    session_id: str
    application_id: str
    candidate_name: str
    questions: List[str]
    answers: List[Dict[str, Any]] = field(default_factory=list)
    current_index: int = 0
    state: str = "in_progress"  # in_progress | completed
    started_at: Optional[str] = None
    ended_at: Optional[str] = None

    @classmethod
    def from_sidecar_json(
        cls, *, application_id: str, session_id: str, payload: Dict[str, Any]
    ) -> "VirtualInterviewSession":
        questions_raw = payload.get("questions") or []
        questions = [q.get("question", "") for q in questions_raw]
        answers: List[Dict[str, Any]] = []
        for q in questions_raw:
            ans = q.get("answer")
            if ans:
                answers.append(
                    {
                        "question": q.get("question", ""),
                        "answer": ans,
                        "at": payload.get("end_time") or payload.get("start_time") or "",
                    }
                )
        current_index = int(payload.get("current_question_index", 0))
        if current_index >= len(questions) and questions:
            state = "completed"
        else:
            state = "in_progress"
        return cls(
            session_id=session_id,
            application_id=application_id,
            candidate_name=payload.get("name") or "",
            questions=questions,
            answers=answers,
            current_index=current_index,
            state=state,
            started_at=payload.get("start_time"),
            ended_at=payload.get("end_time"),
        )

    def to_public_dict(self) -> Dict[str, Any]:
        total = len(self.questions)
        answered = len(self.answers)
        current_question: Optional[str] = None
        if self.state == "in_progress" and 0 <= self.current_index < total:
            current_question = self.questions[self.current_index]
        return {
            "session_id": self.session_id,
            "application_id": self.application_id,
            "candidate_name": self.candidate_name,
            "state": self.state,
            "questions_total": total,
            "questions_answered": answered,
            "current_index": self.current_index,
            "current_question": current_question,
            "transcript": self.answers,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


# ---------------------------------------------------------------------------
# Test helper — kept for backwards compatibility with the in-memory mock
# ---------------------------------------------------------------------------


def reset_virtual_interview_state() -> None:
    """Test helper retained from the old in-memory mock.

    The sidecar persists sessions to disk (``interview_data/*.json``) so
    there is nothing for the wrapper to clear. Tests that need a clean
    slate should restart the sidecar or stub HTTP calls.
    """
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_jd_text(job: Job) -> str:
    """Render a Job into the plain-text JD the sidecar expects on /start.

    When the job's title matches an entry in the official Axis Bank
    JOB_ROLES taxonomy we enrich the JD with the role's canonical
    responsibilities, skill categories and works-with stakeholders so
    the sidecar's question generator gets the same context HR sees on
    Thrive — questions then map cleanly back onto Axis-speak.
    """
    from . import taxonomy

    parts: List[str] = [f"{job.title} — {job.location}"]
    if job.function:
        parts.append(f"Function: {job.function}")
    if job.band:
        parts.append(f"Band: {job.band}")
    if job.required_skills:
        parts.append("Required skills: " + ", ".join(job.required_skills))
    if job.nice_to_have_skills:
        parts.append("Nice to have: " + ", ".join(job.nice_to_have_skills))
    if job.description:
        parts.append("")
        parts.append(job.description)

    role = taxonomy.find_role(job.title)
    if role:
        if role.skill_categories:
            parts.append("")
            parts.append(
                "Axis skill categories: " + ", ".join(role.skill_categories)
            )
        if role.responsibilities:
            parts.append("")
            parts.append("Key responsibilities (Axis taxonomy):")
            for r in role.responsibilities[:8]:
                parts.append(f"- {r}")
        if role.works_with_internal:
            parts.append(
                "Internal stakeholders: " + ", ".join(role.works_with_internal)
            )
        if role.works_with_external:
            parts.append(
                "External stakeholders: " + ", ".join(role.works_with_external)
            )

    return "\n".join(parts).strip()


def _build_resume_text(profile: Profile) -> str:
    """Render a Profile into resume-like text the sidecar can use as context."""
    lines = [
        f"Name: {profile.name}",
        f"Email: {profile.email}",
        f"Current role: {profile.current_role}",
        f"Location: {profile.current_location}",
        f"Tenure: {profile.tenure_years} years",
    ]
    if profile.education:
        lines.append(f"Education: {profile.education}")
    if profile.skills:
        lines.append("Skills: " + ", ".join(profile.skills))
    if profile.kras:
        lines.append("Recent KRAs:")
        for k in profile.kras:
            lines.append(f"- {k}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API — same signatures as the previous in-process mock
# ---------------------------------------------------------------------------


def start_virtual_interview(
    *,
    application: Application,
    job: Job,
    profile: Profile,
    interview: InterviewRecord,
    photo_data_url: str,
    language: str = "en",
) -> VirtualInterviewSession:
    """Spin up a new interview session on the sidecar.

    The sidecar's ``/api/interview/start`` endpoint is multipart and
    *requires* a base64 ``photo`` field — its face-detection gate runs
    inline before the session is created. The candidate page captures
    a webcam frame and passes it through as ``photo_data_url``.

    ``language`` is the candidate-selected interview language ("en" or
    "hi"). The sidecar uses it to (a) generate questions in that
    language, (b) pick a Hindi-friendly TTS voice, and (c) localise
    the welcome script.
    """
    if not photo_data_url or not photo_data_url.startswith("data:"):
        raise ValueError(
            "A valid base64 photo (data: URL) is required by the AI Interview "
            "Agent to verify the candidate's identity before starting."
        )

    lang = (language or "en").strip().lower()
    if lang not in ("en", "hi"):
        lang = "en"

    jd_text = _build_jd_text(job)
    resume_text = _build_resume_text(profile)

    # The team's service accepts resume_file as an UploadFile — we send it
    # as an in-memory text file under that field name.
    files = {
        "resume_file": (
            f"{profile.name.replace(' ', '_')}_resume.txt",
            resume_text.encode("utf-8"),
            "text/plain",
        ),
    }
    data = {
        "name": profile.name,
        "email": profile.email or "",
        "photo": photo_data_url,
        "jd_text": jd_text,
        "question_count": "3",
        "language": lang,
    }

    log.info(
        "Forwarding /api/interview/start to sidecar at %s for application %s",
        VIRTUAL_INTERVIEWER_URL,
        application.id,
    )
    with _client() as client:
        try:
            r = client.post(
                f"{VIRTUAL_INTERVIEWER_URL}/api/interview/start",
                data=data,
                files=files,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"AI Interview Agent unreachable at {VIRTUAL_INTERVIEWER_URL}: {exc}"
            ) from exc

    if r.status_code != 200:
        raise RuntimeError(
            f"AI Interview Agent /start failed: {r.status_code} {r.text[:300]}"
        )
    body = r.json()
    interview_id = body.get("interview_id")
    if not interview_id:
        raise RuntimeError(f"AI Interview Agent /start returned no interview_id: {body}")

    interview.virtual_interview_session_id = interview_id
    interview.virtual_interview_state = "in_progress"
    application.log(
        "agent",
        f"AI Interview Agent created session {interview_id} for {profile.name}",
    )

    # Hydrate from the full session so we have the questions list
    session = _fetch_session(application_id=application.id, interview_id=interview_id)
    return session


def _fetch_session(
    *, application_id: str, interview_id: str
) -> VirtualInterviewSession:
    with _client() as client:
        r = client.get(f"{VIRTUAL_INTERVIEWER_URL}/api/interview/{interview_id}")
    if r.status_code != 200:
        raise RuntimeError(
            f"AI Interview Agent /{interview_id} fetch failed: {r.status_code} {r.text[:300]}"
        )
    body = r.json()
    payload = body.get("interview") or body
    return VirtualInterviewSession.from_sidecar_json(
        application_id=application_id,
        session_id=interview_id,
        payload=payload,
    )


def get_virtual_interview(
    *, interview: InterviewRecord, application_id: Optional[str] = None
) -> Optional[VirtualInterviewSession]:
    if not interview.virtual_interview_session_id:
        return None
    iid = interview.virtual_interview_session_id
    try:
        return _fetch_session(
            application_id=application_id or "", interview_id=iid
        )
    except RuntimeError as exc:
        log.warning("Could not fetch sidecar session %s: %s", iid, exc)
        return None


def submit_virtual_interview_answer(
    *,
    application: Application,
    interview: InterviewRecord,
    answer_text: str,
) -> VirtualInterviewSession:
    """Forward the candidate's answer to the sidecar and refresh state.

    On the final answer the sidecar's ``/answer`` endpoint marks the
    session complete; we then fold the transcript into the InterviewRecord
    and trigger the orchestrator so the R1 scoring loop wakes up.
    """
    if not interview.virtual_interview_session_id:
        raise LookupError("No active virtual interview session for this R1")
    answer_text = (answer_text or "").strip()
    if not answer_text:
        raise ValueError("Answer cannot be empty")

    iid = interview.virtual_interview_session_id
    with _client() as client:
        r = client.post(
            f"{VIRTUAL_INTERVIEWER_URL}/api/interview/{iid}/answer",
            json={"answer": answer_text},
        )
    if r.status_code != 200:
        raise RuntimeError(
            f"AI Interview Agent /answer failed: {r.status_code} {r.text[:300]}"
        )

    session = _fetch_session(application_id=application.id, interview_id=iid)
    interview.virtual_interview_state = session.state

    if session.state == "completed":
        _fold_transcript_into_interview(
            application=application, interview=interview, session=session
        )

    return session


def finalise_virtual_interview(
    *, application: Application, interview: InterviewRecord
) -> Optional[Dict[str, Any]]:
    """Force-end the session early or confirm it ended.

    Idempotent. Used when the candidate clicks "End interview" before
    answering every question, or when the frontend wants to confirm the
    transcript landed.
    """
    if not interview.virtual_interview_session_id:
        return None
    iid = interview.virtual_interview_session_id

    session = _fetch_session(application_id=application.id, interview_id=iid)
    if session.state != "completed":
        # Mark complete locally and fold whatever was captured. The sidecar's
        # /evaluate would also work but it requires every question answered;
        # for early-end we just respect what we have.
        session.state = "completed"
    _fold_transcript_into_interview(
        application=application, interview=interview, session=session
    )
    interview.virtual_interview_state = "completed"
    return session.to_public_dict()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _fold_transcript_into_interview(
    *,
    application: Application,
    interview: InterviewRecord,
    session: VirtualInterviewSession,
) -> None:
    """Translate the captured (Q,A) pairs into TranscriptSegment objects so
    the existing R1 scoring + report pipeline runs unchanged, then re-trigger
    the orchestrator loop so it picks the transcript up immediately.
    """
    if interview.transcript:
        # Already folded — keep idempotent
        return

    segments: List[TranscriptSegment] = []
    now = datetime.utcnow()
    for entry in session.answers:
        segments.append(
            TranscriptSegment(
                speaker="interviewer", text=entry.get("question", ""), at=now
            )
        )
        segments.append(
            TranscriptSegment(
                speaker="candidate", text=entry.get("answer", ""), at=now
            )
        )
    interview.transcript = segments
    application.log(
        "agent",
        f"AI Interview Agent finished — captured {len(session.answers)} "
        f"answers ({len(segments)} transcript segments)",
    )

    try:
        from ..orchestrator import ORCHESTRATOR  # local import to avoid cycle
        ORCHESTRATOR.trigger(application.id)
    except Exception as exc:  # pragma: no cover — defensive
        application.log(
            "agent",
            f"Could not re-trigger orchestrator after folding R1 transcript: {exc}",
            level="warn",
        )


__all__ = [
    "VirtualInterviewSession",
    "start_virtual_interview",
    "get_virtual_interview",
    "submit_virtual_interview_answer",
    "finalise_virtual_interview",
    "reset_virtual_interview_state",
    "VIRTUAL_INTERVIEWER_URL",
]
