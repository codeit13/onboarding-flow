"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { RoleGate } from "@/components/RoleGate";
import { AgentStatusBadge } from "@/components/agent/AgentStatusBadge";
import {
  api,
  type Application,
  type Candidate,
  type Job,
} from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";
import { STAGE_LABEL } from "@/lib/stages";

/**
 * Candidate profile.
 *
 * Static profile (KRAs, skills, education, last rating) plus a live list of
 * every application this employee has against any requisition. The
 * applications block polls every 4s — handy when you're watching the agent
 * move someone through the funnel.
 */
export default function HRCandidateDetailPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <HRCandidateDetailContent />
    </RoleGate>
  );
}

function HRCandidateDetailContent() {
  const params = useParams<{ candId: string }>();
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [error, setError] = useState<string | null>(null);

  // One-shot load — candidate profile is static.
  useEffect(() => {
    let cancelled = false;
    api
      .getCandidate(params.candId)
      .then((c) => !cancelled && setCandidate(c))
      .catch((e) => !cancelled && setError(e?.message || String(e)));
    return () => {
      cancelled = true;
    };
  }, [params.candId]);

  const loadApps = useCallback(() => api.listApplications("hr"), []);
  const loadJobs = useCallback(() => api.listJobs(), []);
  const { data: appsData } = useAutoRefresh<Application[]>(loadApps, 4000);
  const { data: jobsData } = useAutoRefresh<Job[]>(loadJobs, 30000);

  const myApps = useMemo(
    () => (appsData ?? []).filter((a) => a.candidate_id === params.candId),
    [appsData, params.candId],
  );
  const jobById = useMemo(() => {
    const m = new Map<string, Job>();
    (jobsData ?? []).forEach((j) => m.set(j.id, j));
    return m;
  }, [jobsData]);

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <HRSubNav />
      <main className="flex-1 px-8 py-6 max-w-5xl w-full mx-auto">
        <Link
          href="/hr/candidates"
          className="text-axis-magenta text-xs font-medium hover:underline"
        >
          ← Back to candidates
        </Link>

        {error && (
          <div className="mt-6 p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
            {error}
          </div>
        )}
        {!candidate && !error && (
          <p className="mt-6 text-sm text-axis-muted">Loading…</p>
        )}

        {candidate && (
          <>
            <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card shadow-card p-6">
              <p className="text-xs uppercase tracking-wider text-axis-magenta font-semibold">
                Employee profile
              </p>
              <h1 className="text-2xl font-display text-axis-ink mt-1">
                {candidate.name}
              </h1>
              <p className="text-sm text-axis-muted mt-1">
                {candidate.employee_id} · {candidate.email}
              </p>
              <div className="mt-4 grid sm:grid-cols-3 gap-3 text-xs">
                <Field label="Current role" value={candidate.current_role} />
                <Field label="Location" value={candidate.current_location} />
                <Field label="Band" value={candidate.current_band || "—"} />
                <Field
                  label="Tenure"
                  value={`${candidate.tenure_years.toFixed(1)} years`}
                />
                <Field
                  label="Last rating"
                  value={candidate.last_rating || "—"}
                />
                <Field label="Education" value={candidate.education || "—"} />
              </div>
            </div>

            {candidate.compensation && candidate.compensation.current_ctc ? (
              <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card p-5">
                <div className="flex items-baseline justify-between mb-2">
                  <p className="text-xs uppercase text-axis-muted font-semibold">
                    Current compensation
                  </p>
                  {candidate.compensation.pay_period ? (
                    <p className="text-[10px] text-axis-muted">
                      from {candidate.compensation.pay_period}
                      {candidate.compensation.employer
                        ? ` · ${candidate.compensation.employer}`
                        : ""}
                    </p>
                  ) : null}
                </div>
                <p className="text-2xl font-display text-axis-ink">
                  {fmtINR(candidate.compensation.current_ctc)}{" "}
                  <span className="text-xs text-axis-muted">CTC</span>
                </p>
                <ul className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                  {candidate.compensation.basic ? (
                    <CompChip label="Basic" value={candidate.compensation.basic} />
                  ) : null}
                  {candidate.compensation.hra ? (
                    <CompChip label="HRA" value={candidate.compensation.hra} />
                  ) : null}
                  {candidate.compensation.variable ? (
                    <CompChip label="Variable" value={candidate.compensation.variable} />
                  ) : null}
                  {candidate.compensation.special_allowance ? (
                    <CompChip label="Special" value={candidate.compensation.special_allowance} />
                  ) : null}
                </ul>
                {candidate.compensation.extraction_notes ? (
                  <p className="mt-2 text-[11px] text-axis-muted italic">
                    {candidate.compensation.extraction_notes}
                  </p>
                ) : null}
              </div>
            ) : null}

            <div className="mt-4 grid md:grid-cols-2 gap-4">
              <div className="bg-axis-canvas border border-axis-divider rounded-card p-5">
                <p className="text-xs uppercase text-axis-muted font-semibold">
                  Skills
                </p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {candidate.skills.map((s) => (
                    <span
                      key={s}
                      className="text-[10px] px-2 py-0.5 bg-axis-cream rounded"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
              <div className="bg-axis-canvas border border-axis-divider rounded-card p-5">
                <p className="text-xs uppercase text-axis-muted font-semibold">
                  Recent KRAs
                </p>
                <ul className="mt-2 space-y-1 text-xs text-axis-ink-soft list-disc list-inside">
                  {candidate.kras.map((k, i) => (
                    <li key={i}>{k}</li>
                  ))}
                  {candidate.kras.length === 0 && (
                    <li className="text-axis-muted-light italic list-none">
                      No KRAs on file.
                    </li>
                  )}
                </ul>
              </div>
            </div>

            <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card p-5">
              <p className="text-xs uppercase text-axis-muted font-semibold mb-3">
                Applications ({myApps.length})
              </p>
              {myApps.length === 0 && (
                <p className="text-xs text-axis-muted-light italic">
                  This candidate hasn't applied to any open requisition yet.
                </p>
              )}
              <ul className="space-y-2">
                {myApps
                  .slice()
                  .sort(
                    (a, b) =>
                      new Date(b.created_at).getTime() -
                      new Date(a.created_at).getTime(),
                  )
                  .map((a) => {
                    const job = jobById.get(a.job_id);
                    return (
                      <li key={a.id}>
                        <Link
                          href={`/hr/applications/${a.id}`}
                          className="block p-3 border border-axis-divider rounded hover:border-axis-magenta"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-sm font-semibold text-axis-ink truncate">
                                {job?.title || a.job_id}
                              </p>
                              <p className="text-[10px] text-axis-muted">
                                {job?.job_id} · applied{" "}
                                {new Date(a.created_at).toLocaleDateString()} ·
                                match {a.match_percent.toFixed(0)}%
                              </p>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <span
                                className={`text-[10px] px-2 py-0.5 rounded ${
                                  a.stage === "rejected"
                                    ? "bg-axis-pink-soft text-axis-burgundy"
                                    : a.stage === "offer"
                                    ? "bg-axis-cream text-axis-ink"
                                    : "bg-axis-surface text-axis-ink-soft"
                                }`}
                              >
                                {STAGE_LABEL[a.stage]}
                              </span>
                              <AgentStatusBadge status={a.agent_status} />
                            </div>
                          </div>
                        </Link>
                      </li>
                    );
                  })}
              </ul>
            </div>
          </>
        )}
      </main>
      <Footer />
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-axis-divider rounded p-2">
      <p className="text-[9px] uppercase tracking-wider text-axis-muted">
        {label}
      </p>
      <p className="text-axis-ink font-medium mt-0.5">{value}</p>
    </div>
  );
}

function CompChip({ label, value }: { label: string; value: number }) {
  return (
    <li className="border border-axis-divider rounded p-2">
      <p className="text-[9px] uppercase tracking-wider text-axis-muted">
        {label}
      </p>
      <p className="text-axis-ink font-medium mt-0.5">{fmtINR(value)}</p>
    </li>
  );
}

function fmtINR(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(2)} L`;
  return `₹${n.toLocaleString("en-IN")}`;
}
