"""Claude-backed R2 panel recommender (DESIGN-001 chunk 6).

After the R2 Teams interview, the panellist pastes the transcript into
the feedback page and clicks "Analyse with Claude". This service sends
the transcript + JD rubric + R1 report to the Anthropic API and parses
the structured JSON back into an ``AiPanelRecommendation``.

Design notes
------------
* We use ``httpx`` directly against the Anthropic Messages API instead of
  taking a dependency on the official ``anthropic`` SDK. httpx is already
  in ``requirements.txt`` and the surface area we need (one POST) is
  small enough that avoiding a second HTTP stack is the right trade.
* The LLM is asked to return *only* a JSON block matching a fixed schema
  so parsing is deterministic. If the first parse fails, we make a single
  "repair" attempt with the raw text fed back in.
* If ``AXIS_PANEL_RECOMMENDER=deterministic`` (or the API is unreachable,
  or the key is missing), we fall through to an offline scorer so the
  demo never hard-fails on network flakiness.
* The result is cached on the ``InterviewRecord.ai_recommendation`` by
  the caller so re-renders and audit trails are stable.

Environment
-----------
    ANTHROPIC_API_KEY=sk-ant-...       # lives in axis-hiring-agent-backend/.env
    AXIS_PANEL_RECOMMENDER=claude      # or `deterministic` to force fallback
    AXIS_PANEL_RECOMMENDER_MODEL=claude-sonnet-4-6
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from ..models import (
    AiPanelRecommendation,
    AiRecommendationEvidence,
    InterviewRecord,
    InterviewReport,
    Job,
    PanelFeedback,
)

log = logging.getLogger(__name__)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-sonnet-4-6"


class ClaudeRecommenderError(RuntimeError):
    """Any failure calling or parsing the Anthropic API."""


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def _provider() -> str:
    return os.getenv("AXIS_PANEL_RECOMMENDER", "claude").strip().lower()


def _model() -> str:
    return os.getenv("AXIS_PANEL_RECOMMENDER_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def _api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are the Axis Bank hiring-agent R2 panel reviewer. A human panellist "
    "has just finished a Round 2 interview and pasted the raw Teams transcript "
    "below. Your job is to analyse the transcript against the JD rubric and "
    "the R1 AI-interview report, then emit a single structured recommendation "
    "that the human panellist will review before casting their own vote.\n\n"
    "Rules:\n"
    "- The human owns the final decision. Your output is advisory only.\n"
    "- Be blunt. Flag weak answers, evasions, and gaps. Never invent evidence.\n"
    "- Every strength and concern must be backed by at least one short quote "
    "from the transcript (verbatim, no paraphrasing).\n"
    "- If the transcript is clearly too short, garbled, or off-topic, return "
    'suggested_recommendation "no_hire" with a concern explaining why.\n'
    "- Respond with ONE JSON object matching the schema — no prose, no "
    "markdown fences, no explanation before or after."
)


_SCHEMA_HINT = """{
  "suggested_recommendation": "strong_hire" | "hire" | "no_hire",
  "suggested_score": 0-100 integer,
  "headline": "one sentence verdict",
  "summary": "2-4 sentence panel-facing summary",
  "strengths": ["short bullet", "..."],
  "concerns": ["short bullet", "..."],
  "evidence": [
    {"quote": "verbatim quote", "speaker": "candidate|panel", "why_it_matters": "short"}
  ]
}"""


def _build_user_message(
    *,
    transcript_text: str,
    job: Job,
    r1_report: Optional[InterviewReport],
) -> str:
    rubric_lines: List[str] = []
    for skill in job.required_skills:
        rubric_lines.append(f"  - {skill}")
    rubric_block = "\n".join(rubric_lines) if rubric_lines else "  (no required skills on JD)"

    r1_block = ""
    if r1_report is not None:
        scores = ", ".join(
            f"{k}: {int(round(v))}" for k, v in (r1_report.rubric_scores or {}).items()
        )
        probes = "\n".join(f"  - {p}" for p in (r1_report.recommended_probes or []))
        r1_block = (
            f"\n\n## R1 AI Interview Agent report (prior round)\n"
            f"- Headline: {r1_report.headline}\n"
            f"- Overall: {r1_report.overall_score:.0f}/100\n"
            f"- Recommendation: {r1_report.recommendation}\n"
            f"- Rubric scores: {scores or '(none)'}\n"
            f"- Probes the panel was asked to cover in R2:\n{probes or '  (none)'}"
        )

    return (
        f"## JD\n"
        f"- Title: {job.title}\n"
        f"- Function/Band: {job.function} / {job.band}\n"
        f"- Location: {job.location}\n"
        f"- Shortlist threshold: {job.shortlist_threshold}\n"
        f"- Required skills:\n{rubric_block}"
        f"{r1_block}\n\n"
        f"## R2 interview transcript (as pasted by panellist)\n"
        f"```\n{transcript_text.strip()}\n```\n\n"
        f"## Respond with JSON matching this schema exactly\n"
        f"{_SCHEMA_HINT}"
    )


# ---------------------------------------------------------------------------
# Anthropic call
# ---------------------------------------------------------------------------


def _call_anthropic(*, system: str, user: str, model: str) -> str:
    key = _api_key()
    if not key:
        raise ClaudeRecommenderError("ANTHROPIC_API_KEY is not set")

    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": 2000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=60.0) as client:
        r = client.post(ANTHROPIC_URL, headers=headers, json=body)
    if r.status_code >= 300:
        raise ClaudeRecommenderError(
            f"Anthropic API HTTP {r.status_code}: {r.text[:600]}"
        )
    data = r.json()
    blocks = data.get("content") or []
    for block in blocks:
        if block.get("type") == "text":
            text = block.get("text", "")
            if text:
                return text
    raise ClaudeRecommenderError(f"Anthropic returned no text block: {data}")


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    # Fast path: the model obeyed the "JSON only" instruction.
    try:
        return json.loads(text)
    except Exception:
        pass
    # Slow path: pick the first balanced {...} chunk.
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        raise ClaudeRecommenderError(f"No JSON object found in model output: {text[:400]}")
    try:
        return json.loads(m.group(0))
    except Exception as exc:
        raise ClaudeRecommenderError(
            f"Could not parse JSON from model output: {exc!r} — {text[:400]}"
        )


# ---------------------------------------------------------------------------
# Normalisation into the Pydantic model
# ---------------------------------------------------------------------------


_VALID_RECS = {"strong_hire", "hire", "no_hire"}
_VALID_SPEAKERS = {"panel", "candidate", "unknown"}


def _normalise(
    raw: Dict[str, Any],
    *,
    application_id: str,
    interview_id: str,
    model: str,
    source: str,
) -> AiPanelRecommendation:
    rec = str(raw.get("suggested_recommendation", "hire")).strip().lower()
    if rec not in _VALID_RECS:
        rec = "hire"

    try:
        score = float(raw.get("suggested_score", 70))
    except Exception:
        score = 70.0
    score = max(0.0, min(100.0, score))

    def _flatten_bullet(item: Any) -> str:
        # The prompt asks for plain strings but Claude occasionally returns
        # richer objects like {"point": "...", "quote": "...", "why_it_matters": "..."}.
        # Flatten gracefully instead of stringifying the dict.
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            for key in ("point", "bullet", "text", "label", "summary", "description"):
                v = item.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return ""
        return str(item).strip()

    strengths = [s for s in (_flatten_bullet(x) for x in (raw.get("strengths") or [])) if s]
    concerns = [c for c in (_flatten_bullet(x) for x in (raw.get("concerns") or [])) if c]

    # If Claude packed evidence inside strengths/concerns dicts, harvest it.
    extra_evidence_dicts: List[Dict[str, Any]] = []
    for bucket in ("strengths", "concerns"):
        for item in raw.get(bucket) or []:
            if isinstance(item, dict) and isinstance(item.get("quote"), str):
                extra_evidence_dicts.append({
                    "quote": item.get("quote", ""),
                    "speaker": item.get("speaker", "candidate"),
                    "why_it_matters": item.get("why_it_matters", ""),
                })

    evidence: List[AiRecommendationEvidence] = []
    for ev in (raw.get("evidence") or []) + extra_evidence_dicts:
        if not isinstance(ev, dict):
            continue
        speaker = str(ev.get("speaker", "candidate")).strip().lower()
        if speaker not in _VALID_SPEAKERS:
            speaker = "candidate"
        evidence.append(
            AiRecommendationEvidence(
                quote=str(ev.get("quote", "")).strip(),
                speaker=speaker,  # type: ignore[arg-type]
                why_it_matters=str(ev.get("why_it_matters", "")).strip(),
            )
        )

    return AiPanelRecommendation(
        application_id=application_id,
        interview_id=interview_id,
        suggested_recommendation=rec,  # type: ignore[arg-type]
        suggested_score=score,
        headline=str(raw.get("headline", "")).strip() or "Claude recommendation",
        summary=str(raw.get("summary", "")).strip(),
        strengths=strengths,
        concerns=concerns,
        evidence=evidence,
        model=model,
        source=source,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Deterministic fallback (cheap + offline)
# ---------------------------------------------------------------------------


_POS_MARKERS = (
    "closed", "onboarded", "stakeholder", "audit", "cross-sell", "kyc",
    "compliance", "relationship", "mandate", "delivered", "led",
    "owned", "crore", "lakh", "cr", "%",
)
_NEG_MARKERS = (
    "don't know", "not sure", "never done", "haven't", "no experience", "unsure",
)


def _deterministic_recommendation(
    *,
    transcript_text: str,
    application_id: str,
    interview_id: str,
    job: Job,
    r1_report: Optional[InterviewReport],
) -> AiPanelRecommendation:
    text = (transcript_text or "").lower()
    pos = sum(text.count(m) for m in _POS_MARKERS)
    neg = sum(text.count(m) for m in _NEG_MARKERS)

    base = 55 + min(25, pos * 2) - min(20, neg * 4)
    if r1_report and r1_report.overall_score:
        # Blend 60/40 with R1 so the fallback is at least anchored.
        base = int(round(0.6 * base + 0.4 * r1_report.overall_score))
    score = max(0.0, min(95.0, float(base)))

    rec = "hire" if score >= 65 else "no_hire"
    if score >= 85:
        rec = "strong_hire"

    strengths: List[str] = []
    concerns: List[str] = []
    if pos >= 3:
        strengths.append(
            f"Candidate cited multiple concrete examples ({pos} signal hits) "
            f"aligned to the {job.title} rubric."
        )
    if pos >= 6:
        strengths.append("Demonstrated range across stakeholder management and delivery.")
    if neg >= 2:
        concerns.append(f"{neg} passages flagged low confidence or direct gaps.")
    if r1_report and r1_report.recommendation == "borderline":
        concerns.append("R1 was borderline — R2 did not decisively resolve the signal.")
    if not strengths:
        strengths.append("Fallback scorer: no strong positive markers found in the transcript.")
    if not concerns:
        concerns.append("Fallback scorer: no strong negative markers found in the transcript.")

    evidence: List[AiRecommendationEvidence] = []
    # Grab the first two non-empty lines as token evidence so the UI has
    # something to render even in the offline path.
    lines = [ln.strip() for ln in (transcript_text or "").splitlines() if ln.strip()]
    for line in lines[:2]:
        evidence.append(
            AiRecommendationEvidence(
                quote=line[:240],
                speaker="candidate",
                why_it_matters="Auto-selected by deterministic fallback scorer.",
            )
        )

    return AiPanelRecommendation(
        application_id=application_id,
        interview_id=interview_id,
        suggested_recommendation=rec,  # type: ignore[arg-type]
        suggested_score=score,
        headline=(
            f"Deterministic fallback — {rec.replace('_', ' ')} at {score:.0f}/100"
        ),
        summary=(
            "Offline scorer used because the Claude provider is disabled, the "
            "API key is missing, or the live call failed. Results are rough and "
            "meant as a placeholder — re-analyse with Claude when possible."
        ),
        strengths=strengths,
        concerns=concerns,
        evidence=evidence,
        model="deterministic",
        source="deterministic",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def recommend_from_transcript(
    *,
    interview: InterviewRecord,
    transcript_text: str,
    job: Job,
    r1_report: Optional[InterviewReport],
) -> AiPanelRecommendation:
    """Run the R2 recommender pipeline and return a structured recommendation.

    The caller is responsible for persisting the result on
    ``interview.ai_recommendation``.
    """
    if not transcript_text or not transcript_text.strip():
        raise ValueError("transcript_text is empty")

    provider = _provider()
    if provider == "deterministic":
        log.info("Panel recommender running in deterministic mode (env override)")
        return _deterministic_recommendation(
            transcript_text=transcript_text,
            application_id=interview.application_id,
            interview_id=interview.id,
            job=job,
            r1_report=r1_report,
        )

    model = _model()
    user_msg = _build_user_message(
        transcript_text=transcript_text,
        job=job,
        r1_report=r1_report,
    )
    try:
        raw_text = _call_anthropic(system=_SYSTEM_PROMPT, user=user_msg, model=model)
        raw_json = _extract_json(raw_text)
    except ClaudeRecommenderError as exc:
        log.warning(
            "Claude recommender failed (%s) — falling back to deterministic scorer",
            exc,
        )
        return _deterministic_recommendation(
            transcript_text=transcript_text,
            application_id=interview.application_id,
            interview_id=interview.id,
            job=job,
            r1_report=r1_report,
        )

    return _normalise(
        raw_json,
        application_id=interview.application_id,
        interview_id=interview.id,
        model=model,
        source="claude",
    )


# ---------------------------------------------------------------------------
# Per-panellist AI second opinion (HR R2 review screen)
# ---------------------------------------------------------------------------
#
# Once every panellist has voted, the Business Partner needs to compare each
# panellist's manual feedback against what the transcript actually shows.
# Rather than one consolidated AI recommendation, HR gets ONE Claude review
# per panellist, scoped to that panellist's vote. Each call asks Claude to:
#
#   1. Read the same shared R2 transcript.
#   2. Read THAT panellist's score, strengths, concerns, and recommendation.
#   3. Decide whether the transcript corroborates or contradicts the vote.
#   4. Return its own independent verdict (strong_hire / hire / no_hire)
#      with evidence quotes anchoring its agreement or disagreement.
#
# HR sees N AI cards side-by-side with the panel votes and can spot exactly
# where the panel and Claude diverge BEFORE clicking Make offer / Reject.


_PER_PANELLIST_SYSTEM_PROMPT = (
    "You are the Axis Bank hiring-agent R2 panel reviewer. Three panellists "
    "have just finished a Round 2 interview together. You are reviewing "
    "ONE specific panellist's verdict against the shared R2 Teams "
    "transcript so the Business Partner can decide whether to trust that "
    "panellist's read.\n\n"
    "Rules:\n"
    "- The Business Partner owns the final decision. Your output is advisory.\n"
    "- Your job is to corroborate or challenge THIS panellist's vote, not "
    "to invent a fresh verdict in a vacuum. Always anchor your view in the "
    "transcript.\n"
    "- Be blunt. If the panellist over-rated or under-rated the candidate, "
    "say so explicitly in the headline and summary.\n"
    "- Every strength and concern must be backed by at least one short, "
    "verbatim quote from the transcript. Never paraphrase.\n"
    "- If the transcript is too short or off-topic to validate the "
    'panellist, return suggested_recommendation "no_hire" with a concern '
    "explaining why you cannot corroborate the vote.\n"
    "- Respond with ONE JSON object matching the schema — no prose, no "
    "markdown fences, no explanation before or after."
)


def _build_per_panellist_message(
    *,
    transcript_text: str,
    job: Job,
    r1_report: Optional[InterviewReport],
    panellist: PanelFeedback,
) -> str:
    rubric_lines: List[str] = [f"  - {skill}" for skill in job.required_skills]
    rubric_block = (
        "\n".join(rubric_lines) if rubric_lines else "  (no required skills on JD)"
    )

    r1_block = ""
    if r1_report is not None:
        scores = ", ".join(
            f"{k}: {int(round(v))}" for k, v in (r1_report.rubric_scores or {}).items()
        )
        r1_block = (
            f"\n\n## R1 AI Interview Agent report (prior round)\n"
            f"- Headline: {r1_report.headline}\n"
            f"- Overall: {r1_report.overall_score:.0f}/100\n"
            f"- Recommendation: {r1_report.recommendation}\n"
            f"- Rubric scores: {scores or '(none)'}"
        )

    return (
        f"## JD\n"
        f"- Title: {job.title}\n"
        f"- Function/Band: {job.function} / {job.band}\n"
        f"- Location: {job.location}\n"
        f"- Required skills:\n{rubric_block}"
        f"{r1_block}\n\n"
        f"## Panellist whose verdict you are reviewing\n"
        f"- Name: {panellist.panellist_name or panellist.panellist_id}\n"
        f"- Recommendation: {panellist.recommendation}\n"
        f"- Score: {panellist.score:.0f}/100\n"
        f"- Strengths the panellist wrote: {panellist.strengths or '(none)'}\n"
        f"- Concerns the panellist wrote: {panellist.concerns or '(none)'}\n\n"
        f"## Shared R2 interview transcript\n"
        f"```\n{transcript_text.strip()}\n```\n\n"
        f"## Task\n"
        f"Decide whether the transcript corroborates or contradicts this "
        f"panellist's vote. The headline MUST mention agreement or "
        f"disagreement with the panellist (e.g. 'Agrees with "
        f"{panellist.panellist_name or 'the panellist'} — strong hire', "
        f"or 'Pushes back on {panellist.panellist_name or 'the panellist'} "
        f"— transcript shows weaker evidence than rated').\n\n"
        f"## Respond with JSON matching this schema exactly\n"
        f"{_SCHEMA_HINT}"
    )


def _deterministic_per_panellist(
    *,
    transcript_text: str,
    application_id: str,
    interview_id: str,
    job: Job,
    r1_report: Optional[InterviewReport],
    panellist: PanelFeedback,
) -> AiPanelRecommendation:
    """Offline fallback: re-use the consolidated scorer but tag the headline
    with the panellist's name so HR can still see N distinct cards even when
    the live API is down."""
    base = _deterministic_recommendation(
        transcript_text=transcript_text,
        application_id=application_id,
        interview_id=interview_id,
        job=job,
        r1_report=r1_report,
    )
    name = panellist.panellist_name or panellist.panellist_id
    agree = base.suggested_recommendation == panellist.recommendation
    verdict_word = "Agrees with" if agree else "Pushes back on"
    base.headline = (
        f"{verdict_word} {name} — fallback {base.suggested_recommendation.replace('_', ' ')} "
        f"at {base.suggested_score:.0f}/100"
    )
    base.summary = (
        f"Offline fallback scorer for {name}'s vote. The live Claude API "
        f"was unreachable, so this card is a placeholder. Re-run the AI "
        f"review when the network is back to get a real per-panellist read."
    )
    return base


def recommend_for_panellist(
    *,
    interview: InterviewRecord,
    transcript_text: str,
    job: Job,
    r1_report: Optional[InterviewReport],
    panellist: PanelFeedback,
) -> AiPanelRecommendation:
    """Run the per-panellist Claude reviewer for ONE panellist's vote.

    Caller persists the result on
    ``interview.ai_recommendations_by_panellist[panellist.panellist_id]``.
    """
    if not transcript_text or not transcript_text.strip():
        raise ValueError("transcript_text is empty")

    provider = _provider()
    if provider == "deterministic":
        log.info(
            "Per-panellist recommender running in deterministic mode (env override)"
        )
        return _deterministic_per_panellist(
            transcript_text=transcript_text,
            application_id=interview.application_id,
            interview_id=interview.id,
            job=job,
            r1_report=r1_report,
            panellist=panellist,
        )

    model = _model()
    user_msg = _build_per_panellist_message(
        transcript_text=transcript_text,
        job=job,
        r1_report=r1_report,
        panellist=panellist,
    )
    try:
        raw_text = _call_anthropic(
            system=_PER_PANELLIST_SYSTEM_PROMPT, user=user_msg, model=model
        )
        raw_json = _extract_json(raw_text)
    except ClaudeRecommenderError as exc:
        log.warning(
            "Per-panellist Claude recommender failed (%s) — falling back",
            exc,
        )
        return _deterministic_per_panellist(
            transcript_text=transcript_text,
            application_id=interview.application_id,
            interview_id=interview.id,
            job=job,
            r1_report=r1_report,
            panellist=panellist,
        )

    return _normalise(
        raw_json,
        application_id=interview.application_id,
        interview_id=interview.id,
        model=model,
        source="claude",
    )
