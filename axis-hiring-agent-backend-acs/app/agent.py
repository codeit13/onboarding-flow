"""DEPRECATED — legacy linear agent.

This module used to contain a linear, auto-rejecting funnel driver
(``start_application`` → ``run_r1`` → ``finalise``). It was replaced by
the stateful, human-in-the-loop ``app.orchestrator`` and is no longer
imported anywhere in the codebase.

It is kept as an empty module on disk only to avoid breaking any stale
``from app import agent`` imports that might still live in scratch
notebooks. Do NOT add new logic here — every funnel transition belongs
on ``app.orchestrator.ORCHESTRATOR``, which honours the rule that the
agent never auto-rejects a candidate. Every reject decision (intake
screening, post-R1, post-R2) is now an explicit HR action via the
corresponding REST endpoints under ``/applications/{id}/hr-*``.
"""

from __future__ import annotations

import warnings


def __getattr__(name: str):  # pragma: no cover - defensive
    warnings.warn(
        f"app.agent.{name} is deprecated; use app.orchestrator.ORCHESTRATOR instead. "
        "The legacy linear agent auto-rejected candidates, which violates the "
        "human-in-the-loop rule. All funnel transitions must go through the "
        "orchestrator, which pauses WAITING_HR for every reject decision.",
        DeprecationWarning,
        stacklevel=2,
    )
    raise AttributeError(
        f"app.agent has no attribute {name!r}; use app.orchestrator.ORCHESTRATOR"
    )
