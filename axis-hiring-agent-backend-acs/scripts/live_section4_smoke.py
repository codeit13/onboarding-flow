"""End-to-end live Microsoft Graph smoke test for Section 4 of the plan.

Walks one application through every step of "Section 4. End-to-End
Functional Flow" against the **real** Microsoft Graph providers, using the
real Xebia192.onmicrosoft.com tenant. The goal is to prove — before any
live demo — that nothing in the funnel is broken at the integration layer.

Step coverage (numbers map 1:1 to the plan)
-------------------------------------------
  1.  HR creates JD                                  (seeded fixture)
  2.  Candidate applies                              ORCHESTRATOR.start_application
  3.  Agent screens profile                          inside orchestrator
  4.  Agent emails outreach with proposed slots      real Graph sendMail
  5.  Candidate confirms a slot                      on_candidate_confirm_slot
  6.  Agent books R1 Teams meeting                   real Graph create event
  7.  Candidate joins + R1 runs (canned transcript)  on_candidate_start_r1
  8.  Agent scores R1, builds report                 inside orchestrator
  9.  HR approves panel composition                  tick_checklist_item
 10.  Agent books R2 Teams meeting                   real Graph create event
 11.  Panel submits feedback                         submit_panel_feedback
 12.  Agent consolidates verdict, sends offer mail   real Graph sendMail

The script asserts the observable side effects after every step and
**fails loudly** if anything is missing. Run with:

    .venv/bin/python scripts/live_section4_smoke.py

Exit code 0 = green. Anything else = a real bug we must fix before the
demo. Re-running the script is safe — it cleans up the calendar events
it created at the end.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Make the repo importable when run as a script.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# IMPORTANT: load .env BEFORE importing app, so the providers wire up to
# real Graph (the runtime .env has AXIS_*_PROVIDER=graph).
from dotenv import dotenv_values  # noqa: E402
os.environ.update({k: v for k, v in dotenv_values(ROOT / ".env").items() if v})

from app.fixtures import (  # noqa: E402
    GRAPH_TENANT_HM,
    GRAPH_TENANT_HR,
    GRAPH_TENANT_INT_1,
    seed_all,
)
from app.models import AgentStatus, FunnelStage  # noqa: E402
from app.orchestrator import ORCHESTRATOR  # noqa: E402
from app.providers import (  # noqa: E402
    get_calendar_provider,
    get_messaging_provider,
)
from app.store import STORE  # noqa: E402
from app.tools.checklists import tick_checklist_item  # noqa: E402
from app.tools.interview import submit_panel_feedback  # noqa: E402


# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def step(num: int, label: str) -> None:
    print(f"\n{BOLD}{BLUE}─── Step {num}: {label}{RESET}")


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {YELLOW}·{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}")
    raise SystemExit(1)


def assert_true(cond: bool, msg: str) -> None:
    if cond:
        ok(msg)
    else:
        fail(msg)


def join_app(app_id: str, timeout: float = 60.0) -> None:
    """Wait for the orchestrator's background thread for this app to settle."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = ORCHESTRATOR._threads.get(app_id)  # noqa: SLF001
        if t is None or not t.is_alive():
            return
        t.join(timeout=deadline - time.time())
    fail(f"Orchestrator did not settle in {timeout}s for {app_id}")


# ---------------------------------------------------------------------------
# The smoke walk
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"{BOLD}AXIS HIRING AGENT — Section 4 LIVE Graph smoke test{RESET}")
    print(f"  Tenant   : {os.getenv('AXIS_GRAPH_TENANT_ID')}")
    print(f"  Organiser: {os.getenv('AXIS_GRAPH_ORGANISER_UPN')}")
    print(f"  Calendar : {os.getenv('AXIS_CALENDAR_PROVIDER')}")
    print(f"  Messaging: {os.getenv('AXIS_MESSAGING_PROVIDER')}")

    if (os.getenv("AXIS_CALENDAR_PROVIDER", "").lower() != "graph"
            or os.getenv("AXIS_MESSAGING_PROVIDER", "").lower() != "graph"):
        fail("Both AXIS_CALENDAR_PROVIDER and AXIS_MESSAGING_PROVIDER must be 'graph'")

    # Re-seed so the run is reproducible (Graph-mode panels swapped in).
    seed_all()

    # ------------------------------------------------------------------
    # 1. JD seeded
    # ------------------------------------------------------------------
    step(1, "HR creates the JD (seeded fixture)")
    jd = STORE.get_job("job-590321")
    assert_true(jd is not None, f"JD loaded: {jd.title} ({jd.location})")
    panel_ids = {p.user_id for p in jd.panel}
    expected = {
        GRAPH_TENANT_HR.user_id,
        GRAPH_TENANT_HM.user_id,
        GRAPH_TENANT_INT_1.user_id,
    }
    assert_true(
        expected.issubset(panel_ids),
        f"JD panel uses real tenant mailboxes: {sorted(panel_ids)}",
    )

    # ------------------------------------------------------------------
    # 2. Candidate applies
    # ------------------------------------------------------------------
    step(2, "Candidate applies (Rohan Desai → Branch Head, RB-LS, Mumbai)")
    cand = next(
        c for c in STORE.candidates.values()
        if c.profile.employee_id == "EMP10234"
    )
    assert_true(
        "rohan.desai@" in cand.profile.email.lower(),
        f"Candidate is {cand.profile.name} <{cand.profile.email}>",
    )
    app = ORCHESTRATOR.start_application("EMP10234", "job-590321")
    join_app(app.id)
    app = STORE.get_application(app.id)
    info(f"Application id: {app.id}")

    # ------------------------------------------------------------------
    # 3 + 4. Screening + outreach with proposed slots
    # ------------------------------------------------------------------
    step(3, "Agent screens the profile")
    assert_true(app.match_percent >= 75, f"Screening match {app.match_percent:.0f}% (≥75%)")
    assert_true(
        any("Scored profile" in e.message for e in app.events),
        "Screening event recorded on the application audit log",
    )

    step(4, "Agent emails outreach with 3 proposed slots (real Graph sendMail)")
    assert_true(
        app.agent_status == AgentStatus.WAITING_CANDIDATE,
        f"Orchestrator paused for candidate slot pick (status={app.agent_status.value})",
    )
    assert_true(
        len(app.proposed_r1_slots) == 3,
        f"3 R1 slots proposed: "
        + ", ".join(s.start.strftime("%a %d %b %H:%M") for s in app.proposed_r1_slots),
    )
    sent = get_messaging_provider().list_emails(application_id=app.id)
    outreach = next(
        (m for m in sent if m.direction == "out" and "Round 1 Interview" in m.subject),
        None,
    )
    assert_true(outreach is not None, f"Outreach email sent: '{outreach.subject if outreach else None}'")
    assert_true(
        "Talent Acquisition" in outreach.body and "Axis Bank" in outreach.body,
        "Outreach body carries production branding",
    )
    assert_true(
        "[TEST]" not in outreach.subject and "[DIAG]" not in outreach.subject,
        "Outreach subject is free of test/diag markers",
    )

    # ------------------------------------------------------------------
    # 5 + 6. Candidate confirms slot, agent books R1 Teams meeting
    # ------------------------------------------------------------------
    step(5, "Candidate confirms slot 1 (the second proposed slot)")
    ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R1", 1)
    join_app(app.id)
    app = STORE.get_application(app.id)
    assert_true(
        app.selected_r1_slot_index == 1,
        f"Application stored selected_r1_slot_index={app.selected_r1_slot_index}",
    )

    step(6, "Agent books the R1 Teams meeting on real Graph")
    assert_true(
        app.stage == FunnelStage.R1_SCHEDULED,
        f"Application stage = {app.stage.value}",
    )
    cal_events = [
        e for e in get_calendar_provider().list_events(application_id=app.id)
        if not e.cancelled and "Round 1" in e.subject
    ]
    assert_true(len(cal_events) == 1, f"R1 calendar event created: '{cal_events[0].subject}'")
    r1_event = cal_events[0]
    assert_true(
        r1_event.teams_join_url and "teams.microsoft.com" in (r1_event.teams_join_url or ""),
        f"Real Teams join URL provisioned: {r1_event.teams_join_url[:60]}…",
    )
    assert_true(
        cand.profile.email in r1_event.attendees,
        f"Candidate ({cand.profile.email}) is on the invite",
    )
    assert_true(
        GRAPH_TENANT_HR.user_id in r1_event.attendees,
        f"HR partner ({GRAPH_TENANT_HR.user_id}) is on the invite",
    )
    assert_true(
        "Round 1 Interview" in r1_event.subject and "[TEST]" not in r1_event.subject,
        "R1 calendar event subject is production-grade",
    )
    assert_true(
        "Agenda" in r1_event.body and "Talent Acquisition" in r1_event.body,
        "R1 calendar event body has full agenda + signature",
    )

    # ------------------------------------------------------------------
    # 7 + 8. Candidate joins, R1 runs, agent scores
    # ------------------------------------------------------------------
    step(7, "Candidate clicks 'Start interview' — agent runs Round 1")
    ORCHESTRATOR.on_candidate_start_r1(app.id)
    join_app(app.id)
    app = STORE.get_application(app.id)
    assert_true(app.r1_started, "r1_started flag is True")
    assert_true(app.stage == FunnelStage.R1_DONE, f"Stage = {app.stage.value}")

    step(8, "Agent scores R1 and builds the AI report")
    r1 = next(i for i in app.interviews if i.round == "R1")
    assert_true(r1.score is not None and r1.score >= 70, f"R1 scored {r1.score:.0f}/100 (≥70)")
    assert_true(r1.report is not None, f"R1 report built: '{r1.report.headline}'")
    assert_true(
        bool(r1.report.recommended_probes),
        f"Report recommends {len(r1.report.recommended_probes)} panel probes",
    )

    # ------------------------------------------------------------------
    # 9. HR approves panel composition (blocking gate)
    # ------------------------------------------------------------------
    step(9, "HR ticks blocking item: 'Panel composition approved'")
    assert_true(
        app.agent_status == AgentStatus.WAITING_HR,
        f"Orchestrator parked at WAITING_HR ({app.agent_status.value})",
    )
    tick_checklist_item(
        app.id, "R2", "pre", "pre-r2-2",
        actor="hr_partner", note="Panel approved by HR",
    )
    ORCHESTRATOR.on_hr_tick(app.id)
    join_app(app.id)
    app = STORE.get_application(app.id)
    assert_true(
        app.agent_status == AgentStatus.WAITING_CANDIDATE,
        "Agent resumed after HR tick and proposed R2 slots",
    )
    assert_true(len(app.proposed_r2_slots) == 3, f"{len(app.proposed_r2_slots)} R2 slots proposed")

    # ------------------------------------------------------------------
    # 10. Candidate confirms R2 slot, agent books panel meeting
    # ------------------------------------------------------------------
    step(10, "Candidate picks R2 slot 0; agent books panel meeting on real Graph")
    ORCHESTRATOR.on_candidate_confirm_slot(app.id, "R2", 0)
    join_app(app.id)
    app = STORE.get_application(app.id)
    assert_true(
        app.stage == FunnelStage.R2_SCHEDULED,
        f"Stage = {app.stage.value}",
    )
    r2_events = [
        e for e in get_calendar_provider().list_events(application_id=app.id)
        if not e.cancelled and "Round 2" in e.subject
    ]
    assert_true(len(r2_events) == 1, f"R2 calendar event created: '{r2_events[0].subject}'")
    r2_event = r2_events[0]
    assert_true(
        r2_event.teams_join_url and "teams.microsoft.com" in (r2_event.teams_join_url or ""),
        f"R2 Teams join URL provisioned: {r2_event.teams_join_url[:60]}…",
    )
    for must_be_invited in (
        cand.profile.email,
        GRAPH_TENANT_HR.user_id,
        GRAPH_TENANT_HM.user_id,
        GRAPH_TENANT_INT_1.user_id,
    ):
        assert_true(
            must_be_invited in r2_event.attendees,
            f"R2 invite includes {must_be_invited}",
        )
    assert_true(
        "Round 2 Panel Interview" in r2_event.body
        and "Recommended panel probes" in r2_event.body
        and "Talent Acquisition" in r2_event.body,
        "R2 invite body carries panel briefing + production signature",
    )

    # ------------------------------------------------------------------
    # 11. Panel votes
    # ------------------------------------------------------------------
    step(11, "All 3 panellists submit feedback (2 strong_hire + 1 hire)")
    r2 = next(i for i in app.interviews if i.round == "R2")
    panellists = [
        (GRAPH_TENANT_HM.user_id, "strong_hire", 90.0),
        (GRAPH_TENANT_INT_1.user_id, "hire", 85.0),
        (GRAPH_TENANT_HR.user_id, "hire", 84.0),
    ]
    for pid, rec, score in panellists:
        submit_panel_feedback(
            interview_id=r2.id,
            panellist_id=pid,
            score=score,
            strengths="Strong domain fluency, calm under pressure, customer-first mindset.",
            concerns="None blocking — minor coaching on product depth at onboarding.",
            recommendation=rec,
        )
        info(f"vote: {pid} → {rec} ({score:.0f})")
    ORCHESTRATOR.on_panel_feedback(app.id)
    join_app(app.id)
    app = STORE.get_application(app.id)

    # ------------------------------------------------------------------
    # 12. Verdict + offer email
    # ------------------------------------------------------------------
    step(12, "Agent consolidates verdict and sends the offer email (real Graph)")
    assert_true(app.stage == FunnelStage.OFFER, f"Final stage = {app.stage.value}")
    assert_true(
        app.agent_status == AgentStatus.DONE,
        f"Agent status = {app.agent_status.value}",
    )
    sent = get_messaging_provider().list_emails(application_id=app.id)
    offer = next(
        (m for m in sent if m.direction == "out" and "Offer of Employment" in m.subject),
        None,
    )
    assert_true(offer is not None, f"Offer email sent: '{offer.subject if offer else None}'")
    assert_true(
        "welcome aboard" in (offer.body or "").lower(),
        "Offer email carries the welcome paragraph",
    )

    # ------------------------------------------------------------------
    # Cleanup so the next live walkthrough starts on empty calendars
    # ------------------------------------------------------------------
    step(0, "Cleanup: cancel both meetings on real Graph")
    cal = get_calendar_provider()
    for ev in cal.list_events(application_id=app.id):
        try:
            cal.cancel_or_reschedule_meeting(ev.id)
            ok(f"cancelled {ev.subject[:60]}")
        except Exception as e:  # noqa: BLE001
            info(f"could not cancel {ev.id}: {e!r}")

    print(f"\n{BOLD}{GREEN}✓ ALL 12 STEPS PASSED — live Graph integration is healthy.{RESET}\n")


if __name__ == "__main__":
    main()
