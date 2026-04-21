"""Final decision consolidation + application status updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal

from ..models import FunnelStage
from ..store import STORE


@dataclass
class Recommendation:
    verdict: Literal["offer", "reject", "hold"]
    r1_score: float
    r2_avg_score: float
    rationale: str


def consolidate_recommendation(application_id: str, panel_feedback: Dict) -> Recommendation:
    """Merge R1 transcript score + R2 panel feedback into a single verdict.

    POC heuristic: strong hire majority -> offer; any two "no_hire" -> reject;
    otherwise hold for HR. Real impl will use Claude to reason over the full
    transcript + feedback corpus.
    """
    app = STORE.get_application(application_id)
    if not app:
        raise LookupError(f"No application for id={application_id!r}")

    # Find the R1 interview score.
    r1_score = 0.0
    for iv in app.interviews:
        if iv.round == "R1" and iv.score is not None:
            r1_score = iv.score
            break

    submitted = panel_feedback.get("submitted", {})
    if not submitted:
        return Recommendation(
            verdict="hold",
            r1_score=r1_score,
            r2_avg_score=0.0,
            rationale="No panel feedback yet",
        )

    scores = [f["score"] for f in submitted.values()]
    r2_avg = sum(scores) / len(scores)

    recs = [f["recommendation"] for f in submitted.values()]
    strong_hires = sum(1 for r in recs if r == "strong_hire")
    hires = sum(1 for r in recs if r == "hire")
    no_hires = sum(1 for r in recs if r == "no_hire")

    if no_hires >= 2:
        verdict: Literal["offer", "reject", "hold"] = "reject"
        rationale = f"{no_hires} panellists voted no_hire"
    elif strong_hires + hires > no_hires and r1_score >= 70 and r2_avg >= 70:
        verdict = "offer"
        rationale = f"Panel majority positive (R1 {r1_score:.0f}, R2 avg {r2_avg:.0f})"
    else:
        verdict = "hold"
        rationale = f"Mixed signals (R1 {r1_score:.0f}, R2 avg {r2_avg:.0f}) — awaiting HR review"

    return Recommendation(
        verdict=verdict,
        r1_score=r1_score,
        r2_avg_score=r2_avg,
        rationale=rationale,
    )


def update_application_status(application_id: str, status: FunnelStage, next_action: str = "") -> None:
    app = STORE.get_application(application_id)
    if not app:
        raise LookupError(f"No application for id={application_id!r}")
    old = app.stage
    app.stage = status
    if next_action:
        app.next_action = next_action
    app.log("agent", f"Stage {old.value} → {status.value}" + (f" | next: {next_action}" if next_action else ""))
    # Persist so uvicorn --reload (or a crash) doesn't wipe the application
    # mid-flow — in-memory state alone is not survivable during a demo.
    STORE.save_application(app)
