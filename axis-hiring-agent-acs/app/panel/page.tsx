"use client";

import Link from "next/link";
import { useCallback } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import {
  api,
  type PanelHistoryItem,
  type PanelMemberListed,
  type PanelPendingItem,
} from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";
import { usePersona } from "@/lib/persona";

/**
 * Interview Panel queue.
 *
 * Each panellist sees the R2 interviews the orchestrator has scheduled them
 * onto. Polls every 4s — when HR ticks the pre-R2 panel-approval blocking
 * item the orchestrator schedules the meeting in a background thread, and
 * the new card needs to appear here without a manual refresh.
 *
 * Submitting feedback (on the detail page) is the only thing the panellist
 * can do; the orchestrator wakes up automatically once the last vote is in.
 */
export default function PanelQueuePage() {
  return (
    <RoleGate allow={["panel"]}>
      <PanelQueueContent />
    </RoleGate>
  );
}

function PanelQueueContent() {
  const [persona] = usePersona();

  const loadPending = useCallback(async () => {
    if (!persona.identity) return [];
    return api.panelPending(persona.identity);
  }, [persona.identity]);
  const loadHistory = useCallback(async () => {
    if (!persona.identity) return [];
    return api.panelHistory(persona.identity);
  }, [persona.identity]);
  const loadMembers = useCallback(() => api.panelMembers(), []);

  const {
    data: pendingData,
    error,
    refresh,
  } = useAutoRefresh<PanelPendingItem[]>(loadPending, 4000);
  const { data: historyData, loading: historyLoading } =
    useAutoRefresh<PanelHistoryItem[]>(loadHistory, 8000);
  const { data: membersData } = useAutoRefresh<PanelMemberListed[]>(
    loadMembers,
    30000,
  );

  const pending = pendingData ?? [];
  const history = historyData ?? [];
  const members = membersData ?? [];
  const me = members.find((m) => m.user_id === persona.identity);

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />

      {/* Panel hero — consistent burgundy theme */}
      <div className="bg-white border-b border-axis-divider px-8 py-8">
        <div className="max-w-5xl mx-auto flex items-start justify-between gap-4">
          <div>
            <div className="h-1 w-16 bg-gradient-to-r from-axis-burgundy to-axis-accent-pink rounded mb-4" />
            <p className="text-[10px] uppercase tracking-widest text-axis-burgundy font-semibold">
              Interview Panel · Queue
            </p>
            <h1 className="text-2xl font-display text-axis-ink mt-1">
              {me?.name || persona.displayName || "Panel member"}
            </h1>
            <p className="text-sm text-axis-muted mt-2 max-w-2xl leading-relaxed">
              {pending.length === 0 ? (
                <>
                  No Round 2 interviews are waiting for your feedback right now.
                  The AI Hiring Agent will drop a card here the moment a candidate
                  is scheduled onto your panel.
                </>
              ) : (
                <>
                  You have{" "}
                  <strong className="font-bold text-axis-ink">
                    {pending.length} Round 2 interview
                    {pending.length === 1 ? "" : "s"}
                  </strong>{" "}
                  waiting for your feedback. The AI Hiring Agent will not move
                  candidates forward until every panellist has voted.
                </>
              )}
            </p>
            {me && (
              <p className="text-[11px] text-axis-muted mt-3">
                Role:{" "}
                <strong className="text-axis-ink capitalize">
                  {me.role.replace(/_/g, " ")}
                </strong>
                {me.jobs.length > 0 && (
                  <>
                    {" · "}
                    <span title={me.jobs.map((j) => j.title).join(", ")}>
                      {me.jobs.length} active requisition{me.jobs.length === 1 ? "" : "s"}
                    </span>
                  </>
                )}
              </p>
            )}
          </div>
          <button
            onClick={refresh}
            className="text-xs px-4 py-1.5 rounded-btn border border-axis-burgundy text-axis-burgundy hover:bg-axis-pink-soft transition-colors font-semibold"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Guided "what you do here" strip */}
      <div className="bg-axis-canvas border-b border-axis-divider px-8 py-3">
        <div className="max-w-5xl mx-auto text-[11px] text-axis-ink-soft flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-axis-burgundy font-semibold uppercase tracking-wider">
            How this works
          </span>
          <span>1. Open a candidate</span>
          <span>→ 2. Review R1 transcript &amp; score</span>
          <span>→ 3. Submit your panel feedback</span>
          <span>→ 4. Agent consolidates verdict + notifies candidate</span>
        </div>
      </div>

      <main className="flex-1 px-8 py-6 max-w-4xl w-full mx-auto">
        {persona.role !== "panel" && (
          <div className="mb-4 p-3 bg-axis-cream border border-axis-cream-border rounded text-sm text-axis-ink">
            Switch persona to <strong>Interview Panel</strong> in the dark bar
            above to see your real queue.
          </div>
        )}

        {error && (
          <div className="p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
            {error}
          </div>
        )}

        {!error && pending.length === 0 && (
          <div className="p-10 bg-white border border-axis-divider rounded-card text-center">
            <svg
              className="mx-auto mb-4 text-axis-muted"
              width="48"
              height="48"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
            <p className="text-sm font-semibold text-axis-ink mb-1">
              Your queue is clear
            </p>
            <p className="text-xs text-axis-muted max-w-sm mx-auto leading-relaxed">
              No Round 2 interviews need your feedback right now. A new card
              will appear here automatically once the Business Partner approves
              a panel composition.
            </p>
          </div>
        )}

        <div className="space-y-3">
          {pending.map((p) => (
            <div
              key={p.interview_id}
              className="bg-axis-canvas border border-axis-divider rounded-card p-4 flex items-center justify-between"
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold text-axis-ink truncate">
                  {p.candidate_name}
                </p>
                <p className="text-xs text-axis-muted mt-0.5 truncate">
                  {p.job_title} · {p.job_location}
                </p>
                {p.slot_start && (
                  <p className="text-[10px] text-axis-muted-light mt-1">
                    {new Date(p.slot_start).toLocaleString()} →{" "}
                    {p.slot_end
                      ? new Date(p.slot_end).toLocaleTimeString()
                      : "?"}
                  </p>
                )}
                {p.teams_join_url && (
                  <a
                    href={p.teams_join_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[10px] text-axis-burgundy underline mt-0.5 inline-block"
                  >
                    Join Teams meeting ↗
                  </a>
                )}
              </div>
              <Link
                href={`/panel/feedback/${p.application_id}`}
                className="px-4 py-2 rounded-btn bg-axis-burgundy text-white text-xs font-semibold hover:bg-axis-burgundy-dark transition-colors shrink-0"
              >
                Submit feedback
              </Link>
            </div>
          ))}
        </div>

        {/* My submitted votes — read-only history. The panellist cannot edit
            a vote once it's in (audit-trail constraint), but they need to be
            able to look up what they wrote and see the final outcome. */}
        <div className="mt-10">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-axis-burgundy">
              My submitted votes
            </h2>
            <span className="text-[11px] text-axis-muted">
              {history.length} total
            </span>
          </div>
          <p className="text-[11px] text-axis-muted mt-1">
            Read-only audit trail. Once a vote is recorded, it cannot be edited
            from the UI — but you can always come back here to see what you
            submitted and what the panel ultimately decided.
          </p>

          {historyLoading && history.length === 0 ? (
            <div className="mt-3 p-4 bg-axis-canvas border border-axis-divider rounded-card text-xs text-axis-muted flex items-center gap-2">
              <div className="w-4 h-4 border-2 border-axis-burgundy border-t-transparent rounded-full animate-spin" />
              Loading your submitted votes&hellip;
            </div>
          ) : history.length === 0 ? (
            <div className="mt-3 p-4 bg-axis-canvas border border-axis-divider rounded-card text-xs text-axis-muted">
              You haven&apos;t submitted any panel feedback yet. Once you vote on a
              candidate from the queue above, it&apos;ll show up here.
            </div>
          ) : (
            <div className="mt-3 space-y-3">
              {history.map((h) => {
                const recLabel = h.my_recommendation.replace("_", " ");
                const recTone =
                  h.my_recommendation === "strong_hire"
                    ? "bg-axis-cream text-axis-ink"
                    : h.my_recommendation === "hire"
                    ? "bg-axis-surface text-axis-ink"
                    : "bg-axis-pink-soft text-axis-burgundy";
                const stageLabel =
                  h.stage === "offer"
                    ? "Offer extended"
                    : h.stage === "rejected"
                    ? "Rejected"
                    : `Awaiting peer votes (${h.votes_in}/${h.votes_expected})`;
                const stageTone =
                  h.stage === "offer"
                    ? "text-emerald-700"
                    : h.stage === "rejected"
                    ? "text-axis-burgundy"
                    : "text-axis-muted";
                return (
                  <div
                    key={h.interview_id}
                    className="bg-axis-canvas border border-axis-divider rounded-card p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-axis-ink truncate">
                          {h.candidate_name}
                        </p>
                        <p className="text-xs text-axis-muted mt-0.5 truncate">
                          {h.job_title} · {h.job_location}
                        </p>
                        {h.slot_start && (
                          <p className="text-[10px] text-axis-muted-light mt-1">
                            Interviewed{" "}
                            {new Date(h.slot_start).toLocaleString()}
                          </p>
                        )}
                      </div>
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <span
                          className={`text-[10px] font-semibold px-2 py-0.5 rounded ${recTone}`}
                        >
                          {recLabel}
                        </span>
                        <span className="text-[10px] text-axis-ink-soft">
                          {Math.round(h.my_score)}/100
                        </span>
                        <span
                          className={`text-[10px] uppercase tracking-wider ${stageTone}`}
                        >
                          {stageLabel}
                        </span>
                      </div>
                    </div>

                    {(h.my_strengths || h.my_concerns) && (
                      <div className="grid md:grid-cols-2 gap-3 mt-3 pt-3 border-t border-axis-divider">
                        {h.my_strengths && (
                          <div>
                            <p className="text-[9px] uppercase tracking-wider text-axis-muted font-semibold">
                              Your strengths
                            </p>
                            <p className="text-[11px] text-axis-ink-soft mt-1 whitespace-pre-wrap">
                              {h.my_strengths}
                            </p>
                          </div>
                        )}
                        {h.my_concerns && (
                          <div>
                            <p className="text-[9px] uppercase tracking-wider text-axis-muted font-semibold">
                              Your concerns
                            </p>
                            <p className="text-[11px] text-axis-ink-soft mt-1 whitespace-pre-wrap">
                              {h.my_concerns}
                            </p>
                          </div>
                        )}
                      </div>
                    )}

                    <div className="mt-3 pt-2 border-t border-axis-divider flex items-center justify-between">
                      <span className="text-[10px] text-axis-muted">
                        Submitted {new Date(h.submitted_at).toLocaleString()}
                      </span>
                      <Link
                        href={`/panel/feedback/${h.application_id}`}
                        className="text-[11px] text-axis-burgundy hover:underline"
                      >
                        Open read-only →
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
      <Footer />
    </div>
  );
}
