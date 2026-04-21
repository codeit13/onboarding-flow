"""Claude-backed resume parser + JD matcher for the external candidate flow.

The external candidate uploads a PDF / DOCX / TXT resume on the public
landing page. This service sends the extracted plain text plus the
catalogue of open JDs to the Anthropic Messages API and asks Claude to
return a structured profile + ranked match list. Mirrors the design of
``claude_panel_recommender.py`` so we have one consistent pattern for
LLM-backed services in the app.

Why this is its own service
---------------------------
- Keeps the HTTP/JSON plumbing out of the route handler.
- Lets us flip provider via ``AXIS_RESUME_MATCHER=claude|deterministic``
  for tests and offline development.
- Returns the *same* shapes the deterministic fallback returns
  (``Profile`` + ``List[ExternalRecommendation]``) so callers don't
  branch on the source.

Environment
-----------
    ANTHROPIC_API_KEY=sk-ant-...           # backend/.env (already set)
    AXIS_RESUME_MATCHER=claude             # default; set to `deterministic`
                                           #   to force the offline path
    AXIS_RESUME_MATCHER_MODEL=claude-sonnet-4-6
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..models import Job, Profile
from ..tools.external_intake import ExternalRecommendation
from ..tools.intake import list_open_jds

log = logging.getLogger(__name__)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-sonnet-4-6"


class ClaudeResumeMatcherError(RuntimeError):
    """Any failure calling or parsing the Anthropic API."""


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def _provider() -> str:
    return os.getenv("AXIS_RESUME_MATCHER", "claude").strip().lower()


def _model() -> str:
    return (
        os.getenv("AXIS_RESUME_MATCHER_MODEL", _DEFAULT_MODEL).strip()
        or _DEFAULT_MODEL
    )


def _api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are the Axis Bank hiring-agent resume screener. An external "
    "candidate has uploaded their resume to the Axis careers portal. Your "
    "job is to (a) extract a structured profile from the resume and (b) "
    "score the candidate against every open Axis job, returning a ranked "
    "match list. The downstream system will use your output verbatim to "
    "show the candidate which jobs to apply to.\n\n"
    "Rules:\n"
    "- Be honest. A weak match is a weak match — don't inflate scores.\n"
    "- Match scores are 0-100. 75+ means the candidate is a real fit.\n"
    "- Extract the candidate's phone / mobile number exactly as written in "
    "the resume (include country code if present, e.g. '+91 98765 43210'). "
    "If no phone number is present, return an empty string for phone.\n"
    "- For each job, list the matched and missing required skills using "
    "the EXACT skill strings from the JD's required_skills array.\n"
    "- Write a one-sentence rationale per job that a hiring manager can "
    "read in 3 seconds.\n"
    "- If the resume is unreadable, return an empty skills list and score "
    "every job at 0 with rationale 'Could not read resume'.\n"
    "- Respond with ONE JSON object matching the schema below — no prose, "
    "no markdown fences, no explanation before or after."
)


_SCHEMA_HINT = """{
  "profile": {
    "name": "Full Name",
    "email": "name@example.com",
    "phone": "+91 98765 43210",
    "current_role": "Latest job title from the resume",
    "current_location": "City, Country",
    "tenure_years": 0,
    "skills": ["skill 1", "skill 2", "..."]
  },
  "matches": [
    {
      "job_id": "exact job id from the input",
      "match_percent": 0,
      "matched_skills": ["..."],
      "missing_skills": ["..."],
      "rationale": "one sentence"
    }
  ]
}"""


def _build_user_message(*, resume_text: str, jds: List[Job]) -> str:
    jd_blocks: List[str] = []
    for jd in jds:
        req = ", ".join(jd.required_skills) or "(none)"
        nice = ", ".join(jd.nice_to_have_skills) or "(none)"
        jd_blocks.append(
            f"- job_id: {jd.id}\n"
            f"  title: {jd.title}\n"
            f"  function/band: {jd.function} / {jd.band}\n"
            f"  location: {jd.location}\n"
            f"  required_skills: [{req}]\n"
            f"  nice_to_have: [{nice}]"
        )
    jd_block = "\n".join(jd_blocks) if jd_blocks else "(no open jobs)"

    return (
        f"## Open Axis jobs\n{jd_block}\n\n"
        f"## Resume (raw text extracted from PDF/DOCX upload)\n"
        f"```\n{resume_text.strip()[:12000]}\n```\n\n"
        f"## Respond with JSON matching this schema exactly\n"
        f"{_SCHEMA_HINT}"
    )


# ---------------------------------------------------------------------------
# Anthropic call
# ---------------------------------------------------------------------------


def _call_anthropic(*, system: str, user: str, model: str) -> str:
    key = _api_key()
    if not key:
        raise ClaudeResumeMatcherError("ANTHROPIC_API_KEY is not set")

    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": 4000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=120.0) as client:
        r = client.post(ANTHROPIC_URL, headers=headers, json=body)
    if r.status_code >= 300:
        raise ClaudeResumeMatcherError(
            f"Anthropic API HTTP {r.status_code}: {r.text[:600]}"
        )
    data = r.json()
    blocks = data.get("content") or []
    for block in blocks:
        if block.get("type") == "text":
            text = block.get("text", "")
            if text:
                return text
    raise ClaudeResumeMatcherError(f"Anthropic returned no text block: {data}")


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        raise ClaudeResumeMatcherError(
            f"No JSON object found in model output: {text[:400]}"
        )
    try:
        return json.loads(m.group(0))
    except Exception as exc:
        raise ClaudeResumeMatcherError(
            f"Could not parse JSON from model output: {exc!r} — {text[:400]}"
        )


# ---------------------------------------------------------------------------
# Normalisation back into Profile + ExternalRecommendation
# ---------------------------------------------------------------------------


def _normalise(
    raw: Dict[str, Any],
    *,
    resume_text: str,
    jds: List[Job],
) -> Tuple[Profile, List[ExternalRecommendation]]:
    p = raw.get("profile") or {}
    email = str(p.get("email") or "").strip()
    if "@" not in email:
        # Belt-and-braces: dig the email out of the resume directly so we
        # always have something to key the candidate on.
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", resume_text or "")
        email = m.group(0) if m else "unknown@external.invalid"

    name = str(p.get("name") or "").strip() or "External Candidate"
    try:
        tenure = float(p.get("tenure_years") or 0)
    except Exception:
        tenure = 0.0

    skills_raw = p.get("skills") or []
    skills = [str(s).strip() for s in skills_raw if str(s).strip()]

    # Phone: prefer Claude's extraction, else fall back to regex scan over the
    # raw resume text. Real resumes embed phone numbers in many layouts and
    # Claude occasionally omits the field — the regex is the safety net so
    # the Review screen's Phone column is never silently empty.
    phone: Optional[str] = None
    raw_phone = str(p.get("phone") or "").strip()
    if raw_phone:
        digits_only = re.sub(r"[^\d+]", "", raw_phone)
        if len(re.sub(r"[^\d]", "", digits_only)) >= 10:
            phone = digits_only
    if not phone:
        _phone_patterns = [
            r"(?:Phone|Mobile|Cell|Tel|Contact|Ph)[\s.:#\-]*(\+?\d[\d\s\-().]{7,17}\d)",
            r"(\+91[\s\-]?\d{5}[\s\-]?\d{5})",
            r"(\+91[\s\-]?\d{10})",
            r"(?<!\d)([6-9]\d{9})(?!\d)",
            r"(\+\d{1,3}[\s\-]?\d[\d\s\-().]{7,15}\d)",
        ]
        for pat in _phone_patterns:
            m = re.search(pat, resume_text or "", re.IGNORECASE)
            if m:
                candidate_phone = m.group(1)
                digits_only = re.sub(r"[^\d+]", "", candidate_phone)
                if len(re.sub(r"[^\d]", "", digits_only)) >= 10:
                    phone = digits_only
                    break

    profile = Profile(
        employee_id=email,
        name=name,
        email=email,
        current_role=str(p.get("current_role") or "External Applicant").strip(),
        current_location=str(p.get("current_location") or "Unknown").strip(),
        tenure_years=tenure,
        kras=[],
        skills=skills,
        education=None,
        last_rating=None,
        phone=phone,
    )

    jd_by_id = {jd.id: jd for jd in jds}
    matches: List[ExternalRecommendation] = []
    for m in raw.get("matches") or []:
        if not isinstance(m, dict):
            continue
        jid = str(m.get("job_id") or "").strip()
        jd = jd_by_id.get(jid)
        if jd is None:
            continue
        try:
            pct = float(m.get("match_percent") or 0)
        except Exception:
            pct = 0.0
        pct = max(0.0, min(100.0, pct))

        matched = [str(s).strip() for s in (m.get("matched_skills") or []) if str(s).strip()]
        missing = [str(s).strip() for s in (m.get("missing_skills") or []) if str(s).strip()]

        matches.append(
            ExternalRecommendation(
                job_id=jd.id,
                job_title=jd.title,
                location=jd.location,
                match_percent=pct,
                matched_skills=matched,
                missing_skills=missing,
                rationale=str(m.get("rationale") or "").strip(),
            )
        )

    # Make sure every JD is represented even if Claude skipped one — fill
    # the gap with a 0-score row so the UI shows the full catalogue.
    seen = {m.job_id for m in matches}
    for jd in jds:
        if jd.id not in seen:
            matches.append(
                ExternalRecommendation(
                    job_id=jd.id,
                    job_title=jd.title,
                    location=jd.location,
                    match_percent=0.0,
                    matched_skills=[],
                    missing_skills=list(jd.required_skills),
                    rationale="Not scored by the agent",
                )
            )

    matches.sort(key=lambda r: r.match_percent, reverse=True)
    return profile, matches


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def match_resume(
    resume_text: str,
) -> Tuple[Profile, List[ExternalRecommendation], str]:
    """Parse a resume and rank it against every open JD using Claude.

    Returns ``(profile, matches, source)`` where ``source`` is ``'claude'``
    when the live API was used and ``'deterministic'`` when we fell back
    to the offline scorer (no key, network failure, malformed JSON, or
    operator-forced via ``AXIS_RESUME_MATCHER=deterministic``).
    """
    jds = list_open_jds()

    if _provider() != "claude":
        log.info("resume matcher: provider=deterministic (env override)")
        return _deterministic(resume_text, jds)

    if not _api_key():
        log.warning("resume matcher: no ANTHROPIC_API_KEY — falling back")
        return _deterministic(resume_text, jds)

    try:
        text = _call_anthropic(
            system=_SYSTEM_PROMPT,
            user=_build_user_message(resume_text=resume_text, jds=jds),
            model=_model(),
        )
        raw = _extract_json(text)
        profile, matches = _normalise(raw, resume_text=resume_text, jds=jds)
        log.info(
            "resume matcher: claude returned %d skills, top match %.0f%%",
            len(profile.skills),
            matches[0].match_percent if matches else 0,
        )
        return profile, matches, "claude"
    except Exception as exc:  # noqa: BLE001
        log.warning("resume matcher: Claude call failed (%r) — falling back", exc)
        return _deterministic(resume_text, jds)


def _deterministic(
    resume_text: str,
    jds: List[Job],
) -> Tuple[Profile, List[ExternalRecommendation], str]:
    """Offline fallback — uses the same parser/scorer the unit tests rely on."""
    from ..tools.external_intake import parse_resume, recommend_jobs

    profile = parse_resume(resume_text)
    matches = recommend_jobs(profile)
    return profile, matches, "deterministic"
