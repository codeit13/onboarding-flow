"""Domain models for the hiring agent.

Pure Pydantic models. No side effects, no DB calls, no IO. Used by the tools,
the orchestrator, the providers, and the FastAPI routes.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from enum import Enum

IST = timezone(timedelta(hours=5, minutes=30))

def _now_ist() -> datetime:
    """Return current time in IST (UTC+5:30)."""
    return datetime.now(IST)
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Funnel state machine
# ---------------------------------------------------------------------------


class FunnelStage(str, Enum):
    APPLIED = "applied"
    SCREENED = "screened"
    R1_SCHEDULED = "r1_scheduled"
    R1_DONE = "r1_done"
    R2_SCHEDULED = "r2_scheduled"
    # New stage owned by the Offer Discussion Team. Entered when HR
    # decides "offer" after R2 panel feedback. The Offer Team negotiates
    # the final CTC against uploaded salary scripts and rolls out the
    # final offer email — only then does the application move to OFFER.
    OFFER_NEGOTIATION = "offer_negotiation"
    OFFER = "offer"
    # Post-offer engagement stages (candidate-engagement module)
    OFFER_ACCEPTED = "offer_accepted"
    PRE_JOINING = "pre_joining"
    JOINED = "joined"
    OFFER_DECLINED = "offer_declined"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"


# Canonical forward path. `rejected` is terminal and can be entered from
# almost any stage, so it isn't in this list.
STAGE_ORDER: List[FunnelStage] = [
    FunnelStage.APPLIED,
    FunnelStage.SCREENED,
    FunnelStage.R1_SCHEDULED,
    FunnelStage.R1_DONE,
    FunnelStage.R2_SCHEDULED,
    FunnelStage.OFFER_NEGOTIATION,
    FunnelStage.OFFER,
    FunnelStage.OFFER_ACCEPTED,
    FunnelStage.PRE_JOINING,
    FunnelStage.JOINED,
]


class AgentStatus(str, Enum):
    """Orchestrator state machine for a single application.

    This is separate from FunnelStage because the agent can be paused mid-stage
    waiting for HR to tick a blocking item, or waiting for panel feedback.
    """

    IDLE = "idle"                    # nothing running, waiting to be kicked
    RUNNING = "running"              # orchestrator thread is actively working
    WAITING_HR = "waiting_hr"        # blocked on HR ticking a checklist item
    WAITING_CANDIDATE = "waiting_candidate"   # blocked on candidate reply (slot confirm)
    WAITING_PANEL = "waiting_panel"  # R2 scheduled, collecting panel feedback
    WAITING_OFFER_TEAM = "waiting_offer_team"  # HR approved offer — Offer Discussion Team is negotiating CTC
    WAITING_CANDIDATE_ACCEPTANCE = "waiting_candidate_acceptance"  # Offer rolled out, waiting accept/decline
    ENGAGING = "engaging"            # Post-offer engagement touchpoints are firing
    DONE = "done"                    # reached terminal stage (JOINED, REJECTED, OFFER_DECLINED)


# ---------------------------------------------------------------------------
# People & jobs
# ---------------------------------------------------------------------------


class CompensationBreakdown(BaseModel):
    """Structured CTC components extracted by Claude from a salary slip.

    All amounts are in INR per annum (LPA in INR, NOT lakhs). The
    extractor returns floats so Pydantic can round-trip them; the UI is
    responsible for formatting (₹ ##,##,###).
    """

    current_ctc: Optional[float] = None  # gross annual CTC
    basic: Optional[float] = None
    hra: Optional[float] = None
    variable: Optional[float] = None
    special_allowance: Optional[float] = None
    other: Optional[float] = None
    employer: Optional[str] = None  # parsed from the slip header
    pay_period: Optional[str] = None  # e.g. "Mar 2026"
    source_filename: Optional[str] = None
    extracted_at: Optional[datetime] = None
    extraction_source: Optional[Literal["claude", "deterministic"]] = None
    extraction_notes: Optional[str] = None


class Profile(BaseModel):
    """An internal employee profile pulled from Thrive (or parsed from a PDF)."""

    employee_id: str
    name: str
    email: str
    current_role: str
    current_location: str
    current_band: Optional[str] = None
    tenure_years: float
    kras: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    education: Optional[str] = None
    last_rating: Optional[str] = None
    phone: Optional[str] = None  # E.164 format for WhatsApp
    # External-candidate compensation data (extracted from salary slip
    # via Claude). Always None for internal Thrive-loaded employees.
    compensation: Optional[CompensationBreakdown] = None


class PanelMember(BaseModel):
    user_id: str  # Microsoft Graph user id / email
    name: str
    role: Literal["hiring_manager", "interviewer", "hr_partner"]


class Job(BaseModel):
    id: str
    job_id: str  # the human-visible ID on Thrive cards (e.g. "590321")
    title: str
    function: str = "Retail Banking"
    band: str
    tags: List[str]
    location: str
    required_skills: List[str]
    nice_to_have_skills: List[str] = Field(default_factory=list)
    description: str = ""
    hr_partner_id: str
    panel: List[PanelMember]
    shortlist_threshold: float = 75.0  # per-JD override lives here
    opened_on: Optional[datetime] = None
    positions: int = 1


# ---------------------------------------------------------------------------
# Checklists
# ---------------------------------------------------------------------------


class ChecklistItem(BaseModel):
    id: str
    label: str
    blocking: bool = False
    done: bool = False
    owner: Optional[str] = None  # user_id of the person responsible
    note: Optional[str] = None
    ticked_by: Optional[str] = None
    ticked_at: Optional[datetime] = None


class ChecklistInstance(BaseModel):
    id: str
    application_id: str
    round: Literal["R1", "R2"]
    phase: Literal["pre", "post"]
    items: List[ChecklistItem]

    def is_satisfied(self, blocking_only: bool = True) -> bool:
        items = [i for i in self.items if i.blocking] if blocking_only else self.items
        return all(i.done for i in items)

    def pending_blocking(self) -> List[ChecklistItem]:
        return [i for i in self.items if i.blocking and not i.done]

    def progress(self) -> str:
        done = sum(1 for i in self.items if i.done)
        return f"{done}/{len(self.items)}"


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


class TimeSlot(BaseModel):
    start: datetime
    end: datetime

    def overlaps(self, other: "TimeSlot") -> bool:
        return not (self.end <= other.start or other.end <= self.start)


class BusyBlock(BaseModel):
    user_id: str
    slot: TimeSlot
    subject: Optional[str] = None


class CalendarEventView(BaseModel):
    """Read model of a calendar event, safe to send to the frontend."""

    id: str
    organiser_id: str
    attendees: List[str]
    subject: str
    start: datetime
    end: datetime
    teams_join_url: Optional[str] = None
    body: str = ""
    cancelled: bool = False
    application_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------


class TranscriptSegment(BaseModel):
    speaker: Literal["interviewer", "candidate"]
    text: str
    at: Optional[datetime] = None


class PanelFeedback(BaseModel):
    panellist_id: str
    panellist_name: str = ""
    score: float
    strengths: str
    concerns: str
    recommendation: Literal["strong_hire", "hire", "no_hire"]
    submitted_at: datetime


# ---------------------------------------------------------------------------
# Panels (DESIGN-001)
# ---------------------------------------------------------------------------
#
# A Panel is a named group of interviewers that HR can assign to an R2
# interview. Each panel advertises which JDs it is qualified to interview
# for via ``role_scopes`` — a list of patterns like ``"Retail Banking"``
# (function match), ``"DM"`` (band match), ``"Retail Banking/DM"`` (both),
# or ``"*"`` (wildcard). When HR approves an R1-cleared application, the
# system surfaces only the panels whose scopes overlap the JD so HR does
# not have to scroll through every panel in the org.


class Panel(BaseModel):
    id: str
    name: str
    members: List[PanelMember] = Field(default_factory=list)
    role_scopes: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    default_size: int = 1
    active: bool = True
    created_at: datetime = Field(default_factory=_now_ist)
    updated_at: datetime = Field(default_factory=_now_ist)


# ---------------------------------------------------------------------------
# AI panel recommendation (DESIGN-001 chunk 6)
# ---------------------------------------------------------------------------
#
# After an R2 interview the panellist can paste the Teams transcript into
# the feedback page and ask Claude to analyse it. The LLM returns a
# structured recommendation that renders above the human verdict form as
# "Agent recommendation — for your reference". The human still owns the
# final decision; this block is advisory only.


class AiRecommendationEvidence(BaseModel):
    """One transcript quote the model used to justify a signal."""
    quote: str
    speaker: Literal["panel", "candidate", "unknown"] = "candidate"
    why_it_matters: str


class AiPanelRecommendation(BaseModel):
    application_id: str
    interview_id: str
    # Suggested verdict — panellist can accept, override, or ignore.
    suggested_recommendation: Literal["strong_hire", "hire", "no_hire"]
    suggested_score: float  # 0-100
    headline: str
    summary: str
    strengths: List[str] = Field(default_factory=list)
    concerns: List[str] = Field(default_factory=list)
    evidence: List[AiRecommendationEvidence] = Field(default_factory=list)
    model: str = ""
    source: Literal["claude", "deterministic"] = "claude"
    generated_at: datetime = Field(default_factory=_now_ist)


class TranscriptHighlight(BaseModel):
    """A snippet from the candidate's R1 transcript that the agent flagged
    as load-bearing for its recommendation."""
    quote: str
    why_it_matters: str
    sentiment: Literal["positive", "neutral", "negative"] = "positive"
    # Optional Hindi companions, populated only when the candidate spoke
    # Hindi during R1. Old clients ignore them; new HR UI can show a
    # bilingual toggle. The English fields stay authoritative.
    quote_hi: Optional[str] = None
    why_it_matters_hi: Optional[str] = None


class InterviewReport(BaseModel):
    """AI Interview Agent's structured report after R1.

    This is what the panel reads before walking into R2 — it's the agent's
    "what we learned and what you should probe" memo.
    """
    application_id: str
    round: Literal["R1"] = "R1"
    headline: str                              # one-sentence summary
    overall_score: float
    recommendation: Literal["advance", "borderline", "reject"]
    rubric_scores: Dict[str, float] = Field(default_factory=dict)  # per JD-required-skill
    transcript_highlights: List[TranscriptHighlight] = Field(default_factory=list)
    red_flags: List[str] = Field(default_factory=list)
    recommended_probes: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_now_ist)
    # Bilingual analysis. The Claude scorer detects the dominant
    # candidate-side language ("en" / "hi" / "hi-en" code-switched) and,
    # when it is not English, fills the parallel `_hi` fields below
    # with a translated copy of the SAME analysis. The English fields
    # remain authoritative — these are additive so older API clients
    # keep working without code changes.
    transcript_language: Literal["en", "hi", "hi-en"] = "en"
    headline_hi: Optional[str] = None
    red_flags_hi: List[str] = Field(default_factory=list)
    recommended_probes_hi: List[str] = Field(default_factory=list)


class InterviewRecord(BaseModel):
    id: str
    application_id: str
    round: Literal["R1", "R2"]
    teams_meeting_id: Optional[str] = None
    teams_join_url: Optional[str] = None  # surfaced to candidate + panel
    meeting_slot: Optional[TimeSlot] = None
    transcript: List[TranscriptSegment] = Field(default_factory=list)
    score: Optional[float] = None
    rationale: Optional[str] = None
    panel_feedback: List[PanelFeedback] = Field(default_factory=list)
    report: Optional[InterviewReport] = None  # populated after R1 scoring
    # R2 only: raw transcript pasted by the panellist after the Teams call,
    # and the Claude-generated recommendation derived from it. Cached so
    # re-renders do not re-bill the API and so the audit trail is stable.
    pasted_transcript: Optional[str] = None
    ai_recommendation: Optional["AiPanelRecommendation"] = None
    # R2 only: per-panellist transcripts. Each panellist runs their own
    # 1-on-1 with the candidate, so HR's per-panellist Claude review must
    # be against THAT panellist's transcript, not a shared one. Keyed by
    # panellist_id (Graph user id / email).
    pasted_transcripts_by_panellist: Dict[str, str] = Field(default_factory=dict)
    # Per-panellist AI second opinions, keyed by panellist_id. HR runs one
    # of these for each panel vote on the R2 review screen — Claude is
    # asked to corroborate or challenge that specific panellist's verdict
    # against the shared R2 transcript so HR can spot disagreement BEFORE
    # making the final offer / reject call.
    ai_recommendations_by_panellist: Dict[str, "AiPanelRecommendation"] = Field(
        default_factory=dict
    )
    # ACS Teams Interview Agent (R1 only). When the operator dispatches
    # the live ACS bot to join the candidate's R1 Teams meeting, the
    # provider returns a call session id which we stash here so the
    # frontend can poll live status and the service layer can fold the
    # captured transcript back into ``transcript`` once the call ends.
    acs_call_id: Optional[str] = None
    acs_state: Optional[str] = None  # joining | live | ended | failed

    # Virtual Interviewer (R1 only). When the candidate clicks "Start
    # interview" on the live R1 status page they're routed to our
    # in-app virtual interviewer which mirrors the Xebia virtual-
    # interviewer UX. This stashes the active session id so the
    # candidate can refresh / resume, and so the finalise hook knows
    # which session to fold into ``transcript``.
    virtual_interview_session_id: Optional[str] = None
    virtual_interview_state: Optional[str] = None  # in_progress | completed
    # ISO-639-1 language the candidate selected for the AI Interview Agent.
    # The sidecar generates questions, welcome script and TTS audio in
    # this language. We persist it on the InterviewRecord so HR's R1
    # report and the audit trail can show "Round 1 conducted in Hindi".
    language: Literal["en", "hi"] = "en"


# ---------------------------------------------------------------------------
# Application + audit
# ---------------------------------------------------------------------------


class AgentEvent(BaseModel):
    at: datetime
    actor: Literal["agent", "hr_partner", "panel", "candidate", "system", "offer_team", "engagement"]
    message: str
    level: Literal["info", "warn", "error"] = "info"


class Candidate(BaseModel):
    id: str
    profile: Profile
    # ``internal`` candidates have a real Thrive employee_id and an Axis
    # mailbox / calendar that Graph can read. ``external`` candidates were
    # parsed from a pasted resume; they have an email address but NO Axis
    # calendar — the orchestrator must email them slots and parse replies
    # out of the Business Partner's inbox instead of intersecting calendars.
    kind: Literal["internal", "external"] = "internal"


class ActivityItem(BaseModel):
    """Unified activity feed row — emails, calendar events, notifications, agent events.

    The frontend renders a single chronological stream from these.
    """

    id: str
    at: datetime
    kind: Literal["email_out", "email_in", "calendar", "notification", "agent", "checklist"]
    title: str
    detail: str = ""
    application_id: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class Application(BaseModel):
    id: str
    candidate_id: str          # always == Profile.employee_id (single source of truth)
    job_id: str
    match_percent: float
    match_rationale: str = ""
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)

    stage: FunnelStage = FunnelStage.APPLIED
    agent_status: AgentStatus = AgentStatus.IDLE
    next_action: str = ""
    pending_blocking_items: List[str] = Field(default_factory=list)

    # Denormalised flag from Candidate.kind so the orchestrator and the
    # API can branch without joining tables. Stamped at apply-time and
    # never changes for the life of the application.
    candidate_kind: Literal["internal", "external"] = "internal"

    # How this application entered the funnel. "organic" = the candidate
    # applied themselves via Thrive; "bulk_screening" = HR routed from the
    # Bulk CV Screening dashboard; "external_intake" = external candidate
    # applied through the public intake page. Defaults to "organic" so all
    # pre-existing applications get the right value.
    source: Optional[Literal["organic", "bulk_screening", "external_intake"]] = "organic"

    # Provenance for bulk_screening-sourced apps — lets the UI jump back to
    # the exact row in the screening pool that produced this application
    # (used when HR clicks a SCREENED candidate card in the funnel and wants
    # to see the original screening results + Route/Notify actions).
    source_pool_id: Optional[str] = None
    source_row_id: Optional[str] = None

    # External-intake provenance — captured when an external candidate
    # applies through the new natural-language intake. ``search_query``
    # is the literal phrase they typed (e.g. "Branch Manager in Mumbai
    # near Powai"); ``recommendation_source`` records WHICH of the two
    # results-page sections they clicked Apply from. HR uses both for
    # context. Always None for internal Thrive applicants.
    search_query: Optional[str] = None
    recommendation_source: Optional[Literal["search", "ai"]] = None

    # Slot-confirmation state (plan §4.4 — conversational outreach).
    # When the agent has emailed the candidate proposed slots and is waiting
    # for them to pick one, these are populated and `agent_status` is
    # WAITING_CANDIDATE. Once `selected_slot_index` is set, the orchestrator
    # resumes and books the meeting.
    proposed_r1_slots: List[TimeSlot] = Field(default_factory=list)
    selected_r1_slot_index: Optional[int] = None
    proposed_r2_slots: List[TimeSlot] = Field(default_factory=list)
    selected_r2_slot_index: Optional[int] = None

    # Human-in-the-loop screening gate (2026-04-07): we never auto-reject
    # an internal candidate at intake, even when their JD-rubric match is
    # below the shortlist threshold. The orchestrator pauses WAITING_HR,
    # emails the full screening report to the Business Partner, and waits for
    # an explicit advance/regret call. ``hr_screening_decision`` is the
    # outcome of that call:
    #   - None      → HR has not yet decided (paused at the screening gate)
    #   - "advance" → HR overrode the threshold; agent should shortlist + outreach
    #   - "regret"  → HR confirmed reject; agent moves to REJECTED + regret email
    hr_screening_decision: Optional[Literal["advance", "regret"]] = None

    # DESIGN-001: HR explicitly approves an R1-cleared application by
    # selecting one of the panels surfaced from the panel config. The
    # orchestrator reads this at R1_DONE to decide which members'
    # calendars to intersect and who to invite to the R2 Teams meeting.
    # None means HR has not yet approved — the orchestrator stays paused
    # at WAITING_HR until HR acts.
    selected_r2_panel_id: Optional[str] = None

    # Real-gate flag: the candidate must explicitly start the R1 AI interview
    # from the live status page. The orchestrator pauses at R1_SCHEDULED until
    # this flips True (set via on_candidate_start_r1 from the API handler).
    r1_started: bool = False

    created_at: datetime = Field(default_factory=_now_ist)
    updated_at: datetime = Field(default_factory=_now_ist)

    # Offer Discussion Team state (post R2, pre final offer).
    # When HR picks "offer" on the R2 review card, the orchestrator moves
    # the application into FunnelStage.OFFER_NEGOTIATION and pauses
    # WAITING_OFFER_TEAM. A new persona (the Offer Discussion Team) reads
    # the uploaded salary scripts + AI analysis from the intake step,
    # negotiates a final CTC, and clicks "Roll out final offer" — which
    # emails the formal offer letter and flips the stage to OFFER.
    offer_proposed_ctc_lpa: Optional[float] = None  # in absolute INR per annum
    offer_negotiation_notes: str = ""
    offer_rolled_out: bool = False
    offer_rolled_out_at: Optional[datetime] = None
    offer_rolled_out_by: Optional[str] = None  # email / id of offer-team member

    # Post-offer engagement state
    offer_accepted: bool = False
    offer_accepted_at: Optional[datetime] = None
    offer_declined: bool = False
    offer_declined_reason: Optional[str] = None
    withdrawn: bool = False
    withdrawn_reason: Optional[str] = None
    withdrawn_at: Optional[datetime] = None
    candidate_phone: Optional[str] = None  # E.164 for WhatsApp
    expected_joining_date: Optional[datetime] = None
    engagement_journey_id: Optional[str] = None

    events: List[AgentEvent] = Field(default_factory=list)
    interviews: List[InterviewRecord] = Field(default_factory=list)
    checklists: List[ChecklistInstance] = Field(default_factory=list)

    def log(self, actor: str, message: str, level: str = "info") -> None:
        self.events.append(
            AgentEvent(
                at=_now_ist(),
                actor=actor,  # type: ignore[arg-type]
                message=message,
                level=level,  # type: ignore[arg-type]
            )
        )
        self.updated_at = _now_ist()


# ---------------------------------------------------------------------------
# Bulk CV Screening (HR dashboard feature)
# ---------------------------------------------------------------------------


class BulkCandidateRow(BaseModel):
    """One uploaded CV inside a CandidatePool, scored against the pool's JD."""

    row_id: str
    file_name: str
    status: Literal["queued", "parsing", "parsed", "scoring", "done", "error"] = "queued"
    # Populated after resume parsed
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    candidate_phone: Optional[str] = None
    resume_text: Optional[str] = None
    profile: Optional[Profile] = None
    # Populated after JD scoring
    match_percent: Optional[float] = None
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    recommendation: Optional[Literal["shortlist", "maybe", "reject"]] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    strengths: List[str] = Field(default_factory=list)
    concerns: List[str] = Field(default_factory=list)
    evidence_quotes: List[str] = Field(default_factory=list)
    # Per-criterion verdict table when the pool has custom_criteria set.
    # Each item: {criterion, verdict ('met'|'partial'|'not_met'|'unclear'),
    # evidence}. Empty when no criteria were applied.
    criteria_assessment: List[Dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
    # Auto-map mode: best matching job for this CV (populated when pool has no job_id)
    best_job_id: Optional[str] = None
    best_job_title: Optional[str] = None
    # All job scores in auto-map mode: [{job_id, job_title, match_percent, recommendation}]
    all_job_scores: List[Dict[str, Any]] = Field(default_factory=list)
    # Routing: set when HR routes candidate to L1/L2 from the dashboard
    routed_to: Optional[str] = None  # "L1", "L2", "notified-L1", "notified-L2"
    application_id: Optional[str] = None  # link to the created Application
    routed_job_id: Optional[str] = None   # which requisition they were routed to
    routed_job_title: Optional[str] = None


class CandidatePool(BaseModel):
    """A batch of CVs uploaded by an HR partner, scored against one or all JDs."""

    id: str
    job_id: Optional[str] = None  # None = auto-map mode (score against all open roles)
    job_title: str = ""
    mode: Literal["single_jd", "auto_map"] = "single_jd"
    created_by: str = "hr_partner"
    created_at: datetime = Field(default_factory=_now_ist)
    rows: List[BulkCandidateRow] = Field(default_factory=list)
    status: Literal["pending_review", "processing", "done", "failed"] = "processing"

    # Free-text additional screening criteria HR wants the AI to consider
    # alongside the JD match — e.g. "Prefer candidates from Tier-1 private
    # banks", "Must have NRI desk exposure", "Avoid recent campus hires".
    # Stamped at pool creation; threaded into the Claude CV-screener prompt
    # so every row in this pool is scored with the same HR context.
    custom_criteria: Optional[str] = None

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def done_count(self) -> int:
        return sum(1 for r in self.rows if r.status in ("done", "error"))

    @property
    def progress_pct(self) -> float:
        return (self.done_count / self.total * 100) if self.total else 0.0

    def ranked_rows(self) -> List[BulkCandidateRow]:
        """Return rows sorted by match_percent descending (errors at end)."""
        scored = [r for r in self.rows if r.status == "done" and r.match_percent is not None]
        scored.sort(key=lambda r: r.match_percent or 0, reverse=True)
        rest = [r for r in self.rows if r not in scored]
        return scored + rest


# Resolve forward references after all classes are defined.
InterviewRecord.model_rebuild()
