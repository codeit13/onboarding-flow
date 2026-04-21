"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { RoleGate } from "@/components/RoleGate";
import { AgentActivityFeed } from "@/components/agent/AgentActivityFeed";
import { AgentStatusBadge } from "@/components/agent/AgentStatusBadge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  api,
  type ActivityItem,
  type AiPanelRecommendation,
  type Application,
  type ChecklistInstance,
  type ChecklistItem,
  type Job,
  type Panel,
  type R2SlotsByPanelEntry,
} from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";
import { STAGE_LABEL } from "@/lib/stages";

type Tab = "overview" | "checklists" | "transcript" | "activity" | "audit";

/**
 * HR application detail page.
 *
 * The orchestrator drives every transition autonomously, so there are NO
 * "Advance R1 / Schedule R2 / Finalise" buttons here. HR has only three
 * possible actions:
 *
 *   1. Tick off a checklist item (some are blocking — the agent is paused
 *      until they're done).
 *   2. Hit "Unblock agent" if the orchestrator wedged on a transient error
 *      (the backend route is idempotent and just retries).
 *   3. Read.
 *
 * Live state is polled every 4s via useAutoRefresh — application + activity
 * feed in parallel — so the page reflects the agent's progress in real time.
 */
export default function HRApplicationDetailPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <HRApplicationDetailContent />
    </RoleGate>
  );
}

function HRApplicationDetailContent() {
  const params = useParams<{ appId: string }>();
  const [tab, setTab] = useState<Tab>("overview");
  const [acting, setActing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // "Selection ≠ commitment": every checklist tick (especially BLOCKING
  // ones) routes through a confirm dialog before it actually fires.
  const [pendingTick, setPendingTick] = useState<{
    round: "R1" | "R2";
    phase: "pre" | "post";
    item: ChecklistItem;
  } | null>(null);
  const [pendingUnblock, setPendingUnblock] = useState(false);
  const [pendingApprove, setPendingApprove] = useState(false);

  // HR R2 review state — HR reads panel feedback, (optionally) runs the
  // Claude AI review of the transcript ONCE PER PANELLIST so each vote
  // can be corroborated or challenged independently, and then clicks
  // "Make offer" or "Reject" to finalise.
  const [aiRecs, setAiRecs] = useState<Record<string, AiPanelRecommendation>>(
    {},
  );
  const [analysingId, setAnalysingId] = useState<string | null>(null);
  const [analyseErrors, setAnalyseErrors] = useState<Record<string, string>>(
    {},
  );
  const [finalising, setFinalising] = useState(false);
  const [finaliseError, setFinaliseError] = useState<string | null>(null);
  const [pendingDecision, setPendingDecision] =
    useState<"offer" | "reject" | null>(null);

  // DESIGN-001: R2 panel approval state. Only loaded when the app is
  // sitting at R1_DONE with no panel selected yet — replaces the legacy
  // manual ``pre-r2-2`` checklist tick with a prominent action.
  const [availablePanels, setAvailablePanels] = useState<Panel[] | null>(null);
  const [panelsError, setPanelsError] = useState<string | null>(null);
  const [selectedPanelId, setSelectedPanelId] = useState<string>("");
  const [approving, setApproving] = useState(false);
  // R1 HR review (post AI interview): HR sees full AI report + transcript and
  // decides Advance-to-R2 or Regret. The orchestrator now ALWAYS pauses on
  // WAITING_HR after R1 scoring (no auto-reject), so this gate is the single
  // human checkpoint between the AI interview and Round 2.
  const [r1RegretReason, setR1RegretReason] = useState("");
  const [r1Regretting, setR1Regretting] = useState(false);
  const [r1RegretError, setR1RegretError] = useState<string | null>(null);
  const [showR1Transcript, setShowR1Transcript] = useState(false);
  // Bilingual R1 analysis toggle. Defaults to "both" so a Hindi-speaking
  // Business Partner can read either language without extra clicks; only
  // visible when the Claude scorer detected Hindi/code-switched audio
  // (`transcript_language` ∈ {"hi","hi-en"}). For pure-English R1s the
  // toggle is hidden and only the English column renders.
  const [r1Lang, setR1Lang] = useState<"en" | "hi" | "both">("both");
  // Screening review (intake gate): same human-in-the-loop pattern as R1.
  // When the AI screening rubric scores BELOW the JD threshold the
  // orchestrator no longer auto-rejects — it parks the application on
  // HR with the full report and waits for an explicit Advance/Regret.
  const [screeningReason, setScreeningReason] = useState("");
  const [screeningActing, setScreeningActing] = useState<
    "advance" | "regret" | null
  >(null);
  const [screeningError, setScreeningError] = useState<string | null>(null);
  // Per-panel slot preview so HR can compare panels by candidate availability
  // BEFORE approving (BUG-010). Loaded in the same effect as the panel list.
  const [slotsByPanel, setSlotsByPanel] = useState<R2SlotsByPanelEntry[] | null>(
    null,
  );
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [slotsError, setSlotsError] = useState<string | null>(null);

  const loadApp = useCallback(
    () => api.getApplication(params.appId),
    [params.appId],
  );
  const loadActivity = useCallback(
    () => api.listActivity(params.appId),
    [params.appId],
  );

  const {
    data: app,
    error,
    refresh,
  } = useAutoRefresh<Application>(loadApp, 4000);
  const { data: activity, refresh: refreshActivity } = useAutoRefresh<
    ActivityItem[]
  >(loadActivity, 4000);

  // Job fetched lazily once we know the job_id — pinned to a separate hook
  // call so its loader closure depends on app.job_id rather than appId.
  const loadJob = useCallback(async () => {
    if (!app) return null;
    return api.getJob(app.job_id);
  }, [app?.job_id]);
  const { data: job } = useAutoRefresh<Job | null>(loadJob, 60_000);

  const tick = async (
    round: "R1" | "R2",
    phase: "pre" | "post",
    itemId: string,
  ) => {
    if (!app) return;
    setActing(true);
    setActionError(null);
    try {
      await api.tickChecklistItem(app.id, round, phase, itemId);
      // Tick can release a blocking gate — give the orchestrator a beat,
      // then refresh both panes immediately rather than waiting for the
      // next poll tick.
      await Promise.all([refresh(), refreshActivity()]);
    } catch (e: any) {
      setActionError(`Tick failed: ${e?.message || e}`);
    } finally {
      setActing(false);
    }
  };

  const unblock = async () => {
    if (!app) return;
    setActing(true);
    setActionError(null);
    try {
      await api.unblockApplication(app.id);
      await Promise.all([refresh(), refreshActivity()]);
    } catch (e: any) {
      setActionError(`Unblock failed: ${e?.message || e}`);
    } finally {
      setActing(false);
    }
  };

  const needsR2Approval =
    !!app && app.stage === "r1_done" && !app.selected_r2_panel_id;

  useEffect(() => {
    if (!needsR2Approval || !app) return;
    let cancelled = false;
    setPanelsError(null);
    setSlotsError(null);
    setSlotsLoading(true);
    Promise.all([
      api.listPanelsForJob(app.job_id),
      api.r2SlotsByPanel(app.id),
    ])
      .then(([ps, slots]) => {
        if (cancelled) return;
        setAvailablePanels(ps);
        setSlotsByPanel(slots);
        if (ps.length > 0 && !selectedPanelId) setSelectedPanelId(ps[0].id);
      })
      .catch((e) => {
        if (cancelled) return;
        setPanelsError(e?.message || String(e));
      })
      .finally(() => {
        if (!cancelled) setSlotsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsR2Approval, app?.job_id, app?.id]);

  const needsScreeningReview =
    !!app && app.stage === "applied" && app.agent_status === "waiting_hr";

  const decideScreening = async (decision: "advance" | "regret") => {
    if (!app) return;
    setScreeningActing(decision);
    setScreeningError(null);
    try {
      await api.hrScreeningDecision(app.id, decision, screeningReason.trim());
      await Promise.all([refresh(), refreshActivity()]);
    } catch (e: any) {
      setScreeningError(e?.message || String(e));
    } finally {
      setScreeningActing(null);
    }
  };

  const regretR1 = async () => {
    if (!app) return;
    setR1Regretting(true);
    setR1RegretError(null);
    try {
      await api.hrRegretR1(app.id, r1RegretReason.trim());
      await Promise.all([refresh(), refreshActivity()]);
    } catch (e: any) {
      setR1RegretError(e?.message || String(e));
    } finally {
      setR1Regretting(false);
    }
  };

  const approveR2 = async () => {
    if (!app || !selectedPanelId) return;
    setApproving(true);
    setActionError(null);
    try {
      await api.approveR2(app.id, selectedPanelId);
      await Promise.all([refresh(), refreshActivity()]);
    } catch (e: any) {
      setActionError(`Approve R2 failed: ${e?.message || e}`);
    } finally {
      setApproving(false);
    }
  };

  const r1 = app?.interviews.find((i) => i.round === "R1");
  const r2 = app?.interviews.find((i) => i.round === "R2");
  const r1Transcript = r1?.transcript ?? [];
  const r2Transcript = r2?.pasted_transcript ?? "";
  const r2TranscriptByPanellist = r2?.pasted_transcripts_by_panellist ?? {};
  const transcriptForPanellist = (panellistId: string): string =>
    r2TranscriptByPanellist[panellistId] || r2Transcript || "";

  // Hydrate any cached per-panellist Claude recommendations the backend
  // already has on record (so re-renders / refreshes do not lose them
  // and HR does not re-bill the API).
  useEffect(() => {
    const cached = r2?.ai_recommendations_by_panellist;
    if (cached && Object.keys(cached).length > 0) {
      setAiRecs((prev) => ({ ...prev, ...cached }));
    }
  }, [r2?.ai_recommendations_by_panellist]);

  // How many panellists are expected on this R2?
  const expectedPanelSize = (() => {
    if (!app || !availablePanels) return undefined;
    const selected = availablePanels.find(
      (p) => p.id === app.selected_r2_panel_id,
    );
    return selected ? selected.members.length : undefined;
  })();

  // HR review is needed when: the app is sitting at R2_SCHEDULED, the
  // agent is waiting on HR, and at least one panel vote has arrived.
  // (The orchestrator only pauses at WAITING_HR after panel voting is
  // complete in the new flow — see Orchestrator._do_finalise.)
  const needsR2Decision =
    !!app &&
    app.stage === "r2_scheduled" &&
    app.agent_status === "waiting_hr" &&
    (r2?.panel_feedback.length ?? 0) > 0;

  const runAiForPanellist = async (
    panellistId: string,
    force = false,
  ) => {
    if (!app) return;
    const transcript = transcriptForPanellist(panellistId);
    if (!transcript) return;
    setAnalysingId(panellistId);
    setAnalyseErrors((prev) => {
      const next = { ...prev };
      delete next[panellistId];
      return next;
    });
    try {
      const rec = await api.analysePanellist(
        app.id,
        panellistId,
        transcript,
        force,
      );
      setAiRecs((prev) => ({ ...prev, [panellistId]: rec }));
    } catch (e: any) {
      setAnalyseErrors((prev) => ({
        ...prev,
        [panellistId]: e?.message || String(e),
      }));
    } finally {
      setAnalysingId((cur) => (cur === panellistId ? null : cur));
    }
  };

  const finaliseR2 = async (decision: "offer" | "reject") => {
    if (!app) return;
    setFinalising(true);
    setFinaliseError(null);
    try {
      await api.hrR2Decision(app.id, decision);
      await Promise.all([refresh(), refreshActivity()]);
    } catch (e: any) {
      setFinaliseError(e?.message || String(e));
    } finally {
      setFinalising(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <HRSubNav />
      <main className="flex-1 px-8 py-6 max-w-6xl w-full mx-auto">
        <Link
          href="/hr"
          className="text-axis-magenta text-xs font-medium hover:underline"
        >
          ← Back to Business Partner console
        </Link>

        {error && (
          <div className="mt-6 p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
            {error}
          </div>
        )}
        {!app && !error && (
          <p className="mt-6 text-sm text-axis-muted">Loading…</p>
        )}

        {app && (
          <>
            <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card shadow-card p-6">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-xs uppercase tracking-wider text-axis-magenta font-semibold">
                    Application {app.id}
                  </p>
                  <h1 className="text-2xl font-display text-axis-ink mt-1 truncate">
                    {job?.title || app.job_id}
                  </h1>
                  <p className="text-sm text-axis-muted mt-1">
                    Candidate{" "}
                    <strong className="text-axis-ink">{app.candidate_id}</strong>{" "}
                    · JD <code className="text-axis-ink">{job?.job_id}</code> ·
                    Match{" "}
                    <strong className="text-axis-ink">
                      {app.match_percent.toFixed(0)}%
                    </strong>
                  </p>
                </div>
                <div className="flex flex-col items-end gap-2 shrink-0">
                  <span
                    className={`text-xs px-3 py-1 rounded ${
                      app.stage === "rejected"
                        ? "bg-axis-pink-soft text-axis-burgundy"
                        : app.stage === "offer"
                        ? "bg-axis-cream text-axis-ink"
                        : "bg-axis-surface text-axis-ink-soft"
                    }`}
                  >
                    {STAGE_LABEL[app.stage]}
                  </span>
                  <AgentStatusBadge status={app.agent_status} />
                </div>
              </div>

              {app.next_action && (
                <p className="mt-3 text-sm text-axis-ink-soft">
                  {app.next_action}
                </p>
              )}

              {/* Bulk-screening provenance — when this app was auto-created
                  by the screening pool, surface a prominent CTA back to
                  the review screen where HR can see the full row + Route /
                  Notify actions. Keeps the funnel and screening screens
                  stitched together. */}
              {app.source === "bulk_screening" && app.source_pool_id && (
                <div className="mt-3 p-3 rounded border border-axis-magenta/40 bg-axis-pink-soft/40 flex items-center justify-between gap-3">
                  <div className="text-xs text-axis-ink-soft">
                    <p className="font-semibold text-axis-ink">
                      Shortlisted from bulk screening
                    </p>
                    <p className="text-axis-muted mt-0.5">
                      This candidate was auto-shortlisted from the Bulk CV
                      Screening pool. Review the full screening result and
                      route to L1 / L2 or notify the candidate.
                    </p>
                  </div>
                  <Link
                    href={`/hr/bulk-screening/${app.source_pool_id}${
                      app.source_row_id ? `?row=${app.source_row_id}` : ""
                    }`}
                    className="shrink-0 text-xs px-3 py-2 rounded bg-axis-magenta text-white font-semibold hover:bg-axis-burgundy"
                  >
                    Review in Screening Pool →
                  </Link>
                </div>
              )}

              {/* Waiting-on-candidate card — friendly status when the
                  agent is waiting for the candidate to take action (e.g.
                  confirm R1 slot, complete R2 availability). No HR action
                  needed — just informational. */}
              {app.agent_status === "waiting_candidate" &&
                app.stage !== "offer_negotiation" &&
                app.stage !== "offer" &&
                app.stage !== "rejected" && (
                <div className="mt-3 p-3 rounded border border-indigo-200 bg-indigo-50/60 text-xs text-indigo-900">
                  <p className="font-semibold uppercase tracking-wider text-[10px] mb-1 text-indigo-700">
                    Waiting on candidate
                  </p>
                  <p>
                    {app.next_action || "The candidate has been notified and we're waiting for their response."}
                  </p>
                  <p className="mt-1 text-indigo-600/80">
                    No action needed from your side — the agent will proceed automatically once the candidate responds.
                  </p>
                </div>
              )}

              {/* "Agent paused — blocking items" card. Shown only when
                  there are blocking items that HR needs to act on (not
                  when the agent is waiting on the candidate). Hidden at
                  offer / closed stages where leftover lines are stale. */}
              {app.pending_blocking_items.length > 0 &&
                app.agent_status !== "waiting_candidate" &&
                app.stage !== "offer_negotiation" &&
                app.stage !== "offer" &&
                app.stage !== "rejected" && (
                <div className="mt-3 p-3 rounded border border-axis-magenta bg-axis-pink-soft text-xs text-axis-burgundy">
                  <p className="font-semibold uppercase tracking-wider text-[10px] mb-1">
                    Agent paused — blocking items
                  </p>
                  <ul className="list-disc list-inside space-y-0.5">
                    {app.pending_blocking_items.map((label) => (
                      <li key={label}>{label}</li>
                    ))}
                  </ul>
                  <p className="mt-1 text-axis-burgundy/80">
                    Tick the corresponding item under <strong>Checklists</strong>{" "}
                    to release the agent.
                  </p>
                </div>
              )}

              {/* Offer-stage confirmation card. After HR clicks Make offer
                  the page used to silently transition with no explanation,
                  leaving HR staring at stale R2 blocking-item text. This
                  card mirrors the "what's happening now / what happens
                  next" pattern from the candidate status page so HR has
                  closed-loop confirmation that the action landed. */}
              {app.stage === "offer_negotiation" && (
                <div className="mt-4 p-4 rounded-card border-2 border-emerald-300 bg-emerald-50">
                  <p className="text-[10px] uppercase tracking-widest text-emerald-800 font-bold">
                    Offer routed · awaiting Offer Discussion Team
                  </p>
                  <h3 className="text-base font-semibold text-emerald-900 mt-1">
                    Your offer decision has been recorded ✓
                  </h3>
                  <div className="mt-3 grid md:grid-cols-2 gap-3 text-xs text-emerald-900">
                    <div>
                      <p className="font-semibold uppercase tracking-wider text-[10px] mb-1">
                        What's happening now
                      </p>
                      <p>
                        The Offer Discussion Team has been notified. They are
                        preparing the offer letter and will negotiate CTC,
                        joining date, and location with the candidate.
                      </p>
                    </div>
                    <div>
                      <p className="font-semibold uppercase tracking-wider text-[10px] mb-1">
                        What happens next
                      </p>
                      <p>
                        Once the candidate accepts the final terms, the
                        application moves to <strong>Offer extended</strong>{" "}
                        and the agent emails onboarding instructions. You'll
                        see the timeline update on this page.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Final offer-extended confirmation. */}
              {app.stage === "offer" && (
                <div className="mt-4 p-4 rounded-card border-2 border-emerald-400 bg-emerald-50">
                  <p className="text-[10px] uppercase tracking-widest text-emerald-800 font-bold">
                    Offer extended 🎉
                  </p>
                  <h3 className="text-base font-semibold text-emerald-900 mt-1">
                    The candidate has accepted the offer
                  </h3>
                  <p className="mt-2 text-xs text-emerald-900">
                    Onboarding emails have been sent. The application is
                    closed in this funnel — the requisition is filled.
                  </p>
                </div>
              )}

              {/* Closed / rejected confirmation. */}
              {app.stage === "rejected" && (
                <div className="mt-4 p-4 rounded-card border-2 border-axis-magenta bg-axis-pink-soft">
                  <p className="text-[10px] uppercase tracking-widest text-axis-burgundy font-bold">
                    Application closed
                  </p>
                  <h3 className="text-base font-semibold text-axis-burgundy mt-1">
                    Regret communication has been sent
                  </h3>
                  <p className="mt-2 text-xs text-axis-burgundy">
                    The candidate has been informed via email. The
                    application is removed from the active funnel and
                    archived.
                  </p>
                </div>
              )}

              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  onClick={() => {
                    setActionError(null);
                    setPendingUnblock(true);
                  }}
                  disabled={acting}
                  className="px-3 py-1.5 text-xs rounded border border-axis-magenta text-axis-magenta hover:bg-axis-pink-soft disabled:opacity-40"
                  title="Re-poke the orchestrator. Idempotent — safe to spam."
                >
                  {acting ? "Working…" : "Unblock agent"}
                </button>
                <button
                  onClick={() => {
                    refresh();
                    refreshActivity();
                  }}
                  className="px-3 py-1.5 text-xs rounded border border-axis-divider text-axis-ink-soft hover:bg-axis-surface"
                >
                  Refresh
                </button>
                <Link
                  href={`/hr/jobs/${app.job_id}`}
                  className="px-3 py-1.5 text-xs rounded border border-axis-divider text-axis-ink-soft hover:bg-axis-surface"
                >
                  Edit JD checklist template
                </Link>
              </div>

              {actionError && (
                <p className="mt-2 text-xs text-axis-burgundy">{actionError}</p>
              )}
            </div>

            {/* Intake screening review — shown when the AI screening
                rubric came in below the JD threshold and the orchestrator
                is parked waiting for HR to advance or regret. The
                orchestrator never auto-rejects on a screening score, so
                this card is the single human gate at intake. */}
            {needsScreeningReview && job && (
              <div className="mt-4 bg-axis-canvas border-2 border-axis-magenta rounded-card p-6 shadow-card">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold">
                      AI screening · review needed
                    </p>
                    <h2 className="text-lg font-display text-axis-ink mt-1">
                      Candidate scored {app.match_percent.toFixed(0)}% on the
                      JD rubric (threshold {job.shortlist_threshold.toFixed(0)}%)
                    </h2>
                    <p className="text-xs text-axis-ink-soft mt-1">
                      The agent has paused at intake — per the human-in-the-loop
                      rule it never auto-rejects an internal candidate. Review
                      the rubric below, then either Advance to push the
                      candidate into Round 1 anyway, or Regret to close the
                      application with the standard regret email.
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <span className="text-2xl font-display text-axis-ink">
                      {app.match_percent.toFixed(0)}
                      <span className="text-sm text-axis-muted">/100</span>
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded uppercase tracking-wider font-bold bg-amber-100 text-amber-800">
                      below threshold
                    </span>
                  </div>
                </div>

                {app.match_rationale && (
                  <p className="mt-4 text-xs text-axis-ink-soft italic">
                    {app.match_rationale}
                  </p>
                )}

                <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                      Matched skills ({app.matched_skills.length})
                    </p>
                    {app.matched_skills.length > 0 ? (
                      <ul className="mt-1 list-disc list-inside text-xs text-axis-ink-soft space-y-0.5">
                        {app.matched_skills.map((s) => (
                          <li key={s}>{s}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-1 text-xs text-axis-muted-light italic">
                        None
                      </p>
                    )}
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-axis-burgundy font-semibold">
                      Missing skills ({app.missing_skills.length})
                    </p>
                    {app.missing_skills.length > 0 ? (
                      <ul className="mt-1 list-disc list-inside text-xs text-axis-burgundy space-y-0.5">
                        {app.missing_skills.map((s) => (
                          <li key={s}>{s}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-1 text-xs text-axis-muted-light italic">
                        None
                      </p>
                    )}
                  </div>
                </div>

                <div className="mt-5 pt-4 border-t border-axis-divider">
                  <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                    Your decision
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <input
                      type="text"
                      value={screeningReason}
                      onChange={(e) => setScreeningReason(e.target.value)}
                      placeholder="Optional note (audit trail)"
                      className="flex-1 min-w-[240px] text-xs px-3 py-1.5 rounded border border-axis-divider bg-axis-canvas"
                    />
                    <button
                      onClick={() => decideScreening("advance")}
                      disabled={screeningActing !== null}
                      className="px-3 py-1.5 text-xs rounded border border-axis-magenta bg-axis-magenta text-white hover:opacity-90 disabled:opacity-40"
                    >
                      {screeningActing === "advance"
                        ? "Advancing…"
                        : "Advance to Round 1"}
                    </button>
                    <button
                      onClick={() => decideScreening("regret")}
                      disabled={screeningActing !== null}
                      className="px-3 py-1.5 text-xs rounded border border-axis-burgundy text-axis-burgundy hover:bg-axis-pink-soft disabled:opacity-40"
                    >
                      {screeningActing === "regret"
                        ? "Sending regret…"
                        : "Regret candidate"}
                    </button>
                  </div>
                  {screeningError && (
                    <p className="mt-2 text-xs text-axis-burgundy">
                      {screeningError}
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* R1 AI Interview review panel — shown when HR is the gate
                between the AI Round 1 interview result and Round 2. The
                orchestrator no longer auto-rejects on score; HR reads the
                AI's full analysis + transcript and decides Advance vs Regret. */}
            {needsR2Approval && r1 && (
              <div className="mt-4 bg-axis-canvas border-2 border-axis-magenta rounded-card p-6 shadow-card">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold">
                      Round 1 AI Interview · review needed
                    </p>
                    <h2 className="text-lg font-display text-axis-ink mt-1">
                      {r1.report?.headline ||
                        `AI Interviewer scored this candidate ${(r1.score ?? 0).toFixed(0)}/100`}
                    </h2>
                    {r1.report?.headline_hi &&
                      r1Lang !== "en" &&
                      (r1.report.transcript_language === "hi" ||
                        r1.report.transcript_language === "hi-en") && (
                        <h2
                          lang="hi"
                          className="text-base font-display text-axis-burgundy mt-1"
                        >
                          {r1.report.headline_hi}
                        </h2>
                      )}
                    <p className="text-xs text-axis-ink-soft mt-1">
                      The AI Interviewer Agent has finished Round 1 and is
                      waiting for your decision. Read the transcript and the
                      AI's structured analysis below, then advance to R2 or
                      regret the candidate.
                    </p>
                    {(r1.report?.transcript_language === "hi" ||
                      r1.report?.transcript_language === "hi-en") && (
                      <div
                        className="mt-2 inline-flex items-center gap-1 bg-axis-cream/60 border border-axis-cream-border rounded px-2 py-1 text-[10px]"
                        role="group"
                        aria-label="Analysis language"
                      >
                        <span className="text-axis-ink-soft uppercase tracking-wider font-semibold mr-1">
                          {r1.report.transcript_language === "hi"
                            ? "Candidate spoke Hindi"
                            : "Candidate code-switched (Hindi + English)"}{" "}
                          · Show analysis in:
                        </span>
                        {(["en", "hi", "both"] as const).map((opt) => (
                          <button
                            key={opt}
                            type="button"
                            onClick={() => setR1Lang(opt)}
                            className={`px-2 py-0.5 rounded font-bold uppercase tracking-wider ${
                              r1Lang === opt
                                ? "bg-axis-burgundy text-white"
                                : "text-axis-ink-soft hover:bg-axis-cream"
                            }`}
                            aria-pressed={r1Lang === opt}
                          >
                            {opt === "en"
                              ? "English"
                              : opt === "hi"
                              ? "हिंदी"
                              : "Both"}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <span className="text-2xl font-display text-axis-ink">
                      {(r1.score ?? r1.report?.overall_score ?? 0).toFixed(0)}
                      <span className="text-sm text-axis-muted">/100</span>
                    </span>
                    {r1.report?.recommendation && (
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded uppercase tracking-wider font-bold ${
                          r1.report.recommendation === "advance"
                            ? "bg-emerald-100 text-emerald-800"
                            : r1.report.recommendation === "borderline"
                            ? "bg-amber-100 text-amber-800"
                            : "bg-axis-pink-soft text-axis-burgundy"
                        }`}
                      >
                        AI: {r1.report.recommendation}
                      </span>
                    )}
                  </div>
                </div>

                {/* Rubric breakdown */}
                {r1.report?.rubric_scores &&
                  Object.keys(r1.report.rubric_scores).length > 0 && (
                    <div className="mt-4">
                      <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                        Rubric breakdown
                      </p>
                      <div className="mt-2 space-y-1.5">
                        {Object.entries(r1.report.rubric_scores).map(
                          ([skill, val]) => {
                            const pct = Math.max(
                              0,
                              Math.min(100, Number(val) || 0),
                            );
                            return (
                              <div key={skill}>
                                <div className="flex items-center justify-between text-[11px]">
                                  <span className="text-axis-ink-soft">
                                    {skill}
                                  </span>
                                  <span className="text-axis-ink font-semibold">
                                    {pct.toFixed(0)}%
                                  </span>
                                </div>
                                <div className="h-1.5 bg-axis-surface rounded mt-0.5 overflow-hidden">
                                  <div
                                    className="h-full bg-axis-magenta"
                                    style={{ width: `${pct}%` }}
                                  />
                                </div>
                              </div>
                            );
                          },
                        )}
                      </div>
                    </div>
                  )}

                {/* Key findings — structured findings from Claude scorer.
                    Each finding has type (critical/concern/strength),
                    evidence from the transcript, and impact assessment. */}
                {r1.report?.key_findings && r1.report.key_findings.length > 0 && (
                  <div className="mt-4">
                    <p className="text-[10px] uppercase tracking-wider text-axis-burgundy font-semibold mb-2">
                      Key Findings
                    </p>
                    <div className="space-y-2">
                      {(r1.report.key_findings as any[]).map((kf: any, i: number) => {
                        const badge =
                          kf.type === "critical"
                            ? "border-l-axis-burgundy bg-axis-pink-soft"
                            : kf.type === "concern"
                            ? "border-l-amber-500 bg-amber-50"
                            : "border-l-emerald-500 bg-emerald-50";
                        const label =
                          kf.type === "critical"
                            ? "Critical"
                            : kf.type === "concern"
                            ? "Concern"
                            : "Strength";
                        return (
                          <div
                            key={i}
                            className={`border-l-4 rounded p-2.5 ${badge}`}
                          >
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-[9px] uppercase tracking-wider font-bold text-axis-ink-soft">
                                {label}
                              </span>
                            </div>
                            <p className="text-xs text-axis-ink font-medium">
                              {kf.finding}
                            </p>
                            {kf.evidence && (
                              <p className="text-[11px] text-axis-muted italic mt-1">
                                &ldquo;{kf.evidence}&rdquo;
                              </p>
                            )}
                            {kf.impact && (
                              <p className="text-[11px] text-axis-ink-soft mt-1">
                                {kf.impact}
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Red flags — bilingual when the candidate spoke Hindi.
                    Each English bullet is paired with the matching Hindi
                    translation from the Claude scorer (`red_flags_hi[i]`).
                    Pure-English R1s skip the Hindi block entirely. */}
                {r1.report?.red_flags && r1.report.red_flags.length > 0 && (
                  <div className="mt-4">
                    <p className="text-[10px] uppercase tracking-wider text-axis-burgundy font-semibold">
                      Red flags
                    </p>
                    <ul className="mt-1 space-y-1.5 text-xs text-axis-burgundy">
                      {r1.report.red_flags.map((rf, i) => {
                        const hi = r1.report?.red_flags_hi?.[i];
                        return (
                          <li key={i} className="list-disc list-inside">
                            {r1Lang !== "hi" && <span>{rf}</span>}
                            {hi && r1Lang !== "en" && (
                              <p
                                lang="hi"
                                className={`text-axis-burgundy/85 ${
                                  r1Lang === "both" ? "mt-0.5 ml-4 italic" : ""
                                }`}
                              >
                                {hi}
                              </p>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}

                {/* Recommended probes for R2 — same bilingual pattern as
                    red flags. The English ordering is authoritative; the
                    Hindi list mirrors the same order from Claude. */}
                {r1.report?.recommended_probes &&
                  r1.report.recommended_probes.length > 0 && (
                    <div className="mt-4">
                      <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                        Recommended probes for Round 2
                      </p>
                      <ul className="mt-1 space-y-1.5 text-xs text-axis-ink-soft">
                        {r1.report.recommended_probes.map((p, i) => {
                          const hi = r1.report?.recommended_probes_hi?.[i];
                          return (
                            <li key={i} className="list-disc list-inside">
                              {r1Lang !== "hi" && <span>{p}</span>}
                              {hi && r1Lang !== "en" && (
                                <p
                                  lang="hi"
                                  className={`text-axis-ink-soft ${
                                    r1Lang === "both"
                                      ? "mt-0.5 ml-4 italic"
                                      : ""
                                  }`}
                                >
                                  {hi}
                                </p>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  )}

                {/* Transcript Q&A pairs (foldable) */}
                {r1Transcript.length > 0 && (
                  <div className="mt-4">
                    <button
                      type="button"
                      onClick={() => setShowR1Transcript((v) => !v)}
                      className="text-[11px] uppercase tracking-wider text-axis-magenta font-semibold hover:underline"
                    >
                      {showR1Transcript ? "▼" : "▶"} Full transcript (
                      {r1Transcript.length} segments)
                    </button>
                    {showR1Transcript && (
                      <div className="mt-2 max-h-72 overflow-y-auto border border-axis-divider rounded p-3 bg-axis-surface/40 space-y-2">
                        {r1Transcript.map((seg, i) => (
                          <div key={i} className="text-xs">
                            <span
                              className={`font-semibold uppercase tracking-wider text-[9px] ${
                                seg.speaker === "interviewer"
                                  ? "text-axis-magenta"
                                  : "text-axis-ink"
                              }`}
                            >
                              {seg.speaker === "interviewer"
                                ? "AI Interviewer"
                                : "Candidate"}
                            </span>
                            <p className="text-axis-ink-soft">{seg.text}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Proctoring alerts from R1 AI interview */}
                {(() => {
                  const violations =
                    r1?.report?.proctoring_violations ?? r1?.proctoring_violations ?? [];
                  if (violations.length === 0) return null;
                  const critical = violations.filter(
                    (v: any) => v.severity === "critical",
                  );
                  const warnings = violations.filter(
                    (v: any) => v.severity === "warning",
                  );
                  return (
                    <div className="mt-4">
                      <p className="text-[10px] uppercase tracking-wider text-axis-burgundy font-semibold">
                        Proctoring alerts ({violations.length})
                      </p>
                      <p className="text-[11px] text-axis-ink-soft mt-1 mb-2">
                        The AI proctoring system flagged the following
                        incidents during Round 1. Critical alerts indicate
                        potential integrity violations.
                      </p>
                      {critical.length > 0 && (
                        <div className="mb-2">
                          <p className="text-[10px] uppercase tracking-wider text-axis-burgundy font-bold mb-1">
                            Critical ({critical.length})
                          </p>
                          <ul className="space-y-1">
                            {critical.map((v: any, i: number) => (
                              <li
                                key={`crit-${i}`}
                                className="flex items-start gap-2 text-xs border border-axis-magenta bg-axis-pink-soft rounded p-2"
                              >
                                <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] uppercase font-bold bg-axis-burgundy text-white">
                                  {v.type.replace(/_/g, " ")}
                                </span>
                                <span className="text-axis-burgundy">
                                  {v.details || v.type.replace(/_/g, " ")} — Q
                                  {(v.question_index ?? 0) + 1} at{" "}
                                  {new Date(v.timestamp).toLocaleTimeString()}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {warnings.length > 0 && (
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-amber-700 font-bold mb-1">
                            Warnings ({warnings.length})
                          </p>
                          <ul className="space-y-1">
                            {warnings.map((v: any, i: number) => (
                              <li
                                key={`warn-${i}`}
                                className="flex items-start gap-2 text-xs border border-amber-300 bg-amber-50 rounded p-2"
                              >
                                <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] uppercase font-bold bg-amber-600 text-white">
                                  {v.type.replace(/_/g, " ")}
                                </span>
                                <span className="text-amber-800">
                                  {v.details || v.type.replace(/_/g, " ")} — Q
                                  {(v.question_index ?? 0) + 1} at{" "}
                                  {new Date(v.timestamp).toLocaleTimeString()}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* Regret CTA — Advance is handled by the R2 panel approval
                    block immediately below this card. */}
                <div className="mt-5 pt-4 border-t border-axis-divider">
                  <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                    Don't want to advance this candidate?
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <input
                      type="text"
                      value={r1RegretReason}
                      onChange={(e) => setR1RegretReason(e.target.value)}
                      placeholder="Reason for regret (optional)"
                      className="flex-1 min-w-[240px] text-xs px-3 py-1.5 rounded border border-axis-divider bg-axis-canvas"
                    />
                    <button
                      onClick={regretR1}
                      disabled={r1Regretting}
                      className="px-3 py-1.5 text-xs rounded border border-axis-burgundy text-axis-burgundy hover:bg-axis-pink-soft disabled:opacity-40"
                    >
                      {r1Regretting ? "Sending regret…" : "Regret candidate"}
                    </button>
                  </div>
                  {r1RegretError && (
                    <p className="mt-2 text-xs text-axis-burgundy">
                      {r1RegretError}
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Visible processing banner: between "Approve R2 and notify
                panel" click and the orchestrator finishing the calendar
                intersect / Teams invite work, the page used to silently
                sit on the old waiting_hr state for several seconds. The
                user couldn't tell anything was happening. This banner
                stays on screen the whole time the approveR2 call is in
                flight AND covers the brief gap before the polled
                application data flips to waiting_candidate. */}
            {approving && (
              <div
                role="status"
                aria-live="polite"
                className="mt-4 bg-axis-pink-soft border-2 border-axis-magenta rounded-card p-5 shadow-card flex items-start gap-3"
              >
                <span className="inline-block w-5 h-5 rounded-full border-2 border-axis-magenta border-t-transparent animate-spin shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold">
                    Working on it…
                  </p>
                  <p className="text-sm font-display text-axis-ink mt-1">
                    Approving Round 2 and notifying the panel
                  </p>
                  <p className="text-xs text-axis-ink-soft mt-1">
                    The agent is intersecting calendars across the candidate,
                    you and every panel member, generating 3 candidate-friendly
                    R2 slots, and emailing them to the candidate. This usually
                    takes a few seconds — the page will refresh automatically
                    the moment the candidate is notified.
                  </p>
                </div>
              </div>
            )}

            {/* DESIGN-001: R2 approval prompt — prominent CTA that replaces
                the legacy pre-r2-2 checklist tick. */}
            {needsR2Approval && !approving && (
              <div className="mt-4 bg-axis-pink-soft border-2 border-axis-magenta rounded-card p-6 shadow-card">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold">
                      Action needed — Business Partner approval
                    </p>
                    <h2 className="text-lg font-display text-axis-ink mt-1">
                      Approve this candidate for Round 2 and pick a panel
                    </h2>
                    <p className="text-xs text-axis-ink-soft mt-1">
                      The agent is paused waiting for your approval. Select the
                      panel that should run R2 — the system will intersect their
                      calendars with the candidate and propose 3 slots.
                    </p>
                  </div>
                </div>

                {panelsError && (
                  <p className="mt-3 text-xs text-axis-burgundy">
                    Could not load panels: {panelsError}
                  </p>
                )}

                {availablePanels === null && !panelsError && (
                  <p className="mt-3 text-xs text-axis-muted">Loading panels…</p>
                )}

                {availablePanels && availablePanels.length === 0 && (
                  <p className="mt-3 text-xs text-axis-burgundy">
                    No panels match this JD's function/band. Configure one under{" "}
                    <Link href="/hr/admin/panels" className="underline">
                      Panel Configurations
                    </Link>
                    .
                  </p>
                )}

                {availablePanels && availablePanels.length > 0 && (
                  <div className="mt-4 space-y-2">
                    {availablePanels.map((p) => (
                      <label
                        key={p.id}
                        className={`block border rounded-card p-3 cursor-pointer transition ${
                          selectedPanelId === p.id
                            ? "border-axis-magenta bg-axis-canvas"
                            : "border-axis-divider bg-axis-canvas/60 hover:bg-axis-canvas"
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          <input
                            type="radio"
                            name="r2-panel"
                            checked={selectedPanelId === p.id}
                            onChange={() => setSelectedPanelId(p.id)}
                            className="mt-1"
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-sm font-semibold text-axis-ink">
                                {p.name}
                              </span>
                              {p.location && (
                                <span className="text-[10px] text-axis-muted">
                                  {p.location}
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-axis-ink-soft mt-0.5">
                              {p.members.map((m) => m.name).join(", ")}
                            </p>
                            {p.role_scopes.length > 0 && (
                              <div className="mt-1 flex flex-wrap gap-1">
                                {p.role_scopes.map((s) => (
                                  <span
                                    key={s}
                                    className="text-[9px] px-1.5 py-0.5 rounded bg-axis-cream text-axis-ink-soft"
                                  >
                                    {s}
                                  </span>
                                ))}
                              </div>
                            )}
                            {/* BUG-010: per-panel slot preview chips. Live
                                free/busy intersection across candidate + HR
                                + panel members so HR can compare panels by
                                actual availability before approving. */}
                            <div className="mt-2">
                              <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                                Candidate slot preview
                              </p>
                              {(() => {
                                if (slotsLoading && !slotsByPanel) {
                                  return (
                                    <p className="text-[11px] text-axis-muted mt-1">
                                      Checking calendars…
                                    </p>
                                  );
                                }
                                const entry = slotsByPanel?.find(
                                  (e) => e.panel_id === p.id,
                                );
                                if (!entry) {
                                  return (
                                    <p className="text-[11px] text-axis-muted mt-1">
                                      —
                                    </p>
                                  );
                                }
                                if (entry.error) {
                                  return (
                                    <p className="text-[11px] text-axis-burgundy mt-1">
                                      Calendar lookup failed: {entry.error}
                                    </p>
                                  );
                                }
                                if (entry.slots.length === 0) {
                                  return (
                                    <p className="text-[11px] text-axis-burgundy mt-1">
                                      No common slots in the next 5 working days.
                                    </p>
                                  );
                                }
                                return (
                                  <div className="mt-1 flex flex-wrap gap-1">
                                    {entry.slots.map((s) => {
                                      const start = new Date(s.start);
                                      const end = new Date(s.end);
                                      const label = `${start.toLocaleDateString(
                                        "en-IN",
                                        {
                                          weekday: "short",
                                          day: "2-digit",
                                          month: "short",
                                        },
                                      )} · ${start.toLocaleTimeString("en-IN", {
                                        hour: "2-digit",
                                        minute: "2-digit",
                                        hour12: false,
                                      })}–${end.toLocaleTimeString("en-IN", {
                                        hour: "2-digit",
                                        minute: "2-digit",
                                        hour12: false,
                                      })}`;
                                      return (
                                        <span
                                          key={s.start}
                                          className="text-[10px] px-1.5 py-0.5 rounded border border-axis-divider bg-axis-canvas text-axis-ink-soft"
                                        >
                                          {label}
                                        </span>
                                      );
                                    })}
                                  </div>
                                );
                              })()}
                            </div>
                          </div>
                        </div>
                      </label>
                    ))}

                    <div className="pt-2 flex items-center gap-3">
                      <button
                        onClick={() => {
                          setActionError(null);
                          setPendingApprove(true);
                        }}
                        disabled={approving || !selectedPanelId}
                        className="px-4 py-2 text-xs font-semibold rounded bg-axis-magenta text-white hover:bg-axis-burgundy disabled:opacity-40"
                      >
                        {approving
                          ? "Approving…"
                          : "Approve R2 and notify panel"}
                      </button>
                      <Link
                        href="/hr/admin/panels"
                        className="text-xs text-axis-magenta hover:underline"
                      >
                        Manage panels
                      </Link>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* BUG-015: post-approval waiting-for-candidate status panel.
                Once HR has approved R2 the bright pink approval card hides
                itself, so without this strip the page silently goes blank
                and HR has no idea the orchestrator is now waiting for the
                candidate to pick a slot from Thrive. */}
            {app.stage === "r1_done" &&
              !!app.selected_r2_panel_id &&
              app.agent_status === "waiting_candidate" && (
                <div className="mt-4 bg-axis-canvas border border-axis-magenta rounded-card p-5 shadow-card">
                  <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold">
                    R2 approved · waiting for candidate
                  </p>
                  <h2 className="text-base font-display text-axis-ink mt-1">
                    Candidate must pick an R2 slot from Thrive
                  </h2>
                  <p className="text-xs text-axis-ink-soft mt-1">
                    You approved this candidate for Round 2 with{" "}
                    <strong>
                      {availablePanels?.find(
                        (p) => p.id === app.selected_r2_panel_id,
                      )?.name || app.selected_r2_panel_id}
                    </strong>
                    . The agent has emailed the candidate the 3 slots below
                    and is now waiting for them to confirm one from{" "}
                    <strong>Thrive → My Applications</strong>. Once they pick,
                    the agent will lock all three diaries (candidate + you +
                    panel members) with a Teams invite.
                  </p>
                  {app.proposed_r2_slots && app.proposed_r2_slots.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {app.proposed_r2_slots.map((s) => {
                        const start = new Date(s.start);
                        const end = new Date(s.end);
                        const label = `${start.toLocaleDateString("en-IN", {
                          weekday: "short",
                          day: "2-digit",
                          month: "short",
                        })} · ${start.toLocaleTimeString("en-IN", {
                          hour: "2-digit",
                          minute: "2-digit",
                          hour12: false,
                        })}–${end.toLocaleTimeString("en-IN", {
                          hour: "2-digit",
                          minute: "2-digit",
                          hour12: false,
                        })} IST`;
                        return (
                          <span
                            key={s.start}
                            className="text-[11px] px-2 py-1 rounded border border-axis-divider bg-axis-surface text-axis-ink-soft"
                          >
                            {label}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

            {/* R2 HR review — shown once every panellist has voted. HR
                reads the transcript + each panellist's feedback, optionally
                runs the Claude AI review, then clicks Make offer / Reject. */}
            {needsR2Decision && r2 && (
              <div className="mt-4 bg-axis-canvas border-2 border-axis-magenta rounded-card shadow-card p-6">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold">
                      Action needed — final R2 decision
                    </p>
                    <h2 className="text-lg font-display text-axis-ink mt-1">
                      Panel voting complete — make the final call
                    </h2>
                    <p className="text-xs text-axis-ink-soft mt-1">
                      Every panellist has submitted their feedback
                      {expectedPanelSize
                        ? ` (${r2.panel_feedback.length}/${expectedPanelSize})`
                        : ` (${r2.panel_feedback.length} vote${
                            r2.panel_feedback.length === 1 ? "" : "s"
                          })`}
                      . Read each vote below and, if you want a second
                      opinion, run the AI review of the same transcript for
                      comparison before deciding.
                    </p>
                  </div>
                </div>

                {/* Panel feedback cards */}
                <div className="mt-4 space-y-2">
                  <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                    Panel feedback
                  </p>
                  {r2.panel_feedback.map((f) => {
                    const aiRec = aiRecs[f.panellist_id];
                    const isAnalysing = analysingId === f.panellist_id;
                    const aiErr = analyseErrors[f.panellist_id];
                    const agree =
                      aiRec &&
                      aiRec.suggested_recommendation === f.recommendation;
                    const ownTranscript = transcriptForPanellist(f.panellist_id);
                    return (
                      <div
                        key={f.panellist_id}
                        className="border border-axis-divider rounded p-3 bg-axis-surface/30"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-semibold text-axis-ink">
                            {f.panellist_name}
                          </span>
                          <span
                            className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded ${
                              f.recommendation === "strong_hire"
                                ? "bg-axis-cream text-axis-ink"
                                : f.recommendation === "hire"
                                ? "bg-axis-surface text-axis-ink"
                                : "bg-axis-pink-soft text-axis-burgundy"
                            }`}
                          >
                            {f.recommendation.replace("_", " ")} ·{" "}
                            {Math.round(f.score)}/100
                          </span>
                        </div>
                        <p className="text-xs text-axis-ink-soft mt-2">
                          <strong className="text-axis-ink">Strengths:</strong>{" "}
                          {f.strengths || "—"}
                        </p>
                        <p className="text-xs text-axis-ink-soft mt-1">
                          <strong className="text-axis-ink">Concerns:</strong>{" "}
                          {f.concerns || "—"}
                        </p>
                        <p className="text-[10px] text-axis-muted mt-1">
                          Submitted {new Date(f.submitted_at).toLocaleString()}
                        </p>

                        {/* Per-panellist AI second opinion */}
                        <div className="mt-3 border-t border-axis-divider pt-3">
                          <div className="flex items-center justify-between gap-3 flex-wrap">
                            <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-bold">
                              AI second opinion · {f.panellist_name}
                            </p>
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() =>
                                  runAiForPanellist(f.panellist_id, false)
                                }
                                disabled={isAnalysing || !ownTranscript}
                                className="px-3 py-1.5 text-[11px] font-semibold rounded bg-axis-magenta text-white hover:bg-axis-burgundy disabled:opacity-40"
                              >
                                {isAnalysing
                                  ? "AI is reading…"
                                  : aiRec
                                  ? "AI review ready"
                                  : "Run AI review"}
                              </button>
                              {aiRec && !isAnalysing && (
                                <button
                                  onClick={() =>
                                    runAiForPanellist(f.panellist_id, true)
                                  }
                                  className="px-2 py-1.5 text-[11px] rounded border border-axis-divider text-axis-ink-soft hover:bg-axis-surface"
                                >
                                  Re-run
                                </button>
                              )}
                            </div>
                          </div>
                          {!ownTranscript && (
                            <p className="mt-1 text-[10px] text-axis-muted italic">
                              No 1-on-1 transcript on file for this panellist
                              yet — once {f.panellist_name}'s Teams meeting
                              concludes, the transcript will appear here.
                            </p>
                          )}
                          {ownTranscript && (
                            <details className="mt-2">
                              <summary className="text-[10px] text-axis-magenta cursor-pointer hover:underline">
                                Show {f.panellist_name}'s 1-on-1 transcript
                              </summary>
                              <pre className="mt-1 w-full border border-axis-divider rounded px-2 py-1.5 text-[10px] font-mono text-axis-ink whitespace-pre-wrap max-h-60 overflow-y-auto bg-axis-surface/40">
                                {ownTranscript}
                              </pre>
                            </details>
                          )}
                          {aiErr && (
                            <p className="mt-2 text-[11px] text-axis-burgundy">
                              AI review failed: {aiErr}
                            </p>
                          )}
                          {isAnalysing && !aiRec && (
                            <div className="mt-2 flex items-center gap-2 text-[11px] text-axis-muted">
                              <span className="inline-block w-2 h-2 rounded-full bg-axis-magenta animate-pulse" />
                              The agent is comparing {f.panellist_name}'s
                              vote against the shared transcript…
                            </div>
                          )}
                          {aiRec && (
                            <div className="mt-3 border border-axis-magenta rounded p-3 bg-axis-pink-soft/30">
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                  <p className="text-[9px] uppercase tracking-widest text-axis-magenta font-bold">
                                    AI review · for Business Partner only
                                  </p>
                                  <h4 className="text-[13px] font-semibold text-axis-ink mt-0.5">
                                    {aiRec.headline}
                                  </h4>
                                </div>
                                <div className="flex flex-col items-end gap-0.5 shrink-0">
                                  <span
                                    className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                                      aiRec.suggested_recommendation ===
                                      "strong_hire"
                                        ? "bg-axis-cream text-axis-ink"
                                        : aiRec.suggested_recommendation ===
                                          "hire"
                                        ? "bg-axis-surface text-axis-ink"
                                        : "bg-axis-pink-soft text-axis-burgundy"
                                    }`}
                                  >
                                    {aiRec.suggested_recommendation.replace(
                                      "_",
                                      " ",
                                    )}
                                  </span>
                                  <span className="text-[10px] text-axis-ink-soft">
                                    {Math.round(aiRec.suggested_score)}/100
                                  </span>
                                  <span
                                    className={`text-[9px] font-semibold px-1.5 py-0.5 rounded ${
                                      agree
                                        ? "bg-axis-cream text-axis-ink"
                                        : "bg-axis-burgundy text-white"
                                    }`}
                                  >
                                    {agree
                                      ? "Agrees with panellist"
                                      : "Disagrees with panellist"}
                                  </span>
                                  <span className="text-[9px] uppercase tracking-widest text-axis-muted">
                                    {aiRec.source === "claude"
                                      ? "AI review"
                                      : "Offline fallback"}
                                  </span>
                                </div>
                              </div>
                              {aiRec.summary && (
                                <p className="text-[11px] text-axis-ink-soft mt-2">
                                  {aiRec.summary}
                                </p>
                              )}
                              <div className="grid md:grid-cols-2 gap-3 mt-3">
                                {aiRec.strengths.length > 0 && (
                                  <div>
                                    <p className="text-[9px] uppercase tracking-wider text-axis-muted font-semibold">
                                      Strengths
                                    </p>
                                    <ul className="mt-1 text-[11px] text-axis-ink-soft list-disc list-inside space-y-0.5">
                                      {aiRec.strengths.map((s, i) => (
                                        <li key={i}>{s}</li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                                {aiRec.concerns.length > 0 && (
                                  <div>
                                    <p className="text-[9px] uppercase tracking-wider text-axis-muted font-semibold">
                                      Concerns
                                    </p>
                                    <ul className="mt-1 text-[11px] text-axis-burgundy list-disc list-inside space-y-0.5">
                                      {aiRec.concerns.map((c, i) => (
                                        <li key={i}>{c}</li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </div>
                              {aiRec.evidence.length > 0 && (
                                <div className="mt-3">
                                  <p className="text-[9px] uppercase tracking-wider text-axis-muted font-semibold">
                                    Evidence from the transcript
                                  </p>
                                  <ul className="mt-1.5 space-y-1.5">
                                    {aiRec.evidence.map((e, i) => (
                                      <li
                                        key={i}
                                        className="border-l-2 border-axis-magenta pl-2 text-[11px]"
                                      >
                                        <p className="italic text-axis-ink">
                                          "{e.quote}"
                                        </p>
                                        <p className="text-[9px] text-axis-muted mt-0.5">
                                          {e.speaker} — {e.why_it_matters}
                                        </p>
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              <p className="mt-2 text-[9px] text-axis-muted italic">
                                Advisory only — final call is yours.
                              </p>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Per-panellist transcripts now live inside each
                    panellist's feedback card above (each interviewer ran
                    their own 1-on-1 with the candidate). */}
                <div className="mt-4">
                  <p className="text-[10px] text-axis-muted italic">
                    Each panellist met the candidate 1-on-1 — open the
                    transcript inside their card to see what they discussed.
                  </p>
                  {!r2Transcript && (
                    <p className="mt-1 text-[11px] text-axis-muted italic">
                      No transcript on file yet.
                    </p>
                  )}
                </div>

                {/* Per-panellist AI second opinions are rendered inline
                    inside each panel feedback card above. */}

                {/* Decision buttons */}
                <div className="mt-5 border-t border-axis-divider pt-4">
                  <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                    Your final decision
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <button
                      onClick={() => setPendingDecision("offer")}
                      disabled={finalising}
                      className="px-4 py-2 text-xs font-semibold rounded bg-axis-magenta text-white hover:bg-axis-burgundy disabled:opacity-40"
                    >
                      Make offer
                    </button>
                    <button
                      onClick={() => setPendingDecision("reject")}
                      disabled={finalising}
                      className="px-4 py-2 text-xs font-semibold rounded border border-axis-burgundy text-axis-burgundy hover:bg-axis-pink-soft disabled:opacity-40"
                    >
                      Reject
                    </button>
                    {finalising && (
                      <span className="text-xs text-axis-muted">
                        Finalising…
                      </span>
                    )}
                  </div>
                  {finaliseError && (
                    <p className="mt-2 text-xs text-axis-burgundy">
                      {finaliseError}
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Tabs */}
            <div className="mt-6 border-b border-axis-divider flex gap-4">
              {(
                ["overview", "checklists", "transcript", "activity", "audit"] as Tab[]
              ).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`text-xs font-semibold uppercase tracking-wider py-2 border-b-2 ${
                    tab === t
                      ? "border-axis-magenta text-axis-magenta"
                      : "border-transparent text-axis-muted"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>

            <div className="mt-4">
              {tab === "overview" && (
                <div className="bg-axis-canvas border border-axis-divider rounded-card p-5 text-sm space-y-3">
                  <div>
                    <p className="text-xs uppercase text-axis-muted font-semibold">
                      Match rationale
                    </p>
                    <p className="text-axis-ink-soft mt-1">
                      {app.match_rationale}
                    </p>
                  </div>
                  <div className="grid md:grid-cols-2 gap-4">
                    <div>
                      <p className="text-xs uppercase text-axis-muted font-semibold">
                        Matched skills
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {app.matched_skills.map((s) => (
                          <span
                            key={s}
                            className="text-[10px] px-2 py-0.5 bg-axis-cream rounded"
                          >
                            {s}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div>
                      <p className="text-xs uppercase text-axis-muted font-semibold">
                        Missing skills
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {app.missing_skills.map((s) => (
                          <span
                            key={s}
                            className="text-[10px] px-2 py-0.5 bg-axis-pink-soft text-axis-burgundy rounded"
                          >
                            {s}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                  {r1?.score != null && (
                    <div>
                      <p className="text-xs uppercase text-axis-muted font-semibold">
                        R1 score
                      </p>
                      <p className="text-axis-ink mt-1 text-lg font-semibold">
                        {r1.score}/100
                      </p>
                      {r1.rationale && (
                        <p className="text-axis-ink-soft text-xs mt-1">
                          {r1.rationale}
                        </p>
                      )}
                    </div>
                  )}
                  {/* Proctoring alerts summary in overview tab */}
                  {(() => {
                    const violations =
                      r1?.report?.proctoring_violations ?? r1?.proctoring_violations ?? [];
                    if (violations.length === 0) return null;
                    const critical = violations.filter((v: any) => v.severity === "critical");
                    return (
                      <div>
                        <p className="text-xs uppercase text-axis-muted font-semibold">
                          Proctoring alerts
                        </p>
                        <div className="mt-1 flex items-center gap-2">
                          {critical.length > 0 && (
                            <span className="text-[10px] px-2 py-0.5 bg-axis-pink-soft text-axis-burgundy rounded font-semibold">
                              {critical.length} critical
                            </span>
                          )}
                          <span className="text-[10px] px-2 py-0.5 bg-amber-50 text-amber-800 rounded font-semibold">
                            {violations.length} total alert{violations.length !== 1 ? "s" : ""}
                          </span>
                        </div>
                        <ul className="mt-1 space-y-0.5">
                          {violations.slice(0, 5).map((v: any, i: number) => (
                            <li key={i} className="text-xs text-axis-ink-soft">
                              <span className={`font-semibold ${v.severity === "critical" ? "text-axis-burgundy" : "text-amber-700"}`}>
                                [{v.severity}]
                              </span>{" "}
                              {v.type.replace(/_/g, " ")} — Q{(v.question_index ?? 0) + 1}
                            </li>
                          ))}
                          {violations.length > 5 && (
                            <li className="text-xs text-axis-muted italic">
                              +{violations.length - 5} more…
                            </li>
                          )}
                        </ul>
                      </div>
                    );
                  })()}
                  {r2 && r2.panel_feedback.length > 0 && (
                    <div>
                      <p className="text-xs uppercase text-axis-muted font-semibold">
                        Panel feedback ({r2.panel_feedback.length})
                      </p>
                      <ul className="mt-1 space-y-2">
                        {r2.panel_feedback.map((f) => (
                          <li
                            key={f.panellist_id}
                            className="border border-axis-divider rounded p-2"
                          >
                            <div className="flex items-center justify-between">
                              <span className="text-axis-ink font-semibold">
                                {f.panellist_name}
                              </span>
                              <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded bg-axis-cream">
                                {f.recommendation.replace("_", " ")} · {Math.round(f.score)}/100
                              </span>
                            </div>
                            <p className="text-xs text-axis-ink-soft mt-1">
                              <strong>Strengths:</strong> {f.strengths}
                            </p>
                            <p className="text-xs text-axis-ink-soft">
                              <strong>Concerns:</strong> {f.concerns}
                            </p>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {tab === "checklists" && (
                <div className="space-y-4">
                  {app.checklists.length === 0 && (
                    <p className="text-sm text-axis-muted">
                      No checklist instances yet — they're created when the agent
                      schedules a round. Edit the JD's checklist template{" "}
                      <Link
                        href={`/hr/jobs/${app.job_id}`}
                        className="text-axis-magenta underline"
                      >
                        here
                      </Link>
                      .
                    </p>
                  )}
                  {app.checklists.map((cl) => (
                    <ChecklistCard
                      key={cl.id}
                      cl={cl}
                      onRequestTick={(item) => {
                        setActionError(null);
                        setPendingTick({
                          round: cl.round as "R1" | "R2",
                          phase: cl.phase as "pre" | "post",
                          item,
                        });
                      }}
                      disabled={acting}
                    />
                  ))}
                </div>
              )}

              {tab === "transcript" && (
                <div className="bg-axis-canvas border border-axis-divider rounded-card p-5 text-sm">
                  {r1Transcript.length === 0 && (
                    <p className="text-axis-muted">No R1 transcript yet.</p>
                  )}
                  {r1Transcript.map((t, i) => (
                    <div key={i} className="mb-2">
                      <span
                        className={`text-[10px] font-semibold uppercase ${
                          t.speaker === "interviewer"
                            ? "text-axis-magenta"
                            : "text-axis-ink"
                        }`}
                      >
                        {t.speaker}
                      </span>
                      <p className="text-axis-ink-soft">{t.text}</p>
                    </div>
                  ))}
                </div>
              )}

              {tab === "activity" && (
                <div className="bg-axis-canvas border border-axis-divider rounded-card p-5">
                  <AgentActivityFeed
                    items={activity ?? []}
                    emptyLabel="Agent hasn't logged anything for this application yet."
                    defaultCollapsed={false}
                  />
                </div>
              )}

              {tab === "audit" && (
                <div className="bg-axis-canvas border border-axis-divider rounded-card p-5">
                  <ol className="space-y-2 text-xs">
                    {app.events.map((e, i) => (
                      <li key={i} className="flex gap-3">
                        <span className="text-axis-muted-light w-36 shrink-0">
                          {new Date(e.at).toLocaleString()}
                        </span>
                        <span className="text-axis-magenta font-semibold w-20 shrink-0">
                          {e.actor}
                        </span>
                        <span className="text-axis-ink-soft">{e.message}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          </>
        )}
      </main>
      <Footer />

      {/* ----- Confirm dialogs (selection ≠ commitment) ----- */}
      <ConfirmDialog
        open={pendingTick !== null}
        title={
          pendingTick?.item.blocking
            ? "Release the agent on this blocking item?"
            : "Mark this checklist item as done?"
        }
        message={
          pendingTick ? (
            <>
              You're about to tick{" "}
              <strong className="text-axis-ink">{pendingTick.item.label}</strong>{" "}
              on the <strong>{pendingTick.round} · {pendingTick.phase}</strong>{" "}
              checklist.
              {pendingTick.item.blocking ? (
                <>
                  {" "}
                  This is a <strong className="text-axis-burgundy">BLOCKING</strong>{" "}
                  item — the orchestrator is currently paused on it. Confirming
                  will release the agent and let it advance the candidate to
                  the next stage automatically.
                </>
              ) : (
                <> The candidate will not see this tick directly.</>
              )}
            </>
          ) : (
            ""
          )
        }
        consequences={
          pendingTick?.item.blocking
            ? [
                "Your name and the timestamp will be recorded on the audit log.",
                "The agent will resume immediately and may send emails / book meetings.",
                "This action cannot be un-done from the UI.",
              ]
            : [
                "Your name and the timestamp will be recorded on the audit log.",
                "Other items on this checklist are unaffected.",
              ]
        }
        confirmLabel={
          pendingTick?.item.blocking ? "Release the agent" : "Mark as done"
        }
        tone={pendingTick?.item.blocking ? "danger" : "primary"}
        onConfirm={async () => {
          if (!pendingTick) return;
          await tick(pendingTick.round, pendingTick.phase, pendingTick.item.id);
          setPendingTick(null);
        }}
        onCancel={() => setPendingTick(null)}
      />

      <ConfirmDialog
        open={pendingApprove}
        title="Approve this candidate for Round 2?"
        message={
          <>
            You are about to hand the application to the agent and let it run
            the R2 booking flow with{" "}
            <strong>
              {availablePanels?.find((p) => p.id === selectedPanelId)?.name ||
                selectedPanelId}
            </strong>
            . The candidate cannot un-receive the email.
          </>
        }
        consequences={[
          "Sends an R2 invitation email to the candidate with the 3 proposed slots above.",
          "Asks the candidate to pick one of the slots from Thrive → My Applications.",
          "Once the candidate confirms, the agent will book a Teams meeting and lock all three diaries (candidate + you + every panel member).",
          "If the candidate does not pick a slot, the application stays paused on this gate — no calendars are touched.",
        ]}
        confirmLabel="Approve and notify candidate"
        onConfirm={async () => {
          await approveR2();
          setPendingApprove(false);
        }}
        onCancel={() => setPendingApprove(false)}
      />

      <ConfirmDialog
        open={pendingDecision !== null}
        title={
          pendingDecision === "offer"
            ? "Roll the offer out to this candidate?"
            : "Reject this candidate after R2?"
        }
        message={
          pendingDecision === "offer" ? (
            <>
              You're about to approve this candidate for an offer. The agent
              will immediately send the offer letter to the candidate and
              move the application to the <strong>Offer</strong> stage.
            </>
          ) : (
            <>
              You're about to reject this candidate. The agent will send the
              regret email and move the application to the{" "}
              <strong>Rejected</strong> stage.
            </>
          )
        }
        consequences={
          pendingDecision === "offer"
            ? [
                "The candidate receives the offer email immediately.",
                "The CV is archived on the offer path.",
                "Your name and timestamp are recorded in the audit log.",
                "This cannot be un-done from the UI.",
              ]
            : [
                "The candidate receives the regret email immediately.",
                "The CV is moved to the rejected folder.",
                "Your name and timestamp are recorded in the audit log.",
                "This cannot be un-done from the UI.",
              ]
        }
        confirmLabel={
          pendingDecision === "offer" ? "Send the offer" : "Send the regret"
        }
        tone={pendingDecision === "reject" ? "danger" : "primary"}
        onConfirm={async () => {
          if (!pendingDecision) return;
          await finaliseR2(pendingDecision);
          setPendingDecision(null);
        }}
        onCancel={() => setPendingDecision(null)}
      />

      <ConfirmDialog
        open={pendingUnblock}
        title="Re-poke the orchestrator?"
        message={
          <>
            This is the manual fallback for when the agent has wedged on a
            transient error (e.g. a Graph API hiccup). It re-runs the
            orchestrator's tick from where it left off — it does NOT skip any
            blocking checklist items.
          </>
        }
        consequences={[
          "Idempotent — safe even if nothing was wrong.",
          "The action is logged in the audit feed under your name.",
          "If a blocking checklist item is still unticked, the agent will pause again on the same gate.",
        ]}
        confirmLabel="Unblock the agent"
        onConfirm={async () => {
          await unblock();
          setPendingUnblock(false);
        }}
        onCancel={() => setPendingUnblock(false)}
      />
    </div>
  );
}

function ChecklistCard({
  cl,
  onRequestTick,
  disabled,
}: {
  cl: ChecklistInstance;
  onRequestTick: (item: ChecklistItem) => void;
  disabled: boolean;
}) {
  return (
    <div className="bg-axis-canvas border border-axis-divider rounded-card p-4">
      <p className="text-xs uppercase tracking-wider text-axis-magenta font-semibold">
        {cl.round} · {cl.phase}
      </p>
      <ul className="mt-2 space-y-2">
        {cl.items.map((it) => (
          <li key={it.id} className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={it.done}
              disabled={it.done || disabled}
              onChange={() => onRequestTick(it)}
              className="mt-0.5"
            />
            <div className="flex-1">
              <p
                className={
                  it.done ? "text-axis-muted line-through" : "text-axis-ink"
                }
              >
                {it.label}
              </p>
              {it.blocking && !it.done && (
                <span className="text-[10px] text-axis-burgundy font-semibold">
                  BLOCKING — agent is paused on this
                </span>
              )}
              {it.note && (
                <p className="text-[10px] text-axis-muted-light">{it.note}</p>
              )}
              {it.ticked_by && it.ticked_at && (
                <p className="text-[10px] text-axis-muted-light">
                  ticked by {it.ticked_by} ·{" "}
                  {new Date(it.ticked_at).toLocaleString()}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
