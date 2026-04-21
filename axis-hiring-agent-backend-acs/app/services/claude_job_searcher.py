"""Claude-backed semantic job search.

External candidates can type a natural-language query like
``"Branch Manager in any branch in Mumbai near Powai"`` on the intake
page. We send the query plus the open JD catalogue to Claude and ask it
to (a) parse intent (role, location, radius), (b) score every job for
how well it matches the candidate's STATED preference, and (c) return
the matching jobs ranked by intent fit.

This is intentionally **separate** from ``claude_resume_matcher`` —
the resume matcher scores by *qualifications fit*, this service scores
by *what the candidate said they want*. The external results page
shows both side-by-side as two distinct sections.

Falls back to a fast token/keyword scorer when Claude is unavailable so
the demo never breaks; the result shape is identical either way.

Environment
-----------
    ANTHROPIC_API_KEY=sk-ant-...
    AXIS_JOB_SEARCHER=claude              # default; `deterministic` to force offline
    AXIS_JOB_SEARCHER_MODEL=claude-sonnet-4-6
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Tuple

import httpx

from ..models import Job
from ..tools.external_intake import ExternalRecommendation
from ..tools.intake import list_open_jds

log = logging.getLogger(__name__)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-sonnet-4-6"


class ClaudeJobSearcherError(RuntimeError):
    pass


def _provider() -> str:
    return os.getenv("AXIS_JOB_SEARCHER", "claude").strip().lower()


def _model() -> str:
    return (
        os.getenv("AXIS_JOB_SEARCHER_MODEL", _DEFAULT_MODEL).strip()
        or _DEFAULT_MODEL
    )


def _api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are the Axis Bank careers concierge. An external candidate has "
    "typed a natural-language search query describing the kind of role, "
    "location and constraints they want. Your job is to score every open "
    "Axis job against THAT STATED PREFERENCE — not against the "
    "candidate's qualifications. A separate system handles "
    "qualifications matching.\n\n"
    "Rules:\n"
    "- Be charitable on geography. Treat neighbourhood/locality names "
    "(e.g. \"Powai\", \"Bandra\", \"Whitefield\") as the parent city "
    "(Mumbai, Bengaluru) when no exact branch match exists, but PREFER "
    "jobs whose location field includes the city the candidate named.\n"
    "- Be charitable on title. \"Branch Manager\" should also match "
    "\"Branch Head\", \"Cluster Head — Branches\", etc.\n"
    "- WEIGHT TITLE MATCH HEAVIEST. If the candidate's stated role "
    "matches a job's title (or a clear synonym), the score MUST be "
    ">= 80 even if the city differs — Axis hires across cities and a "
    "perfect title match in the wrong city is still a strong lead.\n"
    "- City mismatch alone caps the score at ~85, never lower than 75 "
    "if the title is an exact match. Reserve scores below 60 for jobs "
    "where BOTH the title and the function are off.\n"
    "- match_score is 0–100. 80+ = strong intent match, 60–79 = "
    "partial intent match, <60 = weak. Only return jobs with "
    "score >= 30 — drop the rest.\n"
    "- For each returned job write a one-sentence rationale that names "
    "the specific element of the candidate's query you matched on "
    "(role, city, locality, function, etc.).\n"
    "- Respond with ONE JSON object matching the schema. No prose, no "
    "markdown fences."
)


_SCHEMA_HINT = """{
  "intent": {
    "role": "Branch Manager",
    "city": "Mumbai",
    "locality": "Powai",
    "other": "any branch"
  },
  "matches": [
    {
      "job_id": "exact id from input",
      "match_score": 92,
      "rationale": "one sentence"
    }
  ]
}"""


def _build_user_message(*, query: str, jds: List[Job]) -> str:
    jd_blocks: List[str] = []
    for jd in jds:
        tags = ", ".join(jd.tags) or "(none)"
        jd_blocks.append(
            f"- job_id: {jd.id}\n"
            f"  title: {jd.title}\n"
            f"  function/band: {jd.function} / {jd.band}\n"
            f"  location: {jd.location}\n"
            f"  tags: [{tags}]"
        )
    jd_block = "\n".join(jd_blocks) if jd_blocks else "(no open jobs)"

    return (
        f"## Open Axis jobs\n{jd_block}\n\n"
        f"## Candidate's natural-language search query\n"
        f'"{query.strip()[:500]}"\n\n'
        f"## Respond with JSON matching this schema exactly\n"
        f"{_SCHEMA_HINT}"
    )


def _call_anthropic(*, system: str, user: str, model: str) -> str:
    key = _api_key()
    if not key:
        raise ClaudeJobSearcherError("ANTHROPIC_API_KEY is not set")

    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": 2500,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=60.0) as client:
        r = client.post(ANTHROPIC_URL, headers=headers, json=body)
    if r.status_code >= 300:
        raise ClaudeJobSearcherError(
            f"Anthropic API HTTP {r.status_code}: {r.text[:600]}"
        )
    data = r.json()
    blocks = data.get("content") or []
    for block in blocks:
        if block.get("type") == "text":
            text = block.get("text", "")
            if text:
                return text
    raise ClaudeJobSearcherError(f"Anthropic returned no text block: {data}")


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        raise ClaudeJobSearcherError(
            f"No JSON object in model output: {text[:400]}"
        )
    try:
        return json.loads(m.group(0))
    except Exception as exc:
        raise ClaudeJobSearcherError(
            f"Could not parse JSON: {exc!r} — {text[:400]}"
        )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def search_jobs(query: str) -> Tuple[List[ExternalRecommendation], str]:
    """Run a semantic NL query against the open JD catalogue.

    Returns ``(matches, source)`` where ``source`` is ``'claude'`` or
    ``'deterministic'``. ``matches`` is sorted by descending match
    score, contains ONLY jobs Claude considered relevant (>= 30), and
    is empty if nothing matched.
    """
    query = (query or "").strip()
    jds = list_open_jds()
    if not query or not jds:
        return [], "deterministic"

    if _provider() != "claude":
        return _deterministic(query, jds)

    if not _api_key():
        log.warning("job searcher: no ANTHROPIC_API_KEY — falling back")
        return _deterministic(query, jds)

    try:
        text = _call_anthropic(
            system=_SYSTEM_PROMPT,
            user=_build_user_message(query=query, jds=jds),
            model=_model(),
        )
        raw = _extract_json(text)
        matches = _normalise(raw, jds=jds)
        log.info(
            "job searcher: claude returned %d intent matches for query=%r",
            len(matches),
            query[:60],
        )
        return matches, "claude"
    except Exception as exc:  # noqa: BLE001
        log.warning("job searcher: Claude call failed (%r) — falling back", exc)
        return _deterministic(query, jds)


def _normalise(
    raw: Dict[str, Any],
    *,
    jds: List[Job],
) -> List[ExternalRecommendation]:
    jd_by_id = {jd.id: jd for jd in jds}
    out: List[ExternalRecommendation] = []
    for m in raw.get("matches") or []:
        if not isinstance(m, dict):
            continue
        jid = str(m.get("job_id") or "").strip()
        jd = jd_by_id.get(jid)
        if jd is None:
            continue
        try:
            score = float(m.get("match_score") or 0)
        except Exception:
            score = 0.0
        score = max(0.0, min(100.0, score))
        if score < 30.0:
            continue
        out.append(
            ExternalRecommendation(
                job_id=jd.id,
                job_title=jd.title,
                location=jd.location,
                match_percent=score,
                matched_skills=[],
                missing_skills=[],
                rationale=str(m.get("rationale") or "").strip()
                or f"Matches your search for '{jd.title}'",
            )
        )
    out.sort(key=lambda r: r.match_percent, reverse=True)
    return out


# ---------------------------------------------------------------------------
# Deterministic fallback (token overlap on title + location + tags)
# ---------------------------------------------------------------------------


_STOPWORDS = {
    "i", "am", "looking", "for", "a", "an", "the", "in", "any", "near",
    "with", "to", "and", "or", "of", "at", "on", "my", "is", "be",
    "want", "need", "search", "branch",
}


def _tokens(s: str) -> List[str]:
    return [
        t
        for t in re.split(r"[^A-Za-z0-9]+", (s or "").lower())
        if t and t not in _STOPWORDS and len(t) > 1
    ]


def _deterministic(
    query: str,
    jds: List[Job],
) -> Tuple[List[ExternalRecommendation], str]:
    qtokens = set(_tokens(query))
    if not qtokens:
        return [], "deterministic"

    out: List[ExternalRecommendation] = []
    for jd in jds:
        haystack = " ".join(
            [jd.title, jd.location, jd.function, " ".join(jd.tags)]
        )
        htokens = set(_tokens(haystack))
        if not htokens:
            continue
        overlap = qtokens & htokens
        if not overlap:
            continue
        # Score = overlap fraction × 100, biased toward role/title hits.
        title_tokens = set(_tokens(jd.title))
        title_hits = qtokens & title_tokens
        location_tokens = set(_tokens(jd.location))
        loc_hits = qtokens & location_tokens
        score = (
            (len(overlap) / max(1, len(qtokens))) * 70.0
            + (len(title_hits) > 0) * 20.0
            + (len(loc_hits) > 0) * 10.0
        )
        score = min(100.0, score)
        if score < 30.0:
            continue
        rationale_bits = []
        if title_hits:
            rationale_bits.append(f"role match on '{', '.join(sorted(title_hits))}'")
        if loc_hits:
            rationale_bits.append(f"location match on '{', '.join(sorted(loc_hits))}'")
        rationale = (
            "; ".join(rationale_bits)
            if rationale_bits
            else f"keyword overlap with your search"
        )
        out.append(
            ExternalRecommendation(
                job_id=jd.id,
                job_title=jd.title,
                location=jd.location,
                match_percent=round(score, 1),
                matched_skills=[],
                missing_skills=[],
                rationale=rationale,
            )
        )
    out.sort(key=lambda r: r.match_percent, reverse=True)
    return out, "deterministic"


__all__ = ["search_jobs", "ClaudeJobSearcherError"]
