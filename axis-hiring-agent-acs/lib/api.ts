// Typed client for the FastAPI backend.
//
// Single source of truth for the base URL and the shape of every API
// payload. Mirrors the Pydantic models in `app/models/domain.py` plus the
// route signatures in `app/main.py` — keep them in sync when the backend
// schema changes.
//
// Important: there are NO `/advance/*` calls in the production system. The
// orchestrator drives every transition autonomously. The only human inputs
// are: apply, tick a checklist item, submit panel feedback, and (rarely)
// nudge `unblockApplication` to retry the orchestrator.

// API base resolution order:
//   1. window.__API_BASE__ (runtime override, e.g. set in a <script> tag)
//   2. NEXT_PUBLIC_API_BASE (build-time env, baked at `next dev` / `next build`)
//   3. http://localhost:8000 (demo-stable default)
const _ENV_BASE =
  typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_BASE
    ? process.env.NEXT_PUBLIC_API_BASE
    : "http://localhost:8000";

export const API_BASE =
  typeof window !== "undefined"
    ? (window as any).__API_BASE__ || _ENV_BASE
    : _ENV_BASE;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText} — ${body}`);
  }
  // /demo/reset returns no-content; tolerate empty bodies.
  const text = await res.text();
  return (text ? JSON.parse(text) : (undefined as unknown)) as T;
}

// ---------- Types (mirror the Pydantic models) ----------

export type FunnelStage =
  | "applied"
  | "screened"
  | "r1_scheduled"
  | "r1_done"
  | "r2_scheduled"
  | "offer_negotiation"
  | "offer"
  | "offer_accepted"
  | "pre_joining"
  | "joined"
  | "offer_declined"
  | "rejected";

export type AgentStatus =
  | "idle"
  | "running"
  | "waiting_hr"
  | "waiting_candidate"
  | "waiting_panel"
  | "waiting_offer_team"
  | "waiting_candidate_acceptance"
  | "engaging"
  | "done";

export interface PanelMember {
  user_id: string;
  name: string;
  role: "hiring_manager" | "interviewer" | "hr_partner";
}

export interface Job {
  id: string;
  job_id: string;
  title: string;
  function?: string;
  band: string;
  tags: string[];
  location: string;
  required_skills: string[];
  nice_to_have_skills?: string[];
  description?: string;
  hr_partner_id: string;
  panel: PanelMember[];
  shortlist_threshold: number;
  positions?: number;
}

export interface CompensationBreakdown {
  current_ctc?: number | null;
  basic?: number | null;
  hra?: number | null;
  variable?: number | null;
  special_allowance?: number | null;
  other?: number | null;
  employer?: string | null;
  pay_period?: string | null;
  source_filename?: string | null;
  extracted_at?: string | null;
  extraction_source?: "claude" | "deterministic" | null;
  extraction_notes?: string | null;
}

export interface Candidate {
  id: string;
  employee_id: string;
  name: string;
  email: string;
  current_role: string;
  current_band?: string | null;
  current_location: string;
  tenure_years: number;
  skills: string[];
  kras: string[];
  education?: string | null;
  last_rating?: string | null;
  compensation?: CompensationBreakdown | null;
}

export interface ExternalRecommendation {
  job_id: string;
  job_title: string;
  location: string;
  match_percent: number;
  matched_skills: string[];
  missing_skills: string[];
  rationale: string;
}

export interface ExternalIntakeResponse {
  resume_text: string;
  profile: {
    employee_id: string;
    name: string;
    email: string;
    current_role: string;
    current_location: string;
    tenure_years: number;
    skills: string[];
    compensation?: CompensationBreakdown | null;
  };
  search_query: string;
  search_matches: ExternalRecommendation[];
  search_source: "claude" | "deterministic" | null;
  ai_recommendations: ExternalRecommendation[];
  ai_source: "claude" | "deterministic" | null;
  salary_source: "claude" | "deterministic" | null;
}

export interface ChecklistItem {
  id: string;
  label: string;
  blocking: boolean;
  done: boolean;
  owner?: string | null;
  note?: string | null;
  ticked_by?: string | null;
  ticked_at?: string | null;
}

export interface ChecklistInstance {
  id: string;
  application_id: string;
  round: "R1" | "R2";
  phase: "pre" | "post";
  items: ChecklistItem[];
}

export interface TranscriptSegment {
  speaker: "interviewer" | "candidate";
  text: string;
}

export interface PanelFeedback {
  panellist_id: string;
  panellist_name: string;
  score: number;
  strengths: string;
  concerns: string;
  recommendation: "strong_hire" | "hire" | "no_hire";
  submitted_at: string;
}

export interface TranscriptHighlight {
  quote: string;
  why_it_matters: string;
  sentiment: "positive" | "neutral" | "negative";
  // Optional Hindi (Devanagari) companions populated by the Claude
  // scorer when the candidate spoke Hindi during R1. Frontend should
  // show these in a bilingual toggle on the Business Partner view.
  quote_hi?: string | null;
  why_it_matters_hi?: string | null;
}

// ---- Axis taxonomy (JOB_ROLES + SKILL_MASTER) ----------------------------
//
// These are the canonical Axis Bank role + skill rows shipped from the
// official JOB_ROLES.csv and SKILL_MASTER.csv. The demo MUST source role
// titles, descriptions and skill names from this taxonomy so we never
// invent free-text vocabulary.

export interface TaxonomySkill {
  skill_id: number;
  name: string;
  category: string;
  description: string;
}

export interface TaxonomyRole {
  role_id: string;
  title: string;
  alias: string;
  department: string;
  role_summary: string;
  skills: string[];
  skill_categories: string[];
  responsibilities: string[];
}

export interface TaxonomyRoleDetail extends TaxonomyRole {
  description: string;
  skill_ids: number[];
  works_with_internal: string[];
  works_with_external: string[];
}

export interface ProctoringViolation {
  type: "multiple_people" | "communication_device" | "looking_away";
  timestamp: string;
  question_index: number;
  severity: "warning" | "critical";
  details?: string;
}

export interface InterviewReport {
  application_id: string;
  round: "R1";
  headline: string;
  overall_score: number;
  recommendation: "advance" | "borderline" | "reject";
  rubric_scores: Record<string, number>;
  transcript_highlights: TranscriptHighlight[];
  key_findings?: { type: string; finding: string; evidence?: string; impact?: string }[];
  key_findings_hi?: { type: string; finding: string; evidence?: string; impact?: string }[];
  red_flags: string[];
  recommended_probes: string[];
  generated_at: string;
  // Bilingual analysis. `transcript_language` is the BCP-47-ish tag of
  // the dominant candidate-side language during R1. When it is "hi" or
  // "hi-en" the `*_hi` fields below carry a Devanagari translation of
  // the same analysis (English fields remain authoritative). The HR
  // app page renders a language toggle when these are present.
  transcript_language?: "en" | "hi" | "hi-en";
  headline_hi?: string | null;
  red_flags_hi?: string[];
  recommended_probes_hi?: string[];
  proctoring_violations?: ProctoringViolation[];
}

export interface AiRecommendationEvidence {
  quote: string;
  speaker: "panel" | "candidate" | "unknown";
  why_it_matters: string;
}

export interface AiPanelRecommendation {
  application_id: string;
  interview_id: string;
  suggested_recommendation: "strong_hire" | "hire" | "no_hire";
  suggested_score: number;
  headline: string;
  summary: string;
  strengths: string[];
  concerns: string[];
  evidence: AiRecommendationEvidence[];
  model: string;
  source: "claude" | "deterministic";
  generated_at: string;
}

export interface InterviewRecord {
  id: string;
  application_id: string;
  round: "R1" | "R2";
  teams_meeting_id?: string | null;
  teams_join_url?: string | null;
  meeting_slot?: { start: string; end: string } | null;
  transcript: TranscriptSegment[];
  score?: number | null;
  rationale?: string | null;
  panel_feedback: PanelFeedback[];
  report?: InterviewReport | null;
  pasted_transcript?: string | null;
  ai_recommendation?: AiPanelRecommendation | null;
  ai_recommendations_by_panellist?: Record<string, AiPanelRecommendation>;
  pasted_transcripts_by_panellist?: Record<string, string>;
  acs_call_id?: string | null;
  acs_state?: string | null;
  virtual_interview_session_id?: string | null;
  virtual_interview_state?: string | null;
  proctoring_violations?: ProctoringViolation[];
}

/** Live status payload returned by the Virtual Interviewer endpoints. */
export interface VirtualInterviewStatus {
  session_id?: string;
  application_id?: string;
  candidate_name?: string;
  state: "not_started" | "in_progress" | "completed";
  questions_total?: number;
  questions_answered?: number;
  current_index?: number;
  current_question?: string | null;
  transcript?: { question: string; answer: string; at?: string }[];
  started_at?: string;
  ended_at?: string | null;
}

/** Live status payload returned by the ACS interview endpoints. */
export interface AcsInterviewStatus {
  call_id?: string;
  application_id?: string;
  teams_join_url?: string;
  state: "not_started" | "joining" | "live" | "ended" | "failed";
  questions_total?: number;
  questions_asked?: number;
  current_question?: string | null;
  transcript?: { speaker: "agent" | "candidate"; text: string; at?: string }[];
  started_at?: string;
  ended_at?: string | null;
  error?: string | null;
}

export interface Panel {
  id: string;
  name: string;
  members: PanelMember[];
  role_scopes: string[];
  location?: string | null;
  default_size: number;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface R2SlotsByPanelEntry {
  panel_id: string;
  panel_name: string;
  members: { user_id: string; name: string; role: string }[];
  location?: string | null;
  slots: { start: string; end: string }[];
  error?: string | null;
}

export interface RankedCandidate {
  rank: number;
  application_id: string;
  candidate_id: string;
  candidate_name: string;
  stage: FunnelStage;
  tier: "offer" | "post_r2" | "post_r1" | "pre_r1" | "rejected";
  score: number;
  why: string;
  match_percent: number;
  r1_score?: number | null;
  r2_avg?: number | null;
  last_signal_at: string;
}

export interface JdRanking {
  jd_id: string;
  total: number;
  active: number;
  candidates: RankedCandidate[];
}

export interface AgentEvent {
  at: string;
  actor: "agent" | "hr_partner" | "panel" | "candidate" | "system";
  message: string;
  level?: "info" | "warn" | "error";
}

export interface TimeSlotDTO {
  start: string;
  end: string;
}

export interface Application {
  id: string;
  candidate_id: string;
  job_id: string;
  match_percent: number;
  match_rationale: string;
  matched_skills: string[];
  missing_skills: string[];
  stage: FunnelStage;
  agent_status: AgentStatus;
  next_action: string;
  pending_blocking_items: string[];
  proposed_r1_slots: TimeSlotDTO[];
  selected_r1_slot_index: number | null;
  proposed_r2_slots: TimeSlotDTO[];
  selected_r2_slot_index: number | null;
  selected_r2_panel_id?: string | null;
  hr_screening_decision?: "advance" | "regret" | null;
  candidate_kind?: "internal" | "external";
  source?: "organic" | "bulk_screening" | "external_intake" | null;
  source_pool_id?: string | null;
  source_row_id?: string | null;
  search_query?: string | null;
  recommendation_source?: "search" | "ai" | null;
  r1_started: boolean;
  offer_proposed_ctc_lpa?: number | null;
  offer_negotiation_notes?: string;
  offer_rolled_out?: boolean;
  offer_rolled_out_at?: string | null;
  offer_rolled_out_by?: string | null;
  created_at: string;
  updated_at: string;
  events: AgentEvent[];
  interviews: InterviewRecord[];
  checklists: ChecklistInstance[];
}

/** Row in the Offer Discussion Team queue. */
export interface OfferTeamQueueRow {
  application_id: string;
  candidate_name: string;
  candidate_email: string;
  candidate_current_role: string;
  job_id: string;
  job_title: string;
  job_location: string;
  r1_score: number | null;
  r2_score: number | null;
  current_ctc_lpa: number | null;
  proposed_ctc_lpa: number | null;
  negotiation_notes: string;
  rolled_out: boolean;
  next_action: string;
  updated_at: string;
  // AI-Analysis context for the Offer Discussion Team. Lets them
  // negotiate from the same evidence the panel + Business Partner saw,
  // without bouncing into the application detail page.
  r1_summary?: {
    headline: string;
    overall_score: number;
    recommendation: "advance" | "borderline" | "reject";
    red_flags: string[];
    top_highlights: { quote: string; why: string }[];
  } | null;
  r2_summary?: {
    votes: {
      panellist_name: string;
      score: number;
      recommendation: "strong_hire" | "hire" | "no_hire";
      strengths: string;
      concerns: string;
    }[];
    tally: { strong_hire: number; hire: number; no_hire: number };
    average_score: number | null;
  } | null;
}

export type ActivityKind =
  | "email_out"
  | "email_in"
  | "calendar"
  | "notification"
  | "agent"
  | "checklist";

export interface ActivityItem {
  id: string;
  at: string;
  kind: ActivityKind;
  title: string;
  detail: string;
  application_id?: string | null;
  meta: Record<string, unknown>;
}

export interface HrPartner {
  user_id: string;
  name: string;
  jobs: { id: string; title: string; location: string }[];
}

export interface PanelMemberListed {
  user_id: string;
  name: string;
  role: string;
  jobs: { id: string; title: string; location: string }[];
}

export interface PanelPendingItem {
  application_id: string;
  interview_id: string;
  job_id: string;
  job_title: string;
  job_location: string;
  candidate_name: string;
  slot_start: string | null;
  slot_end: string | null;
  teams_join_url?: string | null;
}

export interface PanelHistoryItem {
  application_id: string;
  interview_id: string;
  job_id: string;
  job_title: string;
  job_location: string;
  candidate_name: string;
  slot_start: string | null;
  slot_end: string | null;
  stage: FunnelStage;
  my_score: number;
  my_strengths: string;
  my_concerns: string;
  my_recommendation: "strong_hire" | "hire" | "no_hire";
  submitted_at: string;
  votes_in: number;
  votes_expected: number;
}

// ---------- API functions ----------

export const api = {
  health: () =>
    request<{
      status: string;
      jobs: number;
      candidates: number;
      applications: number;
      calendar_provider: string;
      messaging_provider: string;
    }>("/health"),

  listJobs: () => request<Job[]>("/jobs"),
  getJob: (jdId: string) => request<Job>(`/jobs/${jdId}`),
  jobsApplicantCounts: () =>
    request<Record<string, number>>("/jobs/applicant-counts"),

  listCandidates: () => request<Candidate[]>("/candidates"),
  getCandidate: (id: string) => request<Candidate>(`/candidates/${id}`),

  listApplications: (visibleTo?: "hr") => {
    const qs = visibleTo ? `?visible_to=${visibleTo}` : "";
    return request<Application[]>(`/applications${qs}`);
  },
  /**
   * All applications belonging to a single candidate (employee_id).
   * Powers the Thrive "My Applications" tray — lets the candidate come
   * back the next day and find everything they've applied to.
   */
  listApplicationsForCandidate: (employeeId: string) =>
    request<Application[]>(
      `/applications?candidate_id=${encodeURIComponent(employeeId)}`,
    ),
  getApplication: (id: string) => request<Application>(`/applications/${id}`),

  /** Unified activity feed (emails + calendar + notifications + agent events). */
  listActivity: (applicationId?: string, limit = 200) => {
    const qs = new URLSearchParams();
    if (applicationId) qs.set("application_id", applicationId);
    qs.set("limit", String(limit));
    return request<ActivityItem[]>(`/activity?${qs.toString()}`);
  },

  apply: (employeeId: string, jdId: string) =>
    request<Application>("/apply", {
      method: "POST",
      body: JSON.stringify({ employee_id: employeeId, jd_id: jdId }),
    }),

  /** Nudge the orchestrator. Idempotent — safe to spam from a Retry button. */
  unblockApplication: (applicationId: string) =>
    request<Application>(`/applications/${applicationId}/unblock`, { method: "POST" }),

  /** Structured AI Interview Agent report after R1. */
  getR1Report: (applicationId: string) =>
    request<InterviewReport>(`/applications/${applicationId}/r1-report`),

  /** Cross-candidate ranking for one JD (HR Command Center leaderboard). */
  jdRanking: (jdId: string) => request<JdRanking>(`/jobs/${jdId}/ranking`),

  /** Candidate clicks "Start interview" on the live status page. */
  startR1Interview: (applicationId: string) =>
    request<Application>(
      `/applications/${applicationId}/start-r1-interview`,
      { method: "POST" },
    ),

  // ---------- ACS Teams Interview Agent ----------
  /** Dispatch the ACS bot to join the candidate's R1 Teams meeting. */
  acsInterviewStart: (applicationId: string) =>
    request<AcsInterviewStatus>(
      `/applications/${applicationId}/acs-interview/start`,
      { method: "POST" },
    ),
  /** Poll live status of the ACS Teams interview bot. */
  acsInterviewStatus: (applicationId: string) =>
    request<AcsInterviewStatus>(
      `/applications/${applicationId}/acs-interview/status`,
    ),
  /** After the bot finishes, fold the captured transcript into the InterviewRecord. */
  acsInterviewFinalise: (applicationId: string) =>
    request<AcsInterviewStatus>(
      `/applications/${applicationId}/acs-interview/finalise`,
      { method: "POST" },
    ),

  // ---------- Virtual Interviewer (candidate-driven) ----------
  /** Start (or resume) the candidate's in-browser AI interview session.
   *
   * The backend proxies this to the team's pre-built AI Interview Agent
   * service, which runs a face-detection gate before creating the session.
   * The candidate's webcam frame is captured client-side and posted as a
   * base64 data URL in the ``photo`` field. */
  virtualInterviewStart: (
    applicationId: string,
    photo: string,
    language: "en" | "hi" = "en",
  ) =>
    request<VirtualInterviewStatus>(
      `/applications/${applicationId}/virtual-interview/start`,
      { method: "POST", body: JSON.stringify({ photo, language }) },
    ),
  /** Read current state of the virtual interview session. */
  virtualInterviewStatus: (applicationId: string) =>
    request<VirtualInterviewStatus>(
      `/applications/${applicationId}/virtual-interview/status`,
    ),
  /** Submit the candidate's answer to the current question. */
  virtualInterviewAnswer: (applicationId: string, answerText: string) =>
    request<VirtualInterviewStatus>(
      `/applications/${applicationId}/virtual-interview/answer`,
      {
        method: "POST",
        body: JSON.stringify({ answer_text: answerText }),
      },
    ),
  /** End the session early and fold the captured transcript. */
  virtualInterviewFinalise: (applicationId: string) =>
    request<VirtualInterviewStatus>(
      `/applications/${applicationId}/virtual-interview/finalise`,
      { method: "POST" },
    ),
  /** Fetch the AI interviewer's TTS welcome message (mp3 base64). */
  virtualInterviewWelcomeAudio: (applicationId: string) =>
    request<{ success: boolean; welcome_message: string; audio_base64: string }>(
      `/applications/${applicationId}/virtual-interview/welcome-audio`,
    ),
  /** Fetch the question text + TTS audio for a given index. The sidecar
   * advances `current_question_index` automatically when this is called. */
  virtualInterviewFullQuestion: (applicationId: string, index: number) =>
    request<{
      success: boolean
      question: { text: string; index: number; total: number }
      audio_base64: string
    }>(
      `/applications/${applicationId}/virtual-interview/full-question/${index}`,
    ),
  /** Send the candidate's recorded audio (base64 data URL) to Deepgram via
   * the sidecar and get back the transcript. */
  virtualInterviewTranscribe: (applicationId: string, audio: string) =>
    request<{ success: boolean; transcript: string }>(
      `/applications/${applicationId}/virtual-interview/transcribe`,
      { method: "POST", body: JSON.stringify({ audio }) },
    ),
  /** Periodic face check during the interview. */
  virtualInterviewVerifyFace: (applicationId: string, photo: string) =>
    request<{ success: boolean; match: boolean; name?: string; message?: string }>(
      `/applications/${applicationId}/virtual-interview/verify-face`,
      { method: "POST", body: JSON.stringify({ photo }) },
    ),

  /** Candidate confirms one of the slots the agent proposed. */
  confirmSlot: (
    applicationId: string,
    slotIndex: number,
    round: "R1" | "R2" = "R1",
  ) =>
    request<Application>(`/applications/${applicationId}/confirm-slot`, {
      method: "POST",
      body: JSON.stringify({ round, slot_index: slotIndex }),
    }),

  /**
   * Candidate picks a CUSTOM R1 start time ("Start now" or a custom
   * date + time from the picker). The backend appends a synthetic
   * 30-minute slot to proposed_r1_slots at `startIso` and confirms it.
   * Only supported for R1 — R2 must intersect real panel calendars.
   */
  confirmCustomR1Slot: (applicationId: string, startIso: string) =>
    request<Application>(`/applications/${applicationId}/confirm-slot`, {
      method: "POST",
      body: JSON.stringify({
        round: "R1",
        slot_index: -1,
        custom_start_iso: startIso,
      }),
    }),

  /**
   * Candidate clicks 'Reschedule' on a booked round. Cancels the existing
   * Teams meeting on Graph and walks the orchestrator back to slot
   * proposal — the candidate then sees a fresh tile picker.
   *
   * Backend refuses (HTTP 400) if the meeting is within 4 hours of starting.
   */
  rescheduleInterview: (
    applicationId: string,
    round: "R1" | "R2",
  ) =>
    request<Application>(
      `/applications/${applicationId}/reschedule/${round}`,
      { method: "POST" },
    ),

  getChecklist: (jdId: string, round: "R1" | "R2", phase: "pre" | "post") =>
    request<{ jd_id: string; round: string; phase: string; items: ChecklistItem[] }>(
      `/jobs/${jdId}/checklist/${round}/${phase}`,
    ),

  customiseChecklist: (
    jdId: string,
    round: "R1" | "R2",
    phase: "pre" | "post",
    extraItems: ChecklistItem[],
  ) =>
    request(`/jobs/${jdId}/checklist/${round}/${phase}/customise`, {
      method: "POST",
      body: JSON.stringify({ extra_items: extraItems }),
    }),

  tickChecklistItem: (
    appId: string,
    round: "R1" | "R2",
    phase: "pre" | "post",
    itemId: string,
    actor = "hr_partner",
    note = "",
  ) =>
    request<ChecklistInstance>(
      `/applications/${appId}/checklist/${round}/${phase}/tick`,
      {
        method: "POST",
        body: JSON.stringify({ item_id: itemId, actor, note }),
      },
    ),

  // ---- Panel configuration (DESIGN-001) ----
  listPanels: () => request<Panel[]>("/panels"),
  listPanelsForJob: (jdId: string) =>
    request<Panel[]>(`/panels/for-job/${encodeURIComponent(jdId)}`),
  r2SlotsByPanel: (applicationId: string) =>
    request<R2SlotsByPanelEntry[]>(
      `/applications/${encodeURIComponent(applicationId)}/r2-slots-by-panel`,
    ),
  createPanel: (req: {
    name: string;
    members: PanelMember[];
    role_scopes: string[];
    location?: string | null;
    default_size?: number;
    active?: boolean;
  }) =>
    request<Panel>("/panels", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  updatePanel: (
    panelId: string,
    req: {
      name?: string;
      members?: PanelMember[];
      role_scopes?: string[];
      location?: string | null;
      default_size?: number;
      active?: boolean;
    },
  ) =>
    request<Panel>(`/panels/${encodeURIComponent(panelId)}`, {
      method: "PATCH",
      body: JSON.stringify(req),
    }),
  deletePanel: (panelId: string) =>
    request<{ status: string; id: string }>(
      `/panels/${encodeURIComponent(panelId)}`,
      { method: "DELETE" },
    ),

  /** HR approves the R1-cleared application and selects the R2 panel. */
  approveR2: (applicationId: string, panelId: string) =>
    request<Application>(`/applications/${applicationId}/approve-r2`, {
      method: "POST",
      body: JSON.stringify({ panel_id: panelId }),
    }),

  /** HR rejects an R1-complete candidate after reading the AI report + transcript. */
  hrRegretR1: (applicationId: string, reason: string) =>
    request<Application>(`/applications/${applicationId}/hr-regret-r1`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),

  /**
   * HR decides on a below-threshold screening match.
   *
   * The orchestrator never auto-rejects an internal candidate at intake
   * — when the AI screening match is below the JD threshold it pauses
   * WAITING_HR and emails the full report to the HR partner. HR then
   * calls this endpoint to either advance (override the threshold and
   * push the candidate into Round 1) or regret (close the application
   * with the post-screening regret email).
   */
  hrScreeningDecision: (
    applicationId: string,
    decision: "advance" | "regret",
    reason: string = "",
  ) =>
    request<Application>(
      `/applications/${applicationId}/hr-screening-decision`,
      {
        method: "POST",
        body: JSON.stringify({ decision, reason }),
      },
    ),

  // -------------------------------------------------------------------
  // Axis taxonomy (JOB_ROLES + SKILL_MASTER) — official catalogue of
  // roles + skills the bank uses internally. Sourced from the two CSVs
  // shipped under backend/data/taxonomy/. Used by the JD editor's role
  // and skill pickers, the candidate match panel, and the HR review
  // page so the demo speaks Axis-speak end to end.
  // -------------------------------------------------------------------
  taxonomyStats: () =>
    request<{ roles: number; skills: number; departments: number; skill_categories: number }>(
      `/taxonomy/stats`,
    ),
  searchTaxonomyRoles: (q: string, limit = 25) =>
    request<TaxonomyRole[]>(
      `/taxonomy/roles?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  getTaxonomyRole: (roleId: string) =>
    request<TaxonomyRoleDetail>(`/taxonomy/roles/${encodeURIComponent(roleId)}`),
  searchTaxonomySkills: (q: string, limit = 30) =>
    request<TaxonomySkill[]>(
      `/taxonomy/skills?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  taxonomySkillCategories: () => request<string[]>(`/taxonomy/skill-categories`),
  taxonomyDepartments: () => request<string[]>(`/taxonomy/departments`),

  /** Run Claude on the R2 transcript; cached on the interview record. HR-only. */
  analyseTranscript: (
    applicationId: string,
    transcriptText: string,
    force = false,
  ) =>
    request<AiPanelRecommendation>(
      `/applications/${applicationId}/analyse-transcript`,
      {
        method: "POST",
        body: JSON.stringify({ transcript_text: transcriptText, force }),
      },
    ),

  /** Run Claude scoped to ONE panellist's vote against THAT panellist's
   *  own 1-on-1 R2 transcript. If transcriptText is omitted the backend
   *  uses the per-panellist transcript already on file. Cached on
   *  InterviewRecord.ai_recommendations_by_panellist[panellistId]. */
  analysePanellist: (
    applicationId: string,
    panellistId: string,
    transcriptText?: string,
    force = false,
  ) =>
    request<AiPanelRecommendation>(
      `/applications/${applicationId}/analyse-panellist/${encodeURIComponent(panellistId)}`,
      {
        method: "POST",
        body: JSON.stringify({
          transcript_text: transcriptText ?? null,
          force,
        }),
      },
    ),

  /** HR finalises the R2 verdict (offer or reject) after reviewing panel feedback. */
  hrR2Decision: (applicationId: string, decision: "offer" | "reject") =>
    request<Application>(`/applications/${applicationId}/hr-r2-decision`, {
      method: "POST",
      body: JSON.stringify({ decision }),
    }),

  // ---------- Offer Discussion Team (post-R2, pre final-offer) ----------
  /** Queue of applications currently sitting with the Offer Discussion Team. */
  offerTeamQueue: () =>
    request<OfferTeamQueueRow[]>("/offer-team/queue"),
  /** Roll out the formal offer letter at the negotiated CTC, moving the
   * application from OFFER_NEGOTIATION → OFFER. */
  offerTeamRollout: (
    applicationId: string,
    body: { final_ctc_lpa: number; notes?: string; rolled_out_by?: string },
  ) =>
    request<Application>(`/applications/${applicationId}/offer-team/rollout`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ---------- External candidate ----------
  externalParseResume: (resumeText: string) =>
    request<{
      profile: {
        employee_id: string;
        name: string;
        email: string;
        current_role: string;
        current_location: string;
        tenure_years: number;
        skills: string[];
      };
      matches: {
        job_id: string;
        job_title: string;
        location: string;
        match_percent: number;
        matched_skills: string[];
        missing_skills: string[];
        rationale: string;
      }[];
    }>("/external/parse-resume", {
      method: "POST",
      body: JSON.stringify({ resume_text: resumeText }),
    }),

  externalParseResumeFile: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/external/parse-resume-file`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    return (await res.json()) as {
      resume_text: string;
      profile: {
        employee_id: string;
        name: string;
        email: string;
        current_role: string;
        current_location: string;
        tenure_years: number;
        skills: string[];
      };
      matches: {
        job_id: string;
        job_title: string;
        location: string;
        match_percent: number;
        matched_skills: string[];
        missing_skills: string[];
        rationale: string;
      }[];
      source: "claude" | "deterministic";
    };
  },

  externalApply: (
    resumeText: string,
    jobId: string,
    opts?: {
      // Identity override from the intake form. We MUST forward these
      // to /external/apply, otherwise the backend re-runs parse_resume
      // on the resume text and silently keys the candidate on whatever
      // email the regex finds in the resume header — which can differ
      // from the email the candidate typed on the intake form, and the
      // tracker page (which queries by typed email) ends up empty.
      name?: string | null;
      email?: string | null;
      searchQuery?: string | null;
      recommendationSource?: "search" | "ai" | null;
      compensation?: CompensationBreakdown | null;
    },
  ) =>
    request<Application>("/external/apply", {
      method: "POST",
      body: JSON.stringify({
        resume_text: resumeText,
        job_id: jobId,
        name: opts?.name ?? null,
        email: opts?.email ?? null,
        search_query: opts?.searchQuery ?? null,
        recommendation_source: opts?.recommendationSource ?? null,
        compensation: opts?.compensation ?? null,
      }),
    }),

  /** Run a Claude semantic NL search against the open JD catalogue. */
  externalSearchJobs: (query: string) =>
    request<{
      query: string;
      matches: ExternalRecommendation[];
      source: "claude" | "deterministic";
    }>("/external/search-jobs", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),

  /** Upload a salary slip (PDF/DOCX/TXT) → structured CTC + components. */
  externalParseSalarySlip: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/external/parse-salary-slip`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    return (await res.json()) as {
      compensation: CompensationBreakdown;
      source: "claude" | "deterministic";
    };
  },

  /** Unified intake: resume + optional salary slip + name/email + NL query
   *  → resume_text + profile (with merged compensation) + AI-ranked matches
   *  + NL search matches in a single Claude-powered round trip. */
  externalIntake: async (params: {
    resume: File;
    salarySlip?: File | null;
    name: string;
    email: string;
    searchQuery: string;
  }) => {
    const fd = new FormData();
    fd.append("resume", params.resume);
    if (params.salarySlip) {
      fd.append("salary_slip", params.salarySlip);
    }
    fd.append("name", params.name);
    fd.append("email", params.email);
    fd.append("search_query", params.searchQuery);
    const res = await fetch(`${API_BASE}/external/intake`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    return (await res.json()) as ExternalIntakeResponse;
  },

  externalApplications: (email: string) =>
    request<Application[]>(
      `/external/applications?email=${encodeURIComponent(email)}`,
    ),

  externalSimulateReply: (senderEmail: string, bodyText: string) =>
    request<{ advanced: boolean }>("/external/simulate-reply", {
      method: "POST",
      body: JSON.stringify({ sender_email: senderEmail, body_text: bodyText }),
    }),

  externalPollInbox: () =>
    request<{ dispatched: number }>("/external/poll-inbox", { method: "POST" }),

  panelPending: (userId: string) =>
    request<PanelPendingItem[]>(
      `/panel/pending?user_id=${encodeURIComponent(userId)}`,
    ),

  /** Read-only list of every R2 vote this panellist has already submitted. */
  panelHistory: (userId: string) =>
    request<PanelHistoryItem[]>(
      `/panel/history?user_id=${encodeURIComponent(userId)}`,
    ),

  panelMembers: () => request<PanelMemberListed[]>("/panel/members"),
  hrPartners: () => request<HrPartner[]>("/hr/partners"),

  submitPanelFeedback: (req: {
    interview_id: string;
    panellist_id: string;
    score: number;
    strengths: string;
    concerns: string;
    recommendation: "strong_hire" | "hire" | "no_hire";
  }) =>
    request<{ status: string; application_id: string | null }>("/panel/feedback", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  debugEmails: (applicationId?: string) => {
    const qs = applicationId ? `?application_id=${applicationId}` : "";
    return request<
      {
        id: string;
        thread_id: string;
        to: string;
        from: string;
        subject: string;
        body: string;
        at: string;
        direction: string;
        application_id?: string | null;
      }[]
    >(`/debug/emails${qs}`);
  },

  debugCalendar: (applicationId?: string) => {
    const qs = applicationId ? `?application_id=${applicationId}` : "";
    return request<
      {
        id: string;
        subject: string;
        organiser_id: string;
        attendees: string[];
        start: string;
        end: string;
        teams_join_url: string | null;
        cancelled: boolean;
        application_id?: string | null;
      }[]
    >(`/debug/calendar${qs}`);
  },

  debugNotifications: () =>
    request<
      {
        id: string;
        to: string;
        message: string;
        at: string;
        application_id?: string | null;
        jd_id?: string | null;
      }[]
    >("/debug/notifications"),

  demoReset: () =>
    request<{ status: string; jobs: number; candidates: number }>("/demo/reset", {
      method: "POST",
    }),
  demoSeedFlow: () =>
    request<{ status: string; applications: string[] }>("/demo/seed-flow", {
      method: "POST",
    }),
  /** Wipe all applications (same as demoReset) and pre-seed ONE application
   *  parked at FunnelStage.OFFER (waiting for candidate to accept). Used to
   *  demo the post-offer engagement / onboarding chat / WhatsApp warm-keep
   *  flow without driving a candidate through the whole funnel first. */
  demoWipePlusOffer: () =>
    request<{
      status: string;
      application_id: string;
      stage: string;
      agent_status: string;
      candidate: string;
      job: string;
      note: string;
    }>("/demo/wipe-plus-offer", { method: "POST" }),

  // ---------- Bulk CV Screening (HR dashboard) ----------
  /** Upload N CVs against a target JD. Returns pool_id immediately;
   *  processing happens asynchronously. Poll with bulkIntakeStatus. */
  bulkIntake: async (
    jobId: string | null,
    files: File[],
    customCriteria?: string,
  ) => {
    const fd = new FormData();
    fd.append("job_id", jobId || "");
    if (customCriteria && customCriteria.trim()) {
      fd.append("custom_criteria", customCriteria.trim());
    }
    for (const f of files) fd.append("files", f);
    const res = await fetch(`${API_BASE}/hr/bulk-intake`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()) as BulkIntakeResponse;
  },
  /** Poll batch status — live progress + per-row state. */
  bulkIntakeStatus: (poolId: string) =>
    request<BulkPoolStatus>(`/hr/bulk-intake/${poolId}`),
  /** Ranked leaderboard for a completed batch. */
  bulkIntakeResults: (poolId: string) =>
    request<BulkLeaderboard>(`/hr/bulk-intake/${poolId}/results`),
  /** Drill-in detail for one CV in a batch. */
  bulkIntakeRowDetail: (poolId: string, rowId: string) =>
    request<BulkRowDetail>(`/hr/bulk-intake/${poolId}/row/${rowId}`),
  /** CSV export URL (opened as a download, not fetched as JSON). */
  bulkIntakeExportUrl: (poolId: string) =>
    `${API_BASE}/hr/bulk-intake/${poolId}/export`,
  /** Batch update contact details for rows in a pool pending review. */
  updatePoolContacts: (
    poolId: string,
    contacts: Array<{
      row_id: string;
      candidate_email?: string;
      candidate_phone?: string;
      candidate_name?: string;
    }>,
  ) =>
    request<{ ok: boolean }>(`/hr/bulk-intake/${poolId}/contacts`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contacts }),
    }),
  /** Start AI scoring after HR has reviewed contacts. */
  startPoolScoring: (poolId: string) =>
    request<{ ok: boolean; pool_id: string }>(
      `/hr/bulk-intake/${poolId}/start-scoring`,
      { method: "POST" },
    ),
  /** List all screening batches for the HR dashboard. */
  candidatePools: () =>
    request<BulkPoolSummary[]>("/hr/candidate-pools"),
  /** Route a bulk-screened candidate to L1 or L2 interview, or notify them. */
  routeCandidate: (
    poolId: string,
    rowId: string,
    round: "L1" | "L2",
    opts?: { job_id?: string; action?: "route" | "notify" },
  ) =>
    request<RouteResponse>(`/hr/bulk-intake/${poolId}/row/${rowId}/route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ round, ...opts }),
    }),
  /** Candidate withdraws their application. */
  withdrawApplication: (appId: string, reason: string) =>
    request<{ status: string; message: string }>(`/applications/${appId}/withdraw`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }),
};

// ---------- Bulk Screening types ----------

export type BulkIntakeResponse = {
  pool_id: string;
  job_id: string | null;
  job_title: string;
  mode: "single_jd" | "auto_map";
  total_files: number;
  status: string;
};

export type BulkPoolStatus = {
  pool_id: string;
  job_id: string | null;
  job_title: string;
  mode: "single_jd" | "auto_map";
  created_by: string;
  created_at: string;
  status: "pending_review" | "processing" | "done" | "failed";
  total: number;
  done_count: number;
  progress_pct: number;
  custom_criteria?: string | null;
  rows: BulkRow[];
};

export type BulkRow = {
  row_id: string;
  file_name: string;
  status: "queued" | "parsing" | "parsed" | "scoring" | "done" | "error";
  candidate_name?: string | null;
  candidate_email?: string | null;
  candidate_phone?: string | null;
  match_percent?: number | null;
  matched_skills: string[];
  missing_skills: string[];
  recommendation?: "shortlist" | "maybe" | "reject" | null;
  headline?: string | null;
  summary?: string | null;
  strengths: string[];
  concerns: string[];
  evidence_quotes: string[];
  criteria_assessment?: CriteriaAssessmentItem[];
  error_message?: string | null;
  routed_to?: "L1" | "L2" | null;
  application_id?: string | null;
};

export type CriteriaAssessmentItem = {
  criterion: string;
  verdict: "met" | "partial" | "not_met" | "unclear";
  evidence: string;
};

export type BulkLeaderboard = {
  pool_id: string;
  job_id: string | null;
  job_title: string;
  mode: "single_jd" | "auto_map";
  status: string;
  total: number;
  leaderboard: BulkLeaderboardEntry[];
};

export type BulkLeaderboardEntry = {
  rank: number;
  row_id: string;
  file_name: string;
  candidate_name?: string | null;
  candidate_email?: string | null;
  candidate_phone?: string | null;
  match_percent?: number | null;
  recommendation?: "shortlist" | "maybe" | "reject" | null;
  headline?: string | null;
  matched_skills: string[];
  missing_skills: string[];
  status: string;
  routed_to?: "L1" | "L2" | null;
  application_id?: string | null;
  // Auto-map fields
  best_job_id?: string | null;
  best_job_title?: string | null;
  all_job_scores?: { job_id: string; job_title: string; location: string; band: string; match_percent: number; recommendation: string }[];
};

export type RouteResponse = {
  ok: boolean;
  application_id: string | null;
  candidate_name: string;
  routed_to: string;
  stage: string;
  message: string;
};

export type BulkRowDetail = BulkRow & {
  pool_id: string;
  job_id: string;
  job_title: string;
  pool_custom_criteria?: string | null;
  resume_text?: string | null;
  profile?: Record<string, unknown> | null;
};

export type BulkPoolSummary = {
  pool_id: string;
  job_id: string | null;
  job_title: string;
  mode: "single_jd" | "auto_map";
  created_by: string;
  created_at: string;
  status: "pending_review" | "processing" | "done" | "failed";
  total: number;
  done_count: number;
  progress_pct: number;
  shortlisted: number;
  candidate_names: string[];
};

// ---------- Engagement Journey types ----------

export type TouchpointKind =
  | "welcome_whatsapp"
  | "buddy_intro"
  | "document_checklist"
  | "culture_video"
  | "employee_stories"
  | "benefits_overview"
  | "weekly_checkin"
  | "linkedin_connect"
  | "it_setup_form"
  | "team_intro_call"
  | "dress_code_tips"
  | "joining_reminder"
  | "day_one_welcome"
  | "custom";

export type TouchpointStatus =
  | "pending"
  | "sent"
  | "delivered"
  | "read"
  | "failed"
  | "skipped";

export interface EngagementTouchpoint {
  id: string;
  kind: TouchpointKind;
  channel: "whatsapp" | "email" | "portal" | "calendar";
  scheduled_at: string;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  candidate_response: string | null;
  status: TouchpointStatus;
  template_id: string | null;
  whatsapp_message_id: string | null;
  error_message: string | null;
}

export interface ConversationMessage {
  id: string;
  journey_id: string;
  direction: "inbound" | "outbound";
  sender: string;
  body: string;
  channel: "whatsapp" | "email" | "portal";
  touchpoint_id: string | null;
  reply_to_id: string | null;
  whatsapp_message_id: string | null;
  timestamp: string;
  status: string | null;
}

export interface EngagementJourney {
  id: string;
  application_id: string;
  candidate_name: string;
  candidate_email: string;
  candidate_phone: string;
  whatsapp_opted_in: boolean;
  offer_accepted_at: string | null;
  expected_joining_date: string | null;
  buddy_name: string | null;
  buddy_email: string | null;
  touchpoints: EngagementTouchpoint[];
  conversations?: ConversationMessage[];
  sentiment_score: number | null;
  risk_level: "low" | "medium" | "high";
  status: "active" | "completed" | "dropped";
  created_at: string;
  updated_at: string;
}

export interface RiskDimension {
  score: number;
  detail: string;
  signals: string[];
}

export interface FlaggedReply {
  touchpoint_id: string;
  touchpoint_kind: string;
  reply_text: string;
  is_query: boolean;
  is_concern: boolean;
  sentiment: "positive" | "negative" | "neutral";
  needs_attention: boolean;
}

export interface RiskAssessment {
  overall_score: number;
  risk_level: "low" | "medium" | "high";
  dimensions: {
    responsiveness: RiskDimension;
    sentiment: RiskDimension;
    compliance: RiskDimension;
    timeline: RiskDimension;
  };
  flagged_replies: FlaggedReply[];
  suggested_actions: string[];
}

export interface EngagementDashboard {
  total_active_journeys: number;
  at_risk_count: number;
  upcoming_touchpoints_24h: { journey_id: string; candidate_name: string; touchpoint_id: string; kind: TouchpointKind; scheduled_at: string }[];
  completion_rate_percent: number;
  journeys: EngagementJourney[];
  risk_assessments?: Record<string, RiskAssessment>;
}

// ---------- Engagement API methods ----------

export async function acceptOffer(
  appId: string,
  phone: string,
  whatsappConsent: boolean,
  expectedJoiningDate: string,
): Promise<EngagementJourney> {
  return request<EngagementJourney>(`/applications/${appId}/offer/accept`, {
    method: "POST",
    body: JSON.stringify({
      phone,
      whatsapp_consent: whatsappConsent,
      expected_joining_date: expectedJoiningDate,
    }),
  });
}

export async function declineOffer(
  appId: string,
  reason?: string,
): Promise<Application> {
  return request<Application>(`/applications/${appId}/offer/decline`, {
    method: "POST",
    body: JSON.stringify({ reason: reason || null }),
  });
}

export async function getEngagementJourney(
  journeyId: string,
): Promise<EngagementJourney> {
  return request<EngagementJourney>(`/engagement/journeys/${journeyId}`);
}

export async function getEngagementByApplication(
  appId: string,
): Promise<EngagementJourney> {
  return request<EngagementJourney>(`/engagement/by-application/${appId}`);
}

export async function listEngagementJourneys(): Promise<EngagementJourney[]> {
  return request<EngagementJourney[]>("/engagement/journeys");
}

export async function getEngagementDashboard(): Promise<EngagementDashboard> {
  return request<EngagementDashboard>("/engagement/dashboard");
}

export async function updateEngagementJourney(
  journeyId: string,
  patch: { buddy_name?: string; buddy_email?: string; expected_joining_date?: string; risk_level?: string },
): Promise<EngagementJourney> {
  return request<EngagementJourney>(`/engagement/journeys/${journeyId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function sendTouchpoint(
  journeyId: string,
  touchpointId: string,
): Promise<EngagementTouchpoint> {
  return request<EngagementTouchpoint>(
    `/engagement/journeys/${journeyId}/touchpoints/${touchpointId}/send`,
    { method: "POST" },
  );
}

export async function skipTouchpoint(
  journeyId: string,
  touchpointId: string,
): Promise<EngagementTouchpoint> {
  return request<EngagementTouchpoint>(
    `/engagement/journeys/${journeyId}/touchpoints/${touchpointId}/skip`,
    { method: "POST" },
  );
}

export async function getAtRiskJourneys(): Promise<EngagementJourney[]> {
  return request<EngagementJourney[]>("/engagement/at-risk");
}

export async function replyToCandidate(
  journeyId: string,
  message: string,
  opts?: { reply_to_id?: string; touchpoint_id?: string },
): Promise<{ status: string; message_id: string }> {
  return request<{ status: string; message_id: string }>(
    `/engagement/journeys/${journeyId}/reply`,
    {
      method: "POST",
      body: JSON.stringify({
        message,
        ...(opts?.reply_to_id ? { reply_to_id: opts.reply_to_id } : {}),
        ...(opts?.touchpoint_id ? { touchpoint_id: opts.touchpoint_id } : {}),
      }),
    },
  );
}

export async function getConversations(
  journeyId: string,
): Promise<{ journey_id: string; candidate_name: string; candidate_phone: string; messages: ConversationMessage[]; total: number }> {
  return request(`/engagement/journeys/${journeyId}/conversations`);
}

export async function retagReplies(): Promise<{ retagged: number }> {
  return request<{ retagged: number }>("/engagement/retag-replies", {
    method: "POST",
  });
}

// ---------------------------------------------------------------------------
// Candidate onboarding chatbot — visible on Thrive status page after the
// offer is accepted. Mirrored into the onboarding team's chat history view.
// ---------------------------------------------------------------------------

export interface OnboardingChatResponse {
  inbound: ConversationMessage;
  outbound: ConversationMessage;
  source: "claude" | "deterministic";
  role_file: string;
}

export async function sendOnboardingChat(
  appId: string,
  message: string,
): Promise<OnboardingChatResponse> {
  return request<OnboardingChatResponse>(
    `/applications/${appId}/onboarding-chat`,
    { method: "POST", body: JSON.stringify({ message }) },
  );
}

export async function getOnboardingChat(
  appId: string,
): Promise<{ journey_id: string | null; messages: ConversationMessage[]; total?: number }> {
  return request(`/applications/${appId}/onboarding-chat`);
}
