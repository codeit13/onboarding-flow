"""Claude-backed CV-vs-JD screener for bulk HR intake.

Evaluates a parsed resume against a specific Job Description and returns a
structured fit report: match score, recommendation (shortlist / maybe /
reject), a one-line headline, strengths, concerns, and evidence quotes
pulled directly from the CV text.

Follows the same service pattern as ``claude_resume_matcher.py`` and
``claude_panel_recommender.py``:
  - env-switchable provider (``AXIS_CV_SCREENER=claude|deterministic``)
  - deterministic fallback via ``scoring_service.score_profile()``
  - returns the same shape regardless of provider so callers don't branch

Environment
-----------
    ANTHROPIC_API_KEY=sk-ant-...
    AXIS_CV_SCREENER=claude                  # default
    AXIS_CV_SCREENER_MODEL=claude-sonnet-4-6
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import httpx

from ..models import Job, Profile

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


@dataclass
class CvScreenResult:
    match_percent: float
    recommendation: str  # "shortlist" | "maybe" | "reject"
    headline: str
    summary: str
    strengths: list
    concerns: list
    evidence_quotes: list
    matched_skills: list
    missing_skills: list
    source: str  # "claude" | "deterministic"
    # Per-criterion breakdown of the HR "additional screening criteria"
    # (if any were provided). Each entry has the shape:
    #   {
    #     "criterion": "<verbatim criterion from HR input>",
    #     "verdict":   "met" | "partial" | "not_met" | "unclear",
    #     "evidence":  "<1-sentence explanation, with CV quote if possible>"
    #   }
    # Empty list when no criteria were supplied or the model omitted it.
    criteria_assessment: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def _provider() -> str:
    return os.getenv("AXIS_CV_SCREENER", "claude").strip().lower()


def _model() -> str:
    return (
        os.getenv("AXIS_CV_SCREENER_MODEL", _DEFAULT_MODEL).strip()
        or _DEFAULT_MODEL
    )


def _api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are the Axis Bank HR screening assistant. An HR partner has uploaded "
    "a batch of CVs and wants you to evaluate each one against a specific "
    "Job Description. Your job is to produce a fit report that helps the HR "
    "partner decide whether to shortlist, hold, or reject the candidate.\n\n"
    "Rules:\n"
    "- Be blunt and honest. If the candidate is a weak fit, say so.\n"
    "- Match scores are 0-100. 75+ = strong fit (shortlist), 50-74 = maybe, "
    "below 50 = reject.\n"
    "- For matched_skills and missing_skills, use the EXACT skill names "
    "from the JD's required_skills list.\n"
    "- Provide 2-4 strengths and 1-3 concerns as bullet points.\n"
    "- evidence_quotes must be VERBATIM fragments (5-20 words each) from "
    "the CV that back up your assessment. Include 2-4 quotes.\n"
    "- headline is a single sentence (max 15 words) a BP can scan in 2 "
    "seconds.\n"
    "- summary is 2-3 sentences with the full reasoning.\n"
    "- If HR has supplied additional screening criteria (see the 'HR "
    "ADDITIONAL SCREENING CRITERIA' block, if present), you MUST also "
    "return a `criteria_assessment` array — one entry per distinct "
    "criterion — with fields { criterion, verdict, evidence }. Valid "
    "verdicts: 'met' (clear evidence in the CV), 'partial' (some signal "
    "but incomplete), 'not_met' (CV contradicts or lacks evidence), "
    "'unclear' (CV silent and cannot be inferred). Evidence is one short "
    "sentence quoting or paraphrasing the CV. If no criteria were "
    "provided, return criteria_assessment: [].\n"
    "- Respond with ONE JSON object matching the schema below — no prose, "
    "no markdown fences, no explanation before or after."
)

_SCHEMA_HINT = """{
  "match_percent": <int 0-100>,
  "recommendation": "<shortlist | maybe | reject>",
  "headline": "<one-sentence headline, max 15 words>",
  "summary": "<2-3 sentences>",
  "strengths": ["<bullet>", ...],
  "concerns": ["<bullet>", ...],
  "evidence_quotes": ["<verbatim CV fragment>", ...],
  "matched_skills": ["<skill from JD required_skills>", ...],
  "missing_skills": ["<skill from JD required_skills>", ...],
  "criteria_assessment": [
    {
      "criterion": "<verbatim criterion from HR input>",
      "verdict":   "met | partial | not_met | unclear",
      "evidence":  "<one short sentence quoting or paraphrasing the CV>"
    }
  ]
}"""


def _build_user_message(
    resume_text: str,
    profile: Profile,
    job: Job,
    custom_criteria: Optional[str] = None,
) -> str:
    jd_block = (
        f"JOB TITLE: {job.title}\n"
        f"FUNCTION: {job.function}\n"
        f"BAND: {job.band}\n"
        f"LOCATION: {job.location}\n"
        f"REQUIRED SKILLS: {', '.join(job.required_skills)}\n"
        f"NICE TO HAVE SKILLS: {', '.join(job.nice_to_have_skills)}\n"
        f"DESCRIPTION:\n{job.description}\n"
    )
    profile_block = (
        f"CANDIDATE NAME: {profile.name}\n"
        f"CURRENT ROLE: {profile.current_role or 'unknown'}\n"
        f"LOCATION: {profile.current_location or 'unknown'}\n"
        f"TENURE: {profile.tenure_years} years\n"
        f"SKILLS (parsed): {', '.join(profile.skills)}\n"
    )
    criteria_block = ""
    if custom_criteria and custom_criteria.strip():
        criteria_block = (
            "=== HR ADDITIONAL SCREENING CRITERIA ===\n"
            "The HR partner running this batch has provided the following "
            "extra context from their internal team. Treat it as high-priority "
            "signal ALONGSIDE the JD match — reflect it in match_percent, "
            "the recommendation, and the strengths / concerns bullets. If a "
            "criterion is hard-blocking (e.g. 'must have NRI desk exposure') "
            "and the candidate lacks it, reduce the score and call it out in "
            "concerns. If the CV evidences a preferred signal, call it out "
            "in strengths.\n\n"
            f"{custom_criteria.strip()}\n\n"
        )
    return (
        f"=== JOB DESCRIPTION ===\n{jd_block}\n"
        f"=== CANDIDATE PROFILE ===\n{profile_block}\n"
        f"{criteria_block}"
        f"=== FULL CV TEXT ===\n{resume_text[:8000]}\n\n"
        f"=== OUTPUT SCHEMA ===\n{_SCHEMA_HINT}\n\n"
        "Evaluate this candidate against this JD"
        + (" and the HR additional criteria above" if criteria_block else "")
        + ". Return ONLY the JSON."
    )


# ---------------------------------------------------------------------------
# Claude path
# ---------------------------------------------------------------------------


def _call_claude(
    resume_text: str,
    profile: Profile,
    job: Job,
    custom_criteria: Optional[str] = None,
) -> CvScreenResult:
    api_key = _api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    user_msg = _build_user_message(resume_text, profile, job, custom_criteria=custom_criteria)
    payload = {
        "model": _model(),
        "max_tokens": 2000,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_msg}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(ANTHROPIC_URL, json=payload, headers=headers)
        resp.raise_for_status()

    body = resp.json()
    raw_text = body["content"][0]["text"]

    # Strip markdown fences if Claude wraps them despite the instruction.
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.error("Claude returned non-JSON: %s", raw_text[:500])
        raise RuntimeError(f"Claude returned non-JSON: {e}") from e

    score = float(data.get("match_percent", 0))
    rec = str(data.get("recommendation", "reject")).lower()
    if rec not in ("shortlist", "maybe", "reject"):
        rec = "shortlist" if score >= 75 else ("maybe" if score >= 50 else "reject")

    # Normalize the per-criterion assessment — tolerate missing fields
    # and clamp the verdict to the allowed enum so the UI never sees junk.
    raw_assessment = data.get("criteria_assessment") or []
    cleaned_assessment: list = []
    _VALID_VERDICTS = {"met", "partial", "not_met", "unclear"}
    if isinstance(raw_assessment, list):
        for item in raw_assessment:
            if not isinstance(item, dict):
                continue
            criterion = str(item.get("criterion") or "").strip()
            verdict = str(item.get("verdict") or "unclear").strip().lower()
            if verdict not in _VALID_VERDICTS:
                verdict = "unclear"
            evidence = str(item.get("evidence") or "").strip()
            if criterion:
                cleaned_assessment.append(
                    {"criterion": criterion, "verdict": verdict, "evidence": evidence}
                )

    return CvScreenResult(
        match_percent=score,
        recommendation=rec,
        headline=str(data.get("headline", "")),
        summary=str(data.get("summary", "")),
        strengths=data.get("strengths", []),
        concerns=data.get("concerns", []),
        evidence_quotes=data.get("evidence_quotes", []),
        matched_skills=data.get("matched_skills", []),
        missing_skills=data.get("missing_skills", []),
        source="claude",
        criteria_assessment=cleaned_assessment,
    )


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------


def _deterministic(
    profile: Profile,
    job: Job,
) -> CvScreenResult:
    """Jaccard skill overlap + tenure heuristic — zero API cost."""
    from ..tools.scoring import score_cv_against_jd

    result = score_cv_against_jd(profile, job)
    score = result.percent
    rec = "shortlist" if score >= 75 else ("maybe" if score >= 50 else "reject")

    return CvScreenResult(
        match_percent=score,
        recommendation=rec,
        headline=f"{profile.name or 'Candidate'}: {score:.0f}% match ({rec})",
        summary=result.rationale,
        strengths=[f"Matched: {s}" for s in result.matched_skills[:4]],
        concerns=[f"Missing: {s}" for s in result.missing_skills[:3]],
        evidence_quotes=[],
        matched_skills=result.matched_skills,
        missing_skills=result.missing_skills,
        source="deterministic",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def screen_cv(
    resume_text: str,
    profile: Profile,
    job: Job,
    custom_criteria: Optional[str] = None,
) -> CvScreenResult:
    """Score one CV against one JD, returning a structured fit report.

    Uses Claude when ``AXIS_CV_SCREENER=claude`` (default) and the API key
    is set. Falls back to the deterministic Jaccard scorer otherwise.

    ``custom_criteria`` is free-text guidance from the HR partner that should
    be weighed alongside the JD match (e.g. "Prefer Tier-1 private bank
    experience", "Must have NRI desk exposure"). Threaded into the Claude
    prompt when provided; ignored by the deterministic fallback.
    """
    provider = _provider()
    if provider == "claude" and _api_key():
        try:
            return _call_claude(resume_text, profile, job, custom_criteria=custom_criteria)
        except Exception as exc:
            log.warning("Claude CV screener failed, falling back: %s", exc)
            return _deterministic(profile, job)
    return _deterministic(profile, job)
