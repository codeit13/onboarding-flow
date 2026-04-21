"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { RoleGate } from "@/components/RoleGate";
import {
  api,
  type Application,
  type HrPartner,
  type Job,
} from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";
import { usePersona } from "@/lib/persona";

/**
 * Requisitions index — every job description visible to the current HR
 * persona, with a per-JD live funnel snapshot.
 *
 * Polls jobs + applications independently. Each row is a click-through to
 * the JD detail page (overview / panel / pipeline / checklist tabs).
 */
export default function HRJobsIndexPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <HRJobsIndexContent />
    </RoleGate>
  );
}

function HRJobsIndexContent() {
  const [persona] = usePersona();
  const [search, setSearch] = useState("");

  const loadJobs = useCallback(() => api.listJobs(), []);
  const loadApps = useCallback(() => api.listApplications("hr"), []);
  const loadHr = useCallback(() => api.hrPartners(), []);

  const { data: jobsData, error: jobsErr } = useAutoRefresh<Job[]>(
    loadJobs,
    8000,
  );
  const { data: appsData } = useAutoRefresh<Application[]>(loadApps, 4000);
  const { data: hrData } = useAutoRefresh<HrPartner[]>(loadHr, 30000);

  const jobs = jobsData ?? [];
  const apps = appsData ?? [];
  const hrPartners = hrData ?? [];

  const myJdIds = useMemo(() => {
    if (persona.role !== "hr_partner") return new Set(jobs.map((j) => j.id));
    const partner = hrPartners.find((p) => p.user_id === persona.identity);
    if (!partner) return new Set(jobs.map((j) => j.id));
    return new Set(partner.jobs.map((j) => j.id));
  }, [persona, hrPartners, jobs]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return jobs
      .filter((j) => myJdIds.has(j.id))
      .filter((j) => {
        if (!q) return true;
        return (
          j.title.toLowerCase().includes(q) ||
          j.job_id.toLowerCase().includes(q) ||
          j.location.toLowerCase().includes(q) ||
          (j.function?.toLowerCase().includes(q) ?? false)
        );
      });
  }, [jobs, myJdIds, search]);

  const appsByJob = useMemo(() => {
    const m = new Map<string, Application[]>();
    apps.forEach((a) => {
      const arr = m.get(a.job_id) ?? [];
      arr.push(a);
      m.set(a.job_id, arr);
    });
    return m;
  }, [apps]);

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <HRSubNav />
      <main className="flex-1 px-8 py-6 max-w-7xl w-full mx-auto">
        <div className="flex items-end justify-between mb-6 flex-wrap gap-3">
          <div>
            <p className="text-[10px] text-axis-magenta font-semibold uppercase tracking-wider">
              Requisitions
            </p>
            <h1 className="text-2xl font-display text-axis-ink mt-1">
              {visible.length} open
            </h1>
            <p className="text-xs text-axis-muted mt-1">
              Click into a requisition to manage its panel, checklist template,
              and live pipeline.
            </p>
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by title, job id, location…"
            className="border border-axis-divider rounded px-3 py-2 text-sm w-72"
          />
        </div>

        {jobsErr && (
          <div className="p-4 mb-4 bg-axis-pink-soft/60 border border-axis-divider rounded-card text-sm text-axis-muted flex items-center gap-2">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 text-axis-muted">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            Unable to reach the backend. Please check your connection and try again.
          </div>
        )}

        <div className="space-y-3">
          {visible.map((j) => {
            const list = appsByJob.get(j.id) ?? [];
            const blocked = list.filter(
              (a) => a.pending_blocking_items.length > 0,
            ).length;
            const offers = list.filter((a) => a.stage === "offer").length;
            const rejected = list.filter((a) => a.stage === "rejected").length;
            const inFlight = list.length - offers - rejected;
            return (
              <Link
                key={j.id}
                href={`/hr/jobs/${j.id}`}
                className="block bg-axis-canvas border border-axis-divider rounded-card shadow-card hover:border-axis-magenta hover:shadow-card-hover p-5 transition"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
                      {j.job_id} · {j.function || j.band}
                    </p>
                    <h2 className="text-base font-semibold text-axis-ink mt-0.5 truncate">
                      {j.title}
                    </h2>
                    <p className="text-xs text-axis-muted mt-1">
                      {j.location} · {j.band}
                      {j.positions && j.positions > 1
                        ? ` · ${j.positions} positions`
                        : ""}{" "}
                      · panel of {j.panel.length}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {j.required_skills.slice(0, 6).map((s) => (
                        <span
                          key={s}
                          className="text-[10px] px-2 py-0.5 bg-axis-cream rounded"
                        >
                          {s}
                        </span>
                      ))}
                      {j.required_skills.length > 6 && (
                        <span className="text-[10px] text-axis-muted-light">
                          +{j.required_skills.length - 6}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="grid grid-cols-4 gap-2 text-center shrink-0">
                    <Stat label="In flight" value={inFlight} />
                    <Stat
                      label="Blocked"
                      value={blocked}
                      tone={blocked > 0 ? "alert" : "neutral"}
                    />
                    <Stat label="Offer" value={offers} tone="positive" />
                    <Stat label="Rejected" value={rejected} />
                  </div>
                </div>
              </Link>
            );
          })}
          {visible.length === 0 && !jobsErr && (
            <div className="p-6 bg-axis-canvas border border-axis-divider rounded-card text-sm text-axis-muted">
              No requisitions match. Try clearing the search filter.
            </div>
          )}
        </div>
      </main>
      <Footer />
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number;
  tone?: "neutral" | "alert" | "positive";
}) {
  const colour =
    tone === "alert"
      ? "text-axis-burgundy"
      : tone === "positive"
      ? "text-axis-magenta"
      : "text-axis-ink";
  return (
    <div className="px-3">
      <p className={`text-2xl font-semibold tabular-nums ${colour}`}>{value}</p>
      <p className="text-[9px] uppercase tracking-wider text-axis-muted">
        {label}
      </p>
    </div>
  );
}
