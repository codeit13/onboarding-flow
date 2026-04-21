"""Agent tools.

Every capability the orchestrator agent can use is exposed as a function in
this package. Each tool:
  * has a narrow, well-typed signature
  * is side-effect-free with respect to everything it doesn't own
  * returns a typed Pydantic model or a primitive
  * writes an audit event to the application when relevant
  * is unit-tested in tests/test_tools_*.py

The Claude Agent SDK wrapper maps these Python functions to tool-use calls.
Tools that talk to the outside world (calendar, mail) are thin wrappers over
``app.providers`` — swap the provider to flip from mock to real Graph.
"""

from .calendar import (
    cancel_or_reschedule_meeting,
    create_teams_meeting,
    find_common_slots,
    get_free_busy,
    list_calendar_events,
)
from .checklists import (
    customise_checklist,
    get_checklist,
    instantiate_checklist,
    is_checklist_satisfied,
    pending_blocking_labels,
    reset_customisations,
    tick_checklist_item,
)
from .decision import consolidate_recommendation, update_application_status
from .intake import get_employee_profile, get_jd, list_open_jds
from .interview import (
    collect_panel_feedback,
    run_virtual_interview,
    submit_panel_feedback,
)
from .messaging import (
    list_emails,
    list_notifications,
    notify_hr_partner,
    notify_panel,
    read_email_thread,
    send_email,
    simulate_candidate_reply,
)
from .routing import move_cv
from .scoring import score_cv_against_jd, score_transcript

__all__ = [
    # intake
    "get_employee_profile",
    "list_open_jds",
    "get_jd",
    # scoring
    "score_cv_against_jd",
    "score_transcript",
    # routing
    "move_cv",
    # checklists
    "customise_checklist",
    "get_checklist",
    "instantiate_checklist",
    "is_checklist_satisfied",
    "pending_blocking_labels",
    "reset_customisations",
    "tick_checklist_item",
    # messaging
    "send_email",
    "read_email_thread",
    "list_emails",
    "notify_hr_partner",
    "notify_panel",
    "list_notifications",
    "simulate_candidate_reply",
    # calendar
    "get_free_busy",
    "find_common_slots",
    "create_teams_meeting",
    "cancel_or_reschedule_meeting",
    "list_calendar_events",
    # interview
    "run_virtual_interview",
    "collect_panel_feedback",
    "submit_panel_feedback",
    # decision
    "consolidate_recommendation",
    "update_application_status",
]
