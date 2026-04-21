"""Scoring tools.

In production these will call Claude (`claude-sonnet-4-6`) with the profile
and JD as context and parse a structured JSON response. For the POC we use a
deterministic Jaccard-style skill overlap so every test is reproducible and
the agent state machine can be validated without needing live Claude calls.

When the real Claude implementation is wired in, the function signature and
return shape stay identical — callers don't change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from ..models import InterviewRecord, Job, Profile, TranscriptSegment


@dataclass
class ScoreResult:
    percent: float
    rationale: str
    matched_skills: List[str]
    missing_skills: List[str]


def _normalize(skill: str) -> str:
    return skill.strip().lower()


def _canonicalise(skill: str) -> str:
    """Snap a free-text skill to its canonical Axis SKILL_MASTER name
    when one exists, then lowercase it for set comparison.

    This makes the resume scorer taxonomy-aware: a JD that says
    ``"Bank Sales"`` and a candidate who wrote ``"bank sales"`` (or even
    a near-variant the SKILL_MASTER recognises) line up correctly
    against the same canonical row.
    """
    try:
        from ..services import taxonomy
        canon = taxonomy.canonicalise_skill(skill)
    except Exception:
        canon = skill
    return _normalize(canon)


def score_cv_against_jd(profile: Profile, jd: Job) -> ScoreResult:
    """Return a 0-100 skill-overlap score plus matched/missing skill lists.

    Deterministic replacement for the Claude scorer. Same signature.
    Skill names are canonicalised against the Axis SKILL_MASTER taxonomy
    before matching so the demo speaks Axis-speak end to end.
    """
    required = {_canonicalise(s) for s in jd.required_skills}
    have = {_canonicalise(s) for s in profile.skills}

    if not required:
        return ScoreResult(percent=0.0, rationale="JD has no required skills", matched_skills=[], missing_skills=[])

    matched = sorted(required & have)
    missing = sorted(required - have)

    overlap = len(matched) / len(required)

    # Tenure boost: +5pp for >=5 years, +10pp for >=8 years, capped at 100.
    tenure_boost = 0.0
    if profile.tenure_years >= 8:
        tenure_boost = 10.0
    elif profile.tenure_years >= 5:
        tenure_boost = 5.0

    percent = min(100.0, round(overlap * 100 + tenure_boost, 1))

    rationale = (
        f"Matched {len(matched)}/{len(required)} required skills "
        f"({', '.join(matched) or 'none'}). "
        f"Missing: {', '.join(missing) or 'none'}. "
        f"Tenure {profile.tenure_years:.1f}y (+{tenure_boost:.0f}pp)."
    )

    return ScoreResult(
        percent=percent,
        rationale=rationale,
        matched_skills=matched,
        missing_skills=missing,
    )


# ---------------------------------------------------------------------------
# Transcript scoring
# ---------------------------------------------------------------------------


_TRANSCRIPT_EVIDENCE_MARKERS = (
    "%", "cr", "crore", "lakh", "bps", "x",
    "₹", "rs", "inr",
    "mandate", "cohort", "portfolio", "stakeholder", "client",
)


def score_transcript(record: InterviewRecord, jd: Job) -> Tuple[float, str]:
    """Score a completed interview transcript against the JD rubric.

    POC heuristic, deterministic but varied. Four signals compose the
    final score so a scripted transcript no longer saturates at 100:

    * **Coverage** — what fraction of JD skills were discussed at all?
      Contributes up to 60 points.
    * **Depth** — average length of the candidate's substantive answers,
      capped at 400 chars. Contributes up to 20 points.
    * **Evidence** — concrete markers across the transcript: numbers,
      percentages, currency, domain artefacts ("mandate", "cohort").
      Contributes up to 15 points.
    * **Engagement** — more than 5 substantive candidate turns earns
      the final 5 points.

    The ceiling is 97 — even a perfect scripted transcript leaves room
    for the R2 panel to probe further. Same signature the Claude-backed
    scorer will expose.
    """
    required = [_normalize(s) for s in jd.required_skills]
    if not required:
        return 0.0, "JD has no required skills — cannot score"

    cand_turns = [s for s in record.transcript if s.speaker == "candidate"]
    if not cand_turns:
        return 0.0, "Empty candidate transcript"

    full_text = " ".join(seg.text.lower() for seg in cand_turns)

    # Coverage (0-60) — credit any required skill that appears verbatim
    # OR via a meaningful token from the skill name. Real candidates
    # describe what they did using their own words; demanding the JD's
    # exact phrasing is what produced the false-reject bug.
    hit: set[str] = set()
    for skill in required:
        if skill in full_text:
            hit.add(skill)
            continue
        tokens = [t for t in skill.split() if len(t) > 3]
        if tokens and any(tok in full_text for tok in tokens):
            hit.add(skill)
    coverage_pts = 60.0 * (len(hit) / len(required))

    # Depth (0-20) — average answer length, capped.
    avg_len = sum(len(seg.text) for seg in cand_turns) / len(cand_turns)
    depth_pts = min(avg_len / 400.0, 1.0) * 20.0

    # Evidence (0-15) — markers of concreteness across the transcript.
    marker_hits = sum(1 for m in _TRANSCRIPT_EVIDENCE_MARKERS if m in full_text)
    evidence_pts = min(marker_hits * 2.0, 15.0)

    # Engagement (0-5) — multi-turn substantive conversation.
    engagement_pts = 5.0 if len(cand_turns) >= 5 else 0.0

    raw = coverage_pts + depth_pts + evidence_pts + engagement_pts
    # Ceiling at 97 so even a perfect scripted run leaves R2 room to probe.
    score = round(min(raw, 97.0), 1)

    rationale = (
        f"Covered {len(hit)}/{len(required)} required skills "
        f"({', '.join(sorted(hit)) or 'none'}). "
        f"Depth {depth_pts:.0f}/20, evidence {evidence_pts:.0f}/15, "
        f"engagement {engagement_pts:.0f}/5."
    )
    return score, rationale
