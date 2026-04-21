"""Cross-candidate ranking for a single JD.

This is the projection HR sees on the JD Command Center: every applicant on
this requisition, ordered by the agent's *current* confidence, with the
reason it ranked them there. As R1 and R2 results land, candidates rise and
fall through the ranking — the function is pure and pulls every signal it
needs from the live ``STORE``.

Tiered scoring:
  * pre-R1   →  match% only
  * post-R1  →  0.7 * R1_score + 0.3 * match%
  * post-R2  →  0.6 * R2_panel_avg + 0.3 * R1_score + 0.1 * match%
  * offer    →  100 (anchored at top)
  * rejected →  0   (anchored at bottom)
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from ..models import Application, FunnelStage, InterviewRecord
from ..store import STORE


class RankedCandidate(BaseModel):
    rank: int
    application_id: str
    candidate_id: str
    candidate_name: str
    stage: FunnelStage
    tier: str            # "offer" | "post_r2" | "post_r1" | "pre_r1" | "rejected"
    score: float         # 0-100, higher is better
    why: str             # human-readable rationale
    match_percent: float
    r1_score: Optional[float] = None
    r2_avg: Optional[float] = None
    last_signal_at: str  # ISO datetime of the most recent signal


class JdRanking(BaseModel):
    jd_id: str
    total: int
    active: int          # not rejected, not offer
    candidates: List[RankedCandidate]


def _r2_avg(record: InterviewRecord) -> Optional[float]:
    if not record.panel_feedback:
        return None
    return sum(fb.score for fb in record.panel_feedback) / len(record.panel_feedback)


def _candidate_name(candidate_id: str) -> str:
    for c in STORE.candidates.values():
        if c.id == candidate_id or c.profile.employee_id == candidate_id:
            return c.profile.name
    return candidate_id


def _score_one(app: Application) -> tuple[str, float, str, Optional[float], Optional[float]]:
    """Return (tier, score, why, r1_score, r2_avg)."""
    if app.stage == FunnelStage.OFFER:
        return ("offer", 100.0, "Offer recommended by panel", None, None)
    if app.stage == FunnelStage.REJECTED:
        return ("rejected", 0.0, "Rejected", None, None)

    r1 = next((i for i in app.interviews if i.round == "R1"), None)
    r2 = next((i for i in app.interviews if i.round == "R2"), None)

    r1_score = float(r1.score) if (r1 and r1.score is not None) else None
    r2_avg = _r2_avg(r2) if r2 else None

    if r2_avg is not None and r1_score is not None:
        score = 0.6 * r2_avg + 0.3 * r1_score + 0.1 * app.match_percent
        return (
            "post_r2",
            score,
            f"Panel avg {r2_avg:.0f} · R1 {r1_score:.0f} · match {app.match_percent:.0f}%",
            r1_score,
            r2_avg,
        )
    if r1_score is not None:
        score = 0.7 * r1_score + 0.3 * app.match_percent
        return (
            "post_r1",
            score,
            f"R1 {r1_score:.0f} · match {app.match_percent:.0f}%",
            r1_score,
            None,
        )
    return (
        "pre_r1",
        app.match_percent,
        f"Profile match {app.match_percent:.0f}% (R1 not yet run)",
        None,
        None,
    )


def rank_for_jd(jd_id: str) -> JdRanking:
    apps = [a for a in STORE.list_applications() if a.job_id == jd_id]
    rows: List[RankedCandidate] = []
    for app in apps:
        tier, score, why, r1_score, r2_avg = _score_one(app)
        rows.append(
            RankedCandidate(
                rank=0,  # filled in below after sort
                application_id=app.id,
                candidate_id=app.candidate_id,
                candidate_name=_candidate_name(app.candidate_id),
                stage=app.stage,
                tier=tier,
                score=round(score, 1),
                why=why,
                match_percent=app.match_percent,
                r1_score=r1_score,
                r2_avg=r2_avg,
                last_signal_at=app.updated_at.isoformat(),
            )
        )

    # Sort: offer first, then by score desc, then rejected last.
    tier_order = {"offer": 0, "post_r2": 1, "post_r1": 2, "pre_r1": 3, "rejected": 4}
    rows.sort(key=lambda r: (tier_order.get(r.tier, 9), -r.score))
    for i, row in enumerate(rows, start=1):
        row.rank = i

    return JdRanking(
        jd_id=jd_id,
        total=len(rows),
        active=sum(1 for r in rows if r.tier not in ("offer", "rejected")),
        candidates=rows,
    )
