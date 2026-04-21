"use client";

import { useCallback, useEffect, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";
import {
  getEngagementDashboard,
  sendTouchpoint,
  skipTouchpoint,
  updateEngagementJourney,
  replyToCandidate,
  retagReplies,
  type ConversationMessage,
  type EngagementDashboard,
  type EngagementJourney,
  type EngagementTouchpoint,
  type RiskAssessment,
  type TouchpointKind,
} from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Touchpoint kind → human-friendly label                            */
/* ------------------------------------------------------------------ */
const KIND_LABEL: Record<TouchpointKind, string> = {
  welcome_whatsapp: "Welcome Message",
  buddy_intro: "Buddy Introduction",
  document_checklist: "Document Checklist",
  culture_video: "Life at Axis",
  employee_stories: "Employee Stories",
  benefits_overview: "Benefits Overview",
  weekly_checkin: "Weekly Check-in",
  linkedin_connect: "LinkedIn Connect",
  it_setup_form: "IT Setup Form",
  team_intro_call: "Team Intro Call",
  dress_code_tips: "Dress Code & Day 1 Tips",
  joining_reminder: "Joining Reminder",
  day_one_welcome: "Day 1 Welcome",
  custom: "Custom",
};

/* ------------------------------------------------------------------ */
/*  Helper: format ISO date to readable string                        */
/* ------------------------------------------------------------------ */
function fmtDate(iso: string | null): string {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const diff = (new Date(iso).getTime() - Date.now()) / (1000 * 60 * 60 * 24);
  return Math.ceil(diff);
}

/* ------------------------------------------------------------------ */
/*  Status badge                                                      */
/* ------------------------------------------------------------------ */
function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-axis-surface text-axis-muted",
    sent: "bg-blue-100 text-blue-700",
    delivered: "bg-indigo-100 text-indigo-700",
    read: "bg-emerald-100 text-emerald-700",
    failed: "bg-red-100 text-red-700",
    skipped: "bg-gray-100 text-gray-500",
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold capitalize ${
        styles[status] || "bg-axis-surface text-axis-muted"
      }`}
    >
      {status}
    </span>
  );
}

function RiskBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    low: "bg-emerald-100 text-emerald-700",
    medium: "bg-amber-100 text-amber-700",
    high: "bg-red-100 text-red-700",
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${
        styles[level] || "bg-axis-surface text-axis-muted"
      }`}
    >
      {level}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Page entry                                                        */
/* ------------------------------------------------------------------ */
export default function OnboardingPage() {
  return (
    <RoleGate allow={["engagement_manager"]}>
      <OnboardingContent />
    </RoleGate>
  );
}

/* ------------------------------------------------------------------ */
/*  Main content                                                      */
/* ------------------------------------------------------------------ */
function OnboardingContent() {
  const loadDashboard = useCallback(() => getEngagementDashboard(), []);
  const { data, loading, error, refresh } =
    useAutoRefresh<EngagementDashboard>(loadDashboard, 10000);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [riskExpandedId, setRiskExpandedId] = useState<string | null>(null);
  const [chatExpandedId, setChatExpandedId] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [retagDone, setRetagDone] = useState(false);

  // One-time retag of stale replies on mount
  useEffect(() => {
    if (!retagDone) {
      retagReplies().then(() => { setRetagDone(true); refresh(); }).catch(() => setRetagDone(true));
    }
  }, [retagDone, refresh]);

  const journeys = data?.journeys ?? [];
  const riskAssessments = data?.risk_assessments ?? {};
  const atRisk = journeys.filter((j) => j.risk_level === "high" || j.risk_level === "medium");

  /* ---- action handlers ---- */
  async function handleSend(journeyId: string, tpId: string) {
    setActionLoading(tpId);
    try {
      await sendTouchpoint(journeyId, tpId);
      await refresh();
    } catch (e: any) {
      alert("Could not send: " + (e?.message || e));
    } finally {
      setActionLoading(null);
    }
  }

  async function handleSkip(journeyId: string, tpId: string) {
    setActionLoading(tpId);
    try {
      await skipTouchpoint(journeyId, tpId);
      await refresh();
    } catch (e: any) {
      alert("Could not skip: " + (e?.message || e));
    } finally {
      setActionLoading(null);
    }
  }

  async function handleAssignBuddy(journey: EngagementJourney) {
    const name = prompt("Buddy name:");
    if (!name) return;
    const email = prompt("Buddy email:");
    if (!email) return;
    try {
      await updateEngagementJourney(journey.id, {
        buddy_name: name,
        buddy_email: email,
      });
      await refresh();
    } catch (e: any) {
      alert("Could not assign buddy: " + (e?.message || e));
    }
  }

  async function handleSendCheckin(journey: EngagementJourney) {
    const pending = journey.touchpoints.find(
      (tp) => tp.status === "pending" && tp.kind === "weekly_checkin",
    );
    if (pending) {
      await handleSend(journey.id, pending.id);
    } else {
      // Send the next pending touchpoint
      const next = journey.touchpoints.find((tp) => tp.status === "pending");
      if (next) {
        await handleSend(journey.id, next.id);
      } else {
        alert("No pending touchpoints to send.");
      }
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />

      {/* Header */}
      <div className="bg-axis-burgundy/5 border-b border-axis-divider px-8 py-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <p className="text-[10px] text-axis-magenta font-semibold uppercase tracking-wider">
              Onboarding Team
            </p>
            <h1 className="text-xl font-semibold text-axis-ink mt-0.5">
              Candidate Engagement Dashboard
            </h1>
            <p className="text-xs text-axis-muted mt-1">
              Monitor and manage post-offer candidate journeys
            </p>
          </div>
          <button
            onClick={() => refresh()}
            className="text-xs px-3 py-1 rounded border border-axis-divider text-axis-ink hover:bg-axis-surface"
          >
            Refresh
          </button>
        </div>
      </div>

      <main className="flex-1 bg-axis-surface px-8 py-6 space-y-6">
        {/* Error banner */}
        {error && (
          <div className="p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
            Could not load dashboard: {error}
          </div>
        )}

        {/* Loading state */}
        {loading && !data && (
          <div className="text-sm text-axis-muted py-12 text-center">
            Loading engagement data...
          </div>
        )}

        {data && (
          <>
            {/* ---- Stats cards ---- */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <StatCard
                label="Active Journeys"
                value={data.total_active_journeys}
              />
              <StatCard
                label="Candidates at Risk"
                value={data.at_risk_count}
                highlight={data.at_risk_count > 0}
              />
              <StatCard
                label="Upcoming in 24h"
                value={data.upcoming_touchpoints_24h.length}
              />
              <StatCard
                label="Completion Rate"
                value={`${data.completion_rate_percent.toFixed(0)}%`}
              />
            </div>

            {/* ---- All Journeys Table ---- */}
            <section>
              <h2 className="text-sm font-semibold text-axis-ink mb-3">
                All journeys
              </h2>

              {journeys.length === 0 ? (
                <div className="p-6 bg-axis-canvas border border-axis-divider rounded-lg text-sm text-axis-muted text-center">
                  No engagement journeys yet. Journeys are created when a candidate accepts an offer.
                </div>
              ) : (
                <div className="bg-axis-canvas border border-axis-divider rounded-lg shadow-sm overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-axis-surface text-axis-muted">
                        <tr>
                          <th className="px-4 py-2.5 text-left font-semibold">
                            Candidate
                          </th>
                          <th className="px-4 py-2.5 text-left font-semibold">
                            Phone
                          </th>
                          <th className="px-4 py-2.5 text-left font-semibold">
                            Status
                          </th>
                          <th className="px-4 py-2.5 text-left font-semibold">
                            Risk
                          </th>
                          <th className="px-4 py-2.5 text-left font-semibold">
                            Joining Date
                          </th>
                          <th className="px-4 py-2.5 text-left font-semibold">
                            Touchpoints
                          </th>
                          <th className="px-4 py-2.5 text-left font-semibold">
                            Actions
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {journeys.map((j) => {
                          const sentCount = j.touchpoints.filter(
                            (tp) => tp.status !== "pending" && tp.status !== "skipped",
                          ).length;
                          const totalTp = j.touchpoints.length;
                          const pct = totalTp > 0 ? (sentCount / totalTp) * 100 : 0;
                          const isExpanded = expandedId === j.id;
                          const isRiskExpanded = riskExpandedId === j.id;
                          const isChatExpanded = chatExpandedId === j.id;
                          const risk = riskAssessments[j.id];

                          return (
                            <JourneyRow
                              key={j.id}
                              journey={j}
                              sentCount={sentCount}
                              totalTp={totalTp}
                              pct={pct}
                              isExpanded={isExpanded}
                              isRiskExpanded={isRiskExpanded}
                              isChatExpanded={isChatExpanded}
                              risk={risk}
                              onToggle={() =>
                                setExpandedId(isExpanded ? null : j.id)
                              }
                              onToggleRisk={() =>
                                setRiskExpandedId(isRiskExpanded ? null : j.id)
                              }
                              onToggleChat={() =>
                                setChatExpandedId(isChatExpanded ? null : j.id)
                              }
                              onSend={handleSend}
                              onSkip={handleSkip}
                              onAssignBuddy={() => handleAssignBuddy(j)}
                              onSendCheckin={() => handleSendCheckin(j)}
                              onRefresh={refresh}
                              actionLoading={actionLoading}
                            />
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </section>
          </>
        )}
      </main>

      <Footer />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Stat Card                                                         */
/* ------------------------------------------------------------------ */
function StatCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string | number;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-4 shadow-sm ${
        highlight
          ? "bg-red-50 border-red-200"
          : "bg-axis-canvas border-axis-divider"
      }`}
    >
      <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
        {label}
      </p>
      <p
        className={`text-2xl font-bold mt-1 ${
          highlight ? "text-red-600" : "text-axis-ink"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Journey row + expandable timeline                                 */
/* ------------------------------------------------------------------ */
function JourneyRow({
  journey,
  sentCount,
  totalTp,
  pct,
  isExpanded,
  isRiskExpanded,
  isChatExpanded,
  risk,
  onToggle,
  onToggleRisk,
  onToggleChat,
  onSend,
  onSkip,
  onAssignBuddy,
  onSendCheckin,
  onRefresh,
  actionLoading,
}: {
  journey: EngagementJourney;
  sentCount: number;
  totalTp: number;
  pct: number;
  isExpanded: boolean;
  isRiskExpanded: boolean;
  isChatExpanded: boolean;
  risk?: RiskAssessment;
  onToggle: () => void;
  onToggleRisk: () => void;
  onToggleChat: () => void;
  onSend: (jId: string, tpId: string) => void;
  onSkip: (jId: string, tpId: string) => void;
  onAssignBuddy: () => void;
  onSendCheckin: () => void;
  onRefresh: () => void;
  actionLoading: string | null;
}) {
  const [replyText, setReplyText] = useState("");
  const [replySending, setReplySending] = useState(false);

  const hasRiskSignals =
    journey.risk_level === "high" || journey.risk_level === "medium";
  const flaggedCount = risk?.flagged_replies?.length ?? 0;
  const conversations = journey.conversations ?? [];
  const msgCount = conversations.length;

  return (
    <>
      <tr className="border-t border-axis-divider hover:bg-axis-surface/50">
        <td className="px-4 py-3 font-semibold text-axis-ink">
          {journey.candidate_name}
        </td>
        <td className="px-4 py-3 text-axis-muted">
          {journey.candidate_phone || "--"}
        </td>
        <td className="px-4 py-3">
          <span className="capitalize text-axis-ink">{journey.status}</span>
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <RiskBadge level={journey.risk_level} />
            {hasRiskSignals && (
              <span className="relative flex h-2.5 w-2.5" title="Risk signals detected">
                <span
                  className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                    journey.risk_level === "high" ? "bg-red-400" : "bg-amber-400"
                  }`}
                />
                <span
                  className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                    journey.risk_level === "high" ? "bg-red-500" : "bg-amber-500"
                  }`}
                />
              </span>
            )}
            {risk && (
              <span className="text-[9px] text-axis-muted">
                {risk.overall_score}
              </span>
            )}
          </div>
        </td>
        <td className="px-4 py-3 text-axis-muted">
          {fmtDate(journey.expected_joining_date)}
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-axis-divider rounded-full overflow-hidden max-w-[100px]">
              <div
                className="h-full bg-axis-magenta rounded-full transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-[10px] text-axis-muted whitespace-nowrap">
              {sentCount}/{totalTp} sent
            </span>
          </div>
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-3">
            <button
              onClick={onToggle}
              className="text-[11px] text-axis-magenta hover:underline font-medium"
            >
              {isExpanded ? "Hide timeline" : "View timeline"}
            </button>
            <span className="text-axis-divider">|</span>
            <button
              onClick={onToggleRisk}
              className={`text-[11px] font-medium hover:underline flex items-center gap-1 ${
                hasRiskSignals
                  ? journey.risk_level === "high"
                    ? "text-red-600"
                    : "text-amber-600"
                  : "text-emerald-600"
              }`}
            >
              {isRiskExpanded ? "Hide risk" : "Risk insights"}
              {flaggedCount > 0 && (
                <span
                  className={`inline-flex items-center justify-center w-4 h-4 rounded-full text-[9px] font-bold text-white ${
                    journey.risk_level === "high" ? "bg-red-500" : "bg-amber-500"
                  }`}
                >
                  {flaggedCount}
                </span>
              )}
            </button>
            <span className="text-axis-divider">|</span>
            <button
              onClick={onToggleChat}
              className="text-[11px] font-medium hover:underline flex items-center gap-1 text-indigo-600"
            >
              {isChatExpanded ? "Hide chat" : "Chat history"}
              {msgCount > 0 && (
                <span className="inline-flex items-center justify-center w-4 h-4 rounded-full text-[9px] font-bold text-white bg-indigo-500">
                  {msgCount}
                </span>
              )}
            </button>
          </div>
        </td>
      </tr>

      {/* Expanded timeline */}
      {isExpanded && (
        <tr className="bg-axis-surface/30">
          <td colSpan={7} className="px-4 py-4">
            <div className="ml-2 border-l-2 border-axis-divider pl-5 space-y-4">
              {journey.touchpoints.length === 0 && (
                <p className="text-xs text-axis-muted">
                  No touchpoints scheduled yet.
                </p>
              )}
              {journey.touchpoints.map((tp, idx) => (
                <TouchpointItem
                  key={tp.id}
                  tp={tp}
                  isLast={idx === journey.touchpoints.length - 1}
                  journeyId={journey.id}
                  candidatePhone={journey.candidate_phone}
                  onSend={onSend}
                  onSkip={onSkip}
                  onReplySent={onRefresh}
                  actionLoading={actionLoading}
                />
              ))}
            </div>
          </td>
        </tr>
      )}

      {/* Expanded Risk Insights panel */}
      {isRiskExpanded && risk && (
        <tr>
          <td colSpan={7} className="px-0 py-0">
            <div
              className={`mx-4 my-3 rounded-lg border shadow-sm overflow-hidden ${
                journey.risk_level === "high"
                  ? "border-red-200 bg-red-50/30"
                  : journey.risk_level === "medium"
                  ? "border-amber-200 bg-amber-50/30"
                  : "border-emerald-200 bg-emerald-50/30"
              }`}
            >
              {/* Risk header with score + quick actions */}
              <div className="px-5 py-3 flex items-center justify-between border-b border-axis-divider/50 bg-white/60">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-semibold text-axis-ink">
                    Risk Assessment
                  </span>
                  <RiskBadge level={risk.risk_level} />
                  <span className="text-[10px] text-axis-muted">
                    Score: {risk.overall_score}/100
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={onAssignBuddy}
                    className="text-[10px] px-2.5 py-1 rounded bg-axis-surface border border-axis-divider text-axis-ink hover:border-axis-magenta"
                  >
                    Assign buddy
                  </button>
                  <button
                    onClick={onSendCheckin}
                    className="text-[10px] px-2.5 py-1 rounded bg-axis-burgundy text-white hover:bg-axis-burgundy-dark"
                  >
                    Send check-in
                  </button>
                </div>
              </div>

              <div className="px-5 py-4 space-y-3">
                {/* Dimension bars */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  {(
                    [
                      ["Responsiveness", risk.dimensions.responsiveness],
                      ["Sentiment", risk.dimensions.sentiment],
                      ["Compliance", risk.dimensions.compliance],
                      ["Timeline", risk.dimensions.timeline],
                    ] as const
                  ).map(([label, dim]) => (
                    <div
                      key={label}
                      className="bg-white rounded p-2.5 border border-axis-divider/30"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] font-semibold text-axis-ink uppercase tracking-wider">
                          {label}
                        </span>
                        <span
                          className={`text-[10px] font-bold ${
                            dim.score > 60
                              ? "text-red-600"
                              : dim.score > 30
                              ? "text-amber-600"
                              : "text-emerald-600"
                          }`}
                        >
                          {dim.score}
                        </span>
                      </div>
                      <div className="h-1.5 bg-axis-divider rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${
                            dim.score > 60
                              ? "bg-red-500"
                              : dim.score > 30
                              ? "bg-amber-500"
                              : "bg-emerald-500"
                          }`}
                          style={{ width: `${dim.score}%` }}
                        />
                      </div>
                      <p className="text-[10px] text-axis-muted mt-1 leading-tight">
                        {dim.detail}
                      </p>
                      {dim.signals.length > 0 && (
                        <ul className="mt-1 space-y-0.5">
                          {dim.signals.map((s, si) => (
                            <li
                              key={si}
                              className="text-[10px] text-red-600 flex items-start gap-1"
                            >
                              <span className="shrink-0 mt-0.5">&#9888;</span>
                              {s}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>

                {/* Flagged replies */}
                {risk.flagged_replies.length > 0 && (
                  <div className="bg-amber-50 border border-amber-200 rounded p-3">
                    <p className="text-[10px] font-semibold text-amber-800 uppercase tracking-wider mb-2">
                      Replies needing attention
                    </p>
                    <div className="space-y-1.5">
                      {risk.flagged_replies.map((fr, fi) => (
                        <div
                          key={fi}
                          className="flex items-start gap-2 text-[11px]"
                        >
                          <span
                            className={`shrink-0 px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase ${
                              fr.is_concern
                                ? "bg-red-100 text-red-700"
                                : fr.is_query
                                ? "bg-blue-100 text-blue-700"
                                : "bg-amber-100 text-amber-700"
                            }`}
                          >
                            {fr.is_concern
                              ? "Concern"
                              : fr.is_query
                              ? "Query"
                              : "Negative"}
                          </span>
                          <span className="text-axis-ink italic">
                            &ldquo;{fr.reply_text}&rdquo;
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Suggested actions */}
                {risk.suggested_actions.length > 0 && (
                  <div className="bg-emerald-50 border border-emerald-200 rounded p-3">
                    <p className="text-[10px] font-semibold text-emerald-800 uppercase tracking-wider mb-2">
                      Suggested actions
                    </p>
                    <ul className="space-y-1">
                      {risk.suggested_actions.map((action, ai) => (
                        <li
                          key={ai}
                          className="text-[11px] text-emerald-900 flex items-start gap-2"
                        >
                          <span className="shrink-0 text-emerald-600 font-bold">
                            {ai + 1}.
                          </span>
                          {action}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}

      {/* Expanded Chat History panel */}
      {isChatExpanded && (
        <tr>
          <td colSpan={7} className="px-0 py-0">
            <div className="mx-4 my-3 rounded-lg border border-indigo-200 bg-indigo-50/20 shadow-sm overflow-hidden">
              {/* Chat header */}
              <div className="px-5 py-3 flex items-center justify-between border-b border-indigo-100 bg-white/80">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-axis-ink">
                    Conversation History
                  </span>
                  <span className="text-[10px] text-axis-muted">
                    {journey.candidate_name} &middot; {journey.candidate_phone}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 font-medium">
                    {msgCount} message{msgCount !== 1 ? "s" : ""}
                  </span>
                </div>
              </div>

              {/* Chat messages */}
              <div className="px-5 py-4 max-h-[400px] overflow-y-auto space-y-3">
                {conversations.length === 0 ? (
                  <p className="text-xs text-axis-muted text-center py-6">
                    No messages exchanged yet. Messages will appear here as touchpoints are sent and the candidate responds.
                  </p>
                ) : (
                  (() => {
                    const sorted = [...conversations].sort(
                      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
                    );
                    // Build a lookup for reply-to context
                    const msgById: Record<string, typeof sorted[0]> = {};
                    sorted.forEach((m) => { msgById[m.id] = m; });

                    return sorted.map((msg) => {
                      const isOutbound = msg.direction === "outbound";
                      const time = fmtDateTime(msg.timestamp);
                      // Resolve the message this is replying to
                      const replyToMsg = msg.reply_to_id ? msgById[msg.reply_to_id] : null;

                      return (
                        <div
                          key={msg.id}
                          className={`flex ${isOutbound ? "justify-end" : "justify-start"}`}
                        >
                          <div
                            className={`max-w-[75%] rounded-lg px-3 py-2 shadow-sm ${
                              isOutbound
                                ? "bg-emerald-50 border border-emerald-200 text-axis-ink rounded-br-sm"
                                : "bg-white border border-gray-200 text-axis-ink rounded-bl-sm"
                            }`}
                          >
                            {/* Reply-to context bar (WhatsApp-style) */}
                            {replyToMsg && (
                              <div className="mb-1.5 px-2 py-1.5 rounded bg-gray-100 border-l-2 border-axis-magenta">
                                <span className="text-[9px] font-semibold text-axis-magenta block">
                                  Replying to {replyToMsg.direction === "outbound"
                                    ? replyToMsg.sender === "system" ? "Axis Bank" : "Onboarding Team"
                                    : journey.candidate_name}
                                </span>
                                <span className="text-[9px] text-axis-muted line-clamp-2 leading-snug">
                                  {replyToMsg.body.length > 120 ? replyToMsg.body.slice(0, 120) + "…" : replyToMsg.body}
                                </span>
                              </div>
                            )}
                            <div className="flex items-center gap-2 mb-0.5">
                              <span
                                className={`text-[9px] font-semibold uppercase tracking-wider ${
                                  isOutbound ? "text-emerald-700" : "text-axis-muted"
                                }`}
                              >
                                {isOutbound
                                  ? msg.sender === "system"
                                    ? "Axis Bank"
                                    : msg.channel === "portal"
                                    ? "Onboarding Assistant"
                                    : "Onboarding Team"
                                  : journey.candidate_name}
                              </span>
                              {msg.channel === "portal" && (
                                <span className="text-[8px] px-1.5 py-0.5 rounded-full bg-axis-magenta/10 text-axis-magenta font-semibold uppercase tracking-wider">
                                  Portal Chat
                                </span>
                              )}
                              {msg.channel === "whatsapp" && (
                                <span className="text-[8px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-semibold uppercase tracking-wider">
                                  WhatsApp
                                </span>
                              )}
                              {msg.channel === "email" && (
                                <span className="text-[8px] px-1.5 py-0.5 rounded-full bg-sky-100 text-sky-700 font-semibold uppercase tracking-wider">
                                  Email
                                </span>
                              )}
                              <span className="text-[9px] text-axis-muted">
                                {time}
                              </span>
                            </div>
                            <p className="text-[11px] leading-relaxed text-axis-ink whitespace-pre-line">
                              {msg.body}
                            </p>
                            {/* Internal-only KB citations for Portal Chat —
                                never shown to the candidate. */}
                            {isOutbound && msg.channel === "portal" && Array.isArray((msg as { citations?: Array<{ doc?: string; section?: string }> }).citations) && ((msg as { citations?: Array<{ doc?: string; section?: string }> }).citations?.length ?? 0) > 0 && (
                              <div className="mt-2 pt-2 border-t border-emerald-200/70">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <span className="text-[8px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-semibold uppercase tracking-wider">
                                    Internal
                                  </span>
                                  <span className="text-[9px] font-semibold text-axis-muted uppercase tracking-wider">
                                    KB Sources
                                  </span>
                                </div>
                                <ul className="space-y-0.5">
                                  {(msg as { citations?: Array<{ doc?: string; section?: string }> }).citations!.map((c, ci) => (
                                    <li key={ci} className="text-[10px] leading-snug text-axis-muted">
                                      <span className="font-mono text-axis-ink/80">{c.doc}</span>
                                      {c.section ? <span className="text-axis-muted"> — {c.section}</span> : null}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {msg.touchpoint_id && (
                              <span className="text-[8px] mt-1 inline-block text-axis-muted/60">
                                {isOutbound ? "via" : "re"}: {msg.touchpoint_id.slice(0, 11)}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    });
                  })()
                )}
              </div>

              {/* Reply input */}
              <div className="px-5 py-3 border-t border-indigo-100 bg-white/80">
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={replyText}
                    onChange={(e) => setReplyText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && replyText.trim() && !replySending) {
                        handleReply();
                      }
                    }}
                    placeholder="Type a reply to send via WhatsApp..."
                    className="flex-1 text-xs px-3 py-2 border border-axis-divider rounded-lg focus:outline-none focus:ring-1 focus:ring-axis-magenta"
                  />
                  <button
                    disabled={!replyText.trim() || replySending}
                    onClick={handleReply}
                    className="text-[11px] px-4 py-2 rounded-lg bg-axis-burgundy text-white hover:bg-axis-burgundy-dark disabled:opacity-50 font-medium"
                  >
                    {replySending ? "Sending..." : "Send"}
                  </button>
                </div>
                <p className="text-[9px] text-axis-muted mt-1">
                  Messages are sent via WhatsApp to {journey.candidate_phone}
                </p>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );

  async function handleReply() {
    if (!replyText.trim()) return;
    setReplySending(true);
    try {
      await replyToCandidate(journey.id, replyText.trim());
      setReplyText("");
      onRefresh();
    } catch (e: any) {
      alert("Failed to send: " + (e?.message || e));
    } finally {
      setReplySending(false);
    }
  }
}

/* ------------------------------------------------------------------ */
/*  Touchpoint timeline item                                          */
/* ------------------------------------------------------------------ */
function TouchpointItem({
  tp,
  journeyId,
  candidatePhone,
  onSend,
  onSkip,
  onReplySent,
  actionLoading,
}: {
  tp: EngagementTouchpoint;
  isLast?: boolean;
  journeyId: string;
  candidatePhone?: string;
  onSend: (jId: string, tpId: string) => void;
  onSkip: (jId: string, tpId: string) => void;
  onReplySent?: () => void;
  actionLoading: string | null;
}) {
  const isLoading = actionLoading === tp.id;
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [replySending, setReplySending] = useState(false);

  async function sendInlineReply() {
    const msg = replyText.trim();
    if (!msg) return;
    setReplySending(true);
    try {
      await replyToCandidate(journeyId, msg, { touchpoint_id: tp.id });
      setReplyText("");
      setReplyOpen(false);
      onReplySent?.();
    } catch (e: unknown) {
      const m = e instanceof Error ? e.message : String(e);
      alert("Failed to send WhatsApp reply: " + m);
    } finally {
      setReplySending(false);
    }
  }

  return (
    <div className="relative">
      {/* Dot on the timeline line */}
      <div
        className={`absolute -left-[25px] top-1 w-2.5 h-2.5 rounded-full border-2 ${
          tp.status === "pending"
            ? "bg-white border-axis-muted"
            : tp.status === "failed"
            ? "bg-red-400 border-red-500"
            : tp.status === "skipped"
            ? "bg-gray-300 border-gray-400"
            : "bg-axis-magenta border-axis-magenta"
        }`}
      />

      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold text-axis-ink">
            {KIND_LABEL[tp.kind] || tp.kind}
          </p>
          <p className="text-[10px] text-axis-muted mt-0.5">
            Scheduled: {fmtDateTime(tp.scheduled_at)}
            {tp.sent_at && <> &middot; Sent: {fmtDateTime(tp.sent_at)}</>}
            {tp.delivered_at && (
              <> &middot; Delivered: {fmtDateTime(tp.delivered_at)}</>
            )}
            {tp.read_at && <> &middot; Read: {fmtDateTime(tp.read_at)}</>}
          </p>
          {tp.candidate_response && (() => {
            const lower = tp.candidate_response!.toLowerCase();
            const isQuery = ["?", "when", "how", "what", "where", "can you", "will i", "do i", "query", "question"].some(
              (s) => lower.includes(s),
            );
            const isConcern = ["worried", "concern", "delay", "postpone", "other offer", "not sure", "cannot", "unable", "issue", "problem", "still thinking", "thinking about", "not decided", "hesitant", "doubt", "come back to me", "get back to me", "unclear", "confused", "exact r&r", "roles and responsibilities", "need time", "let me think"].some(
              (s) => lower.includes(s),
            );
            const needsAttention = isQuery || isConcern;
            return (
              <div
                className={`mt-1 rounded px-2 py-1 ${
                  needsAttention
                    ? isConcern
                      ? "bg-red-50 border border-red-200"
                      : "bg-blue-50 border border-blue-200"
                    : "bg-axis-surface"
                }`}
              >
                {needsAttention && (
                  <span
                    className={`text-[9px] font-semibold uppercase tracking-wider ${
                      isConcern ? "text-red-600" : "text-blue-600"
                    }`}
                  >
                    {isConcern ? "⚠ Concern" : "❓ Query"}{" · "}
                  </span>
                )}
                <span className="text-[10px] text-axis-ink-soft italic">
                  &ldquo;{tp.candidate_response}&rdquo;
                </span>
                <div className="mt-1.5 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setReplyOpen((v) => !v)}
                    className="text-[10px] px-2 py-0.5 rounded bg-emerald-600 text-white hover:bg-emerald-700"
                  >
                    {replyOpen ? "Cancel" : "Reply on WhatsApp"}
                  </button>
                  {candidatePhone && (
                    <span className="text-[9px] text-axis-muted">
                      via WhatsApp to {candidatePhone}
                    </span>
                  )}
                </div>
                {replyOpen && (
                  <div className="mt-2 flex gap-2">
                    <textarea
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      onKeyDown={(e) => {
                        if (
                          e.key === "Enter" &&
                          !e.shiftKey &&
                          replyText.trim() &&
                          !replySending
                        ) {
                          e.preventDefault();
                          sendInlineReply();
                        }
                      }}
                      rows={2}
                      placeholder={`Type your reply to ${needsAttention ? "this query" : "the candidate"}…`}
                      className="flex-1 text-[11px] px-2 py-1.5 border border-axis-divider rounded focus:outline-none focus:ring-1 focus:ring-axis-magenta"
                    />
                    <button
                      type="button"
                      disabled={!replyText.trim() || replySending}
                      onClick={sendInlineReply}
                      className="text-[10px] px-3 py-1.5 rounded bg-axis-burgundy text-white hover:bg-axis-burgundy-dark disabled:opacity-50 h-fit"
                    >
                      {replySending ? "Sending…" : "Send"}
                    </button>
                  </div>
                )}
              </div>
            );
          })()}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <StatusBadge status={tp.status} />
          {tp.status === "pending" && (
            <>
              <button
                disabled={isLoading}
                onClick={() => onSend(journeyId, tp.id)}
                className="text-[10px] px-2 py-1 rounded bg-axis-magenta text-white hover:bg-axis-burgundy disabled:opacity-50"
              >
                {isLoading ? "..." : "Send now"}
              </button>
              <button
                disabled={isLoading}
                onClick={() => onSkip(journeyId, tp.id)}
                className="text-[10px] px-2 py-1 rounded border border-axis-divider text-axis-muted hover:border-axis-magenta disabled:opacity-50"
              >
                Skip
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
