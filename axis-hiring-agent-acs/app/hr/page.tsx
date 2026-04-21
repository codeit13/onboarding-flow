"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { RoleGate } from "@/components/RoleGate";
import { AgentActivityFeed } from "@/components/agent/AgentActivityFeed";
import { AgentStatusBadge } from "@/components/agent/AgentStatusBadge";
import {
  api,
  type ActivityItem,
  type Application,
  type Candidate,
  type HrPartner,
  type Job,
  type JdRanking,
} from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";
import { STAGE_KANBAN, STAGE_LABEL } from "@/lib/stages";
import { usePersona } from "@/lib/persona";

/**
 * HR Partner kanban console.
 *
 * Live view of every requisition the current HR persona owns. Polls jobs +
 * applications + candidates + activity every 4 seconds via useAutoRefresh
 * (each loader is independent so a slow endpoint doesn't stall the others).
 *
 * The kanban itself is a "passenger" view of the orchestrator's state — the
 * agent moves cards through columns; HR clicks into a card to tick a
 * blocking checklist item or hit "Unblock agent" if the orchestrator wedged.
 * No advance buttons live here.
 */
export default function HRPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <HRPageContent />
    </RoleGate>
  );
}

function HRPageContent() {
  const [persona] = usePersona();
  const [jdFilter, setJdFilter] = useState<string>("all");
  const [sourceFilter, setSourceFilter] = useState<string>("all");

  const loadJobs = useCallback(() => api.listJobs(), []);
  const loadApps = useCallback(() => api.listApplications("hr"), []);
  const loadCands = useCallback(() => api.listCandidates(), []);
  const loadHr = useCallback(() => api.hrPartners(), []);
  const loadActivity = useCallback(() => api.listActivity(undefined, 60), []);

  const { data: jobsData, error: jobsErr, refresh: refreshJobs } =
    useAutoRefresh<Job[]>(loadJobs, 8000);
  const { data: appsData, refresh: refreshApps } = useAutoRefresh<Application[]>(
    loadApps,
    4000,
  );
  const { data: candsData } = useAutoRefresh<Candidate[]>(loadCands, 30000);
  const { data: hrData } = useAutoRefresh<HrPartner[]>(loadHr, 30000);
  const { data: activityData, refresh: refreshActivity } = useAutoRefresh<
    ActivityItem[]
  >(loadActivity, 4000);

  const jobs = jobsData ?? [];
  const apps = appsData ?? [];
  const cands = candsData ?? [];
  const hrPartners = hrData ?? [];

  // Restrict to current HR partner (when the persona identity matches one).
  const myJdIds = useMemo(() => {
    if (persona.role !== "hr_partner") return new Set(jobs.map((j) => j.id));
    const partner = hrPartners.find((p) => p.user_id === persona.identity);
    if (!partner) return new Set(jobs.map((j) => j.id));
    return new Set(partner.jobs.map((j) => j.id));
  }, [persona, hrPartners, jobs]);

  const visibleJobs = useMemo(
    () => jobs.filter((j) => myJdIds.has(j.id)),
    [jobs, myJdIds],
  );

  const filteredApps = useMemo(() => {
    return apps.filter((a) => {
      if (!myJdIds.has(a.job_id)) return false;
      if (jdFilter !== "all" && a.job_id !== jdFilter) return false;
      if (sourceFilter !== "all" && a.source !== sourceFilter) return false;
      return true;
    });
  }, [apps, myJdIds, jdFilter, sourceFilter]);

  // Filter the activity feed to applications visible to this HR partner.
  const visibleAppIds = useMemo(
    () => new Set(filteredApps.map((a) => a.id)),
    [filteredApps],
  );
  const filteredActivity = useMemo(() => {
    if (!activityData) return [];
    return activityData.filter(
      (it) => !it.application_id || visibleAppIds.has(it.application_id),
    );
  }, [activityData, visibleAppIds]);

  const candById = useMemo(() => {
    const m = new Map<string, Candidate>();
    cands.forEach((c) => m.set(c.id, c));
    return m;
  }, [cands]);

  const jobById = useMemo(() => {
    const m = new Map<string, Job>();
    jobs.forEach((j) => m.set(j.id, j));
    return m;
  }, [jobs]);

  // Funnel summary — useful at-a-glance signal in the header.
  const blockedCount = filteredApps.filter(
    (a) => a.pending_blocking_items.length > 0,
  ).length;
  const runningCount = filteredApps.filter((a) => a.agent_status === "running")
    .length;

  const refreshAll = () => {
    refreshJobs();
    refreshApps();
    refreshActivity();
  };

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <HRSubNav />

      <div className="bg-axis-burgundy/5 border-b border-axis-divider px-8 py-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <p className="text-[10px] text-axis-magenta font-semibold uppercase tracking-wider">
              Business Partner Console
            </p>
            <h1 className="text-xl font-semibold text-axis-ink mt-0.5">
              Hiring Funnel — {visibleJobs.length} requisition
              {visibleJobs.length === 1 ? "" : "s"}
            </h1>
            <p className="text-xs text-axis-muted mt-1">
              Autonomous agent · {filteredApps.length} applications ·{" "}
              <span className="text-axis-magenta font-semibold">
                {runningCount} running
              </span>
              {blockedCount > 0 && (
                <>
                  {" "}
                  ·{" "}
                  <span className="text-axis-burgundy font-semibold">
                    {blockedCount} waiting on you
                  </span>
                </>
              )}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={jdFilter}
              onChange={(e) => setJdFilter(e.target.value)}
              className="text-xs border border-axis-divider rounded px-2 py-1 bg-axis-canvas"
            >
              <option value="all">All JDs</option>
              {visibleJobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.job_id} · {j.title}
                </option>
              ))}
            </select>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="text-xs border border-axis-divider rounded px-2 py-1 bg-axis-canvas"
            >
              <option value="all">All sources</option>
              <option value="organic">Organic</option>
              <option value="bulk_screening">Bulk Screening</option>
              <option value="external_intake">External Intake</option>
            </select>
            <button
              onClick={refreshAll}
              className="text-xs px-3 py-1 rounded border border-axis-divider text-axis-ink-soft hover:bg-axis-surface"
            >
              Refresh
            </button>
            <Link
              href="/thrive"
              className="text-xs text-axis-magenta hover:underline font-medium"
            >
              ← Back to Thrive
            </Link>
          </div>
        </div>

      </div>

      <main className="flex-1 bg-axis-surface">
        {jobsErr && (
          <div className="m-8 p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
            Backend unreachable: {jobsErr}
          </div>
        )}

        {/* Live cross-candidate ranking — only when a single JD is selected. */}
        {jdFilter !== "all" && (
          <div className="px-8 pt-6">
            <JdLeaderboard jdId={jdFilter} />
          </div>
        )}

        <div className="flex">
          {/* Kanban */}
          <div className="flex-1 overflow-x-auto px-8 py-6">
            {!jobsErr && filteredApps.length === 0 && (
              <div className="p-6 bg-axis-canvas border border-axis-divider rounded-card text-sm text-axis-muted">
                No applications in scope yet. Hit{" "}
                <strong>Reset &amp; seed</strong> in the dark bar above, or go to{" "}
                <Link href="/thrive" className="text-axis-magenta underline">
                  Thrive
                </Link>{" "}
                and apply as an employee.
              </div>
            )}

            {filteredApps.length > 0 && (
              <div className="flex gap-4 min-w-max">
                {STAGE_KANBAN.map((stage) => {
                  const col = filteredApps.filter((a) => a.stage === stage);
                  return (
                    <div
                      key={stage}
                      className="w-64 shrink-0 bg-axis-canvas border border-axis-divider rounded-card"
                    >
                      <div className="px-3 py-2 border-b border-axis-divider flex items-center justify-between">
                        <span className="text-xs font-semibold text-axis-ink">
                          {STAGE_LABEL[stage]}
                        </span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-axis-surface text-axis-muted">
                          {col.length}
                        </span>
                      </div>
                      <div className="p-2 space-y-2 min-h-[120px]">
                        {col.map((a) => {
                          const cand = candById.get(a.candidate_id);
                          const job = jobById.get(a.job_id);
                          const blocked = a.pending_blocking_items.length > 0;
                          return (
                            <Link
                              key={a.id}
                              href={`/hr/applications/${a.id}`}
                              className={`block p-2 rounded border bg-axis-canvas ${
                                blocked
                                  ? "border-axis-magenta"
                                  : "border-axis-divider hover:border-axis-magenta"
                              }`}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-xs font-semibold text-axis-ink truncate">
                                  {cand?.name || a.candidate_id}
                                </span>
                                <div className="flex items-center gap-1 shrink-0">
                                  {a.source === "bulk_screening" && (
                                    <span className="text-[9px] px-1.5 py-0.5 bg-indigo-100 text-indigo-700 rounded-full font-semibold">
                                      Bulk
                                    </span>
                                  )}
                                  {a.source === "external_intake" && (
                                    <span className="text-[9px] px-1.5 py-0.5 bg-teal-100 text-teal-700 rounded-full font-semibold">
                                      External
                                    </span>
                                  )}
                                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-axis-pink-soft text-axis-burgundy">
                                    {a.match_percent.toFixed(0)}%
                                  </span>
                                </div>
                              </div>
                              <p className="text-[10px] text-axis-muted mt-0.5 truncate">
                                {a.candidate_id} · {job?.job_id}
                              </p>
                              <p
                                className="text-[10px] font-mono text-axis-magenta mt-0.5 truncate"
                                title={a.id}
                              >
                                {a.id}
                              </p>
                              <p className="text-[10px] text-axis-muted-light mt-0.5 truncate">
                                {job?.title}
                              </p>
                              <div className="mt-1 flex items-center justify-between gap-2">
                                <AgentStatusBadge status={a.agent_status} />
                                {blocked && (
                                  <span className="text-[9px] uppercase tracking-wider text-axis-burgundy font-semibold">
                                    Blocked
                                  </span>
                                )}
                              </div>
                              {a.next_action && (
                                <p className="text-[10px] text-axis-ink-soft mt-1 line-clamp-2">
                                  {a.next_action}
                                </p>
                              )}
                            </Link>
                          );
                        })}
                        {col.length === 0 && (
                          <p className="text-[10px] text-axis-muted-light text-center py-4">
                            empty
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Activity side panel */}
          <aside className="w-80 shrink-0 border-l border-axis-divider bg-axis-canvas px-4 py-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-axis-ink">
                Live agent activity
              </h2>
              <button
                onClick={refreshActivity}
                className="text-[10px] uppercase tracking-wider text-axis-magenta hover:underline"
              >
                Refresh
              </button>
            </div>
            <p className="text-[10px] text-axis-muted mb-3">
              Unified stream of emails, meetings, notifications and agent steps
              for the requisitions in your scope.
            </p>
            <AgentActivityFeed
              items={filteredActivity}
              maxHeight="max-h-[calc(100vh-260px)]"
              emptyLabel="No agent activity yet."
            />
          </aside>
        </div>
      </main>
      <Footer />
    </div>
  );
}

/**
 * Live cross-candidate leaderboard for one JD. Polls /jobs/:jdId/ranking
 * every 4 seconds so candidates rise/fall as R1 and R2 results land.
 */
function JdLeaderboard({ jdId }: { jdId: string }) {
  const load = useCallback(() => api.jdRanking(jdId), [jdId]);
  const { data, error } = useAutoRefresh<JdRanking>(load, 4000);

  if (error) {
    return (
      <div className="bg-axis-pink-soft border border-axis-magenta rounded p-3 text-xs text-axis-burgundy">
        Could not load ranking: {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="text-xs text-axis-muted">Loading leaderboard…</div>
    );
  }

  return (
    <div className="bg-axis-canvas border border-axis-divider rounded-card shadow-card">
      <div className="px-4 py-3 border-b border-axis-divider flex items-center justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
            Live cross-candidate ranking
          </p>
          <h2 className="text-sm font-semibold text-axis-ink mt-0.5">
            {data.active} active · {data.total} total applicants
          </h2>
        </div>
        <p className="text-[10px] text-axis-muted">
          Recomputed live as R1 / R2 results land
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-axis-surface text-axis-muted">
            <tr>
              <th className="px-3 py-2 text-left">#</th>
              <th className="px-3 py-2 text-left">Candidate</th>
              <th className="px-3 py-2 text-left">Tier</th>
              <th className="px-3 py-2 text-left">Score</th>
              <th className="px-3 py-2 text-left">Why the agent ranked them here</th>
            </tr>
          </thead>
          <tbody>
            {data.candidates.map((row) => (
              <tr key={row.application_id} className="border-t border-axis-divider">
                <td className="px-3 py-2 font-semibold text-axis-ink">{row.rank}</td>
                <td className="px-3 py-2">
                  <Link
                    href={`/hr/applications/${row.application_id}`}
                    className="text-axis-magenta hover:underline font-medium"
                  >
                    {row.candidate_name}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <span
                    className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${
                      row.tier === "offer"
                        ? "bg-emerald-100 text-emerald-700"
                        : row.tier === "post_r2"
                        ? "bg-axis-magenta/20 text-axis-magenta"
                        : row.tier === "post_r1"
                        ? "bg-amber-100 text-amber-700"
                        : row.tier === "rejected"
                        ? "bg-axis-burgundy/10 text-axis-burgundy"
                        : "bg-axis-divider/40 text-axis-ink-soft"
                    }`}
                  >
                    {row.tier.replace("_", " ")}
                  </span>
                </td>
                <td className="px-3 py-2 font-semibold text-axis-ink">
                  {row.score.toFixed(0)}
                </td>
                <td className="px-3 py-2 text-axis-ink-soft">{row.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
