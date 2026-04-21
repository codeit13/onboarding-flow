"use client";

import Link from "next/link";
import { useCallback, useMemo } from "react";
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
  type HrPartner,
  type Job,
} from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";
import { STAGE_KANBAN, STAGE_LABEL } from "@/lib/stages";
import { usePersona } from "@/lib/persona";

/**
 * HR Partner dashboard.
 *
 * The "what does my world look like right now" landing page. Funnels every
 * piece of state the HR persona cares about into a single screen:
 *
 *   - KPI strip:    open requisitions, candidates in flight, blocked apps,
 *                   apps the agent moved in the last hour, offers issued.
 *   - Funnel chart: stacked bar of apps per stage (filtered to the partner's
 *                   own JDs).
 *   - Action list:  applications that are paused on a blocking item — these
 *                   are the only things HR has to *do* in the autonomous
 *                   model.
 *   - Live feed:    the unified activity stream so the partner can scrub
 *                   what the agent has been doing.
 *
 * Polls every 4s via useAutoRefresh.
 */
export default function HRDashboardPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <HRDashboardContent />
    </RoleGate>
  );
}

function HRDashboardContent() {
  const [persona] = usePersona();

  const loadJobs = useCallback(() => api.listJobs(), []);
  const loadApps = useCallback(() => api.listApplications("hr"), []);
  const loadHr = useCallback(() => api.hrPartners(), []);
  const loadActivity = useCallback(() => api.listActivity(undefined, 80), []);

  const { data: jobsData } = useAutoRefresh<Job[]>(loadJobs, 8000);
  const { data: appsData, error: appsErr, refresh: refreshApps } =
    useAutoRefresh<Application[]>(loadApps, 4000);
  const { data: hrData } = useAutoRefresh<HrPartner[]>(loadHr, 30000);
  const { data: activityData, refresh: refreshActivity } = useAutoRefresh<
    ActivityItem[]
  >(loadActivity, 4000);

  const jobs = jobsData ?? [];
  const apps = appsData ?? [];
  const hrPartners = hrData ?? [];
  const activity = activityData ?? [];

  // Restrict to current HR partner's requisitions when the persona maps.
  const myJdIds = useMemo(() => {
    if (persona.role !== "hr_partner") return new Set(jobs.map((j) => j.id));
    const partner = hrPartners.find((p) => p.user_id === persona.identity);
    if (!partner) return new Set(jobs.map((j) => j.id));
    return new Set(partner.jobs.map((j) => j.id));
  }, [persona, hrPartners, jobs]);

  const myJobs = useMemo(
    () => jobs.filter((j) => myJdIds.has(j.id)),
    [jobs, myJdIds],
  );
  const myApps = useMemo(
    () => apps.filter((a) => myJdIds.has(a.job_id)),
    [apps, myJdIds],
  );

  // KPI numerators.
  const inFlight = myApps.filter(
    (a) => a.stage !== "rejected" && a.stage !== "offer",
  ).length;
  const blocked = myApps.filter((a) => a.pending_blocking_items.length > 0);
  const offers = myApps.filter((a) => a.stage === "offer").length;
  const rejected = myApps.filter((a) => a.stage === "rejected").length;

  // "Moved in last hour" — proxy: updated_at within 60 min.
  const oneHourAgo = Date.now() - 60 * 60 * 1000;
  const recentlyMoved = myApps.filter(
    (a) => new Date(a.updated_at).getTime() > oneHourAgo,
  ).length;

  // Funnel chart data.
  const funnelMax = Math.max(
    1,
    ...STAGE_KANBAN.map((s) => myApps.filter((a) => a.stage === s).length),
  );

  const visibleAppIds = useMemo(
    () => new Set(myApps.map((a) => a.id)),
    [myApps],
  );
  const filteredActivity = useMemo(
    () =>
      activity.filter(
        (it) => !it.application_id || visibleAppIds.has(it.application_id),
      ),
    [activity, visibleAppIds],
  );

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <HRSubNav />

      <main className="flex-1 px-8 py-6 max-w-7xl w-full mx-auto">
        <div className="flex items-end justify-between mb-6 flex-wrap gap-3">
          <div>
            <p className="text-[10px] text-axis-magenta font-semibold uppercase tracking-wider">
              Business Partner Dashboard
            </p>
            <h1 className="text-2xl font-display text-axis-ink mt-1">
              Good {greeting()},{" "}
              {persona.displayName?.split(" ")[0] || "team"}.
            </h1>
            <p className="text-xs text-axis-muted mt-1">
              The autonomous agent is running. You only need to step in when
              you see something blocked.
            </p>
          </div>
          <button
            onClick={() => {
              refreshApps();
              refreshActivity();
            }}
            className="text-xs px-3 py-1 rounded border border-axis-divider text-axis-ink-soft hover:bg-axis-surface"
          >
            Refresh
          </button>
        </div>

        {appsErr && (
          <div className="mb-4 p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
            Backend unreachable: {appsErr}
          </div>
        )}

        {/* KPI strip */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Kpi
            label="Open requisitions"
            value={myJobs.length}
            href="/hr/jobs"
          />
          <Kpi label="In flight" value={inFlight} href="/hr" />
          <Kpi
            label="Blocked on you"
            value={blocked.length}
            tone={blocked.length > 0 ? "alert" : "neutral"}
            href="/hr"
          />
          <Kpi
            label="Moved last hour"
            value={recentlyMoved}
            tone="positive"
          />
          <Kpi label="Offers issued" value={offers} tone="positive" />
        </div>

        <div className="grid lg:grid-cols-3 gap-4 mt-6">
          {/* Funnel chart */}
          <section className="lg:col-span-2 bg-axis-canvas border border-axis-divider rounded-card shadow-card p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-axis-ink">
                Funnel snapshot
              </h2>
              <Link
                href="/hr"
                className="text-[10px] text-axis-magenta uppercase tracking-wider hover:underline"
              >
                Open kanban →
              </Link>
            </div>
            <p className="text-[11px] text-axis-muted mt-0.5">
              {myApps.length} applications across {myJobs.length} requisitions
              · {rejected} rejected · {offers} offered
            </p>
            <div className="mt-4 space-y-2">
              {STAGE_KANBAN.map((s) => {
                const n = myApps.filter((a) => a.stage === s).length;
                const pct = (n / funnelMax) * 100;
                return (
                  <div key={s} className="flex items-center gap-3 text-xs">
                    <span className="w-24 shrink-0 text-axis-ink-soft">
                      {STAGE_LABEL[s]}
                    </span>
                    <div className="flex-1 h-3 bg-axis-surface rounded">
                      <div
                        className="h-3 bg-axis-magenta rounded transition-all"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="w-8 text-right tabular-nums text-axis-ink font-semibold">
                      {n}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Action queue */}
          <section className="bg-axis-canvas border border-axis-divider rounded-card shadow-card p-5">
            <h2 className="text-sm font-semibold text-axis-ink">
              Waiting on you
            </h2>
            <p className="text-[11px] text-axis-muted mt-0.5">
              The agent has paused on these — tick the blocking item to release
              it.
            </p>
            {blocked.length === 0 && (
              <p className="text-xs text-axis-muted-light italic mt-4">
                Nothing blocked. Enjoy the silence.
              </p>
            )}
            <ul className="mt-3 space-y-2">
              {blocked.slice(0, 6).map((a) => {
                const job = jobs.find((j) => j.id === a.job_id);
                return (
                  <li key={a.id}>
                    <Link
                      href={`/hr/applications/${a.id}`}
                      className="block p-2 border border-axis-magenta rounded hover:bg-axis-pink-soft/40"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-axis-ink truncate">
                          {a.candidate_id}
                        </span>
                        <AgentStatusBadge status={a.agent_status} />
                      </div>
                      <p className="text-[10px] text-axis-muted mt-0.5 truncate">
                        {job?.title || a.job_id}
                      </p>
                      <p className="text-[10px] text-axis-burgundy mt-1 truncate">
                        ⛔ {a.pending_blocking_items[0]}
                      </p>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>

        {/* Live activity */}
        <section className="mt-6 bg-axis-canvas border border-axis-divider rounded-card shadow-card p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-axis-ink">
              Live agent activity
            </h2>
            <Link
              href="/ops"
              className="text-[10px] text-axis-magenta uppercase tracking-wider hover:underline"
            >
              Full ops console →
            </Link>
          </div>
          <AgentActivityFeed
            items={filteredActivity}
            maxHeight="max-h-96"
            emptyLabel="No agent activity yet."
          />
        </section>
      </main>
      <Footer />
    </div>
  );
}

function Kpi({
  label,
  value,
  tone = "neutral",
  href,
}: {
  label: string;
  value: number;
  tone?: "neutral" | "positive" | "alert";
  href?: string;
}) {
  const toneClass =
    tone === "alert"
      ? "border-axis-magenta bg-axis-pink-soft text-axis-burgundy"
      : tone === "positive"
      ? "border-axis-cream-border bg-axis-cream text-axis-ink"
      : "border-axis-divider bg-axis-canvas text-axis-ink";
  const inner = (
    <div className={`p-4 rounded-card border ${toneClass}`}>
      <p className="text-[10px] uppercase tracking-wider opacity-70">{label}</p>
      <p className="text-3xl font-semibold mt-1 tabular-nums">{value}</p>
    </div>
  );
  if (href)
    return (
      <Link href={href} className="block hover:-translate-y-0.5 transition">
        {inner}
      </Link>
    );
  return inner;
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "morning";
  if (h < 17) return "afternoon";
  return "evening";
}
