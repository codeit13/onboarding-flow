"""Checklist tools.

Checklist templates are per-JD-round-phase. The Business Partner can customise each
template before the flow runs. When the orchestrator reaches a phase it
``instantiate_checklist``s the template onto the application (snapshot), so
later template edits don't rewrite history.

Blocking items gate the orchestrator:
  * ``is_checklist_satisfied(blocking_only=True)`` is the pause predicate
  * When HR ticks a blocking item, the orchestrator recomputes satisfaction
    and resumes the flow from where it paused.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Tuple

from ..models import ChecklistInstance, ChecklistItem
from ..store import STORE

Round = Literal["R1", "R2"]
Phase = Literal["pre", "post"]


# ---------------------------------------------------------------------------
# Default templates (ship out-of-the-box, editable per JD)
# ---------------------------------------------------------------------------


def _default_template(round_: Round, phase: Phase) -> List[ChecklistItem]:
    if round_ == "R1" and phase == "pre":
        return [
            ChecklistItem(id="pre-r1-1", label="Candidate confirmed slot via email", blocking=True, owner="agent"),
            ChecklistItem(id="pre-r1-2", label="Teams meeting link sent to candidate + Business Partner", blocking=True, owner="agent"),
            ChecklistItem(id="pre-r1-3", label="Candidate Thrive profile + KRAs attached to meeting brief", blocking=True, owner="agent"),
            ChecklistItem(id="pre-r1-4", label="JD and required-skills list loaded into AI interviewer", blocking=True, owner="agent"),
            ChecklistItem(id="pre-r1-5", label="Business Partner acknowledged outreach plan", blocking=False, owner="hr_partner"),
            ChecklistItem(id="pre-r1-6", label="Joining instructions email sent", blocking=False, owner="agent"),
        ]
    if round_ == "R1" and phase == "post":
        return [
            ChecklistItem(id="post-r1-1", label="Transcript captured and stored", blocking=True, owner="agent"),
            ChecklistItem(id="post-r1-2", label="Claude scored transcript against JD rubric", blocking=True, owner="agent"),
            ChecklistItem(id="post-r1-3", label="Pass/fail decision recorded", blocking=True, owner="agent"),
            ChecklistItem(id="post-r1-4", label="Business Partner notified of outcome", blocking=False, owner="agent"),
        ]
    if round_ == "R2" and phase == "pre":
        return [
            ChecklistItem(id="pre-r2-1", label="R1 transcript + score attached to invite", blocking=True, owner="agent"),
            ChecklistItem(id="pre-r2-2", label="Business Partner approved panel composition", blocking=True, owner="hr_partner"),
            ChecklistItem(id="pre-r2-3", label="Common free slot found across panel + candidate", blocking=True, owner="agent"),
            ChecklistItem(id="pre-r2-4", label="Teams meeting created + all invited", blocking=True, owner="agent"),
            ChecklistItem(id="pre-r2-5", label="Panel briefing doc shared 24h before", blocking=False, owner="agent"),
            ChecklistItem(id="pre-r2-6", label="Feedback form link attached to invite", blocking=False, owner="agent"),
        ]
    if round_ == "R2" and phase == "post":
        return [
            ChecklistItem(id="post-r2-1", label="All panellists submitted feedback", blocking=True, owner="panel"),
            ChecklistItem(id="post-r2-2", label="Consolidated recommendation produced", blocking=True, owner="agent"),
            ChecklistItem(id="post-r2-3", label="Final decision recorded", blocking=True, owner="agent"),
            ChecklistItem(id="post-r2-4", label="Candidate notified", blocking=False, owner="agent"),
        ]
    raise ValueError(f"Unknown checklist: {round_=} {phase=}")


# ---------------------------------------------------------------------------
# Per-JD customisation layer. Business Partners add/edit items; we overlay on default.
# Keyed by (jd_id, round, phase).
# ---------------------------------------------------------------------------

_CUSTOMISATIONS: Dict[Tuple[str, Round, Phase], List[ChecklistItem]] = {}


def customise_checklist(
    jd_id: str,
    round_: Round,
    phase: Phase,
    extra_items: List[ChecklistItem],
) -> None:
    """Business Partner adds items on top of the default template for a JD."""
    _CUSTOMISATIONS[(jd_id, round_, phase)] = list(extra_items)


def get_checklist(jd_id: str, round_: Round, phase: Phase) -> List[ChecklistItem]:
    """Return the merged template for a JD × round × phase."""
    if STORE.get_job(jd_id) is None:
        raise LookupError(f"No JD found for id={jd_id!r}")
    merged = list(_default_template(round_, phase))
    extra = _CUSTOMISATIONS.get((jd_id, round_, phase), [])
    merged.extend(extra)
    return merged


# ---------------------------------------------------------------------------
# Instance management on an application
# ---------------------------------------------------------------------------


def instantiate_checklist(application_id: str, round_: Round, phase: Phase) -> ChecklistInstance:
    app = STORE.get_application(application_id)
    if not app:
        raise LookupError(f"No application for id={application_id!r}")

    # Idempotent: if we already have this instance, return it unchanged.
    for c in app.checklists:
        if c.round == round_ and c.phase == phase:
            return c

    template = get_checklist(app.job_id, round_, phase)
    instance = ChecklistInstance(
        id=f"chk-{application_id}-{round_}-{phase}",
        application_id=application_id,
        round=round_,
        phase=phase,
        items=[ChecklistItem(**i.model_dump()) for i in template],
    )
    app.checklists.append(instance)
    app.log("agent", f"Instantiated {round_} {phase} checklist ({len(instance.items)} items)")
    return instance


def _find_instance(application_id: str, round_: Round, phase: Phase) -> ChecklistInstance:
    app = STORE.get_application(application_id)
    if not app:
        raise LookupError(f"No application for id={application_id!r}")
    for c in app.checklists:
        if c.round == round_ and c.phase == phase:
            return c
    raise LookupError(f"Checklist not instantiated: {round_} {phase}")


def tick_checklist_item(
    application_id: str,
    round_: Round,
    phase: Phase,
    item_id: str,
    actor: str = "agent",
    note: str = "",
) -> ChecklistInstance:
    inst = _find_instance(application_id, round_, phase)
    for item in inst.items:
        if item.id == item_id:
            if item.done:
                return inst  # already ticked — idempotent
            item.done = True
            item.ticked_by = actor
            item.ticked_at = datetime.utcnow()
            if note:
                item.note = note
            app = STORE.get_application(application_id)
            if app:
                app.log(actor, f"Checklist ✓ {round_}/{phase}/{item.label}")
            return inst
    raise LookupError(f"Checklist item {item_id!r} not found in {round_} {phase}")


def is_checklist_satisfied(
    application_id: str,
    round_: Round,
    phase: Phase,
    blocking_only: bool = True,
) -> bool:
    try:
        inst = _find_instance(application_id, round_, phase)
    except LookupError:
        return False
    return inst.is_satisfied(blocking_only=blocking_only)


def pending_blocking_labels(application_id: str) -> List[str]:
    """Return labels of every blocking item across all checklist instances
    on this application that is not yet done. Used to populate
    Application.pending_blocking_items for UI display."""
    app = STORE.get_application(application_id)
    if not app:
        return []
    out: List[str] = []
    for inst in app.checklists:
        for item in inst.pending_blocking():
            out.append(f"[{inst.round}/{inst.phase}] {item.label}")
    return out


def reset_customisations() -> None:
    """Used by tests."""
    _CUSTOMISATIONS.clear()
