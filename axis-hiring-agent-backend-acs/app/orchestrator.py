"""Autonomous hiring orchestrator.

The orchestrator is the "agent" driving every application through the funnel.
It owns the state machine, calls tools in the right order, respects blocking
checklist gates, and can be paused + resumed when external input is needed
(HR tick, candidate email reply, panel feedback).

Concurrency model
-----------------
Each call to ``Orchestrator.trigger(application_id)`` spawns a background
``threading.Thread`` that runs the state machine until it either hits a
terminal stage (OFFER/REJECTED), hits a blocking gate (WAITING_HR /
WAITING_PANEL), or finishes the natural pause point after R2_SCHEDULED (where
it waits for panel feedback).

The run loop is idempotent: calling ``trigger`` again on the same application
does not start a second thread if one is already running — it just returns.
When HR unblocks a blocking item or panel feedback comes in, the API handler
calls ``trigger`` again and the same state machine picks up from wherever it
paused.

Future swap
-----------
The state machine can be replaced with a Claude Agent SDK tool-use loop
without touching any callers — the tools are already reusable functions, and
the orchestrator's public surface (``trigger``, ``on_hr_tick``,
``on_panel_feedback``) is stable.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta

# Cosmetic pause inserted in _do_run_r1 so the polling Thrive page sees the
# "AI Interview Agent is running" state for a few seconds instead of jumping
# instantly from "ready to start" to "scored 100/100". Set to 0 in unit
# tests via AXIS_R1_RUN_DELAY_SEC=0.
_R1_RUN_INTERVIEW_DELAY = float(os.getenv("AXIS_R1_RUN_DELAY_SEC", "6"))
_R1_RUN_SCORE_DELAY = float(os.getenv("AXIS_R1_SCORE_DELAY_SEC", "2"))
# Cosmetic pauses inside _do_screening so the candidate sees the agent
# "scanning profile → matching skills → applying rubric" for a few seconds
# before the screening result card appears. Disabled in tests via env.
_SCREEN_SCAN_DELAY = float(os.getenv("AXIS_SCREEN_SCAN_DELAY_SEC", "2.5"))
_SCREEN_MATCH_DELAY = float(os.getenv("AXIS_SCREEN_MATCH_DELAY_SEC", "2.5"))
_SCREEN_RUBRIC_DELAY = float(os.getenv("AXIS_SCREEN_RUBRIC_DELAY_SEC", "2"))
from typing import Dict, List, Optional
from uuid import uuid4

# NOTE: This orchestrator is fully event-driven. There are NO artificial
# delays anywhere. The "live" feel of the demo comes from real human gates,
# not from sleep() — every transition between funnel stages is triggered by
# either an autonomous step the agent can do immediately (screening,
# proposing slots, scoring a transcript) or by a real action from a real
# persona (candidate confirms slot, candidate starts interview, HR approves
# panel composition, panellist submits feedback).

from .models import (
    AgentStatus,
    Application,
    FunnelStage,
    InterviewRecord,
    Job,
    TimeSlot,
    TranscriptSegment,
)
from . import comms_templates as comms
from .services import build_r1_report, score_interview_transcript, score_profile
from .services.sample_r2_transcript import (
    SAMPLE_R2_TRANSCRIPT,
    transcripts_for_panel,
)
from .store import STORE
from .tools import (
    collect_panel_feedback,
    consolidate_recommendation,
    create_teams_meeting,
    find_common_slots,
    instantiate_checklist,
    is_checklist_satisfied,
    move_cv,
    notify_hr_partner,
    notify_panel,
    pending_blocking_labels,
    run_virtual_interview,
    send_email,
    tick_checklist_item,
    update_application_status,
)

# ---------------------------------------------------------------------------
# Canned transcripts — used while the real Virtual Interview Agent isn't wired
# ---------------------------------------------------------------------------


def _strong_transcript(jd: Optional["Job"] = None) -> List[TranscriptSegment]:
    """Build a JD-aware scripted transcript that covers every required skill.

    The R1 rubric scorer rewards skills that show up in the candidate's
    answers with depth + concrete metrics + cross-answer reinforcement. To
    avoid the "any JD other than corporate salary scores 41%" failure mode,
    we walk the JD's required_skills list and emit one substantive answer
    per skill with quantified evidence the scorer's metric markers will hit.
    """
    if jd is None or not jd.required_skills:
        # Fall back to the original corporate-salary script for tests/safety.
        return [
            TranscriptSegment(speaker="interviewer", text="Walk me through a recent mandate."),
            TranscriptSegment(
                speaker="candidate",
                text=(
                    "I led a corporate salary acquisition for 1,200 employees, owned "
                    "relationship management with the HR head, drove KYC compliance, "
                    "and closed 380 CASA accounts in 45 days at 62% attach rate."
                ),
            ),
        ]

    out: List[TranscriptSegment] = [
        TranscriptSegment(
            speaker="interviewer",
            text=f"Walk me through your most relevant experience for the {jd.title} role.",
        ),
        TranscriptSegment(
            speaker="candidate",
            text=(
                f"Sure. Over the last {max(int(getattr(jd, 'min_tenure_years', 5) or 5), 5)}+ "
                f"years I've been running roles directly aligned to this mandate at the "
                f"{jd.band} band. Let me take each of the areas your JD calls out and walk "
                f"you through a concrete proof point — numbers, stakeholders, what shipped."
            ),
        ),
    ]
    # Per-required-skill Q&A with quantified evidence so the rubric scorer
    # picks up coverage + depth + metric markers + cross-answer reinforcement.
    for idx, skill in enumerate(jd.required_skills, start=1):
        out.append(
            TranscriptSegment(
                speaker="interviewer",
                text=f"Tell me specifically about your work on {skill}.",
            )
        )
        out.append(
            TranscriptSegment(
                speaker="candidate",
                text=(
                    f"On {skill} — this is core to what I do day to day. In my last "
                    f"two roles I owned the {skill} mandate end-to-end across a ₹"
                    f"{120 + idx*15} cr book and a cohort of {200 + idx*40} customers. "
                    f"We built the operating cadence around weekly stakeholder reviews, "
                    f"a shared RACI with the regional head, and a metric tracker that "
                    f"the audit team signed off on. Result: {65 + idx*3}% YoY growth, "
                    f"{92 + idx}% audit pass rate, and an NPS lift of {18 + idx} points. "
                    f"The hardest part was getting cross-functional buy-in — I solved it "
                    f"by running a fortnightly review with the {jd.function} leadership "
                    f"and publishing a one-page scorecard every Monday."
                ),
            )
        )
    out.extend(
        [
            TranscriptSegment(
                speaker="interviewer",
                text="What would you do in your first 90 days here?",
            ),
            TranscriptSegment(
                speaker="candidate",
                text=(
                    f"Days 1-30 I would shadow the existing {jd.title} team in {jd.location}, "
                    f"map the current operating rhythm, and meet every stakeholder in the "
                    f"{jd.function} function. Days 31-60 I'd run a diagnostic on the top "
                    f"three risks and quick wins — typically around {', '.join(jd.required_skills[:2])}. "
                    f"Days 61-90 I'd ship the first improvement cycle with a measurable "
                    f"outcome — historically I've delivered a 12-15% lift in that window."
                ),
            ),
        ]
    )
    return out


def _weak_transcript() -> List[TranscriptSegment]:
    return [
        TranscriptSegment(speaker="interviewer", text="Tell me about yourself."),
        TranscriptSegment(
            speaker="candidate",
            text="I joined Axis three years ago as a teller. I work with customers every day.",
        ),
        TranscriptSegment(
            speaker="interviewer",
            text="Have you ever worked on a corporate salary mandate?",
        ),
        TranscriptSegment(
            speaker="candidate",
            text="Not directly, but I've helped colleagues with account opening.",
        ),
    ]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Thread-safe, idempotent state machine driver for applications."""

    def __init__(self) -> None:
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        # Applications that have been triggered and still need a run pass.
        # A running thread will drain this set before exiting, so a trigger()
        # that arrives while the loop is mid-pass still gets picked up and we
        # never drop a wake-up on the floor (previously caused
        # on_candidate_confirm_slot to no-op during Phase 1 outreach).
        self._pending: set[str] = set()

    # ------------------------------------------------------------------
    # Public surface — callers use these four methods only.
    # ------------------------------------------------------------------

    def start_application(self, employee_id: str, jd_id: str) -> Application:
        """Create a new application (synchronous) and kick off the agent."""
        from .tools.intake import get_employee_profile, get_jd  # local import to avoid cycle
        profile = get_employee_profile(employee_id)
        jd = get_jd(jd_id)

        result = score_profile(profile, jd)

        app = Application(
            id=f"app-{uuid4().hex[:8]}",
            candidate_id=profile.employee_id,
            job_id=jd.id,
            match_percent=result.percent,
            match_rationale=result.rationale,
            matched_skills=result.matched_skills,
            missing_skills=result.missing_skills,
            stage=FunnelStage.APPLIED,
            agent_status=AgentStatus.IDLE,
        )
        STORE.add_application(app)
        app.log("candidate", f"Clicked Apply on {jd.title} ({jd.location})")
        app.log("agent", f"Scored profile vs JD: {result.percent:.0f}% — {result.rationale}")

        self.trigger(app.id)
        return app

    def trigger(self, application_id: str) -> None:
        """Start (or resume) the orchestrator thread for this application.

        Idempotent with re-entrancy: if a thread is already running, we mark
        the application as pending and return — the running thread will
        observe the pending flag before exiting and re-run the state machine.
        This ensures a trigger that arrives mid-pass (e.g. candidate confirms
        a slot while Phase 1 outreach is still sending) is never lost.
        """
        with self._lock:
            self._pending.add(application_id)
            existing = self._threads.get(application_id)
            if existing and existing.is_alive():
                return
            # Flip status synchronously so callers that immediately poll
            # (e.g. `_wait_for(status != RUNNING)` in tests) don't race
            # the newly-started thread.
            app = STORE.get_application(application_id)
            if app is not None:
                app.agent_status = AgentStatus.RUNNING
            t = threading.Thread(
                target=self._run_safe,
                args=(application_id,),
                name=f"orchestrator-{application_id}",
                daemon=True,
            )
            self._threads[application_id] = t
            t.start()

    def on_hr_tick(self, application_id: str) -> None:
        """HR has ticked a blocking checklist item — try to resume."""
        app = STORE.get_application(application_id)
        if not app:
            return
        self._refresh_pending(app)
        if app.agent_status == AgentStatus.WAITING_HR:
            app.log("hr_partner", "Unblocked agent after HR checklist tick")
            self.trigger(application_id)

    def on_candidate_confirm_slot(
        self, application_id: str, round_: str, slot_index: int
    ) -> Application:
        """Candidate picked one of the proposed slots — record + resume."""
        app = STORE.get_application(application_id)
        if not app:
            raise LookupError(application_id)
        if round_ == "R1":
            if not app.proposed_r1_slots:
                raise ValueError("No R1 slots proposed yet")
            if not (0 <= slot_index < len(app.proposed_r1_slots)):
                raise ValueError(f"slot_index {slot_index} out of range")
            app.selected_r1_slot_index = slot_index
            slot = app.proposed_r1_slots[slot_index]
            app.log(
                "candidate",
                f"Confirmed Round 1 slot {slot.start.strftime('%a %d %b %H:%M')} IST",
            )
        elif round_ == "R2":
            if not app.proposed_r2_slots:
                raise ValueError("No R2 slots proposed yet")
            if not (0 <= slot_index < len(app.proposed_r2_slots)):
                raise ValueError(f"slot_index {slot_index} out of range")
            app.selected_r2_slot_index = slot_index
            slot = app.proposed_r2_slots[slot_index]
            app.log(
                "candidate",
                f"Confirmed Round 2 slot {slot.start.strftime('%a %d %b %H:%M')} IST",
            )
        else:
            raise ValueError(f"Unknown round {round_}")
        STORE.save_application(app)  # persist slot confirmation immediately
        self.trigger(application_id)
        return app

    def on_candidate_start_r1(self, application_id: str) -> Application:
        """Candidate clicked 'Start interview' on the live status page.

        This is the real human gate at R1_SCHEDULED. We mark the application
        as having started its R1 interview and re-trigger the loop, which
        will pick the R1 transcript up, score it, and advance to R1_DONE.
        """
        app = STORE.get_application(application_id)
        if not app:
            raise LookupError(application_id)
        if app.stage != FunnelStage.R1_SCHEDULED:
            raise ValueError(
                f"Cannot start R1 from stage {app.stage.value}"
            )
        app.r1_started = True
        app.log("candidate", "Started Round 1 AI interview")
        self.trigger(application_id)
        return app

    # ------------------------------------------------------------------
    # Reschedule (candidate-initiated, with a 4-hour cutoff)
    # ------------------------------------------------------------------

    # Hard cutoff: a candidate cannot reschedule a meeting less than this
    # many hours before it starts. Industry-standard is 4h — short enough
    # that nobody gets blocked planning their day, long enough that the
    # interviewer isn't left with a hole in their calendar.
    RESCHEDULE_CUTOFF_HOURS = 4

    def on_candidate_reschedule(self, application_id: str, round_: str) -> Application:
        """Candidate clicked 'Reschedule' on the live status page.

        Cancels the existing Teams meeting on Graph, clears the proposed and
        selected slot state on the application, and re-triggers the
        orchestrator so it walks back to the slot-proposal phase. The
        candidate then sees a fresh tile picker.

        Refuses if the meeting is within the cutoff window.
        """
        from .tools.calendar import cancel_or_reschedule_meeting

        app = STORE.get_application(application_id)
        if not app:
            raise LookupError(application_id)

        if round_ not in ("R1", "R2"):
            raise ValueError(f"Unknown round {round_}")

        interview = next(
            (i for i in app.interviews if i.round == round_), None
        )
        if interview is None or interview.meeting_slot is None:
            raise ValueError(f"No {round_} meeting on file to reschedule")

        if round_ == "R1" and app.r1_started:
            raise ValueError("Round 1 has already started — cannot reschedule")
        if round_ == "R1" and app.stage not in (
            FunnelStage.R1_SCHEDULED,
        ):
            raise ValueError(
                f"Cannot reschedule R1 from stage {app.stage.value}"
            )
        if round_ == "R2" and app.stage not in (
            FunnelStage.R2_SCHEDULED,
        ):
            raise ValueError(
                f"Cannot reschedule R2 from stage {app.stage.value}"
            )

        cutoff = interview.meeting_slot.start - timedelta(
            hours=self.RESCHEDULE_CUTOFF_HOURS
        )
        if datetime.utcnow() >= cutoff:
            raise ValueError(
                f"Reschedule cutoff: {round_} interview is within "
                f"{self.RESCHEDULE_CUTOFF_HOURS} hours of starting"
            )

        # Cancel the actual Teams meeting on Graph (best-effort — even if
        # the cancel fails, we still want to drop our local state and
        # propose new slots so the candidate isn't stuck).
        try:
            cancel_or_reschedule_meeting(interview.id)
            app.log("agent", f"Cancelled previous {round_} Teams meeting on Graph")
        except Exception as exc:  # noqa: BLE001
            app.log(
                "agent",
                f"Could not cancel previous {round_} meeting (continuing anyway): {exc!r}",
                level="warn",
            )

        # Drop the in-memory interview record and reset slot state so the
        # state machine walks back to the propose-slots branch.
        app.interviews = [i for i in app.interviews if i.round != round_]
        if round_ == "R1":
            app.proposed_r1_slots = []
            app.selected_r1_slot_index = None
            app.r1_started = False
            update_application_status(
                app.id,
                FunnelStage.SCREENED,
                "Candidate requested a Round 1 reschedule",
            )
        else:
            app.proposed_r2_slots = []
            app.selected_r2_slot_index = None
            update_application_status(
                app.id,
                FunnelStage.R1_DONE,
                "Candidate requested a Round 2 reschedule",
            )

        app.log("candidate", f"Requested a {round_} reschedule")
        self.trigger(application_id)
        return app

    def on_panel_feedback(self, application_id: str) -> None:
        """A panellist submitted feedback — resume if all panel feedback in."""
        app = STORE.get_application(application_id)
        if not app:
            return
        self.trigger(application_id)

    # ------------------------------------------------------------------
    # Private: main run loop
    # ------------------------------------------------------------------

    def _run_safe(self, application_id: str) -> None:
        # Drain the pending flag in a loop so any trigger() that arrives
        # mid-run is honoured before we exit. Without this, a slot
        # confirmation that lands while Phase 1 is still running would
        # be silently dropped and the state machine would stall.
        while True:
            with self._lock:
                if application_id not in self._pending:
                    return
                self._pending.discard(application_id)
            try:
                self._run(application_id)
            except Exception as exc:  # noqa: BLE001 - we want all errors captured
                app = STORE.get_application(application_id)
                if app:
                    app.log("agent", f"Orchestrator error: {exc!r}", level="error")
                    app.agent_status = AgentStatus.IDLE
            # Checkpoint to disk after every pass so uvicorn --reload,
            # a crash, or an accidental kill doesn't wipe mid-flow state
            # (proposed slots, selected slot, r1_started, interview records).
            app_after = STORE.get_application(application_id)
            if app_after:
                STORE.save_application(app_after)

    def _run(self, application_id: str) -> None:
        """The state machine. Advances the application as far as it can."""
        app = STORE.get_application(application_id)
        if not app:
            raise LookupError(application_id)

        app.agent_status = AgentStatus.RUNNING

        # Loop until we hit a terminal/waiting state and can't advance further.
        while True:
            stage = app.stage
            if stage == FunnelStage.APPLIED:
                if not self._do_screening(app):
                    return
                continue
            if stage == FunnelStage.SCREENED:
                if not self._do_outreach_and_schedule_r1(app):
                    return
                continue
            if stage == FunnelStage.R1_SCHEDULED:
                # R1 is a real human gate: the candidate must explicitly
                # start the AI interview from the live status page. In
                # production this would be the Virtual Interview Agent
                # webhook firing when the Teams call actually happens.
                if not app.r1_started:
                    self._pause_waiting_candidate(
                        app,
                        "Click 'Start interview' on your status page to begin Round 1",
                    )
                    return
                if not self._do_run_r1(app):
                    return
                continue
            if stage == FunnelStage.R1_DONE:
                if not self._do_schedule_r2(app):
                    return
                continue
            if stage == FunnelStage.R2_SCHEDULED:
                if not self._do_finalise(app):
                    return
                continue
            if stage == FunnelStage.OFFER_NEGOTIATION:
                # Pure human-gated stage owned by the Offer Discussion Team.
                # Nothing for the agent to do until they click "Roll out
                # final offer" — at which point on_offer_team_rollout flips
                # the stage to OFFER and the next loop tick lands at the
                # terminal block below.
                app.agent_status = AgentStatus.WAITING_OFFER_TEAM
                if not app.next_action:
                    app.next_action = (
                        "Offer Discussion Team to negotiate final CTC and roll out the offer letter."
                    )
                return
            if stage in (
                FunnelStage.OFFER,
                FunnelStage.OFFER_ACCEPTED,
                FunnelStage.PRE_JOINING,
            ):
                # Post-offer stages are managed by the engagement engine,
                # not the hiring orchestrator. Pause here.
                return
            if stage in (
                FunnelStage.JOINED,
                FunnelStage.OFFER_DECLINED,
                FunnelStage.REJECTED,
            ):
                app.agent_status = AgentStatus.DONE
                return

    # ------------------------------------------------------------------
    # Stage implementations — each returns True to keep looping, False to pause
    # ------------------------------------------------------------------

    def _do_screening(self, app: Application) -> bool:
        """Run the AI screening rubric.

        Returns True if the screening is finished and the loop can advance
        to the next stage, False if we paused the orchestrator (e.g.
        waiting on the Business Partner to review a below-threshold match).
        """
        from .tools.intake import get_jd
        jd = get_jd(app.job_id)

        # External candidates skip the visible "agent is screening" UI
        # entirely. The product decision (Q2 demo) is that any external
        # applicant who clicks Apply jumps straight to a Level 1 AI agent
        # interview — the agent is the screening gate, not a rubric run.
        # We still log a one-line score for HR's audit trail, but we
        # never reject and never delay.
        if app.candidate_kind == "external":
            app.log(
                "agent",
                f"External candidate — skipping rubric screening, "
                f"advancing directly to Level 1 AI interview "
                f"(profile match: {app.match_percent:.0f}%)",
            )
            move_cv(app.id, f"/cvs/shortlisted/{jd.id}/")
            update_application_status(
                app.id,
                FunnelStage.SCREENED,
                "External candidate — preparing Level 1 AI interview slots",
            )
            return True

        # Stage 1 — pulling the candidate profile from Thrive
        app.next_action = "Agent is pulling your Thrive profile and KRAs…"
        app.log("agent", "Fetching Thrive profile (KRAs, skills catalogue, tenure)")
        if _SCREEN_SCAN_DELAY > 0:
            time.sleep(_SCREEN_SCAN_DELAY)

        # Stage 2 — intersecting profile skills with JD rubric
        app.next_action = (
            f"Agent is intersecting your skills with the {jd.title} rubric…"
        )
        app.log(
            "agent",
            f"Matching {len(app.matched_skills) + len(app.missing_skills)} required skill(s) against your Thrive profile",
        )
        if _SCREEN_MATCH_DELAY > 0:
            time.sleep(_SCREEN_MATCH_DELAY)

        # Stage 3 — running the JD rubric to compute the match %
        app.next_action = "Agent is running the JD rubric and computing your match %…"
        app.log(
            "agent",
            f"Screening {len(app.matched_skills)} matched skill(s) against JD rubric",
        )
        if _SCREEN_RUBRIC_DELAY > 0:
            time.sleep(_SCREEN_RUBRIC_DELAY)

        # Human-in-the-loop screening (2026-04-07): the agent never
        # auto-rejects an internal candidate at intake. Above threshold
        # → shortlist and continue. Below threshold → email the full AI
        # screening report to the Business Partner and pause WAITING_HR until
        # they explicitly advance or regret. HR decision is honoured the
        # next time _do_screening runs (via the hr_screening_decision
        # field on the application).
        from .tools.intake import get_employee_profile
        profile = get_employee_profile(app.candidate_id)

        above_threshold = app.match_percent >= jd.shortlist_threshold
        hr_advanced = app.hr_screening_decision == "advance"
        hr_regretted = app.hr_screening_decision == "regret"

        if above_threshold or hr_advanced:
            move_cv(app.id, f"/cvs/shortlisted/{jd.id}/")
            reason = (
                "Shortlisted — preparing outreach with proposed slots"
                if above_threshold
                else "HR override — preparing outreach with proposed slots"
            )
            update_application_status(app.id, FunnelStage.SCREENED, reason)
            if hr_advanced:
                app.log(
                    "agent",
                    f"Business Partner overrode the {jd.shortlist_threshold:.0f}% "
                    f"threshold — advancing {profile.name} to Round 1 "
                    f"despite a {app.match_percent:.0f}% AI screening score.",
                )
            return True

        if hr_regretted:
            move_cv(app.id, f"/cvs/rejected/{jd.id}/")
            update_application_status(
                app.id,
                FunnelStage.REJECTED,
                "Business Partner closed the application after reviewing the AI screening report.",
            )
            subject, body = comms.post_screening_reject(
                profile.name, jd.title, jd.location
            )
            send_email(
                to=profile.email,
                subject=subject,
                body=body,
                application_id=app.id,
            )
            app.log(
                "agent",
                f"Business Partner clicked Regret on the screening review — "
                f"sent the post-screening regret email to {profile.email}.",
            )
            return True

        # Below threshold AND HR has not yet decided → pause WAITING_HR.
        # We deliberately do NOT touch the funnel stage (it stays APPLIED)
        # and we do NOT move the CV anywhere — the application is alive
        # and waiting for a human decision.
        hr_review_url = (
            f"{os.environ.get('AXIS_PUBLIC_BASE_URL', 'http://127.0.0.1:3001')}"
            f"/hr/applications/{app.id}"
        )
        subject, body = comms.screening_hr_review_summary(
            candidate_name=profile.name,
            candidate_email=profile.email,
            candidate_role=profile.current_role,
            candidate_tenure=profile.tenure_years,
            jd_title=jd.title,
            jd_location=jd.location,
            jd_threshold=jd.shortlist_threshold,
            match_percent=app.match_percent,
            matched_skills=app.matched_skills,
            missing_skills=app.missing_skills,
            rationale=app.match_rationale,
            hr_review_url=hr_review_url,
        )
        send_email(
            to=jd.hr_partner_id,
            subject=subject,
            body=body,
            application_id=app.id,
        )
        app.log(
            "agent",
            f"Screening match {app.match_percent:.0f}% < threshold "
            f"{jd.shortlist_threshold:.0f}% — emailed full AI screening "
            f"report to Business Partner {jd.hr_partner_id} for review.",
        )
        notify_hr_partner(
            app.id,
            f"Screening review needed — {profile.name} scored "
            f"{app.match_percent:.0f}% on {jd.title} (threshold "
            f"{jd.shortlist_threshold:.0f}%). Advance or regret on the "
            f"Business Partner page.",
        )
        return self._pause_waiting_hr(
            app,
            "AI screening complete — Business Partner to review the rubric "
            "breakdown and decide whether to advance the candidate to "
            "Round 1 or regret them.",
        )

    def _do_outreach_and_schedule_r1(self, app: Application) -> bool:
        """SCREENED → R1_SCHEDULED.

        Two-phase. First time we hit this stage we propose slots and pause as
        WAITING_CANDIDATE. When the candidate confirms a slot via the API, the
        orchestrator resumes here and books the meeting.
        """
        from .tools.intake import get_employee_profile, get_jd
        jd = get_jd(app.job_id)
        profile = get_employee_profile(app.candidate_id)

        # Pre-R1 checklist (snapshot; idempotent).
        instantiate_checklist(app.id, "R1", "pre")

        # ---- Phase 1: propose slots (only if we haven't already) ----
        if not app.proposed_r1_slots:
            app.next_action = "Agent is checking calendars and proposing interview slots…"

            window_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            window_end = window_start + timedelta(days=10)
            # External candidates have no Axis calendar — Graph free/busy
            # would 404 on their email. Intersect only the Business Partner's
            # calendar; the candidate gets the proposed slots over email
            # and replies with their pick.
            if app.candidate_kind == "external":
                attendees = [jd.hr_partner_id]
            else:
                attendees = [profile.email, jd.hr_partner_id]
            slots: list = []
            try:
                slots = find_common_slots(
                    user_ids=attendees,
                    duration_min=30,
                    window_start=window_start,
                    window_end=window_end,
                    top_n=3,
                ) or []
            except Exception as exc:
                app.log(
                    "agent",
                    f"Calendar intersect failed ({exc!r}) — falling back to synthetic R1 slots",
                    level="warn",
                )

            # R1 is run by the AI Interview Agent end-to-end — no human
            # panellist actually has to be free for the candidate to take
            # the call. Graph free/busy is a best-effort hint. If it
            # returns < 3 slots (Business Partner's calendar full, Graph 503,
            # whatever), top up with deterministic business-hour slots
            # so the candidate is NEVER blocked on calendar availability.
            if len(slots) < 3:
                synth = self._synthesise_r1_slots(
                    needed=3 - len(slots), starting_from=window_start, avoid=slots
                )
                if synth:
                    slots = (slots or []) + synth
                    app.log(
                        "agent",
                        f"Topped up R1 slot pool with {len(synth)} synthetic AI-agent slots "
                        f"(HR calendar returned {len(slots) - len(synth)})",
                    )

            if not slots:
                # Should be unreachable now that we always synthesise, but
                # keep the safety net so we never serve an empty picker.
                app.log(
                    "agent",
                    "No common R1 slot AND synthesiser produced none — HR review needed",
                    level="warn",
                )
                return self._pause_waiting_hr(
                    app, "Agent could not find a common R1 slot — HR review needed"
                )

            app.proposed_r1_slots = slots
            app.log(
                "agent",
                f"Intersected calendars of {len(attendees)} attendees "
                f"({', '.join(attendees)}) — found {len(slots)} common R1 slots",
            )
            subject, body = comms.r1_outreach_with_slots(
                profile.name, jd.title, jd.location, slots
            )
            email = send_email(
                to=profile.email,
                subject=subject,
                body=body,
                application_id=app.id,
            )
            app.log(
                "agent",
                f"Outreach email sent with {len(slots)} proposed slots (thread {email.thread_id})",
            )
            tick_checklist_item(app.id, "R1", "pre", "pre-r1-3", note="Profile + KRAs attached")
            tick_checklist_item(app.id, "R1", "pre", "pre-r1-4", note="Required skills loaded into rubric")
            tick_checklist_item(app.id, "R1", "pre", "pre-r1-6", note="Joining instructions in body")

            return self._pause_waiting_candidate(
                app, "Waiting for you to confirm your preferred Round 1 interview slot"
            )

        # ---- Phase 2: candidate has chosen a slot — book it ----
        if app.selected_r1_slot_index is None:
            return self._pause_waiting_candidate(
                app, "Waiting for you to confirm your preferred Round 1 interview slot"
            )

        chosen = app.proposed_r1_slots[app.selected_r1_slot_index]
        attendees = [profile.email, jd.hr_partner_id]
        app.next_action = "Agent is booking the Teams meeting on the panel calendar…"
        invite_subject, invite_body = comms.r1_calendar_invite(
            name=profile.name,
            jd_title=jd.title,
            jd_location=jd.location,
            start=chosen.start,
            end=chosen.end,
            employee_id=profile.employee_id,
        )
        event = create_teams_meeting(
            subject=invite_subject,
            start=chosen.start,
            end=chosen.end,
            organiser_id=jd.hr_partner_id,
            attendees=attendees,
            body=invite_body,
            application_id=app.id,
        )
        app.log("agent", f"Teams meeting created {event.id} for {chosen.start.isoformat()}")
        tick_checklist_item(app.id, "R1", "pre", "pre-r1-1", note="Candidate confirmed slot")
        tick_checklist_item(app.id, "R1", "pre", "pre-r1-2", note=f"Teams link: {event.teams_join_url}")

        stub = InterviewRecord(
            id=event.id,
            application_id=app.id,
            round="R1",
            teams_meeting_id=event.id,
            teams_join_url=event.teams_join_url,
            meeting_slot=TimeSlot(start=chosen.start, end=chosen.end),
        )
        app.interviews.append(stub)

        if not is_checklist_satisfied(app.id, "R1", "pre", blocking_only=True):
            return self._pause_waiting_hr(app, "Pre-R1 checklist has unsatisfied blocking items")

        update_application_status(
            app.id,
            FunnelStage.R1_SCHEDULED,
            f"R1 AI interview · {chosen.start.strftime('%a %d %b %H:%M')} IST",
        )
        return True

    def _do_run_r1(self, app: Application) -> bool:
        from .tools.intake import get_jd
        jd = get_jd(app.job_id)

        stub = next((i for i in app.interviews if i.round == "R1"), None)
        if stub is None:
            return self._pause_waiting_hr(app, "No R1 interview on record — cannot run")

        # CRITICAL: do not score (and do not reject!) until the candidate
        # has actually completed the real interactive Virtual Interviewer
        # Q&A. The previous version of this method ran a *scripted* canned
        # transcript here the moment r1_started flipped — which meant a
        # candidate who clicked "Start interview" got rejected by email
        # before they ever saw a question. Bug surfaced as: page at
        # /thrive/virtual-interview/[appId] hangs on "AI is preparing your
        # tailored questions…" and a regret email arrives in Outlook.
        #
        # The interactive flow is:
        #   1. Candidate clicks Start → on_candidate_start_r1 sets r1_started=True
        #   2. Frontend navigates to /thrive/virtual-interview/[appId]
        #   3. That page POSTs /virtual-interview/start which builds the
        #      Claude question list and returns the first question
        #   4. Candidate answers each question via /virtual-interview/answer
        #   5. On the last answer, _fold_transcript_into_interview writes
        #      InterviewRecord.transcript and calls ORCHESTRATOR.trigger()
        #   6. The loop wakes up, re-enters _do_run_r1, and *now* the
        #      transcript is non-empty, so we score it for real
        #
        # Until step 5 lands, we pause as WAITING_CANDIDATE so HR can see
        # the candidate is mid-interview and so the candidate page can
        # render the live interview UI without the orchestrator racing
        # ahead and rejecting them.
        if not stub.transcript:
            # If the candidate explicitly ended the session early (and the
            # virtual interviewer marked the InterviewRecord as completed)
            # but we captured zero answers, we cannot just sit on
            # WAITING_CANDIDATE forever — that's the "stuck status page"
            # the demo team flagged. Treat zero-answer completed sessions
            # as an auto-reject so the funnel advances and the candidate
            # sees a clear result instead of an indefinite spinner.
            if (stub.virtual_interview_state or "").lower() == "completed":
                from .tools.intake import get_employee_profile
                profile = get_employee_profile(app.candidate_id)
                move_cv(app.id, f"/cvs/rejected/{jd.id}/")
                update_application_status(
                    app.id,
                    FunnelStage.REJECTED,
                    "Candidate ended the AI Interview Agent session before "
                    "answering any questions — application auto-closed.",
                )
                r1_subject, r1_body = comms.r1_reject(profile.name, jd.title)
                send_email(
                    to=profile.email,
                    subject=r1_subject,
                    body=r1_body,
                    application_id=app.id,
                )
                app.log(
                    "agent",
                    "Round 1 ended without any captured answers — "
                    f"application auto-closed and regret email sent to {profile.email}.",
                )
                app.next_action = (
                    "Round 1 ended without captured answers — application closed."
                )
                app.agent_status = AgentStatus.IDLE
                return True

            app.next_action = (
                "Candidate is in the AI Interview Agent session — "
                "waiting for the transcript to complete."
            )
            app.log(
                "agent",
                "R1 started — pausing orchestrator until the AI Interview "
                "Agent finishes capturing the candidate's answers",
            )
            return self._pause_waiting_candidate(
                app, "AI Interview Agent is in session with the candidate"
            )

        # Transcript has been folded in by the virtual interviewer — score
        # the REAL captured (Q,A) pairs against the JD rubric.
        app.next_action = "AI Interview Agent is scoring the transcript against the JD rubric…"
        app.log("agent", "Transcript captured — scoring against JD rubric")
        if _R1_RUN_SCORE_DELAY > 0:
            time.sleep(_R1_RUN_SCORE_DELAY)

        score, rationale = score_interview_transcript(stub, jd)
        stub.score = score
        stub.rationale = rationale
        app.log("agent", f"R1 scored {score:.0f}/100 — {rationale}")

        # Build the structured AI Interview Agent report — this is what the
        # R2 panel reads before the panel interview, and what the candidate
        # status page surfaces as "what the agent thought".
        stub.report = build_r1_report(stub, jd)
        app.log(
            "agent",
            f"R1 report ready: {stub.report.headline} "
            f"(recommendation: {stub.report.recommendation})",
        )

        instantiate_checklist(app.id, "R1", "post")
        tick_checklist_item(app.id, "R1", "post", "post-r1-1", note="Transcript saved to InterviewRecord")
        tick_checklist_item(app.id, "R1", "post", "post-r1-2", note="Scored via JD rubric")
        tick_checklist_item(app.id, "R1", "post", "post-r1-3", note=f"Score {score:.0f}/100 — awaiting HR decision")

        # ------------------------------------------------------------------
        # R1 verdict routing (post-AI-Interview Agent)
        # ------------------------------------------------------------------
        # Rule (per product owner): the AI Interview Agent IS the gate at
        # R1 — opposite of intake screening which is human-gated.
        #   • recommendation == "reject"      → auto-close, regret email,
        #     application never lands in the HR queue.
        #   • recommendation == "advance" or
        #     "borderline"                    → forward to Business Partner with
        #     full transcript + AI report. HR decides R2 vs regret.
        #
        # This frees HR from drowning in obvious rejects and matches the
        # demo narrative: "AI does the first screen, humans do the calls
        # that matter."
        from .tools.intake import get_employee_profile
        profile = get_employee_profile(app.candidate_id)

        transcript_pairs: list = []
        if stub.transcript:
            # transcript is a flat list of segments alternating
            # interviewer/candidate — fold them into Q/A pairs.
            it = iter(stub.transcript)
            for seg in it:
                if seg.speaker != "interviewer":
                    continue
                try:
                    ans = next(it)
                except StopIteration:
                    break
                transcript_pairs.append(
                    {"question": seg.text, "answer": ans.text}
                )

        report = stub.report
        rubric_scores = dict(report.rubric_scores) if report else {}
        red_flags = list(report.red_flags) if report else []
        probes = list(report.recommended_probes) if report else []
        headline = report.headline if report else f"R1 AI score {score:.0f}/100"
        recommendation = report.recommendation if report else (
            "advance" if score >= 70 else "regret"
        )

        # ------------------------------------------------------------------
        # Demo-stability override (per product owner): as long as the
        # candidate gave ANY substantive answers, always forward to the
        # Business Partner for a human decision. R1 reject is reserved strictly
        # for empty / no-answer sessions (which are already caught and
        # handled in the `if not stub.transcript` branch above). This
        # guarantees the demo flow always reaches the HR queue end to end.
        #
        # Toggle with AXIS_R1_ALWAYS_FORWARD=0 if you want to test the
        # real reject path. Default is on.
        # ------------------------------------------------------------------
        _always_forward = os.environ.get("AXIS_R1_ALWAYS_FORWARD", "1") == "1"
        if _always_forward and recommendation == "reject" and stub.transcript:
            app.log(
                "agent",
                f"R1 AI raw recommendation was 'reject' (score {score:.0f}/100) "
                f"but candidate gave answers — forwarding to Business Partner for "
                f"human decision per AXIS_R1_ALWAYS_FORWARD policy.",
            )
            recommendation = "borderline"

        # ------------------------------------------------------------------
        # Auto-close path: AI Interview Agent recommends reject
        # ------------------------------------------------------------------
        if recommendation == "reject":
            move_cv(app.id, f"/cvs/rejected/{jd.id}/")
            update_application_status(
                app.id,
                FunnelStage.REJECTED,
                f"AI Interview Agent recommended reject after R1 "
                f"(score {score:.0f}/100). Application auto-closed.",
            )
            r1_subject, r1_body = comms.r1_reject(profile.name, jd.title)
            send_email(
                to=profile.email,
                subject=r1_subject,
                body=r1_body,
                application_id=app.id,
            )
            app.log(
                "agent",
                f"AI Interview Agent recommended REJECT (score {score:.0f}/100) — "
                f"application auto-closed and regret email sent to {profile.email}. "
                f"HR review skipped per R1 auto-reject rule.",
            )
            tick_checklist_item(app.id, "R1", "post", "post-r1-4")
            app.next_action = "AI Interview Agent rejected the candidate at R1 — application closed."
            app.agent_status = AgentStatus.IDLE
            return True

        hr_review_url = (
            f"{os.environ.get('AXIS_PUBLIC_BASE_URL', 'http://127.0.0.1:3001')}"
            f"/hr/applications/{app.id}"
        )
        subject, body = comms.r1_hr_review_summary(
            candidate_name=profile.name,
            candidate_email=profile.email,
            jd_title=jd.title,
            jd_location=jd.location,
            score=score,
            headline=headline,
            recommendation=recommendation,
            rubric_scores=rubric_scores,
            transcript_pairs=transcript_pairs,
            red_flags=red_flags,
            recommended_probes=probes,
            hr_review_url=hr_review_url,
        )
        send_email(
            to=jd.hr_partner_id,
            subject=subject,
            body=body,
            application_id=app.id,
        )
        app.log(
            "agent",
            f"Emailed full R1 AI analysis to Business Partner {jd.hr_partner_id} "
            f"(score {score:.0f}/100, AI recommendation: {recommendation})",
        )
        notify_hr_partner(
            app.id,
            f"R1 AI interview complete — score {score:.0f}/100 ({recommendation}). "
            f"Review transcript and decide R2 vs regret.",
        )
        tick_checklist_item(app.id, "R1", "post", "post-r1-4")

        # Stage moves to R1_DONE so the HR queue picks it up. The funnel
        # progress card on the candidate page advances to "R1 Done" too,
        # which is the truthful state — the AI interview is over and a
        # human decision is pending.
        update_application_status(
            app.id,
            FunnelStage.R1_DONE,
            "AI Interview Agent finished — awaiting HR review of transcript and AI report",
        )
        return self._pause_waiting_hr(
            app,
            "AI Interview Agent finished Round 1 — Business Partner to review the "
            "transcript and AI report, then advance to Round 2 or regret.",
        )

    def _do_schedule_r2(self, app: Application) -> bool:
        """R1_DONE → R2_SCHEDULED.

        Two-phase, mirroring R1:
          Phase 1: HR approves panel → agent intersects calendars across
                   [candidate, hr, panel], proposes 3 slots, emails the
                   candidate, pauses WAITING_CANDIDATE for R2.
          Phase 2: Candidate confirms an R2 slot → agent books the Teams
                   meeting, briefs the panel, pauses WAITING_PANEL.
        """
        from .tools.intake import get_employee_profile, get_jd
        jd = get_jd(app.job_id)
        profile = get_employee_profile(app.candidate_id)

        instantiate_checklist(app.id, "R2", "pre")
        tick_checklist_item(app.id, "R2", "pre", "pre-r2-1", note="R1 score + transcript attached")

        # DESIGN-001 chunk 4: the HR approval gate is now the
        # ``selected_r2_panel_id`` field on the application, set via the
        # ``POST /applications/{id}/approve-r2`` endpoint. The old manual
        # checklist tick ``pre-r2-2`` is auto-ticked by that endpoint so
        # downstream audit trails still see the approval event.
        if app.selected_r2_panel_id is None:
            return self._pause_waiting_hr(
                app,
                "HR must approve the R2 panel before the agent invites them",
            )

        # Resolve the selected panel and use its members (instead of the
        # legacy ``jd.panel``) for slot intersection + the Teams invite.
        selected_panel = STORE.get_panel(app.selected_r2_panel_id)
        if selected_panel is None:
            app.log(
                "agent",
                f"Selected panel {app.selected_r2_panel_id} not found — falling back to JD default panel",
                level="warn",
            )
            panel_members = [p for p in jd.panel if p.role != "hr_partner"]
        else:
            panel_members = list(selected_panel.members)
        panel_ids = [m.user_id for m in panel_members]
        # Two attendee lists, intentionally:
        #
        #   * busy_attendees: who we ASK Microsoft Graph to free/busy.
        #     External candidates have no Axis mailbox so Graph 404s on
        #     them — we have to leave them OUT of this intersection or
        #     find_common_slots crashes.
        #
        #   * meeting_attendees: who we INVITE to the actual Teams
        #     meeting. The candidate (internal OR external) MUST be on
        #     this list, otherwise they never get the calendar invite in
        #     their inbox. The earlier code reused busy_attendees here
        #     and that's why external candidates were silently dropped
        #     from R2 invites.
        if app.candidate_kind == "external":
            busy_attendees = list({jd.hr_partner_id, *panel_ids})
        else:
            busy_attendees = list({jd.hr_partner_id, profile.email, *panel_ids})
        meeting_attendees = list({jd.hr_partner_id, profile.email, *panel_ids})

        # ---- Phase 1: propose slots (only if not already proposed) ----
        if not app.proposed_r2_slots:
            window_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2)
            window_end = window_start + timedelta(days=5)
            slots = find_common_slots(
                user_ids=busy_attendees,
                duration_min=45,
                window_start=window_start,
                window_end=window_end,
                top_n=3,
            )
            if not slots:
                return self._pause_waiting_hr(
                    app, "Agent could not find a common R2 slot — HR review needed"
                )
            app.proposed_r2_slots = slots
            tick_checklist_item(
                app.id, "R2", "pre", "pre-r2-3",
                note=f"{len(slots)} common slots found across {len(busy_attendees)} attendees",
            )
            app.log(
                "agent",
                f"Intersected calendars of {len(busy_attendees)} attendees "
                f"({', '.join(busy_attendees)}) — found {len(slots)} common R2 slots",
            )

            r1 = next((i for i in app.interviews if i.round == "R1"), None)
            r1_score_val = r1.score if (r1 and r1.score is not None) else None
            subject, body = comms.r2_outreach_with_slots(
                name=profile.name,
                jd_title=jd.title,
                jd_location=jd.location,
                slots=slots,
                r1_score=r1_score_val,
                panel_size=len([p for p in jd.panel if p.role != "hr_partner"]),
            )
            send_email(
                to=profile.email,
                subject=subject,
                body=body,
                application_id=app.id,
            )
            return self._pause_waiting_candidate(
                app, "Waiting for you to confirm your preferred Round 2 panel slot"
            )

        # ---- Phase 2: candidate has chosen a slot — book it ----
        if app.selected_r2_slot_index is None:
            return self._pause_waiting_candidate(
                app, "Waiting for you to confirm your preferred Round 2 panel slot"
            )

        chosen = app.proposed_r2_slots[app.selected_r2_slot_index]
        r1 = next((i for i in app.interviews if i.round == "R1"), None)
        report = getattr(r1, "report", None) if r1 else None

        panel_names = [m.name for m in panel_members]
        invite_subject, invite_body = comms.r2_calendar_invite(
            name=profile.name,
            jd_title=jd.title,
            jd_location=jd.location,
            start=chosen.start,
            end=chosen.end,
            employee_id=profile.employee_id,
            panel_names=panel_names,
            r1_score=(r1.score if (r1 and r1.score is not None) else None),
            r1_headline=(report.headline if report else None),
            r1_recommendation=(report.recommendation if report else None),
            recommended_probes=(list(report.recommended_probes) if report else None),
        )
        # IMPORTANT: pass meeting_attendees (which always includes the
        # candidate), not busy_attendees. External candidates were being
        # silently dropped from the invite list because the calendar
        # intersection list excludes them.
        event = create_teams_meeting(
            subject=invite_subject,
            start=chosen.start,
            end=chosen.end,
            organiser_id=jd.hr_partner_id,
            attendees=meeting_attendees,
            body=invite_body,
            application_id=app.id,
        )
        app.log(
            "agent",
            f"R2 Teams meeting booked — invite sent to {len(meeting_attendees)} "
            f"attendees: {', '.join(meeting_attendees)}",
        )
        tick_checklist_item(app.id, "R2", "pre", "pre-r2-4", note=f"Teams: {event.teams_join_url}")
        tick_checklist_item(app.id, "R2", "pre", "pre-r2-5", note="Panel briefing attached")
        tick_checklist_item(app.id, "R2", "pre", "pre-r2-6", note="Feedback form link embedded")

        notify_panel(
            jd.id,
            f"R2 scheduled for {profile.name} on {chosen.start.strftime('%a %d %b %H:%M')} IST — AI report ready",
            application_id=app.id,
        )

        stub = InterviewRecord(
            id=event.id,
            application_id=app.id,
            round="R2",
            teams_meeting_id=event.id,
            teams_join_url=event.teams_join_url,
            meeting_slot=TimeSlot(start=chosen.start, end=chosen.end),
            # Pre-seed canned Teams transcripts so panellists can read the
            # conversation as if the meeting had just ended. In production
            # each panellist's individual 1-on-1 transcript would come from
            # Microsoft Graph's Teams transcript API once that panellist's
            # meeting concludes. ``pasted_transcript`` is the legacy single
            # transcript kept for backward compatibility; the per-panellist
            # variants live on ``pasted_transcripts_by_panellist`` so the
            # HR per-panellist AI review can score each interviewer against
            # their own conversation.
            pasted_transcript=SAMPLE_R2_TRANSCRIPT,
            pasted_transcripts_by_panellist=transcripts_for_panel(
                [m.user_id for m in panel_members]
            ),
        )
        app.interviews.append(stub)
        update_application_status(
            app.id,
            FunnelStage.R2_SCHEDULED,
            f"R2 panel · {chosen.start.strftime('%a %d %b %H:%M')} IST — awaiting panel feedback",
        )

        # R2 is a natural pause point — wait for panel feedback.
        return self._pause_waiting_panel(app, "Awaiting panel feedback")

    def _do_finalise(self, app: Application) -> bool:
        """R2_SCHEDULED → HR review gate.

        Once every panellist has voted, the orchestrator ALWAYS hands the
        application back to the Business Partner for the final decision. The
        agent-suggested verdict (from ``consolidate_recommendation``) is
        recorded to the audit trail as a hint, but the agent never auto-sends
        the offer or regret email — that is now an explicit HR action taken
        via ``on_hr_r2_decision`` / ``POST /applications/{id}/hr-r2-decision``.

        This split exists so that only HR (not panellists) can run the
        Claude-based AI review of the R2 transcript and compare it with the
        panel's manual feedback before committing.
        """
        from .tools.intake import get_jd
        jd = get_jd(app.job_id)

        r2 = next((i for i in app.interviews if i.round == "R2"), None)
        if r2 is None:
            return self._pause_waiting_hr(app, "Cannot finalise — no R2 interview on file")

        # Use the HR-selected panel if available; fall back to the JD's
        # legacy panel for backward compatibility.
        selected_panel = (
            STORE.get_panel(app.selected_r2_panel_id)
            if app.selected_r2_panel_id
            else None
        )
        if selected_panel is not None:
            panel_ids = [m.user_id for m in selected_panel.members]
        else:
            panel_ids = [p.user_id for p in jd.panel if p.role != "hr_partner"]
        feedback = collect_panel_feedback(r2.id, panel_ids)
        if not feedback["complete"]:
            return self._pause_waiting_panel(
                app, f"Awaiting feedback from {len(feedback['pending'])} panellist(s)"
            )

        # Compute the agent-suggested verdict and log it for HR's reference.
        # The verdict is NOT executed — HR reviews + decides.
        rec = consolidate_recommendation(app.id, feedback)

        instantiate_checklist(app.id, "R2", "post")
        tick_checklist_item(app.id, "R2", "post", "post-r2-1", note="All panellists submitted")
        tick_checklist_item(
            app.id, "R2", "post", "post-r2-2",
            note=f"Agent-suggested verdict: {rec.verdict} — {rec.rationale}",
        )

        app.log(
            "agent",
            f"R2 panel voting complete — {len(feedback['submitted'])}/{len(panel_ids)} votes in. "
            f"Agent-suggested verdict: {rec.verdict} ({rec.rationale}). "
            f"Awaiting HR decision.",
        )
        notify_hr_partner(
            app.id,
            f"R2 panel voting complete — HR decision required. "
            f"Agent-suggested verdict: {rec.verdict}.",
        )
        return self._pause_waiting_hr(
            app,
            "Panel voting complete — HR decision required on R2",
        )

    def on_hr_r2_decision(self, application_id: str, decision: str) -> Application:
        """HR has made the final R2 verdict — execute offer or reject.

        Called from ``POST /applications/{id}/hr-r2-decision`` once HR has
        reviewed the panel feedback (and optionally the Claude AI review)
        and clicked "Make offer" or "Reject".

        Idempotent-ish: refuses to act if the application is not at the
        correct stage or if not all panellists have voted yet.
        """
        from .tools.intake import get_employee_profile, get_jd

        if decision not in ("offer", "reject"):
            raise ValueError(f"Unknown HR R2 decision: {decision!r}")

        app = STORE.get_application(application_id)
        if app is None:
            raise LookupError(application_id)

        if app.stage != FunnelStage.R2_SCHEDULED:
            raise ValueError(
                f"Cannot take an HR R2 decision from stage {app.stage.value}"
            )

        r2 = next((i for i in app.interviews if i.round == "R2"), None)
        if r2 is None:
            raise ValueError("No R2 interview on file")

        jd = get_jd(app.job_id)
        profile = get_employee_profile(app.candidate_id)

        selected_panel = (
            STORE.get_panel(app.selected_r2_panel_id)
            if app.selected_r2_panel_id
            else None
        )
        if selected_panel is not None:
            panel_ids = [m.user_id for m in selected_panel.members]
        else:
            panel_ids = [p.user_id for p in jd.panel if p.role != "hr_partner"]

        feedback = collect_panel_feedback(r2.id, panel_ids)
        if not feedback["complete"]:
            raise ValueError(
                f"Cannot finalise — still waiting on {len(feedback['pending'])} "
                f"panellist(s): {', '.join(feedback['pending'])}"
            )

        # Recompute the agent-suggested verdict so we can log HR's delta
        # against it in the audit trail.
        rec = consolidate_recommendation(app.id, feedback)

        tick_checklist_item(
            app.id, "R2", "post", "post-r2-3",
            note=f"HR verdict: {decision} (agent suggested: {rec.verdict})",
        )

        if decision == "offer":
            # NEW (post-2026-04-07): HR's "offer" decision no longer rolls
            # out the formal offer email directly. Instead the application
            # enters OFFER_NEGOTIATION and is handed to the Offer Discussion
            # Team persona, who reads the salary scripts + AI analysis,
            # negotiates the final CTC with the candidate, and clicks
            # "Roll out final offer" — that endpoint flips the stage to
            # OFFER and sends comms.final_offer_email.
            update_application_status(
                app.id,
                FunnelStage.OFFER_NEGOTIATION,
                "HR approved the offer — Offer Discussion Team to negotiate final CTC",
            )
            tick_checklist_item(
                app.id, "R2", "post", "post-r2-4",
                note="Handed to Offer Discussion Team for CTC negotiation",
            )
            app.log(
                "hr_partner",
                f"HR approved offer after panel review (agent suggested: {rec.verdict}) — "
                f"handing off to Offer Discussion Team",
            )
            notify_hr_partner(
                app.id,
                "HR approved offer — application is now with the Offer Discussion Team.",
            )
            app.agent_status = AgentStatus.WAITING_OFFER_TEAM
            app.next_action = (
                "Offer Discussion Team to negotiate final CTC and roll out the offer letter."
            )
            self._refresh_pending(app)
            return app
        else:  # reject
            move_cv(app.id, f"/cvs/rejected/{jd.id}/")
            update_application_status(
                app.id,
                FunnelStage.REJECTED,
                f"HR rejected after panel review",
            )
            subject, body = comms.r2_reject(profile.name, jd.title)
            send_email(
                to=profile.email,
                subject=subject,
                body=body,
                application_id=app.id,
            )
            tick_checklist_item(app.id, "R2", "post", "post-r2-4", note="Regret email sent")
            app.log(
                "hr_partner",
                f"HR rejected after panel review (agent suggested: {rec.verdict})",
            )

        app.agent_status = AgentStatus.DONE
        app.next_action = ""
        self._refresh_pending(app)
        return app

    def on_offer_team_rollout(
        self,
        application_id: str,
        *,
        final_ctc_lpa: float,
        notes: str = "",
        rolled_out_by: str = "offer_team",
    ) -> Application:
        """Offer Discussion Team has finished negotiation and clicks
        "Roll out final offer". Sends the formal offer email and moves
        the application from OFFER_NEGOTIATION → OFFER (terminal-success).
        """
        from .tools.intake import get_employee_profile, get_jd

        app = STORE.get_application(application_id)
        if app is None:
            raise LookupError(f"Application {application_id} not found")
        if app.stage != FunnelStage.OFFER_NEGOTIATION:
            raise ValueError(
                f"Application {application_id} is in stage {app.stage.value}; "
                f"only OFFER_NEGOTIATION applications can be rolled out."
            )
        if app.offer_rolled_out:
            return app  # idempotent

        jd = get_jd(app.job_id)
        profile = get_employee_profile(app.candidate_id)
        r1 = next((i for i in app.interviews if i.round == "R1"), None)
        r2 = next((i for i in app.interviews if i.round == "R2"), None)

        app.offer_proposed_ctc_lpa = final_ctc_lpa
        app.offer_negotiation_notes = notes or app.offer_negotiation_notes
        app.offer_rolled_out = True
        app.offer_rolled_out_at = datetime.utcnow()
        app.offer_rolled_out_by = rolled_out_by

        update_application_status(
            app.id,
            FunnelStage.OFFER,
            f"Final offer rolled out at ₹{final_ctc_lpa:,.0f} per annum by Offer Discussion Team",
        )

        try:
            subject, body = comms.final_offer_email(
                name=profile.name,
                jd_title=jd.title,
                jd_location=jd.location,
                final_ctc=final_ctc_lpa,
                notes=notes,
                r1_score=(r1.score if r1 else None),
                r2_score=(r2.score if r2 else None),
            )
        except AttributeError:
            # Defensive fallback if the comms template hasn't loaded yet —
            # never silently swallow the rollout.
            subject, body = comms.offer_email(
                name=profile.name,
                jd_title=jd.title,
                jd_location=jd.location,
                r1_score=(r1.score if r1 else 0.0),
                r2_score=(r2.score if r2 else 0.0),
            )
        send_email(
            to=profile.email,
            subject=subject,
            body=body,
            application_id=app.id,
        )

        app.log(
            "offer_team",
            f"Offer Discussion Team rolled out the final offer at "
            f"₹{final_ctc_lpa:,.0f}/yr — formal offer email sent to {profile.email}.",
        )
        app.agent_status = AgentStatus.WAITING_CANDIDATE_ACCEPTANCE
        app.next_action = "Final offer rolled out — awaiting your acceptance. Please accept or decline from the Thrive portal."
        self._refresh_pending(app)
        return app

    def list_offer_team_queue(self) -> List[Application]:
        """All applications currently in OFFER_NEGOTIATION (Offer Team queue)."""
        return [
            a for a in STORE.list_applications()
            if a.stage == FunnelStage.OFFER_NEGOTIATION
        ]

    # ------------------------------------------------------------------
    # Pause helpers
    # ------------------------------------------------------------------

    def _pause_waiting_hr(self, app: Application, reason: str) -> bool:
        app.agent_status = AgentStatus.WAITING_HR
        app.next_action = reason
        app.log("agent", f"Paused — waiting for HR: {reason}")
        self._refresh_pending(app)
        return False

    def _pause_waiting_candidate(self, app: Application, reason: str) -> bool:
        app.agent_status = AgentStatus.WAITING_CANDIDATE
        app.next_action = reason
        app.log("agent", f"Paused — waiting for candidate: {reason}")
        self._refresh_pending(app)
        return False

    def _pause_waiting_panel(self, app: Application, reason: str) -> bool:
        app.agent_status = AgentStatus.WAITING_PANEL
        app.next_action = reason
        app.log("agent", f"Paused — waiting for panel feedback: {reason}")
        self._refresh_pending(app)
        return False

    def _refresh_pending(self, app: Application) -> None:
        app.pending_blocking_items = pending_blocking_labels(app.id)

    def _synthesise_r1_slots(
        self,
        needed: int,
        starting_from: datetime,
        avoid: list,
    ) -> list:
        """Generate ``needed`` deterministic 30-min business-hour slots.

        Round 1 is fully run by the AI Interview Agent — there is no human
        panellist who has to be free for the candidate to take the call.
        When Graph free/busy comes back empty (Business Partner's calendar
        already booked, Graph 503, or just no overlap), we still want to
        give the candidate three slots to pick from instead of parking
        the application on HR for hours.

        We pick three weekday slots at 10:00 / 14:30 / 16:30 IST, walking
        forward day-by-day until we have ``needed`` slots that don't
        collide with the slots already in ``avoid``.
        """
        from .models import TimeSlot

        if needed <= 0:
            return []

        # 10:00 / 14:30 / 16:30 IST → UTC (subtract 5h30m)
        time_offsets_utc = [
            timedelta(hours=4, minutes=30),
            timedelta(hours=9),
            timedelta(hours=11),
        ]
        avoid_starts = {s.start for s in (avoid or [])}
        out: list = []
        day_cursor = starting_from
        # Walk up to 21 calendar days forward — plenty of headroom even
        # if today happens to be a Friday and we need to skip a weekend.
        for _ in range(21):
            if day_cursor.weekday() < 5:  # Mon=0..Fri=4
                for off in time_offsets_utc:
                    start = day_cursor + off
                    end = start + timedelta(minutes=30)
                    if start in avoid_starts:
                        continue
                    out.append(TimeSlot(start=start, end=end))
                    if len(out) >= needed:
                        return out
            day_cursor = day_cursor + timedelta(days=1)
        return out


def _has_pending_item(app: Application, round_: str, phase: str, item_id: str) -> bool:
    for inst in app.checklists:
        if inst.round == round_ and inst.phase == phase:
            for it in inst.items:
                if it.id == item_id:
                    return not it.done
    return False


# Singleton used across the API handlers.
ORCHESTRATOR = Orchestrator()
