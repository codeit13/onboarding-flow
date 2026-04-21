"""Claude-backed salary slip extractor.

External candidates upload their latest salary slip during intake. This
service sends the extracted plain text to the Anthropic Messages API
and asks Claude to return a structured ``CompensationBreakdown`` —
current annual CTC plus the standard Indian payroll components (basic,
HRA, variable, special allowance, other).

Mirrors the pattern in ``claude_resume_matcher.py``: real Claude API
when available, deterministic regex fallback when not, and the same
return shape either way so callers don't branch on the source.

Why this matters
----------------
HR sees the candidate's current CTC + components on the application
card BEFORE the panel meeting, which lets the hiring manager think
about offer fit early. The orchestrator can also use the gross CTC for
basic offer-band sanity checks against the JD's expected band.

Environment
-----------
    ANTHROPIC_API_KEY=sk-ant-...
    AXIS_SALARY_EXTRACTOR=claude              # default; `deterministic` to force offline
    AXIS_SALARY_EXTRACTOR_MODEL=claude-sonnet-4-6
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import httpx

from ..models import CompensationBreakdown

log = logging.getLogger(__name__)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-sonnet-4-6"


class ClaudeSalaryExtractorError(RuntimeError):
    """Any failure calling or parsing the Anthropic API."""


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def _provider() -> str:
    return os.getenv("AXIS_SALARY_EXTRACTOR", "claude").strip().lower()


def _model() -> str:
    return (
        os.getenv("AXIS_SALARY_EXTRACTOR_MODEL", _DEFAULT_MODEL).strip()
        or _DEFAULT_MODEL
    )


def _api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are the Axis Bank hiring-agent compensation parser. An external "
    "candidate has uploaded their most recent monthly salary slip. Extract "
    "their compensation into the structured shape below.\n\n"
    "Rules:\n"
    "- All amounts are in Indian Rupees (INR). Convert lakhs/crores to "
    "rupees if the slip uses those units.\n"
    "- Annualise monthly figures: ``current_ctc`` and every component "
    "MUST be the ANNUAL value, not the monthly value. Multiply monthly "
    "earnings by 12.\n"
    "- ``current_ctc`` = the candidate's gross annual cost-to-company. "
    "If the slip shows a CTC line directly, use that. Otherwise sum the "
    "annualised earnings (basic + HRA + special allowance + other "
    "fixed) and add any explicit annual variable / bonus.\n"
    "- ``basic`` = annualised basic salary line.\n"
    "- ``hra`` = annualised house rent allowance line.\n"
    "- ``variable`` = annual variable / performance pay / bonus, if "
    "shown anywhere on the slip. Use 0 if not present.\n"
    "- ``special_allowance`` = annualised special / flexi allowance line.\n"
    "- ``other`` = sum of any remaining annualised earning lines.\n"
    "- ``employer`` = company name from the slip header.\n"
    "- ``pay_period`` = the month / year on the slip (e.g. \"Mar 2026\").\n"
    "- If the document is not a salary slip or is unreadable, return "
    "``current_ctc: null`` and put a short reason in ``notes``.\n"
    "- Respond with ONE JSON object matching the schema — no prose, no "
    "markdown fences, no explanation before or after."
)


_SCHEMA_HINT = """{
  "current_ctc": 1850000,
  "basic": 740000,
  "hra": 296000,
  "variable": 222000,
  "special_allowance": 444000,
  "other": 148000,
  "employer": "HDFC Bank Ltd.",
  "pay_period": "Mar 2026",
  "notes": "Optional short note for HR"
}"""


def _build_user_message(*, slip_text: str) -> str:
    return (
        f"## Salary slip (raw text extracted from PDF/DOCX upload)\n"
        f"```\n{slip_text.strip()[:8000]}\n```\n\n"
        f"## Respond with JSON matching this schema exactly\n"
        f"{_SCHEMA_HINT}"
    )


# ---------------------------------------------------------------------------
# Anthropic call
# ---------------------------------------------------------------------------


def _call_anthropic(*, system: str, user: str, model: str) -> str:
    key = _api_key()
    if not key:
        raise ClaudeSalaryExtractorError("ANTHROPIC_API_KEY is not set")

    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": 1500,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=60.0) as client:
        r = client.post(ANTHROPIC_URL, headers=headers, json=body)
    if r.status_code >= 300:
        raise ClaudeSalaryExtractorError(
            f"Anthropic API HTTP {r.status_code}: {r.text[:600]}"
        )
    data = r.json()
    blocks = data.get("content") or []
    for block in blocks:
        if block.get("type") == "text":
            text = block.get("text", "")
            if text:
                return text
    raise ClaudeSalaryExtractorError(f"Anthropic returned no text block: {data}")


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
        raise ClaudeSalaryExtractorError(
            f"No JSON object found in model output: {text[:400]}"
        )
    try:
        return json.loads(m.group(0))
    except Exception as exc:
        raise ClaudeSalaryExtractorError(
            f"Could not parse JSON from model output: {exc!r} — {text[:400]}"
        )


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if f < 0:
            return None
        return f
    except Exception:
        return None


def _normalise(
    raw: Dict[str, Any],
    *,
    source_filename: Optional[str],
    extraction_source: str,
) -> CompensationBreakdown:
    return CompensationBreakdown(
        current_ctc=_to_float(raw.get("current_ctc")),
        basic=_to_float(raw.get("basic")),
        hra=_to_float(raw.get("hra")),
        variable=_to_float(raw.get("variable")),
        special_allowance=_to_float(raw.get("special_allowance")),
        other=_to_float(raw.get("other")),
        employer=(str(raw.get("employer")).strip() if raw.get("employer") else None),
        pay_period=(str(raw.get("pay_period")).strip() if raw.get("pay_period") else None),
        source_filename=source_filename,
        extracted_at=datetime.utcnow(),
        extraction_source=extraction_source,  # type: ignore[arg-type]
        extraction_notes=(str(raw.get("notes")).strip() if raw.get("notes") else None),
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def extract_salary(
    slip_text: str,
    *,
    source_filename: Optional[str] = None,
) -> Tuple[CompensationBreakdown, str]:
    """Extract a structured compensation breakdown from a salary slip.

    Returns ``(breakdown, source)`` where ``source`` is ``'claude'`` when
    the live API was used and ``'deterministic'`` when we fell back to
    the offline regex parser.
    """
    if _provider() != "claude":
        log.info("salary extractor: provider=deterministic (env override)")
        return _deterministic(slip_text, source_filename=source_filename)

    if not _api_key():
        log.warning("salary extractor: no ANTHROPIC_API_KEY — falling back")
        return _deterministic(slip_text, source_filename=source_filename)

    try:
        text = _call_anthropic(
            system=_SYSTEM_PROMPT,
            user=_build_user_message(slip_text=slip_text),
            model=_model(),
        )
        raw = _extract_json(text)
        breakdown = _normalise(
            raw, source_filename=source_filename, extraction_source="claude"
        )
        log.info(
            "salary extractor: claude returned ctc=%s",
            breakdown.current_ctc,
        )
        return breakdown, "claude"
    except Exception as exc:  # noqa: BLE001
        log.warning("salary extractor: Claude call failed (%r) — falling back", exc)
        return _deterministic(slip_text, source_filename=source_filename)


# ---------------------------------------------------------------------------
# Deterministic fallback (regex over the salary slip text)
# ---------------------------------------------------------------------------


# Money pattern: comma-grouped (Indian "3,40,000" or international "340,000")
# OR a flat 4+ digit run. Anything shorter is rejected so year tokens like
# "FY25" or "2025" can never be misread as a real amount.
#  - 4+ digits also catches "2025" — but a year on its own line would
#    require a label match first, which we anchor before scanning.
_QUALIFYING_AMOUNT_RE = re.compile(
    r"(?:\u20B9|Rs\.?|INR)?\s*"
    r"((?:\d{1,3}(?:,\d{2,3})+(?:\.\d+)?)|(?:\d{4,}(?:\.\d+)?))"
)


def _grep_amount(label_pattern: str, text: str) -> Optional[float]:
    """Find the first qualifying money amount that follows ``label_pattern``.

    Algorithm: locate the label, then scan forward up to ~120 characters
    for the FIRST number that matches ``_QUALIFYING_AMOUNT_RE``. Stops
    at the next newline + label-looking line so we don't bleed into the
    next payslip row.

    A "qualifying" amount is one that is either comma-grouped or has 4+
    digits. This is what stops "(FY25 bonus)" from getting parsed as ₹25,
    which was a real bug we shipped before this rewrite.
    """
    label_re = re.compile(label_pattern, re.IGNORECASE)
    label_match = label_re.search(text)
    if not label_match:
        return None
    # Look at the next 120 chars after the label, but stop at the NEXT
    # newline that's followed by something that looks like a new line
    # of content — this keeps row boundaries clean on tab-extracted slips.
    window_start = label_match.end()
    window = text[window_start : window_start + 200]
    # If there's a newline, only consider up to the newline (each table
    # row is on its own line after our extractor walks docx tables).
    nl = window.find("\n")
    if nl != -1:
        window = window[:nl]
    amt_match = _QUALIFYING_AMOUNT_RE.search(window)
    if not amt_match:
        return None
    try:
        return float(amt_match.group(1).replace(",", ""))
    except Exception:
        return None


def _annualise(monthly: Optional[float]) -> Optional[float]:
    return None if monthly is None else round(monthly * 12, 2)


def _deterministic(
    slip_text: str,
    *,
    source_filename: Optional[str],
) -> Tuple[CompensationBreakdown, str]:
    """Offline regex parser used in tests + when Claude is unreachable."""
    text = slip_text or ""

    # Try to find an explicit annual CTC line first.
    ctc = _grep_amount(r"(?:annual\s+ctc|ctc\s+per\s+annum|ctc)", text)
    basic_monthly = _grep_amount(r"basic", text)
    hra_monthly = _grep_amount(r"\b(?:h\.?r\.?a\.?|house\s+rent\s+allowance)\b", text)
    variable_annual = _grep_amount(
        r"(?:variable\s+pay|annual\s+bonus|performance\s+pay)", text
    )
    special_monthly = _grep_amount(
        r"(?:special\s+allowance|flexi\s+benefit|flexible\s+benefit)", text
    )

    basic = _annualise(basic_monthly)
    hra = _annualise(hra_monthly)
    special = _annualise(special_monthly)

    if ctc is None:
        # Sum what we did find (annualised) — better than nothing for HR.
        parts = [p for p in [basic, hra, special, variable_annual] if p is not None]
        ctc = round(sum(parts), 2) if parts else None

    # Employer = first non-blank line, capped at 60 chars (slips usually
    # put the company logo / name at the top).
    employer = None
    for line in text.splitlines():
        line = line.strip()
        if line:
            employer = line[:60]
            break

    pay_period = None
    m = re.search(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2})",
        text,
        re.IGNORECASE,
    )
    if m:
        pay_period = m.group(1)

    breakdown = CompensationBreakdown(
        current_ctc=ctc,
        basic=basic,
        hra=hra,
        variable=variable_annual,
        special_allowance=special,
        other=None,
        employer=employer,
        pay_period=pay_period,
        source_filename=source_filename,
        extracted_at=datetime.utcnow(),
        extraction_source="deterministic",
        extraction_notes=(
            None
            if ctc is not None
            else "Could not parse a CTC figure from the slip text"
        ),
    )
    return breakdown, "deterministic"


__all__ = [
    "extract_salary",
    "ClaudeSalaryExtractorError",
]
