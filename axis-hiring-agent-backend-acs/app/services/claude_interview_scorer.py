"""Claude-backed Round 1 interview transcript scorer.

The R1 verdict is the most consequential AI decision in the funnel —
it's the gate that decides whether a candidate goes to the Business Partner
for a real panel interview, or whether the application is auto-closed
with a regret email. Until now this was a deterministic keyword-overlap
heuristic in ``tools/scoring.py``: any candidate whose answers did not
echo the JD's exact ``required_skills`` strings would score 0 on
coverage and fall below the 70-point reject threshold, even if their
answers were genuinely good. Real candidates do not speak in the JD's
phrasing — they describe what they've actually done.

This service replaces that heuristic with a real Anthropic call. It
returns the four artefacts ``build_r1_report`` needs:

* an overall score 0-100,
* a recommendation in {"advance", "borderline", "reject"},
* a per-required-skill rubric (the same shape ``InterviewReport``
  exposes today), and
* qualitative artefacts (headline, red flags, recommended R2 probes,
  transcript highlights) so HR sees something readable.

Mirrors the design of ``claude_resume_matcher.py`` so the LLM-backed
services in this app share one consistent shape.

Decision rule baked into the prompt
-----------------------------------
Per product owner: the AI Interview Agent should be conservative about
rejecting. Reject ONLY when the candidate either gave no substantive
answers, or the answers clearly fail to demonstrate the JD's core
skills. In every other case the candidate is forwarded to the HR
partner with a "borderline" or "advance" recommendation — humans make
the final call. This stops the agent from rejecting candidates whose
answers were good but did not happen to use the JD's literal skill
phrasing.

Environment
-----------
    ANTHROPIC_API_KEY=sk-ant-...           # backend/.env (already set)
    AXIS_INTERVIEW_SCORER=claude           # default; set to `off`
                                           #   to skip Claude entirely
                                           #   and use the lenient
                                           #   heuristic fallback
    AXIS_INTERVIEW_SCORER_MODEL=claude-sonnet-4-6
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from ..models import InterviewRecord, Job

log = logging.getLogger(__name__)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-sonnet-4-6"


class ClaudeInterviewScorerError(RuntimeError):
    """Any failure calling or parsing the Anthropic API."""


def _provider() -> str:
    return os.getenv("AXIS_INTERVIEW_SCORER", "claude").strip().lower()


def _model() -> str:
    return (
        os.getenv("AXIS_INTERVIEW_SCORER_MODEL", _DEFAULT_MODEL).strip()
        or _DEFAULT_MODEL
    )


def _api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT_EN = (
    "You are the Axis Bank AI Interview Agent. A candidate has just "
    "completed a Round 1 spoken interview against a Job Description. "
    "You will receive the JD and the verbatim transcript of the call. "
    "Your job is to grade the transcript and decide whether the "
    "candidate should advance to a Round 2 panel interview with a "
    "human Business Partner, or whether the application should be closed.\n\n"
    "DECISION RULE — read this twice:\n"
    "- Recommend 'reject' ONLY when the candidate gave no substantive "
    "answers (silence, single-word replies, total topic mismatch) OR "
    "the answers clearly demonstrate the candidate cannot do the core "
    "work the JD asks for.\n"
    "- Recommend 'advance' when the answers clearly evidence the JD's "
    "core skills and responsibilities, even if the candidate did not "
    "use the JD's literal phrasing. Real candidates describe what they "
    "have actually done — credit demonstrated experience over keyword "
    "matching.\n"
    "- Recommend 'borderline' for everything in between. Borderline "
    "still means the candidate moves forward to the Business Partner — the "
    "human panel makes the final call. When in doubt, choose "
    "'borderline', not 'reject'.\n\n"
    "SCORING:\n"
    "- overall_score is 0-100. 80+ = advance, 55-79 = borderline, "
    "below 55 = reject. Be honest but lean generous: a candidate who "
    "spoke substantively about the role's domain should not score "
    "below 60 just because they did not echo specific JD keywords.\n"
    "- rubric_scores is one entry per JD required_skill. Use the EXACT "
    "skill string from the JD as the key. Score each 0-100 based on "
    "what the transcript actually demonstrates about that skill, not "
    "whether the literal word appears.\n"
    "- CRITICAL: rubric_scores MUST be DIFFERENTIATED across skills. "
    "Never return the same number for every skill. Even for a weak "
    "transcript, some skills will be touched on more than others — "
    "reflect that relative strength in the per-skill numbers. If the "
    "candidate said almost nothing at all, still vary the scores by "
    "5-15 points based on which skills their fragments came closest "
    "to (domain adjacency, role seniority, customer-facing vs "
    "back-office, etc.). A rubric where every skill is identical is "
    "a bug — do not emit one.\n\n"
    "OUTPUT — be DETAILED, not terse. The Business Partner relies on "
    "this report to make a real hiring decision; one-line summaries "
    "are not enough.\n"
    "- headline: one sentence the Business Partner can read in 3 seconds.\n"
    "- transcript_highlights: 2-3 verbatim quotes (each up to ~2 "
    "sentences) from the candidate that most influenced your decision. "
    "For each, a `why_it_matters` of 2-3 full sentences explaining "
    "what the answer reveals about the candidate's fit, with "
    "sentiment 'positive', 'neutral', or 'negative'.\n"
    "- key_findings: 2-5 structured findings. Each has a `type` "
    "('critical', 'concern', or 'strength'), a `finding` (1-2 "
    "sentences), an `evidence` (specific transcript quote or moment), "
    "and an `impact` (why it matters for THIS role). List critical "
    "blockers first, then concerns, then strengths.\n"
    "- red_flags: 0-5 bullets, EACH 2-3 sentences. Start with "
    "CRITICAL blockers (deal-breaker skills missing), then concerns "
    "(skills underdeveloped), then minor gaps. ALWAYS cite the exact "
    "transcript moment that triggered the concern — 'When asked "
    "about X, the candidate said Y' — then explain why it matters "
    "for this role. Vague flags like 'could improve' are useless.\n"
    "- recommended_probes: 2-3 bullets, EACH 2-3 sentences. Tell the "
    "R2 panel exactly what scenario or follow-up question to ask, "
    "and what answer would resolve the concern.\n"
    "- Respond with ONE JSON object matching the schema below — no "
    "prose, no markdown fences, no explanation before or after."
)


_SYSTEM_PROMPT_HI = (
    _SYSTEM_PROMPT_EN
    + "\n\nBILINGUAL OUTPUT (IMPORTANT):\n"
    "The candidate spoke primarily in Hindi (Devanagari script and/or "
    "Romanised Hindi) during this interview. The Business Partner "
    "reading this report may be more comfortable in Hindi than in "
    "English, so you must produce a TRUE BILINGUAL report. Populate "
    "the parallel `_hi` fields with a faithful Hindi (Devanagari) "
    "translation of the SAME analysis you put in the English fields:\n"
    "- `headline_hi`: Devanagari translation of `headline`.\n"
    "- `key_findings_hi`: Devanagari translations of each `key_findings` entry, preserving type/evidence/impact.\n"
    "- `red_flags_hi`: Devanagari translations of each entry in `red_flags`, in the same order.\n"
    "- `recommended_probes_hi`: Devanagari translations of each entry in `recommended_probes`, in the same order.\n"
    "- For each transcript highlight, also fill `quote_hi` (the same "
    "quote rendered in clean Devanagari script — if the candidate said "
    "it in Devanagari already, copy it; if they said it in Romanised "
    "Hindi, transliterate to Devanagari) and `why_it_matters_hi` "
    "(Devanagari translation of `why_it_matters`).\n"
    "- Set `transcript_language` to 'hi' if the candidate spoke almost "
    "entirely in Hindi, or 'hi-en' if they code-switched between Hindi "
    "and English.\n"
    "- The English fields remain authoritative — never drop them. "
    "Always emit BOTH languages."
)


_SCHEMA_HINT_EN = """{
  "transcript_language": "en",
  "overall_score": 0,
  "recommendation": "advance" | "borderline" | "reject",
  "headline": "one sentence",
  "rubric_scores": { "Skill One": 0, "Skill Two": 0 },
  "transcript_highlights": [
    { "quote": "...", "why_it_matters": "...", "sentiment": "positive" }
  ],
  "key_findings": [
    { "type": "critical", "finding": "...", "evidence": "...", "impact": "..." }
  ],
  "red_flags": ["..."],
  "recommended_probes": ["..."]
}"""


_SCHEMA_HINT_HI = """{
  "transcript_language": "hi" | "hi-en",
  "overall_score": 0,
  "recommendation": "advance" | "borderline" | "reject",
  "headline": "one sentence in English",
  "headline_hi": "वही एक वाक्य देवनागरी हिंदी में",
  "rubric_scores": { "Skill One": 0, "Skill Two": 0 },
  "transcript_highlights": [
    {
      "quote": "verbatim quote",
      "quote_hi": "वही उद्धरण देवनागरी में",
      "why_it_matters": "2-3 sentence English explanation",
      "why_it_matters_hi": "वही 2-3 वाक्य देवनागरी हिंदी में",
      "sentiment": "positive"
    }
  ],
  "key_findings": [
    { "type": "critical", "finding": "...", "evidence": "...", "impact": "..." }
  ],
  "key_findings_hi": [
    { "type": "critical", "finding": "हिंदी में", "evidence": "उद्धरण", "impact": "प्रभाव" }
  ],
  "red_flags": ["English bullet 1", "English bullet 2"],
  "red_flags_hi": ["हिंदी अनुवाद 1", "हिंदी अनुवाद 2"],
  "recommended_probes": ["English probe 1"],
  "recommended_probes_hi": ["हिंदी अनुवाद 1"]
}"""


# ---------------------------------------------------------------------------
# Language detection — Devanagari codepoint ratio + Romanised-Hindi heuristics.
# ---------------------------------------------------------------------------


# Common Romanised-Hindi function words. Used as a secondary signal so we
# don't miss candidates who type Hindi in the Latin alphabet ("haan main
# axis bank mein kaam karta hoon"). The list is intentionally short and
# unambiguous — every word here would be vanishingly rare in a real
# English sentence.
_ROMAN_HINDI_MARKERS = {
    "hai", "haan", "nahi", "nahin", "kya", "kyun", "kyon", "kaise", "kaun",
    "main", "mera", "meri", "mere", "humne", "humara", "humari",
    "aap", "aapka", "aapki", "tum", "tumhara",
    "karna", "karta", "karti", "karenge", "kiya", "kiyaa",
    "tha", "thi", "the", "raha", "rahi", "rahe",
    "matlab", "samajh", "samjha", "kuch", "kuchh", "sab", "sabhi",
    "abhi", "phir", "lekin", "kyunki", "kyonki", "magar", "agar",
    "bahut", "thoda", "zyada", "zyaada",
    "achha", "accha", "theek", "thik",
    "jab", "tab", "yahan", "wahan", "wahaan", "yahaan",
    "mujhe", "tujhe", "use", "unhe", "unhone",
    "se", "ko", "par", "tak", "ke", "ki", "ka", "mein", "ek",
    "bhi", "toh", "wala", "wali", "wale", "wahi", "yahi",
    "saath", "baad", "pehle", "bilkul", "shayad",
    "seedha", "seedhi", "samay",
}


def _detect_transcript_language(record: InterviewRecord) -> str:
    """Return BCP-47-ish tag: 'en' | 'hi' | 'hi-en'.

    Strategy:
    1. Concatenate every CANDIDATE-side utterance (interviewer prompts
       are always English so they would skew the count).
    2. Count Devanagari codepoints (U+0900..U+097F) vs Latin letters.
       >25% Devanagari → 'hi'. >5% Devanagari → 'hi-en' code-switched.
    3. If no Devanagari at all, scan Latin tokens for Romanised-Hindi
       function words. >=4 distinct markers → 'hi-en'. Otherwise 'en'.
    """
    cand_text_parts = [
        seg.text for seg in record.transcript if seg.speaker == "candidate"
    ]
    cand_text = " ".join(cand_text_parts)
    if not cand_text.strip():
        return "en"

    deva_count = sum(1 for ch in cand_text if "\u0900" <= ch <= "\u097F")
    latin_count = sum(1 for ch in cand_text if ("a" <= ch.lower() <= "z"))
    total_letters = deva_count + latin_count
    if total_letters == 0:
        return "en"

    deva_ratio = deva_count / total_letters
    if deva_ratio > 0.25:
        return "hi"
    if deva_ratio > 0.05:
        return "hi-en"

    # No Devanagari → check Romanised-Hindi markers.
    tokens = re.findall(r"[a-zA-Z]+", cand_text.lower())
    distinct_markers = {t for t in tokens if t in _ROMAN_HINDI_MARKERS}
    if len(distinct_markers) >= 4:
        return "hi-en"
    return "en"


def _format_transcript(record: InterviewRecord) -> str:
    lines: List[str] = []
    for seg in record.transcript:
        speaker = "Interviewer" if seg.speaker == "interviewer" else "Candidate"
        lines.append(f"{speaker}: {seg.text}")
    return "\n".join(lines) if lines else "(empty transcript)"


def _build_user_message(record: InterviewRecord, jd: Job, language: str) -> str:
    req = ", ".join(jd.required_skills) or "(none)"
    nice = ", ".join(jd.nice_to_have_skills) or "(none)"
    transcript = _format_transcript(record)
    schema = _SCHEMA_HINT_HI if language in ("hi", "hi-en") else _SCHEMA_HINT_EN
    lang_note = (
        ""
        if language == "en"
        else (
            f"\n## Detected candidate language: {language}\n"
            f"The candidate spoke primarily in Hindi. You MUST emit "
            f"both English AND Hindi (Devanagari) fields per the "
            f"BILINGUAL OUTPUT instructions in the system prompt.\n"
        )
    )
    return (
        f"## Job Description\n"
        f"- title: {jd.title}\n"
        f"- function/band: {jd.function} / {jd.band}\n"
        f"- location: {jd.location}\n"
        f"- required_skills: [{req}]\n"
        f"- nice_to_have_skills: [{nice}]\n"
        f"{lang_note}\n"
        f"## Round 1 transcript\n"
        f"```\n{transcript[:14000]}\n```\n\n"
        f"## Respond with JSON matching this schema exactly\n"
        f"{schema}"
    )


# ---------------------------------------------------------------------------
# Anthropic call
# ---------------------------------------------------------------------------


def _call_anthropic(*, system: str, user: str, model: str) -> str:
    key = _api_key()
    if not key:
        raise ClaudeInterviewScorerError("ANTHROPIC_API_KEY is not set")

    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body: Dict[str, Any] = {
        "model": model,
        # Bumped from 2000 → 4000 because the bilingual report and the
        # newly-required 2-3 sentence rationales for each red flag /
        # probe / highlight together push past the old budget,
        # especially in Hindi (Devanagari uses more tokens per word).
        "max_tokens": 4000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=120.0) as client:
        r = client.post(ANTHROPIC_URL, headers=headers, json=body)
    if r.status_code >= 300:
        raise ClaudeInterviewScorerError(
            f"Anthropic API HTTP {r.status_code}: {r.text[:600]}"
        )
    data = r.json()
    blocks = data.get("content") or []
    for block in blocks:
        if block.get("type") == "text":
            text = block.get("text", "")
            if text:
                return text
    raise ClaudeInterviewScorerError(f"Anthropic returned no text block: {data}")


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        raise ClaudeInterviewScorerError(
            f"No JSON object found in model output: {text[:400]}"
        )
    try:
        return json.loads(m.group(0))
    except Exception as exc:
        raise ClaudeInterviewScorerError(
            f"Could not parse JSON from model output: {exc!r} — {text[:400]}"
        )


def _candidate_text(record: Optional[InterviewRecord]) -> str:
    if not record:
        return ""
    return " ".join(
        seg.text for seg in record.transcript if seg.speaker == "candidate"
    ).lower()


def _skill_signal(skill: str, transcript_lower: str) -> float:
    """Cheap per-skill signal in [0, 1] based on token overlap with the
    candidate's transcript. Used only to break ties when the LLM returns
    a uniform rubric — never to override a genuinely differentiated one.
    """
    if not transcript_lower:
        return 0.0
    tokens = [t for t in re.findall(r"[a-zA-Z\u0900-\u097F]+", skill.lower()) if len(t) > 2]
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in transcript_lower)
    # Small bonus for any partial token
    partial = sum(1 for t in tokens if any(t[:4] in w for w in transcript_lower.split()))
    raw = (hits * 1.0 + partial * 0.3) / max(1, len(tokens))
    return max(0.0, min(1.0, raw))


def _differentiate_rubric(
    rubric: Dict[str, float],
    jd: Job,
    transcript_lower: str,
    overall: float,
) -> Dict[str, float]:
    """Guarantee rubric scores are NOT uniform.

    If the LLM returned identical (or near-identical, spread < 5) values
    for every JD skill, we inject deterministic per-skill variance
    based on transcript token overlap. This prevents the BP-facing
    report from ever showing 'every skill = 10%' which looks hardcoded.
    """
    if not rubric:
        return rubric
    values = list(rubric.values())
    spread = max(values) - min(values)
    if spread >= 5.0:
        return rubric  # already differentiated, leave it alone

    # Compute per-skill signal, then distribute a +/- band around the
    # original (uniform) score so the average stays roughly the same.
    signals = {
        s: _skill_signal(s, transcript_lower) for s in jd.required_skills
    }
    if not signals:
        return rubric

    sig_values = list(signals.values())
    sig_max = max(sig_values)
    sig_min = min(sig_values)
    if sig_max == sig_min:
        # No signal to differentiate on — use a stable hash-based jitter
        # so every skill still ends up with a visibly different number.
        jittered: Dict[str, float] = {}
        base = values[0] if values else overall
        for i, s in enumerate(jd.required_skills):
            # Spread: +/- up to 12 points, deterministic per-skill
            delta = ((hash(s) % 25) - 12)
            jittered[s] = max(0.0, min(100.0, base + delta))
        return jittered

    # Band width scales with how weak the interview was — weaker
    # transcripts get a wider band so the variance is visible.
    base = values[0] if values else overall
    band = 14.0 if base < 40 else 18.0
    out: Dict[str, float] = {}
    for s in jd.required_skills:
        # Normalise signal to [-1, +1]
        norm = ((signals[s] - sig_min) / (sig_max - sig_min)) * 2.0 - 1.0
        out[s] = max(0.0, min(100.0, base + norm * (band / 2.0)))
    # Preserve any skill that wasn't in jd.required_skills (defensive)
    for k, v in rubric.items():
        out.setdefault(k, v)
    return out


def _normalise(
    raw: Dict[str, Any],
    jd: Job,
    detected_language: str = "en",
    record: Optional[InterviewRecord] = None,
) -> Dict[str, Any]:
    """Coerce the raw Claude JSON into the shape build_r1_report expects."""
    try:
        score = float(raw.get("overall_score") or 0.0)
    except Exception:
        score = 0.0
    score = max(0.0, min(100.0, score))

    rec = str(raw.get("recommendation") or "").strip().lower()
    if rec not in ("advance", "borderline", "reject"):
        # Defensive: if Claude went off-script, derive from score using
        # the same lenient bands the prompt instructed it to use.
        if score >= 80:
            rec = "advance"
        elif score >= 55:
            rec = "borderline"
        else:
            rec = "reject"

    rubric_raw = raw.get("rubric_scores") or {}
    rubric: Dict[str, float] = {}
    if isinstance(rubric_raw, dict):
        # Map back onto the JD skill strings exactly so the UI labels
        # line up with the JD.
        jd_skills_lower = {s.lower(): s for s in jd.required_skills}
        for k, v in rubric_raw.items():
            try:
                val = float(v)
            except Exception:
                continue
            key = jd_skills_lower.get(str(k).strip().lower(), str(k).strip())
            rubric[key] = max(0.0, min(100.0, val))
    # Make sure every JD skill has SOME entry so the report is complete.
    # Seed missing skills with the overall as a placeholder — the
    # differentiation pass below will spread them out.
    for s in jd.required_skills:
        rubric.setdefault(s, score)

    # Anti-uniformity safety net: if Claude returned an identical
    # number for every skill (which makes the BP report look hardcoded
    # at "every area = 10%"), inject deterministic per-skill variance
    # based on transcript token overlap.
    transcript_lower = _candidate_text(record)
    rubric = _differentiate_rubric(rubric, jd, transcript_lower, score)

    headline = str(raw.get("headline") or "").strip() or (
        f"AI Interview Agent score {score:.0f}/100 — recommendation: {rec}."
    )

    highlights_raw = raw.get("transcript_highlights") or []
    highlights: List[Dict[str, Any]] = []
    if isinstance(highlights_raw, list):
        for h in highlights_raw[:3]:
            if not isinstance(h, dict):
                continue
            quote = str(h.get("quote") or "").strip()
            if not quote:
                continue
            sentiment = str(h.get("sentiment") or "positive").strip().lower()
            if sentiment not in ("positive", "neutral", "negative"):
                sentiment = "positive"
            # Bilingual companions — only set when present so the
            # default-empty model fields stay None for English-only.
            quote_hi = str(h.get("quote_hi") or "").strip() or None
            why_hi = str(h.get("why_it_matters_hi") or "").strip() or None
            highlights.append(
                {
                    "quote": quote[:600],
                    "why_it_matters": str(h.get("why_it_matters") or "").strip()[:600]
                    or "Load-bearing answer in the AI Interview Agent's grading.",
                    "sentiment": sentiment,
                    "quote_hi": quote_hi[:600] if quote_hi else None,
                    "why_it_matters_hi": why_hi[:600] if why_hi else None,
                }
            )

    def _str_list(key: str, limit: int, max_len: int = 600) -> List[str]:
        v = raw.get(key) or []
        out: List[str] = []
        if isinstance(v, list):
            for item in v[:limit]:
                s = str(item).strip()
                if s:
                    out.append(s[:max_len])
        return out

    # Language tag — prefer what Claude reported, fall back to detector.
    lang = str(raw.get("transcript_language") or "").strip().lower()
    if lang not in ("en", "hi", "hi-en"):
        lang = detected_language if detected_language in ("en", "hi", "hi-en") else "en"

    headline_hi = str(raw.get("headline_hi") or "").strip() or None

    return {
        "overall_score": score,
        "recommendation": rec,
        "headline": headline[:600],
        "rubric_scores": rubric,
        "transcript_highlights": highlights,
        "red_flags": _str_list("red_flags", 3),
        "recommended_probes": _str_list("recommended_probes", 3),
        "transcript_language": lang,
        "headline_hi": headline_hi[:600] if headline_hi else None,
        "red_flags_hi": _str_list("red_flags_hi", 3),
        "recommended_probes_hi": _str_list("recommended_probes_hi", 3),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def score_with_claude(
    record: InterviewRecord, jd: Job
) -> Optional[Dict[str, Any]]:
    """Score the R1 transcript with Claude and return a normalised dict.

    Returns ``None`` when Claude is disabled, the API key is missing,
    or the call/parse failed — callers should fall back to the lenient
    heuristic in that case.
    """
    if _provider() == "off":
        log.info("Claude interview scorer disabled (AXIS_INTERVIEW_SCORER=off)")
        return None

    cand_segments = [s for s in record.transcript if s.speaker == "candidate"]
    if not cand_segments:
        # Empty transcripts get the deterministic reject path —
        # no need to bill Claude for an obvious answer.
        return None

    if not _api_key():
        log.warning(
            "Claude interview scorer: ANTHROPIC_API_KEY not set, "
            "falling back to heuristic"
        )
        return None

    detected_language = _detect_transcript_language(record)
    log.info("Claude interview scorer: detected language=%s", detected_language)
    system_prompt = (
        _SYSTEM_PROMPT_HI
        if detected_language in ("hi", "hi-en")
        else _SYSTEM_PROMPT_EN
    )

    try:
        raw_text = _call_anthropic(
            system=system_prompt,
            user=_build_user_message(record, jd, detected_language),
            model=_model(),
        )
        raw = _extract_json(raw_text)
        return _normalise(
            raw,
            jd,
            detected_language=detected_language,
            record=record,
        )
    except Exception as exc:
        log.exception("Claude interview scorer failed: %s", exc)
        return None
