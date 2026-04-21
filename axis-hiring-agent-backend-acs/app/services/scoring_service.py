"""Scoring service — wraps the heuristic tools today, swap for Claude later.

Keeping a thin service layer here means the orchestrator imports
``score_profile`` (stable signature) instead of coupling to the tool package,
so switching to a Claude-backed scorer is a one-file change.
"""

from __future__ import annotations

from typing import Tuple

from ..models import InterviewRecord, Job, Profile
from ..tools.scoring import ScoreResult, score_cv_against_jd, score_transcript


def score_profile(profile: Profile, jd: Job) -> ScoreResult:
    return score_cv_against_jd(profile, jd)


def score_interview_transcript(record: InterviewRecord, jd: Job) -> Tuple[float, str]:
    return score_transcript(record, jd)
