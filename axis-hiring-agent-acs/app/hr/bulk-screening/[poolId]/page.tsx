"use client";

/**
 * Bulk Screening Leaderboard — ranked candidates scored against a JD.
 *
 * Polls /hr/bulk-intake/{poolId} every 3s while processing. Once done,
 * shows the full leaderboard with drill-in drawers, CSV export, and
 * shortlist buttons (L1 / L2) to push candidates into the interview pipeline.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import { HRSubNav } from "@/components/hr/HRSubNav";
import {
  api,
  type BulkPoolStatus,
  type BulkLeaderboard,
  type BulkLeaderboardEntry,
  type BulkRowDetail,
  type Job,
} from "@/lib/api";

export default function BulkScreeningPoolPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <PoolContent />
    </RoleGate>
  );
}

function PoolContent() {
  const params = useParams<{ poolId: string }>();
  const searchParams = useSearchParams();
  const poolId = params?.poolId;
  // Optional deep-link target — set when HR opens this page from an
  // application detail in the funnel (?row=<row_id>). We auto-open the
  // drawer on that row once the leaderboard is loaded so HR lands exactly
  // on the screening result they clicked through from.
  const deepLinkRowId = searchParams?.get("row") || null;
  const didDeepLinkRef = useRef(false);

  const [status, setStatus] = useState<BulkPoolStatus | null>(null);
  const [leaderboard, setLeaderboard] = useState<BulkLeaderboardEntry[]>([]);
  const [poolMode, setPoolMode] = useState<"single_jd" | "auto_map">("single_jd");
  const [drawerRow, setDrawerRow] = useState<BulkRowDetail | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [routingRowId, setRoutingRowId] = useState<string | null>(null);
  const [routeToast, setRouteToast] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Routing modal state (auto-map: pick requisition + route/notify)
  const [routeModal, setRouteModal] = useState<{
    entry: BulkLeaderboardEntry;
    round: "L1" | "L2";
  } | null>(null);
  const [routeModalJobId, setRouteModalJobId] = useState<string>("");
  const [routeModalAction, setRouteModalAction] = useState<"route" | "notify">("route");
  const [allJobs, setAllJobs] = useState<Job[]>([]);
  const [jobsLoaded, setJobsLoaded] = useState(false);

  // Verdict filter for leaderboard
  const [verdictFilter, setVerdictFilter] = useState<"shortlist_maybe" | "shortlist" | "maybe" | "reject" | "all">("shortlist_maybe");

  // Poll for status while processing
  const fetchStatus = useCallback(async () => {
    if (!poolId) return;
    try {
      const s = await api.bulkIntakeStatus(poolId);
      setStatus(s);
      setPoolMode(s.mode || "single_jd");
      if (s.status === "pending_review") {
        if (pollRef.current) clearInterval(pollRef.current);
      } else if (s.status !== "processing") {
        if (pollRef.current) clearInterval(pollRef.current);
        const lb = await api.bulkIntakeResults(poolId);
        setLeaderboard(lb.leaderboard);
        setPoolMode(lb.mode || "single_jd");
      }
    } catch {}
  }, [poolId]);

  useEffect(() => {
    fetchStatus();
    pollRef.current = setInterval(fetchStatus, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchStatus]);

  // Load all jobs for auto-map routing modal and cross-JD insights
  useEffect(() => {
    if (!jobsLoaded) {
      api.listJobs().then((jobs) => { setAllJobs(jobs); setJobsLoaded(true); }).catch(() => {});
    }
  }, [jobsLoaded]);

  const openDrawer = useCallback(
    async (rowId: string) => {
      if (!poolId) return;
      setDrawerLoading(true);
      try {
        const detail = await api.bulkIntakeRowDetail(poolId, rowId);
        setDrawerRow(detail);
      } catch {}
      setDrawerLoading(false);
    },
    [poolId],
  );

  // Auto-open the drawer when we arrived here with ?row=<row_id>. Run once
  // the leaderboard has loaded so we know the row is visible; also scroll
  // it into view and briefly highlight it so HR can tell where they landed.
  useEffect(() => {
    if (didDeepLinkRef.current) return;
    if (!deepLinkRowId) return;
    if (leaderboard.length === 0) return;
    const match = leaderboard.find((e) => e.row_id === deepLinkRowId);
    if (!match) return;
    didDeepLinkRef.current = true;
    openDrawer(deepLinkRowId);
    // Defer scroll until the row renders
    setTimeout(() => {
      const el = document.getElementById(`row-${deepLinkRowId}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("ring-2", "ring-axis-magenta");
        setTimeout(() => el.classList.remove("ring-2", "ring-axis-magenta"), 2500);
      }
    }, 200);
  }, [deepLinkRowId, leaderboard, openDrawer]);

  // Always open confirmation modal before routing
  const handleRouteClick = useCallback(
    (entry: BulkLeaderboardEntry, round: "L1" | "L2", e?: React.MouseEvent) => {
      if (e) e.stopPropagation();
      setRouteModal({ entry, round });
      setRouteModalAction("route");
      if (poolMode === "auto_map") {
        setRouteModalJobId(entry.best_job_id || allJobs[0]?.id || "");
      } else {
        // Single JD — use pool's job_id
        setRouteModalJobId("");
      }
    },
    [poolMode, allJobs],
  );

  // Execute the actual routing API call
  const executeRoute = useCallback(
    async (
      rowId: string,
      round: "L1" | "L2",
      opts?: { job_id?: string; action?: "route" | "notify" },
    ) => {
      if (!poolId) return;
      setRoutingRowId(rowId);
      try {
        const result = await api.routeCandidate(poolId, rowId, round, opts);
        setLeaderboard((prev) =>
          prev.map((entry) =>
            entry.row_id === rowId
              ? { ...entry, routed_to: result.routed_to as BulkLeaderboardEntry["routed_to"], application_id: result.application_id }
              : entry,
          ),
        );
        if (drawerRow && drawerRow.row_id === rowId) {
          setDrawerRow((prev) =>
            prev
              ? { ...prev, routed_to: result.routed_to as BulkLeaderboardEntry["routed_to"], application_id: result.application_id }
              : prev,
          );
        }
        setRouteToast(result.message);
        setTimeout(() => setRouteToast(null), 5000);
      } catch (err: any) {
        const msg = err?.message || "Routing failed";
        setRouteToast(msg);
        setTimeout(() => setRouteToast(null), 4000);
      }
      setRoutingRowId(null);
      setRouteModal(null);
    },
    [poolId, drawerRow],
  );

  if (!status) {
    return (
      <>
        <TopBar />
        <HRSubNav />
        <main className="min-h-screen bg-axis-surface flex items-center justify-center">
          <p className="text-sm text-axis-muted">Loading batch...</p>
        </main>
      </>
    );
  }

  if (status.status === "pending_review") {
    return (
      <>
        <TopBar />
        <HRSubNav />
        <main className="min-h-screen bg-axis-surface py-10 px-6">
          <div className="max-w-4xl mx-auto">
            <Link
              href="/hr/bulk-screening"
              className="text-xs text-axis-magenta hover:underline"
            >
              &larr; Back to all batches
            </Link>
            <div className="mt-6 bg-amber-50 border border-amber-200 rounded-card shadow-card p-6">
              <h2 className="text-lg font-display text-axis-ink mb-2">
                Contact details review pending
              </h2>
              <p className="text-sm text-axis-muted mb-4">
                Review and verify candidate contact details before starting the screening.
              </p>
              <Link
                href={`/hr/bulk-screening/${poolId}/review`}
                className="inline-flex items-center gap-1 px-4 py-2 text-sm font-semibold bg-axis-magenta text-white rounded hover:bg-axis-burgundy transition-colors"
              >
                Go to Review &rarr;
              </Link>
            </div>
          </div>
        </main>
        <Footer />
      </>
    );
  }

  const isProcessing = status.status === "processing";

  // Pre-compute auto-map role breakdown
  const roleBreakdown = (() => {
    const roleMap = new Map<string, { count: number; shortlisted: number }>();
    leaderboard.forEach((e) => {
      if (e.best_job_title && e.status !== "error") {
        const existing = roleMap.get(e.best_job_title) || { count: 0, shortlisted: 0 };
        existing.count++;
        if (e.recommendation === "shortlist") existing.shortlisted++;
        roleMap.set(e.best_job_title, existing);
      }
    });
    return Array.from(roleMap.entries());
  })();

  // Pre-compute processing bar counts
  const scoringCount = status.rows.filter((r) => r.status === "scoring" || r.status === "parsing").length;
  const doneCount = status.rows.filter((r) => r.status === "done").length;
  const queuedCount = status.rows.filter((r) => r.status === "queued").length;
  const erroredCount = status.rows.filter((r) => r.status === "error").length;

  // Pre-compute verdict filter counts & filtered leaderboard
  const shortlistCount = leaderboard.filter((e) => e.recommendation === "shortlist").length;
  const maybeCount = leaderboard.filter((e) => e.recommendation === "maybe").length;
  const rejectCount = leaderboard.filter((e) => e.recommendation === "reject").length;
  const filteredLeaderboard = verdictFilter === "all"
    ? leaderboard
    : verdictFilter === "shortlist_maybe"
      ? leaderboard.filter((e) => e.recommendation === "shortlist" || e.recommendation === "maybe" || e.status === "error")
      : leaderboard.filter((e) => e.recommendation === verdictFilter || e.status === "error");

  return (
    <>
      <TopBar />
      <HRSubNav />
      <main className="min-h-screen bg-axis-surface py-10 px-6">
        <div className="max-w-6xl mx-auto">
          {/* Header */}
          <Link
            href="/hr/bulk-screening"
            className="text-xs text-axis-magenta hover:underline"
          >
            &larr; Back to all batches
          </Link>

          <div className="flex items-start justify-between mt-4 mb-4">
            <div>
              <div className="h-1 w-16 bg-axis-burgundy rounded mb-3" />
              <h1 className="text-2xl font-display text-axis-ink">
                {poolMode === "auto_map" ? "Auto-mapped Screening" : status.job_title}
              </h1>
              <p className="text-xs text-axis-muted mt-1">
                {status.total} CVs &middot;{" "}
                {new Date(status.created_at).toLocaleDateString("en-IN", {
                  day: "numeric",
                  month: "short",
                  year: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
                {" "}&middot; Batch {status.pool_id.slice(0, 12)}
              </p>
              {status.custom_criteria && (
                <div className="mt-3 p-2.5 rounded border border-axis-magenta/30 bg-axis-magenta/5 max-w-2xl">
                  <p className="text-[10px] uppercase tracking-wider font-semibold text-axis-magenta mb-1">
                    Additional screening criteria applied
                  </p>
                  <p className="text-xs text-axis-ink-soft leading-relaxed whitespace-pre-wrap">
                    {status.custom_criteria}
                  </p>
                </div>
              )}
            </div>
            {!isProcessing && poolId && (
              <a
                href={api.bulkIntakeExportUrl(poolId)}
                className="px-4 py-2 text-xs font-semibold border border-axis-magenta text-axis-magenta rounded hover:bg-axis-magenta hover:text-white transition-colors"
              >
                Export CSV
              </a>
            )}
          </div>

          {/* Role info card */}
          {!isProcessing && (
            <div className={`mb-6 rounded-card border p-4 ${
              poolMode === "auto_map"
                ? "bg-indigo-50/40 border-indigo-200"
                : "bg-axis-burgundy/5 border-axis-burgundy/20"
            }`}>
              {poolMode === "auto_map" ? (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-[10px] px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded-full font-semibold">
                      Auto-mapped
                    </span>
                    <span className="text-xs text-axis-muted">
                      Candidates scored against all open requisitions to find best fit
                    </span>
                  </div>
                  {/* Show role breakdown from leaderboard */}
                  {roleBreakdown.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-1">
                      {roleBreakdown.map(([title, { count, shortlisted }]) => (
                        <span
                          key={title}
                          className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 bg-white border border-indigo-200 rounded-lg"
                        >
                          <span className="font-semibold text-axis-ink">{title}</span>
                          <span className="text-axis-muted">
                            {count} candidate{count > 1 ? "s" : ""}
                            {shortlisted > 0 && (
                              <span className="text-green-600 font-semibold"> · {shortlisted} shortlisted</span>
                            )}
                          </span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-axis-burgundy/10 flex items-center justify-center">
                    <span className="text-axis-burgundy text-lg font-bold">
                      {status.job_title?.charAt(0) || "R"}
                    </span>
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-axis-ink">{status.job_title}</p>
                    <p className="text-[11px] text-axis-muted">
                      Single requisition screening &middot; {status.total} CVs ranked against this role
                    </p>
                    {allJobs.length > 1 && (
                      <p className="text-[10px] text-indigo-600 mt-0.5">
                        Candidates also scored against {allJobs.length - 1} other open role{allJobs.length > 2 ? "s" : ""} for cross-JD insights
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Progress bar */}
          {isProcessing && (
            <div className="mb-8 border border-axis-magenta/30 bg-axis-magenta/5 rounded-card p-5">
              <div className="flex items-center gap-3 mb-3">
                <span className="inline-block w-5 h-5 rounded-full border-2 border-axis-magenta border-t-transparent animate-spin" />
                <div>
                  <p className="text-sm font-semibold text-axis-ink">
                    AI is screening {status.total} CVs{scoringCount > 1 ? ` (${scoringCount} in parallel)` : ""}...
                  </p>
                  <p className="text-xs text-axis-muted">
                    {doneCount} completed{scoringCount > 0 ? ` · ${scoringCount} scoring now` : ""}{queuedCount > 0 ? ` · ${queuedCount} queued` : ""}{erroredCount > 0 ? ` · ${erroredCount} failed` : ""}
                  </p>
                </div>
              </div>
              <div className="w-full bg-axis-divider rounded-full h-2">
                <div
                  className="bg-axis-magenta h-2 rounded-full transition-all duration-500"
                  style={{ width: `${status.progress_pct}%` }}
                />
              </div>
              {/* Live row status chips */}
              <div className="mt-3 flex flex-wrap gap-1">
                {status.rows.map((r) => (
                  <span
                    key={r.row_id}
                    className={`text-[10px] px-1.5 py-0.5 rounded ${
                      r.status === "done"
                        ? "bg-green-50 text-green-700"
                        : r.status === "error"
                          ? "bg-red-50 text-red-700"
                          : r.status === "scoring"
                            ? "bg-amber-50 text-amber-700 animate-pulse"
                            : r.status === "parsing"
                              ? "bg-blue-50 text-blue-700 animate-pulse"
                              : "bg-gray-50 text-gray-500"
                    }`}
                  >
                    {r.file_name.split(".")[0].slice(0, 20)}: {r.status}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Failed batch banner */}
          {status.status === "failed" && (
            <div className="mb-6 border border-red-200 bg-red-50 rounded-card p-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-red-700">
                  Batch partially failed
                </p>
                <p className="text-xs text-red-600 mt-0.5">
                  Some CVs could not be processed (server restarted during screening). Create a new batch to re-screen them.
                </p>
              </div>
              <Link
                href="/hr/bulk-screening/new"
                className="px-4 py-2 text-xs font-semibold bg-axis-magenta text-white rounded hover:bg-axis-burgundy transition-colors whitespace-nowrap"
              >
                New Batch
              </Link>
            </div>
          )}

          {/* Summary strip */}
          {!isProcessing && (
            <div className="grid grid-cols-4 gap-4 mb-8">
              {[
                { label: "Total CVs", value: status.total },
                {
                  label: "Shortlist",
                  value: status.rows.filter((r) => r.recommendation === "shortlist").length,
                  color: "text-green-700",
                },
                {
                  label: "Maybe",
                  value: status.rows.filter((r) => r.recommendation === "maybe").length,
                  color: "text-amber-600",
                },
                {
                  label: "Reject",
                  value: status.rows.filter((r) => r.recommendation === "reject").length,
                  color: "text-red-600",
                },
              ].map((kpi) => (
                <div
                  key={kpi.label}
                  className="bg-axis-canvas border border-axis-divider rounded-card p-4 text-center"
                >
                  <p className={`text-2xl font-bold ${kpi.color || "text-axis-ink"}`}>
                    {kpi.value}
                  </p>
                  <p className="text-xs text-axis-muted mt-1">{kpi.label}</p>
                </div>
              ))}
            </div>
          )}

          {/* Leaderboard table */}
          {!isProcessing && leaderboard.length > 0 && (
            <>
            {/* Verdict filter bar */}
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[10px] font-semibold text-axis-muted uppercase tracking-wide">Show:</span>
              {([
                { key: "shortlist_maybe", label: "Shortlisted + Maybe", count: shortlistCount + maybeCount, color: "bg-green-100 text-green-800 border-green-300" },
                { key: "shortlist", label: "Shortlisted only", count: shortlistCount, color: "bg-green-100 text-green-800 border-green-300" },
                { key: "maybe", label: "Maybe only", count: maybeCount, color: "bg-amber-100 text-amber-800 border-amber-300" },
                { key: "reject", label: "Rejected", count: rejectCount, color: "bg-red-100 text-red-800 border-red-300" },
                { key: "all", label: "All", count: leaderboard.length, color: "bg-axis-magenta/10 text-axis-magenta border-axis-magenta/30" },
              ] as const).map(({ key, label, count, color }) => (
                <button
                  key={key}
                  onClick={() => setVerdictFilter(key)}
                  className={`px-2.5 py-1 text-[11px] font-medium rounded-full border transition-colors ${
                    verdictFilter === key ? color : "bg-white text-axis-muted border-axis-divider hover:border-axis-magenta/30"
                  }`}
                >
                  {label} ({count})
                </button>
              ))}
            </div>

            <div className="bg-axis-canvas border border-axis-divider rounded-card shadow-card overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-axis-divider bg-axis-surface">
                    <th className="text-left px-4 py-3 text-xs font-semibold text-axis-muted">#</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-axis-muted">Candidate</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-axis-muted">
                      {poolMode === "auto_map" ? "Best Fit Role" : "Cross-JD Insight"}
                    </th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-axis-muted">Match</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-axis-muted">Verdict</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-axis-muted">Headline</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-axis-muted">Skills</th>
                    <th className="text-center px-4 py-3 text-xs font-semibold text-axis-muted">Shortlist for Interview</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLeaderboard.map((entry) => {
                    const isError = entry.status === "error";
                    return (
                    <tr
                      key={entry.row_id}
                      id={`row-${entry.row_id}`}
                      className={`border-b border-axis-divider/50 transition ${isError ? "opacity-50 bg-red-50/30" : "hover:bg-axis-surface/50 cursor-pointer"}`}
                      onClick={() => !isError && openDrawer(entry.row_id)}
                    >
                      <td className="px-4 py-3 text-axis-muted font-mono text-xs">
                        {entry.rank}
                      </td>
                      <td className="px-4 py-3">
                        <p className={`font-semibold ${isError ? "text-axis-muted" : "text-axis-ink"}`}>
                          {entry.candidate_name || entry.file_name}
                        </p>
                        {entry.candidate_email && (
                          <p className="text-[11px] text-axis-muted">
                            {entry.candidate_email}
                          </p>
                        )}
                        {isError && (
                          <p className="text-[10px] text-red-500 mt-0.5">
                            Failed — re-upload in a new batch
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {isError ? (
                          <span className="text-xs text-red-400">--</span>
                        ) : poolMode === "auto_map" ? (
                          entry.best_job_title ? (
                            <div>
                              <p className="text-xs font-semibold text-axis-ink">
                                {entry.best_job_title}
                              </p>
                              {entry.all_job_scores && entry.all_job_scores.length > 1 && (
                                <p className="text-[10px] text-axis-muted mt-0.5">
                                  +{entry.all_job_scores.length - 1} other role{entry.all_job_scores.length > 2 ? "s" : ""} scored
                                </p>
                              )}
                            </div>
                          ) : (
                            <span className="text-xs text-axis-muted">Pending</span>
                          )
                        ) : entry.all_job_scores && entry.all_job_scores.length > 1 ? (
                          entry.best_job_id !== status?.job_id ? (
                            <div>
                              <p className="text-[11px] font-semibold text-indigo-700">
                                Better fit: {entry.best_job_title}
                              </p>
                              <p className="text-[10px] text-axis-muted mt-0.5">
                                {entry.all_job_scores[0].match_percent.toFixed(0)}% match
                              </p>
                            </div>
                          ) : (
                            <span className="text-[11px] text-green-700 font-semibold">Best match &#10003;</span>
                          )
                        ) : (
                          <span className="text-[10px] text-axis-muted">--</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {isError ? (
                          <span className="text-xs text-red-400">—</span>
                        ) : (
                        <span
                          className={`font-bold ${
                            (entry.match_percent || 0) >= 75
                              ? "text-green-700"
                              : (entry.match_percent || 0) >= 50
                                ? "text-amber-600"
                                : "text-red-600"
                          }`}
                        >
                          {entry.match_percent?.toFixed(0)}%
                        </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {isError ? (
                          <span className="text-[10px] px-2 py-0.5 rounded bg-red-50 text-red-500 border border-red-200">
                            failed
                          </span>
                        ) : (
                        <span
                          className={`text-xs px-2 py-0.5 rounded ${
                            entry.recommendation === "shortlist"
                              ? "bg-green-50 text-green-700 border border-green-200"
                              : entry.recommendation === "maybe"
                                ? "bg-amber-50 text-amber-600 border border-amber-200"
                                : "bg-red-50 text-red-600 border border-red-200"
                          }`}
                        >
                          {entry.recommendation}
                        </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-axis-muted max-w-[200px] truncate">
                        {isError ? "—" : entry.headline}
                      </td>
                      <td className="px-4 py-3 text-xs text-axis-muted">
                        {isError ? "—" : `${entry.matched_skills.length}/${entry.matched_skills.length + entry.missing_skills.length}`}
                      </td>
                      <td className="px-4 py-3 text-center" onClick={(e) => e.stopPropagation()}>
                        {isError ? (
                          <span className="text-[10px] text-red-400">—</span>
                        ) : entry.routed_to ? (
                          entry.routed_to.startsWith("notified") ? (
                            <span className="inline-flex items-center gap-1 text-[11px] px-2 py-1 bg-indigo-50 text-indigo-700 border border-indigo-200 rounded font-semibold">
                              Notified
                            </span>
                          ) : entry.application_id ? (
                          <Link
                            href={`/hr/applications/${entry.application_id}`}
                            className="inline-flex items-center gap-1 text-[11px] px-2 py-1 bg-axis-burgundy/10 text-axis-burgundy border border-axis-burgundy/20 rounded font-semibold hover:bg-axis-burgundy/20 transition-colors"
                            onClick={(e) => e.stopPropagation()}
                          >
                            Routed to {entry.routed_to} &rarr;
                          </Link>
                          ) : (
                            <span className="text-[11px] text-axis-muted">{entry.routed_to}</span>
                          )
                        ) : (
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={(e) => handleRouteClick(entry, "L1", e)}
                              disabled={routingRowId === entry.row_id}
                              className="text-[11px] px-2.5 py-1 bg-axis-magenta text-white rounded hover:bg-axis-burgundy transition-colors disabled:opacity-50 font-semibold"
                            >
                              {routingRowId === entry.row_id ? "..." : "L1"}
                            </button>
                            <button
                              onClick={(e) => handleRouteClick(entry, "L2", e)}
                              disabled={routingRowId === entry.row_id}
                              className="text-[11px] px-2.5 py-1 bg-white text-axis-magenta border border-axis-magenta rounded hover:bg-axis-magenta hover:text-white transition-colors disabled:opacity-50 font-semibold"
                            >
                              {routingRowId === entry.row_id ? "..." : "L2"}
                            </button>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-axis-magenta text-xs">
                        {isError ? "" : "View →"}
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            </>
          )}
        </div>
      </main>

      {/* Route success toast */}
      {routeToast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[60] bg-axis-ink text-white px-6 py-3 rounded-lg shadow-xl text-sm font-medium max-w-lg text-center animate-fade-in">
          {routeToast}
        </div>
      )}

      {/* Drill-in drawer */}
      {(drawerRow || drawerLoading) && (
        <div className="fixed inset-0 z-50 flex">
          <div
            className="flex-1 bg-black/30"
            onClick={() => setDrawerRow(null)}
          />
          <div className="w-[480px] bg-axis-canvas border-l border-axis-divider shadow-2xl overflow-y-auto p-6">
            {drawerLoading && !drawerRow ? (
              <p className="text-sm text-axis-muted">Loading...</p>
            ) : drawerRow ? (
              <>
                <button
                  onClick={() => setDrawerRow(null)}
                  className="text-xs text-axis-magenta hover:underline mb-4"
                >
                  &times; Close
                </button>
                <h2 className="text-lg font-display text-axis-ink mb-1">
                  {drawerRow.candidate_name || drawerRow.file_name}
                </h2>
                {drawerRow.candidate_email && (
                  <p className="text-xs text-axis-muted mb-2">
                    {drawerRow.candidate_email}
                  </p>
                )}

                {/* Cross-JD role scores (auto_map and single_jd with cross-JD data) */}
                {drawerRow.best_job_title && drawerRow.all_job_scores && drawerRow.all_job_scores.length > 1 && (
                  <div className="mb-4 p-3 bg-indigo-50/50 border border-indigo-200 rounded-lg">
                    <p className="text-[11px] font-semibold text-indigo-800 mb-1 uppercase tracking-wider">
                      {poolMode === "auto_map" ? "Best Fit Role" : "Cross-JD Role Matches"}
                    </p>
                    <p className="text-sm font-semibold text-axis-ink mb-2">
                      {drawerRow.best_job_title}
                    </p>
                    {drawerRow.all_job_scores && drawerRow.all_job_scores.length > 0 && (
                      <>
                        <p className="text-[10px] font-semibold text-axis-muted mb-1 uppercase tracking-wider">
                          All Role Scores
                        </p>
                        <div className="space-y-1">
                          {drawerRow.all_job_scores.map((js: any, i: number) => (
                            <div
                              key={js.job_id}
                              className={`flex items-center justify-between text-[11px] px-2 py-1 rounded ${
                                i === 0 ? "bg-indigo-100/80 font-semibold" : "bg-white/60"
                              }`}
                            >
                              <span className="text-axis-ink truncate max-w-[220px]">
                                {js.job_title}
                              </span>
                              <div className="flex items-center gap-2">
                                <span
                                  className={`font-bold ${
                                    js.match_percent >= 75
                                      ? "text-green-700"
                                      : js.match_percent >= 50
                                        ? "text-amber-600"
                                        : "text-red-600"
                                  }`}
                                >
                                  {js.match_percent.toFixed(0)}%
                                </span>
                                <span
                                  className={`text-[9px] px-1.5 py-0.5 rounded ${
                                    js.recommendation === "shortlist"
                                      ? "bg-green-50 text-green-700"
                                      : js.recommendation === "maybe"
                                        ? "bg-amber-50 text-amber-600"
                                        : "bg-red-50 text-red-600"
                                  }`}
                                >
                                  {js.recommendation}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}

                {/* Score badge */}
                <div className="flex items-center gap-4 mb-6">
                  <div
                    className={`text-3xl font-bold ${
                      (drawerRow.match_percent || 0) >= 75
                        ? "text-green-700"
                        : (drawerRow.match_percent || 0) >= 50
                          ? "text-amber-600"
                          : "text-red-600"
                    }`}
                  >
                    {drawerRow.match_percent?.toFixed(0)}%
                  </div>
                  <span
                    className={`text-xs px-2 py-1 rounded ${
                      drawerRow.recommendation === "shortlist"
                        ? "bg-green-50 text-green-700"
                        : drawerRow.recommendation === "maybe"
                          ? "bg-amber-50 text-amber-600"
                          : "bg-red-50 text-red-600"
                    }`}
                  >
                    {drawerRow.recommendation?.toUpperCase()}
                  </span>
                </div>

                {/* Route action buttons */}
                <div className="mb-6 p-4 bg-axis-surface border border-axis-divider rounded-card">
                  <p className="text-[11px] font-semibold text-axis-muted mb-2 uppercase tracking-wider">
                    Shortlist for Interview
                  </p>
                  {drawerRow.routed_to ? (
                    <div className="flex items-center gap-2">
                      <span className={`text-xs px-3 py-1.5 rounded font-semibold ${
                        drawerRow.routed_to.startsWith("notified")
                          ? "bg-indigo-50 text-indigo-700 border border-indigo-200"
                          : "bg-axis-burgundy/10 text-axis-burgundy border border-axis-burgundy/20"
                      }`}>
                        {drawerRow.routed_to.startsWith("notified") ? "Candidate notified" : `Routed to ${drawerRow.routed_to}`}
                      </span>
                      {drawerRow.application_id && (
                      <Link
                        href={`/hr/applications/${drawerRow.application_id}`}
                        className="text-xs text-axis-magenta hover:underline font-semibold"
                      >
                        View application &rarr;
                      </Link>
                      )}
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          const entry = leaderboard.find(e => e.row_id === drawerRow!.row_id);
                          if (entry) handleRouteClick(entry, "L1");
                          else executeRoute(drawerRow!.row_id, "L1");
                        }}
                        disabled={routingRowId === drawerRow.row_id}
                        className="flex-1 py-2 text-sm font-semibold bg-axis-magenta text-white rounded hover:bg-axis-burgundy transition-colors disabled:opacity-50"
                      >
                        {routingRowId === drawerRow.row_id ? "Shortlisting..." : "Shortlist for L1 (R1 Interview)"}
                      </button>
                      <button
                        onClick={() => {
                          const entry = leaderboard.find(e => e.row_id === drawerRow!.row_id);
                          if (entry) handleRouteClick(entry, "L2");
                          else executeRoute(drawerRow!.row_id, "L2");
                        }}
                        disabled={routingRowId === drawerRow.row_id}
                        className="flex-1 py-2 text-sm font-semibold bg-white text-axis-magenta border border-axis-magenta rounded hover:bg-axis-magenta hover:text-white transition-colors disabled:opacity-50"
                      >
                        {routingRowId === drawerRow.row_id ? "Shortlisting..." : "Shortlist for L2 (R2 Panel)"}
                      </button>
                    </div>
                  )}
                  <p className="text-[10px] text-axis-muted mt-2">
                    {drawerRow.routed_to
                      ? drawerRow.routed_to === "L1"
                        ? "Candidate has been notified with R1 interview slot options."
                        : "Application awaits HR panel selection for R2 scheduling."
                      : "L1 sends the candidate directly to an AI-powered R1 interview. L2 skips R1 and schedules a panel interview."}
                  </p>
                </div>

                {/* Headline */}
                {drawerRow.headline && (
                  <p className="text-sm font-semibold text-axis-ink mb-1">
                    {drawerRow.headline}
                  </p>
                )}
                {drawerRow.summary && (
                  <p className="text-xs text-axis-muted mb-4">
                    {drawerRow.summary}
                  </p>
                )}

                {/* HR additional-criteria assessment — shown only when
                    the pool was created with custom_criteria. Each row
                    shows the criterion, a verdict chip (met/partial/
                    not_met/unclear), and the AI's evidence sentence.
                    This is what answers "did the AI actually weigh my
                    extra requirements?" — without this block HR can't
                    tell the criteria were honoured. */}
                {drawerRow.pool_custom_criteria &&
                  drawerRow.criteria_assessment &&
                  drawerRow.criteria_assessment.length > 0 && (
                  <div className="mb-4 p-3 rounded border border-axis-magenta/30 bg-axis-magenta/5">
                    <p className="text-[11px] font-semibold text-axis-magenta mb-2 uppercase tracking-wider">
                      Additional Criteria — Per-criterion Assessment
                    </p>
                    <ul className="space-y-2">
                      {drawerRow.criteria_assessment.map((item, i) => {
                        const chip =
                          item.verdict === "met"
                            ? "bg-green-100 text-green-800 border-green-200"
                            : item.verdict === "partial"
                            ? "bg-amber-100 text-amber-800 border-amber-200"
                            : item.verdict === "not_met"
                            ? "bg-red-100 text-red-800 border-red-200"
                            : "bg-slate-100 text-slate-600 border-slate-200";
                        const label =
                          item.verdict === "not_met"
                            ? "NOT MET"
                            : item.verdict.toUpperCase();
                        return (
                          <li key={i} className="text-xs">
                            <div className="flex items-start gap-2">
                              <span
                                className={`shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded border ${chip}`}
                              >
                                {label}
                              </span>
                              <span className="text-axis-ink font-medium">
                                {item.criterion}
                              </span>
                            </div>
                            {item.evidence && (
                              <p className="text-[11px] text-axis-muted mt-0.5 ml-[52px] leading-snug">
                                {item.evidence}
                              </p>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}

                {/* No-assessment fallback — criteria were supplied but
                    the model returned an empty array (shouldn't normally
                    happen with the updated prompt). Tell HR explicitly
                    so they don't assume silence == "all met". */}
                {drawerRow.pool_custom_criteria &&
                  (!drawerRow.criteria_assessment ||
                    drawerRow.criteria_assessment.length === 0) && (
                  <div className="mb-4 p-3 rounded border border-amber-200 bg-amber-50 text-xs text-amber-900">
                    Additional criteria were applied but the per-criterion
                    breakdown is not available for this candidate. Re-run
                    screening to regenerate the assessment.
                  </div>
                )}

                {/* Strengths */}
                {drawerRow.strengths.length > 0 && (
                  <div className="mb-4">
                    <p className="text-[11px] font-semibold text-green-700 mb-1">
                      STRENGTHS
                    </p>
                    <ul className="space-y-1">
                      {drawerRow.strengths.map((s, i) => (
                        <li key={i} className="text-xs text-axis-ink flex gap-1">
                          <span className="text-green-500">+</span> {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Concerns */}
                {drawerRow.concerns.length > 0 && (
                  <div className="mb-4">
                    <p className="text-[11px] font-semibold text-red-600 mb-1">
                      CONCERNS
                    </p>
                    <ul className="space-y-1">
                      {drawerRow.concerns.map((c, i) => (
                        <li key={i} className="text-xs text-axis-ink flex gap-1">
                          <span className="text-red-400">-</span> {c}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Evidence quotes */}
                {drawerRow.evidence_quotes.length > 0 && (
                  <div className="mb-4">
                    <p className="text-[11px] font-semibold text-axis-muted mb-1">
                      EVIDENCE FROM CV
                    </p>
                    {drawerRow.evidence_quotes.map((q, i) => (
                      <blockquote
                        key={i}
                        className="text-xs italic text-axis-ink border-l-2 border-axis-magenta/40 pl-2 py-1 mb-1"
                      >
                        "{q}"
                      </blockquote>
                    ))}
                  </div>
                )}

                {/* Skills */}
                <div className="flex gap-4 mb-4">
                  <div className="flex-1">
                    <p className="text-[11px] font-semibold text-axis-muted mb-1">
                      MATCHED SKILLS
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {drawerRow.matched_skills.map((s) => (
                        <span
                          key={s}
                          className="text-[10px] px-1.5 py-0.5 bg-green-50 text-green-700 rounded"
                        >
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex-1">
                    <p className="text-[11px] font-semibold text-axis-muted mb-1">
                      MISSING SKILLS
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {drawerRow.missing_skills.map((s) => (
                        <span
                          key={s}
                          className="text-[10px] px-1.5 py-0.5 bg-red-50 text-red-600 rounded"
                        >
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </>
            ) : null}
          </div>
        </div>
      )}

      {/* ── Routing Modal (auto-map: pick requisition + action) ── */}
      {/* ── Routing Confirmation Modal ── */}
      {routeModal && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setRouteModal(null)} />
          <div className="relative bg-axis-canvas rounded-xl shadow-2xl border border-axis-divider w-full max-w-lg mx-4 p-6 animate-fade-in">
            <button
              onClick={() => setRouteModal(null)}
              className="absolute top-3 right-3 text-axis-muted hover:text-axis-ink text-lg"
            >
              &times;
            </button>

            <h3 className="text-lg font-display text-axis-ink mb-1">
              Shortlist {routeModal.entry.candidate_name || routeModal.entry.file_name}
            </h3>
            <p className="text-xs text-axis-muted mb-5">
              {poolMode === "auto_map"
                ? `Choose the requisition and how to proceed for ${routeModal.round} interview.`
                : `Confirm shortlisting for ${routeModal.round} interview for ${status?.job_title || "this role"}.`}
            </p>

            {/* Single JD: show role info card */}
            {poolMode !== "auto_map" && status?.job_title && (
              <div className="mb-4 p-3 bg-axis-burgundy/5 border border-axis-burgundy/20 rounded-lg">
                <p className="text-[10px] font-semibold text-axis-muted uppercase tracking-wider mb-0.5">Requisition</p>
                <p className="text-sm font-semibold text-axis-ink">{status.job_title}</p>
              </div>
            )}

            {/* Auto-map: Requisition picker */}
            {poolMode === "auto_map" && (
              <>
                <label className="block text-xs font-semibold text-axis-ink mb-1.5">
                  Select Requisition
                </label>
                <select
                  value={routeModalJobId}
                  onChange={(e) => setRouteModalJobId(e.target.value)}
                  className="w-full border border-axis-divider rounded-lg px-3 py-2.5 text-sm text-axis-ink bg-white mb-1 focus:outline-none focus:ring-2 focus:ring-axis-magenta/30"
                >
                  {routeModal.entry.all_job_scores && routeModal.entry.all_job_scores.length > 0 ? (
                    <>
                      <optgroup label="Scored roles (ranked by fit)">
                        {routeModal.entry.all_job_scores.map((js) => (
                          <option key={js.job_id} value={js.job_id}>
                            {js.job_title} — {js.match_percent}% match ({js.recommendation})
                          </option>
                        ))}
                      </optgroup>
                      {allJobs.filter(j => !routeModal.entry.all_job_scores?.some(s => s.job_id === j.id)).length > 0 && (
                        <optgroup label="Other open requisitions">
                          {allJobs
                            .filter(j => !routeModal.entry.all_job_scores?.some(s => s.job_id === j.id))
                            .map(j => (
                              <option key={j.id} value={j.id}>
                                {j.title}{j.location ? ` — ${j.location}` : ""}
                              </option>
                            ))}
                        </optgroup>
                      )}
                    </>
                  ) : (
                    allJobs.map(j => (
                      <option key={j.id} value={j.id}>
                        {j.title}{j.location ? ` — ${j.location}` : ""}
                      </option>
                    ))
                  )}
                </select>
                {routeModal.entry.best_job_id === routeModalJobId && (
                  <p className="text-[10px] text-green-600 mb-4">Best fit based on CV screening</p>
                )}
                {routeModal.entry.best_job_id !== routeModalJobId && (
                  <p className="text-[10px] text-axis-muted mb-4">&nbsp;</p>
                )}
              </>
            )}

            {/* Candidate summary */}
            <div className="mb-4 p-3 bg-axis-surface border border-axis-divider rounded-lg flex items-center gap-3">
              <div className="flex-1">
                <p className="text-sm font-semibold text-axis-ink">
                  {routeModal.entry.candidate_name || routeModal.entry.file_name}
                </p>
                {routeModal.entry.candidate_email && (
                  <p className="text-[11px] text-axis-muted">{routeModal.entry.candidate_email}</p>
                )}
              </div>
              <div className="text-right">
                <span className={`text-lg font-bold ${
                  (routeModal.entry.match_percent || 0) >= 75 ? "text-green-700"
                    : (routeModal.entry.match_percent || 0) >= 50 ? "text-amber-600"
                    : "text-red-600"
                }`}>
                  {routeModal.entry.match_percent?.toFixed(0)}%
                </span>
                <span className={`ml-1.5 text-[10px] px-1.5 py-0.5 rounded ${
                  routeModal.entry.recommendation === "shortlist" ? "bg-green-50 text-green-700"
                    : routeModal.entry.recommendation === "maybe" ? "bg-amber-50 text-amber-600"
                    : "bg-red-50 text-red-600"
                }`}>
                  {routeModal.entry.recommendation}
                </span>
              </div>
            </div>

            {/* Action: Shortlist directly vs Notify candidate */}
            <label className="block text-xs font-semibold text-axis-ink mb-2">
              Action
            </label>
            <div className="grid grid-cols-2 gap-3 mb-6">
              <button
                type="button"
                onClick={() => setRouteModalAction("route")}
                className={`p-3 rounded-lg border-2 text-left transition-all ${
                  routeModalAction === "route"
                    ? "border-axis-magenta bg-axis-magenta/5"
                    : "border-axis-divider hover:border-axis-muted"
                }`}
              >
                <p className="text-sm font-semibold text-axis-ink">Shortlist directly</p>
                <p className="text-[11px] text-axis-muted mt-0.5">
                  Create application and schedule {routeModal.round} interview
                </p>
              </button>
              <button
                type="button"
                onClick={() => setRouteModalAction("notify")}
                className={`p-3 rounded-lg border-2 text-left transition-all ${
                  routeModalAction === "notify"
                    ? "border-indigo-500 bg-indigo-50/50"
                    : "border-axis-divider hover:border-axis-muted"
                }`}
              >
                <p className="text-sm font-semibold text-axis-ink">Notify candidate</p>
                <p className="text-[11px] text-axis-muted mt-0.5">
                  Send invite to apply via candidate portal
                </p>
              </button>
            </div>

            {/* Notification contact details (visible when notify is selected) */}
            {routeModalAction === "notify" && (
              <div className="mb-6 p-3 bg-indigo-50/60 border border-indigo-200 rounded-lg">
                <p className="text-[11px] font-semibold text-indigo-800 uppercase tracking-wider mb-2">
                  Notification will be sent to:
                </p>
                {routeModal.entry.candidate_email ? (
                  <div className="space-y-1">
                    <p className="text-sm text-axis-ink flex items-center gap-2">
                      <span className="text-axis-muted text-[11px] w-12">Email</span>
                      <span className="font-medium">{routeModal.entry.candidate_email}</span>
                    </p>
                    {routeModal.entry.candidate_phone ? (
                      <p className="text-sm text-axis-ink flex items-center gap-2">
                        <span className="text-axis-muted text-[11px] w-12">Phone</span>
                        <span className="font-medium">{routeModal.entry.candidate_phone}</span>
                      </p>
                    ) : (
                      <p className="text-[11px] text-amber-600 mt-1">
                        Phone not available — email notification only
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="text-[11px] text-red-600">
                    No contact details available for this candidate.
                  </p>
                )}
              </div>
            )}

            {/* Confirm button */}
            <div className="flex gap-3">
              <button
                onClick={() => setRouteModal(null)}
                className="flex-1 py-2.5 text-sm font-semibold border border-axis-divider text-axis-muted rounded-lg hover:bg-axis-surface transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() =>
                  executeRoute(routeModal.entry.row_id, routeModal.round, {
                    ...(poolMode === "auto_map" ? { job_id: routeModalJobId } : {}),
                    action: routeModalAction,
                  })
                }
                disabled={(poolMode === "auto_map" && !routeModalJobId) || routingRowId === routeModal.entry.row_id}
                className={`flex-1 py-2.5 text-sm font-semibold rounded-lg transition-colors disabled:opacity-50 ${
                  routeModalAction === "notify"
                    ? "bg-indigo-600 text-white hover:bg-indigo-700"
                    : "bg-axis-magenta text-white hover:bg-axis-burgundy"
                }`}
              >
                {routingRowId === routeModal.entry.row_id
                  ? "Processing..."
                  : routeModalAction === "notify"
                    ? "Send Notification"
                    : `Shortlist for ${routeModal.round}`}
              </button>
            </div>
          </div>
        </div>
      )}

      <Footer />
    </>
  );
}
