"""Claude-backed onboarding assistant for offered + accepted candidates.

Loads Axis Bank policy docs from ``app/knowledge/`` (general + per-role
markdown files) and lets the candidate ask free-text questions about
culture, travel, reimbursement, leave, benefits, onboarding schedule,
etc. Answers are always grounded in the loaded docs and **contextualised
to the role the candidate was hired for** (Branch Manager, BDM,
Relationship Manager, etc.).

Design mirrors the other Claude services in this package:
  - env toggle (``AXIS_ONBOARDING_ASSISTANT=claude|deterministic``)
  - deterministic fallback so the UI always gets a reply even without the key
  - shape is identical across providers so the caller doesn't branch
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-sonnet-4-6"

# Repo-relative knowledge base
_KB_DIR = Path(__file__).resolve().parent.parent / "knowledge"
_GENERAL_DIR = _KB_DIR / "general"
_ROLES_DIR = _KB_DIR / "roles"


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


@dataclass
class AssistantReply:
    answer: str
    role_file_used: str  # which role doc was selected (filename or "default")
    source: str  # "claude" | "deterministic"
    # Citations grounding the answer. Each entry is
    # ``{"doc": "general/travel_policy.md", "section": "Domestic Travel …"}``
    # so the onboarding team can verify exactly which KB passage the
    # assistant relied on.
    citations: List[Dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------


def _provider() -> str:
    return os.getenv("AXIS_ONBOARDING_ASSISTANT", "claude").strip().lower()


def _model() -> str:
    return (
        os.getenv("AXIS_ONBOARDING_ASSISTANT_MODEL", _DEFAULT_MODEL).strip()
        or _DEFAULT_MODEL
    )


def _api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


# ---------------------------------------------------------------------------
# Role mapping — picks the right role doc from the job title.
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    return title.lower().replace("-", " ").replace("_", " ")


def _pick_role_file(job_title: str) -> Path:
    """Pick the most relevant role doc for a given JD title.

    Heuristic keyword match against the files in ``roles/``. Falls back
    to ``default.md``.
    """
    t = _slugify(job_title or "")
    candidates: List[Tuple[int, Path]] = []

    mapping = {
        "branch_manager.md": ["branch manager", "branch head", "flagship"],
        "business_development_manager.md": [
            "business development",
            "bdm",
            "corporate salary",
            "sales manager",
        ],
        "relationship_manager.md": [
            "relationship manager",
            "wealth",
            "burgundy",
            "priority",
            "portfolio manager",
        ],
    }
    for fname, keywords in mapping.items():
        score = sum(1 for kw in keywords if kw in t)
        if score:
            candidates.append((score, _ROLES_DIR / fname))

    if candidates:
        candidates.sort(key=lambda x: -x[0])
        return candidates[0][1]
    return _ROLES_DIR / "default.md"


def _load_kb(job_title: str) -> Tuple[str, str]:
    """Concatenate general docs + the chosen role doc.

    Each doc is framed with an explicit ``DOC_ID`` marker that Claude is
    instructed to reference in its citations (e.g. ``general/culture.md``).
    Returns ``(corpus_text, role_file_name)``.
    """
    general_chunks: List[str] = []
    if _GENERAL_DIR.exists():
        for md in sorted(_GENERAL_DIR.glob("*.md")):
            try:
                doc_id = f"general/{md.name}"
                general_chunks.append(
                    f"\n\n===== DOC_ID: {doc_id} =====\n{md.read_text()}"
                )
            except Exception as exc:  # pragma: no cover
                log.warning("Skipping %s: %s", md, exc)

    role_file = _pick_role_file(job_title)
    role_text = ""
    if role_file.exists():
        try:
            doc_id = f"roles/{role_file.name}"
            role_text = (
                f"\n\n===== DOC_ID: {doc_id} =====\n{role_file.read_text()}"
            )
        except Exception as exc:  # pragma: no cover
            log.warning("Role file %s unreadable: %s", role_file, exc)

    corpus = "".join(general_chunks) + role_text
    return corpus, role_file.name


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are the Axis Bank onboarding assistant. A candidate who has accepted an "
    "offer is chatting with you in the candidate portal (Thrive). Your job is to "
    "answer their onboarding questions warmly, accurately, and in the context "
    "of the specific role they've been hired for.\n\n"
    "Rules:\n"
    "- Ground every answer in the POLICY KNOWLEDGE BASE below. Quote specific "
    "numbers, caps, or deadlines when the docs contain them. Do not invent "
    "figures.\n"
    "- When the docs differ by band or role (travel class, insurance cover, "
    "fuel reimbursement, etc.), use the candidate's role + band to give the "
    "right row. The candidate's role is provided in the CONTEXT block.\n"
    "- If the question is clearly outside the KB (e.g. 'which ATM is nearest', "
    "'what's the stock price'), say so and suggest a human SPOC.\n"
    "- Tone: warm, concise, second-person. No corporate jargon. No AI "
    "language ('as an AI', 'I'm a model', etc.).\n"
    "- Keep replies under 180 words unless the user explicitly asks for more "
    "detail. Use short bullet points when listing numbers/limits.\n"
    "- If the KB is silent on a point, say so honestly and point them to the "
    "right email from the KB (payroll, HR Ops, IT helpdesk, onboarding team).\n\n"
    "CITATIONS (mandatory):\n"
    "Every KB doc is introduced by an exact line ``===== DOC_ID: <path> =====`` "
    "followed by its markdown, whose ``##`` headings are the section names. "
    "You MUST list every doc + section you actually used in a citations "
    "array.\n\n"
    "OUTPUT FORMAT (strict):\n"
    "Respond with ONE JSON object, no prose, no markdown fences, matching:\n"
    "{\n"
    '  "answer": "<the warm, candidate-facing reply>",\n'
    '  "citations": [\n'
    '    { "doc": "<DOC_ID exactly as shown>", "section": "<H2/H3 heading or a short descriptor>" }\n'
    "  ]\n"
    "}\n"
    "If the KB genuinely had nothing relevant, return citations: []."
)


def _build_user_message(
    question: str,
    candidate_name: str,
    job_title: str,
    job_band: Optional[str],
    expected_joining_date: Optional[str],
    kb_text: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Assemble the user-turn text for Claude."""
    history_block = ""
    if chat_history:
        turns = []
        for m in chat_history[-8:]:  # keep last 8 turns, stay inside context budget
            who = "Candidate" if m.get("direction") == "inbound" else "Assistant"
            turns.append(f"{who}: {m.get('body','').strip()}")
        if turns:
            history_block = (
                "=== RECENT CHAT HISTORY ===\n" + "\n".join(turns) + "\n\n"
            )

    ctx = (
        f"=== CANDIDATE CONTEXT ===\n"
        f"Name: {candidate_name or 'Candidate'}\n"
        f"Hired for: {job_title or 'Axis Bank role'}\n"
        f"Band: {job_band or 'as per offer letter'}\n"
        f"Expected joining date: {expected_joining_date or 'see offer letter'}\n\n"
    )
    return (
        ctx
        + history_block
        + f"=== POLICY KNOWLEDGE BASE ===\n{kb_text[:18000]}\n\n"
        + f"=== CANDIDATE QUESTION ===\n{question.strip()}\n\n"
        + "Answer the candidate's question using the KB above, contextualised "
        "to their role. Do not prefix with 'Answer:' — reply directly."
    )


# ---------------------------------------------------------------------------
# Claude path
# ---------------------------------------------------------------------------


def _call_claude(
    question: str,
    candidate_name: str,
    job_title: str,
    job_band: Optional[str],
    expected_joining_date: Optional[str],
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> AssistantReply:
    api_key = _api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    kb_text, role_file = _load_kb(job_title or "")
    user_msg = _build_user_message(
        question=question,
        candidate_name=candidate_name,
        job_title=job_title,
        job_band=job_band,
        expected_joining_date=expected_joining_date,
        kb_text=kb_text,
        chat_history=chat_history,
    )
    payload = {
        "model": _model(),
        "max_tokens": 700,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_msg}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    with httpx.Client(timeout=45) as client:
        resp = client.post(ANTHROPIC_URL, json=payload, headers=headers)
        resp.raise_for_status()

    body = resp.json()
    raw_text = body["content"][0]["text"].strip()

    # Strip markdown fences if Claude wraps them despite the instruction.
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    answer_text = cleaned
    citations: List[Dict[str, str]] = []
    try:
        data = json.loads(cleaned)
        answer_text = str(data.get("answer", cleaned)).strip()
        raw_cits = data.get("citations") or []
        if isinstance(raw_cits, list):
            for c in raw_cits:
                if not isinstance(c, dict):
                    continue
                doc = str(c.get("doc") or "").strip()
                section = str(c.get("section") or "").strip()
                if doc:
                    citations.append({"doc": doc, "section": section})
    except json.JSONDecodeError:
        log.warning("Onboarding assistant returned non-JSON; using raw text.")

    return AssistantReply(
        answer=answer_text,
        role_file_used=role_file,
        source="claude",
        citations=citations,
    )


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------


def _deterministic(
    question: str,
    candidate_name: str,
    job_title: str,
) -> AssistantReply:
    """Keyword-based canned reply so the UI always has a response."""
    q = question.lower()
    role_file = _pick_role_file(job_title or "").name
    if any(k in q for k in ["culture", "values", "pride", "dei"]):
        ans = (
            f"Hi {candidate_name or 'there'} — Axis's culture is built on five "
            "values: customer centricity, ethics, teamwork, ownership, and "
            "execution. There's an active diversity network (GiG Axis, Axis "
            "Ability, Pride@Axis) and a zero-tolerance POSH policy. Quarterly "
            "1:1s and annual 360° feedback are standard."
        )
    elif any(k in q for k in ["travel", "flight", "hotel", "ticket"]):
        ans = (
            "Travel entitlements are band-based (economy for AM/DM/SM/CM-VP; "
            "business for SVP+). Domestic hotel tariffs range ₹3.5K–₹12K "
            "depending on tier/band. Raise requests in Concur before travel "
            "and submit receipts within 15 days. Full policy: travel.desk@axisbank.com."
        )
    elif any(k in q for k in ["reimburse", "mobile", "internet", "fuel", "meal"]):
        ans = (
            "Monthly reimbursements: mobile (₹1.2K–₹2.5K by band), broadband "
            "(₹1K–₹2K), meal vouchers (₹2.2K–₹2.5K Sodexo). Fuel cards start at "
            "SM band (₹15K/month). Learning & development is ₹25K/year (AM-SM) "
            "or ₹50K (CM+). Claims go through Concur."
        )
    elif any(k in q for k in ["leave", "holiday", "vacation", "pl ", "sick"]):
        ans = (
            "You get 30 days Privilege Leave, 8 Casual, 10 Sick, plus 14 public "
            "holidays. Maternity: 26 weeks paid; paternity: 10 days. Apply via "
            "Axis People Connect. Branch and BDM roles are fully on-site; "
            "corporate roles are 3 days in / 2 days WFH."
        )
    elif any(k in q for k in ["insurance", "medical", "health", "gmc", "gpa"]):
        ans = (
            "GMC family floater: ₹5L (AM/DM) → ₹15L (VP+). GTL is 3× CTC, paid "
            "by the bank. GPA is ₹25L, 24×7. Top-up to ₹50L at group rates. "
            "Annual health check: 100% reimbursed."
        )
    else:
        ans = (
            f"Thanks {candidate_name or 'there'} — I'll pass this on to the "
            "onboarding team (onboarding@axisbank.com) and they'll get back to "
            "you within a working day. Meanwhile your buddy, whose details are "
            "in Axis Pulse, is a great first call."
        )

    return AssistantReply(answer=ans, role_file_used=role_file, source="deterministic")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ask(
    question: str,
    candidate_name: str,
    job_title: str,
    job_band: Optional[str] = None,
    expected_joining_date: Optional[str] = None,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> AssistantReply:
    """Answer a candidate's onboarding question in the context of their role.

    ``chat_history`` is an ordered list of prior messages (oldest first), each
    shaped ``{"direction": "inbound|outbound", "body": "..."}`` — the service
    keeps the last 8 turns for context.
    """
    provider = _provider()
    if provider == "claude" and _api_key():
        try:
            return _call_claude(
                question=question,
                candidate_name=candidate_name,
                job_title=job_title,
                job_band=job_band,
                expected_joining_date=expected_joining_date,
                chat_history=chat_history,
            )
        except Exception as exc:
            log.warning("Claude onboarding assistant failed, falling back: %s", exc)
            return _deterministic(question, candidate_name, job_title)
    return _deterministic(question, candidate_name, job_title)
