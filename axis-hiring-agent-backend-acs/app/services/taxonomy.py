"""Axis Bank role + skill taxonomy.

Loads the official Axis Bank ``JOB_ROLES`` and ``SKILL_MASTER`` CSVs
shipped under ``data/taxonomy/`` and exposes them as a singleton in
memory. Every part of the demo that needs to talk about *roles* (JDs,
descriptions, responsibilities, required skills) or *skills* (resume
match, R1 rubric, interview questions) MUST go through this module
instead of using ad-hoc strings, so the demo always speaks the same
vocabulary HR uses internally.

The CSVs are parsed lazily on first access and cached for the rest of
the process — they are ~25 MB combined and take ~1-2s to parse, which
is fine for a long-running uvicorn worker but unacceptable per-request.

Today's feedback (2026-04-07): use ONLY this taxonomy in the demo.
That means:

* ``app.fixtures`` seeds Job objects sourced from real entries here.
* ``services.scoring_service`` scores resumes against the canonical
  skill list, not free-text guesses.
* ``services.interview_report`` builds R1 rubrics from
  ``role.skill_categories`` so HR sees the same buckets they have on
  Thrive.
* ``services.virtual_interviewer`` derives R1 questions from
  ``role.responsibilities``.
* The frontend ``/jobs/new`` and ``/hr/applications/...`` pages
  autocomplete skills via ``GET /taxonomy/skills``.
"""

from __future__ import annotations

import ast
import csv
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Increase the CSV field size cap — JOB_ROLES rows contain very long
# job_description blobs that easily exceed Python's default 131 072 char
# limit and would otherwise raise ``_csv.Error: field larger than field
# limit``.
csv.field_size_limit(10 * 1024 * 1024)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Skill:
    """One row from SKILL_MASTER.csv."""

    skill_id: int
    name: str
    category: str
    description: str


@dataclass(frozen=True)
class Role:
    """One row from JOB_ROLES.csv (an Axis Bank job role).

    ``id`` is the row sequence (used as a stable internal handle).
    ``role_id`` is the human-visible Axis role number that HR sees on
    Thrive (e.g. ``"10000553"``).
    """

    id: int
    role_id: str
    title: str
    alias: str
    department: str
    role_summary: str
    description: str
    skills: Tuple[str, ...]
    skill_ids: Tuple[int, ...]
    skill_categories: Tuple[str, ...]
    responsibilities: Tuple[str, ...]
    works_with_internal: Tuple[str, ...] = field(default_factory=tuple)
    works_with_external: Tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


_LOCK = threading.Lock()
_LOADED = False
_ROLES: List[Role] = []
_ROLES_BY_ID: Dict[str, Role] = {}
_ROLES_BY_TITLE_KEY: Dict[str, Role] = {}
_SKILLS: List[Skill] = []
_SKILLS_BY_ID: Dict[int, Skill] = {}
_SKILLS_BY_NAME_KEY: Dict[str, Skill] = {}
_SKILL_CATEGORIES: List[str] = []
_DEPARTMENTS: List[str] = []


def _data_dir() -> Path:
    """Resolve the directory holding the two CSVs.

    Defaults to ``<repo>/data/taxonomy``. Can be overridden via the
    ``AXIS_TAXONOMY_DIR`` env var (used by tests + alternative deploys).
    """
    override = os.environ.get("AXIS_TAXONOMY_DIR")
    if override:
        return Path(override)
    # app/services/taxonomy.py -> app/services -> app -> repo root
    return Path(__file__).resolve().parents[2] / "data" / "taxonomy"


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def _parse_listish(raw: str) -> List[str]:
    """Best-effort parser for the JSON-ish list columns in JOB_ROLES.csv.

    The CSV uses Python ``repr``-style lists with double quotes, e.g.
    ``["Bank Account Management", "Banking Services"]``. We try
    ``json.loads`` first (covers the well-formed case), fall back to
    ``ast.literal_eval`` (handles single quotes and stray commas), and
    finally return ``[]`` so a malformed row never breaks startup.
    """
    raw = (raw or "").strip()
    if not raw or raw in {"[]", "null", "None"}:
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
    except Exception:
        pass
    try:
        v = ast.literal_eval(raw)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
    except Exception:
        pass
    return []


def _parse_intish_list(raw: str) -> List[int]:
    out: List[int] = []
    for item in _parse_listish(raw):
        try:
            out.append(int(item))
        except (ValueError, TypeError):
            continue
    return out


def _parse_works_with(raw: str) -> Tuple[List[str], List[str]]:
    raw = (raw or "").strip()
    if not raw:
        return [], []
    try:
        v = json.loads(raw)
    except Exception:
        try:
            v = ast.literal_eval(raw)
        except Exception:
            return [], []
    if not isinstance(v, dict):
        return [], []
    internal = [str(x).strip() for x in (v.get("internal") or []) if str(x).strip()]
    external = [str(x).strip() for x in (v.get("external") or []) if str(x).strip()]
    return internal, external


def _load() -> None:
    """Parse both CSVs once and populate the module-level caches."""
    global _LOADED, _ROLES, _SKILLS, _SKILL_CATEGORIES, _DEPARTMENTS

    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return

        data_dir = _data_dir()
        roles_path = data_dir / "job_roles.csv"
        skills_path = data_dir / "skill_master.csv"

        if not roles_path.exists() or not skills_path.exists():
            logger.warning(
                "Axis taxonomy CSVs not found under %s — taxonomy will be empty",
                data_dir,
            )
            _LOADED = True
            return

        # ---- skills ----
        skills: List[Skill] = []
        with skills_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    sid = int(row["SKILL_ID"])
                except (KeyError, ValueError, TypeError):
                    continue
                name = (row.get("SKILL_NAME") or "").strip()
                if not name:
                    continue
                skills.append(
                    Skill(
                        skill_id=sid,
                        name=name,
                        category=(row.get("SKILL_CATEGORY") or "").strip(),
                        description=(row.get("SKILL_DESCRIPTION") or "").strip(),
                    )
                )
        _SKILLS = skills
        _SKILLS_BY_ID.clear()
        _SKILLS_BY_NAME_KEY.clear()
        for s in skills:
            _SKILLS_BY_ID[s.skill_id] = s
            _SKILLS_BY_NAME_KEY[_norm(s.name)] = s

        cats = sorted({s.category for s in skills if s.category})
        _SKILL_CATEGORIES = cats

        # ---- roles ----
        roles: List[Role] = []
        with roles_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    seq = int(row["id"])
                except (KeyError, ValueError, TypeError):
                    continue
                title = (row.get("title") or "").strip()
                if not title:
                    continue
                internal, external = _parse_works_with(row.get("worth_with") or "")
                role = Role(
                    id=seq,
                    role_id=(row.get("role_id") or "").strip(),
                    title=title,
                    alias=(row.get("alias") or "").strip(),
                    department=(row.get("department") or "").strip(),
                    role_summary=(row.get("role_summary") or "").strip(),
                    description=(row.get("job_description") or "").strip(),
                    skills=tuple(_parse_listish(row.get("skills") or "")),
                    skill_ids=tuple(_parse_intish_list(row.get("skill_ids") or "")),
                    skill_categories=tuple(
                        _parse_listish(row.get("skill_categories") or "")
                    ),
                    responsibilities=tuple(
                        _parse_listish(row.get("responsibilities") or "")
                    ),
                    works_with_internal=tuple(internal),
                    works_with_external=tuple(external),
                )
                roles.append(role)
        _ROLES = roles
        _ROLES_BY_ID.clear()
        _ROLES_BY_TITLE_KEY.clear()
        for r in roles:
            if r.role_id:
                _ROLES_BY_ID[r.role_id] = r
            _ROLES_BY_TITLE_KEY.setdefault(_norm(r.title), r)
            _ROLES_BY_TITLE_KEY.setdefault(_norm(r.alias), r)

        _DEPARTMENTS = sorted({r.department for r in roles if r.department})

        logger.info(
            "Axis taxonomy loaded: %d roles, %d skills, %d departments",
            len(_ROLES),
            len(_SKILLS),
            len(_DEPARTMENTS),
        )
        _LOADED = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_loaded() -> None:
    _load()


def all_roles() -> List[Role]:
    _load()
    return list(_ROLES)


def all_skills() -> List[Skill]:
    _load()
    return list(_SKILLS)


def departments() -> List[str]:
    _load()
    return list(_DEPARTMENTS)


def skill_categories() -> List[str]:
    _load()
    return list(_SKILL_CATEGORIES)


def get_role_by_id(role_id: str) -> Optional[Role]:
    _load()
    return _ROLES_BY_ID.get(str(role_id).strip())


def get_role_by_title(title: str) -> Optional[Role]:
    _load()
    if not title:
        return None
    return _ROLES_BY_TITLE_KEY.get(_norm(title))


def find_role(query: str) -> Optional[Role]:
    """Best-effort lookup: exact role_id, then exact title/alias, then a
    fuzzy contains-match against the title.

    Used by ``fixtures`` so the seed jobs can be authored against the
    taxonomy by either role_id or a recognisable substring of the title.
    """
    _load()
    if not query:
        return None
    q = query.strip()
    role = _ROLES_BY_ID.get(q)
    if role:
        return role
    role = _ROLES_BY_TITLE_KEY.get(_norm(q))
    if role:
        return role
    qn = _norm(q)
    for r in _ROLES:
        if qn in _norm(r.title) or (r.alias and qn in _norm(r.alias)):
            return r
    return None


def search_roles(query: str, limit: int = 20) -> List[Role]:
    _load()
    if not query:
        return _ROLES[:limit]
    qn = _norm(query)
    hits: List[Role] = []
    for r in _ROLES:
        hay = " ".join((r.title, r.alias, r.department, r.role_summary)).lower()
        if qn in hay:
            hits.append(r)
            if len(hits) >= limit:
                break
    return hits


def get_skill_by_id(skill_id: int) -> Optional[Skill]:
    _load()
    try:
        return _SKILLS_BY_ID.get(int(skill_id))
    except (ValueError, TypeError):
        return None


def get_skill_by_name(name: str) -> Optional[Skill]:
    _load()
    if not name:
        return None
    return _SKILLS_BY_NAME_KEY.get(_norm(name))


def search_skills(query: str, limit: int = 20) -> List[Skill]:
    _load()
    if not query:
        return _SKILLS[:limit]
    qn = _norm(query)
    out: List[Skill] = []
    for s in _SKILLS:
        if qn in _norm(s.name) or qn in _norm(s.category):
            out.append(s)
            if len(out) >= limit:
                break
    return out


def canonicalise_skill(name: str) -> str:
    """Return the canonical Axis SKILL_MASTER name for ``name`` if found,
    otherwise echo the input untouched.

    Used by the resume scorer + intake parser so free-text skill blurbs
    on a JD or candidate CV always get pinned to the official catalogue.
    """
    s = get_skill_by_name(name)
    return s.name if s else name


def categorise_skills(names: Iterable[str]) -> Dict[str, List[str]]:
    """Group a list of skill names by their Axis category, lowercasing
    unmatched names into a synthetic ``Other`` bucket.

    Used by ``services.interview_report`` to build the R1 rubric: each
    SKILL_CATEGORY becomes one row in the rubric so the candidate is
    scored against the same buckets HR has on Thrive.
    """
    _load()
    out: Dict[str, List[str]] = {}
    for n in names:
        s = get_skill_by_name(n)
        cat = s.category if s and s.category else "Other"
        out.setdefault(cat, []).append(s.name if s else n)
    return out


@lru_cache(maxsize=1)
def stats() -> Dict[str, int]:
    _load()
    return {
        "roles": len(_ROLES),
        "skills": len(_SKILLS),
        "departments": len(_DEPARTMENTS),
        "skill_categories": len(_SKILL_CATEGORIES),
    }
