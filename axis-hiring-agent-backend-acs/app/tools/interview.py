"""Interview tools — Round 1 (AI) + Round 2 (panel) glue."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional
from uuid import uuid4

from ..models import InterviewRecord, PanelFeedback, TranscriptSegment
from ..store import STORE


# ---------------------------------------------------------------------------
# Round 1 — Virtual Interview Agent
# ---------------------------------------------------------------------------


def run_virtual_interview(
    application_id: str,
    teams_meeting_id: str,
    scripted_transcript: List[TranscriptSegment],
    interview_id: Optional[str] = None,
) -> InterviewRecord:
    """Hand off to the existing Virtual Interview Agent.

    For the POC we accept a scripted transcript so tests are deterministic and
    the demo can replay a canned interview. The real implementation will stream
    the live conversation into the transcript list.
    """
    app = STORE.get_application(application_id)
    if not app:
        raise LookupError(f"No application for id={application_id!r}")

    # If an R1 stub already exists (scheduled but no transcript yet), populate it.
    stub = next((i for i in app.interviews if i.round == "R1" and i.id == (interview_id or i.id) and not i.transcript), None)
    if stub is None:
        stub = next((i for i in app.interviews if i.round == "R1" and not i.transcript), None)

    if stub is None:
        stub = InterviewRecord(
            id=interview_id or f"int-{uuid4().hex[:8]}",
            application_id=application_id,
            round="R1",
            teams_meeting_id=teams_meeting_id,
            transcript=[],
        )
        app.interviews.append(stub)

    stub.transcript = list(scripted_transcript)
    app.log("agent", f"Virtual interview R1 completed ({len(scripted_transcript)} turns)")
    return stub


# ---------------------------------------------------------------------------
# Round 2 — panel feedback collection
# ---------------------------------------------------------------------------


def submit_panel_feedback(
    interview_id: str,
    panellist_id: str,
    score: float,
    strengths: str,
    concerns: str,
    recommendation: Literal["strong_hire", "hire", "no_hire"],
    panellist_name: str = "",
) -> PanelFeedback:
    """Persist panel feedback onto the InterviewRecord.

    Looks up the R2 interview across all applications by interview_id, so the
    caller (API handler) doesn't need to know which application owns it.
    """
    target: Optional[InterviewRecord] = None
    for app in STORE.list_applications():
        for iv in app.interviews:
            if iv.id == interview_id and iv.round == "R2":
                target = iv
                break
        if target:
            break
    if target is None:
        raise LookupError(f"No R2 interview with id={interview_id!r}")

    # Overwrite any prior submission from this panellist (idempotent).
    target.panel_feedback = [f for f in target.panel_feedback if f.panellist_id != panellist_id]
    fb = PanelFeedback(
        panellist_id=panellist_id,
        panellist_name=panellist_name,
        score=score,
        strengths=strengths,
        concerns=concerns,
        recommendation=recommendation,
        submitted_at=datetime.utcnow(),
    )
    target.panel_feedback.append(fb)
    return fb


def collect_panel_feedback(interview_id: str, expected_panellists: List[str]) -> Dict:
    """Return all feedback so far + which panellists are still pending."""
    for app in STORE.list_applications():
        for iv in app.interviews:
            if iv.id == interview_id and iv.round == "R2":
                submitted_ids = {f.panellist_id for f in iv.panel_feedback}
                return {
                    "submitted": {f.panellist_id: f.model_dump() for f in iv.panel_feedback},
                    "pending": [p for p in expected_panellists if p not in submitted_ids],
                    "complete": all(p in submitted_ids for p in expected_panellists),
                }
    return {"submitted": {}, "pending": list(expected_panellists), "complete": False}


def _reset_interview() -> None:
    """Test helper — no module-level state any more since feedback lives
    on the InterviewRecord itself, but keep the symbol for backward compat."""
    return None
