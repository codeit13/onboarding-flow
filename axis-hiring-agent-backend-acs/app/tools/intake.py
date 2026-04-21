"""Intake tools — pull employee profile from Thrive + list open JDs."""

from __future__ import annotations

from typing import List

from ..models import Job, Profile
from ..store import STORE


def get_employee_profile(employee_id: str) -> Profile:
    """Primary intake path. Reads the employee's internal Thrive profile.

    In the real system this will call the Thrive/OutSystems API. For the POC we
    resolve against the in-memory store seeded from ``app.fixtures``.
    """
    # The fixtures seed candidates keyed by candidate id. We also accept
    # lookup by the human employee id stamped on the Profile.
    for cand in STORE.candidates.values():
        if cand.profile.employee_id == employee_id or cand.id == employee_id:
            return cand.profile
    raise LookupError(f"No employee found for id={employee_id!r}")


def list_open_jds() -> List[Job]:
    """Return every currently-open job description."""
    return STORE.list_jobs()


def get_jd(jd_id: str) -> Job:
    """Return the full JD including Business Partner + panel + rubric."""
    job = STORE.get_job(jd_id)
    if not job:
        raise LookupError(f"No JD found for id={jd_id!r}")
    return job
