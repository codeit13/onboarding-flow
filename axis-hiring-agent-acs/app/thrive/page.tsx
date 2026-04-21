"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { TopBar } from "@/components/thrive/TopBar";
import { LeftRail } from "@/components/thrive/LeftRail";
import { HeroBanner } from "@/components/thrive/HeroBanner";
import { NotificationStrip } from "@/components/thrive/NotificationStrip";
import { JobCard } from "@/components/thrive/JobCard";
import { RightRail } from "@/components/thrive/RightRail";
import { Footer } from "@/components/thrive/Footer";
import { ApplyConfirmModal } from "@/components/thrive/ApplyConfirmModal";
import { MyApplicationsCard } from "@/components/thrive/MyApplicationsCard";
import { RoleGate } from "@/components/RoleGate";
import { api, type Application, type Candidate, type Job as ApiJob } from "@/lib/api";
import { usePersona } from "@/lib/persona";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";

// Mirrors backend scoring.py for preview only (no tenure-boost display).
function previewMatch(jd: ApiJob, candidate: Candidate): number {
  const required = new Set(jd.required_skills.map((s) => s.toLowerCase().trim()));
  const have = new Set(candidate.skills.map((s) => s.toLowerCase().trim()));
  let matched = 0;
  required.forEach((s) => {
    if (have.has(s)) matched += 1;
  });
  if (required.size === 0) return 0;
  const overlap = matched / required.size;
  let boost = 0;
  if (candidate.tenure_years >= 8) boost = 10;
  else if (candidate.tenure_years >= 5) boost = 5;
  return Math.min(100, Math.round(overlap * 100 + boost));
}

function skillSplit(jd: ApiJob, candidate: Candidate): {
  matched: string[];
  missing: string[];
} {
  const have = new Set(candidate.skills.map((s) => s.toLowerCase().trim()));
  const matched: string[] = [];
  const missing: string[] = [];
  for (const s of jd.required_skills) {
    if (have.has(s.toLowerCase().trim())) matched.push(s);
    else missing.push(s);
  }
  return { matched, missing };
}

export default function ThriveHomePage() {
  return (
    <RoleGate allow={["employee"]}>
      <ThriveHomeContent />
    </RoleGate>
  );
}

/* ---------- next-step copy for the hero CTA ---------- */
function nextStepCTA(app: Application): { label: string; description: string } {
  if (app.stage === "screened" && app.agent_status === "waiting_candidate")
    return { label: "Confirm Interview Slot", description: "Pick your preferred Round 1 interview time" };
  if (app.stage === "screened")
    return { label: "View Application", description: "We're finding the best interview times for you" };
  if (app.stage === "r1_scheduled" && !app.r1_started)
    return { label: "Start R1 Interview", description: "Your Round 1 interview is ready — good luck!" };
  if (app.stage === "r1_scheduled")
    return { label: "View Progress", description: "Round 1 interview in progress" };
  if (app.stage === "r1_done")
    return { label: "View Progress", description: "Round 1 cleared — Round 2 is being arranged" };
  if (app.stage === "r2_scheduled")
    return { label: "View Progress", description: "Round 2 panel interview is scheduled" };
  if (app.stage === "offer")
    return { label: "View Offer", description: "Congratulations! Your offer is ready" };
  if (app.stage === "offer_accepted")
    return { label: "View Journey", description: "Offer accepted — your onboarding has begun" };
  if (app.stage === "pre_joining")
    return { label: "View Journey", description: "Getting ready for your Day 1 at Axis Bank" };
  if (app.stage === "joined")
    return { label: "View Journey", description: "Welcome aboard! You're part of Axis Bank now" };
  if (app.stage === "offer_declined")
    return { label: "View Details", description: "We wish you the best in your future endeavours" };
  if (app.stage === "withdrawn")
    return { label: "View Details", description: "You have withdrawn this application" };
  return { label: "View Application", description: "Your application is being processed" };
}

function stageLabel(stage: string): string {
  switch (stage) {
    case "applied": return "Applied";
    case "screened": return "Screened";
    case "r1_scheduled": return "R1 Scheduled";
    case "r1_done": return "R1 Cleared";
    case "r2_scheduled": return "R2 Scheduled";
    case "offer_negotiation": return "Offer Negotiation";
    case "offer": return "Offer Extended";
    case "offer_accepted": return "Offer Accepted";
    case "pre_joining": return "Pre-Joining";
    case "joined": return "Joined";
    case "offer_declined": return "Offer Declined";
    case "withdrawn": return "Withdrawn";
    case "rejected": return "Closed";
    default: return stage;
  }
}

function ThriveHomeContent() {
  const router = useRouter();
  const [persona] = usePersona();
  const [jobs, setJobs] = useState<ApiJob[]>([]);
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [externalApps, setExternalApps] = useState<Application[]>([]);

  // Modal state
  const [pendingJob, setPendingJob] = useState<ApiJob | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Withdraw/Decline modal state
  const [withdrawAppId, setWithdrawAppId] = useState<string | null>(null);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [withdrawSubmitting, setWithdrawSubmitting] = useState(false);
  const [withdrawSuccess, setWithdrawSuccess] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [js, cs, cnt] = await Promise.all([
          api.listJobs(),
          api.listCandidates(),
          api.jobsApplicantCounts().catch(() => ({}) as Record<string, number>),
        ]);
        if (cancelled) return;
        setJobs(js);
        setCounts(cnt);
        const c =
          cs.find((x) => x.id === persona.identity) ||
          cs.find((x) => x.employee_id === persona.identity) ||
          cs[0] ||
          null;
        setCandidate(c);

        // Fetch both internal + external applications for this candidate
        const [internalApps, extApps] = await Promise.all([
          c ? api.listApplicationsForCandidate(c.employee_id || c.id).catch(() => []) : Promise.resolve([]),
          c?.email ? api.externalApplications(c.email).catch(() => []) : Promise.resolve([]),
        ]);
        if (!cancelled) {
          // Merge and deduplicate by app id
          const seen = new Set<string>();
          const merged: Application[] = [];
          for (const a of [...internalApps, ...extApps]) {
            if (!seen.has(a.id)) { seen.add(a.id); merged.push(a); }
          }
          setExternalApps(merged);
        }
      } catch (e: any) {
        setError(e.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [persona.identity]);

  // Auto-refresh all apps (internal + external) to catch stage transitions
  const extLoader = useCallback(async () => {
    if (!candidate) return [] as Application[];
    const [internal, external] = await Promise.all([
      api.listApplicationsForCandidate(candidate.employee_id || candidate.id).catch(() => []),
      candidate.email ? api.externalApplications(candidate.email).catch(() => []) : Promise.resolve([]),
    ]);
    const seen = new Set<string>();
    const merged: Application[] = [];
    for (const a of [...internal, ...external]) {
      if (!seen.has(a.id)) { seen.add(a.id); merged.push(a); }
    }
    return merged;
  }, [candidate?.id, candidate?.email, candidate?.employee_id]);
  const { data: liveExtApps } = useAutoRefresh<Application[]>(extLoader, 4000);
  // Prefer live-polled data once it has apps; otherwise fall back to the
  // initial fetch from useEffect (which resolves before loading=false).
  const currentExtApps =
    liveExtApps && liveExtApps.length > 0 ? liveExtApps : externalApps;

  // Always show external candidate view — internal employee view is not
  // the use case for Axis Bank's hiring portal. External candidates see
  // the clean candidate experience whether or not they have apps yet.
  const hasExternalApps = true;

  const jobsById = useMemo(() => {
    const m: Record<string, ApiJob> = {};
    for (const j of jobs) m[j.id] = j;
    return m;
  }, [jobs]);

  const viewJobs = useMemo(() => {
    if (!candidate) return [];
    return jobs.map((j) => ({
      id: j.id,
      jobId: j.job_id,
      matchPercent: previewMatch(j, candidate),
      title: j.title,
      band: j.band,
      tags: j.tags,
      location: j.location,
      applicants: counts[j.id] ?? 0,
      highSkillMatch: previewMatch(j, candidate) >= 75,
    }));
  }, [jobs, candidate, counts]);

  const handleApplyClick = (jobId: string) => {
    const j = jobs.find((x) => x.id === jobId);
    if (j) setPendingJob(j);
  };

  const handleConfirm = async () => {
    if (!candidate || !pendingJob) return;
    setSubmitting(true);
    try {
      const app = await api.apply(candidate.id, pendingJob.id);
      router.push(`/thrive/status/${app.id}`);
    } catch (e: any) {
      alert(`Apply failed: ${e.message}`);
      setSubmitting(false);
    }
  };

  const handleWithdraw = async () => {
    if (!withdrawAppId || !withdrawReason.trim()) return;
    setWithdrawSubmitting(true);
    try {
      await api.withdrawApplication(withdrawAppId, withdrawReason.trim());
      setWithdrawSuccess(true);
      // Refresh apps after a moment
      setTimeout(() => {
        setWithdrawAppId(null);
        setWithdrawReason("");
        setWithdrawSuccess(false);
        window.location.reload();
      }, 2000);
    } catch (e: any) {
      alert(e.message || "Failed to withdraw");
    } finally {
      setWithdrawSubmitting(false);
    }
  };

  const canWithdraw = (app: Application) => {
    const terminal = ["offer_declined", "withdrawn", "rejected", "joined"];
    return !terminal.includes(app.stage);
  };

  const split =
    candidate && pendingJob ? skillSplit(pendingJob, candidate) : { matched: [], missing: [] };
  const previewPct =
    candidate && pendingJob ? previewMatch(pendingJob, candidate) : 0;

  // ─── Loading state — avoid flashing the wrong view ──────────
  if (loading) {
    return (
      <div className="min-h-screen flex flex-col bg-axis-canvas">
        <TopBar />
        <main className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <div className="inline-block w-8 h-8 border-3 border-axis-burgundy border-t-transparent rounded-full animate-spin mb-4" />
            <p className="text-sm text-axis-muted">Loading your dashboard…</p>
          </div>
        </main>
        <Footer />
      </div>
    );
  }

  // ─── External candidate view ─────────────────────────────────
  if (hasExternalApps) {
    const activeApps = currentExtApps.filter((a) => a.stage !== "rejected" && a.stage !== "withdrawn");
    const primaryApp = activeApps[0] || currentExtApps[0];
    const primaryJob = primaryApp ? jobsById[primaryApp.job_id] : null;
    const cta = primaryApp ? nextStepCTA(primaryApp) : null;

    return (
      <div className="min-h-screen flex flex-col bg-axis-canvas">
        <TopBar />

        <main className="flex-1 px-8 py-6 bg-axis-canvas">
          <div className="max-w-4xl mx-auto">
            {/* Welcome bar */}
            <div className="mt-2 mb-8">
              <div className="h-1 w-16 bg-axis-burgundy rounded mb-4" />
              <h1 className="text-2xl font-display text-axis-ink">
                Welcome, {candidate?.name || "Candidate"}
              </h1>
              <p className="text-sm text-axis-muted mt-1">
                {candidate?.email}
              </p>
            </div>

            {/* ── Primary application hero card ── */}
            {primaryApp && primaryJob && cta && (
              <div className="bg-white border border-axis-divider rounded-xl shadow-lg overflow-hidden mb-8">
                {/* Accent bar */}
                <div className="h-1.5 bg-gradient-to-r from-axis-burgundy to-axis-magenta" />
                <div className="p-8">
                  <div className="flex items-start justify-between gap-6">
                    <div className="flex-1">
                      <p className="text-[11px] uppercase tracking-widest text-axis-magenta font-semibold mb-2">
                        Your Application
                      </p>
                      <h2 className="text-xl font-display text-axis-ink mb-1">
                        {primaryJob.title}
                      </h2>
                      <p className="text-sm text-axis-muted">
                        {primaryJob.location} &middot; {primaryJob.band} band &middot; Job ID {primaryJob.job_id}
                      </p>
                      <p className="text-[10px] text-axis-muted-light mt-1">
                        Application ID: {primaryApp.id}
                      </p>

                      {/* Stage */}
                      <div className="flex items-center gap-3 mt-4">
                        <span className="text-xs px-3 py-1 bg-axis-burgundy/10 text-axis-burgundy border border-axis-burgundy/20 rounded-full font-semibold">
                          {stageLabel(primaryApp.stage)}
                        </span>
                      </div>

                      {/* Next step description */}
                      <p className="text-sm text-axis-ink mt-4">
                        {cta.description}
                      </p>
                    </div>

                    {/* CTA button + Decline */}
                    <div className="shrink-0 flex flex-col items-center gap-2 pt-2">
                      {primaryApp.stage === "withdrawn" ? (
                        <span className="px-5 py-2.5 bg-gray-100 text-gray-500 font-semibold rounded-btn text-sm border border-gray-200">
                          Withdrawn
                        </span>
                      ) : (
                        <>
                          <Link
                            href={`/thrive/status/${primaryApp.id}`}
                            className="px-6 py-3 bg-axis-burgundy text-white font-semibold rounded-btn hover:bg-axis-burgundy-dark transition-colors shadow-card text-sm"
                          >
                            {cta.label} &rarr;
                          </Link>
                          {canWithdraw(primaryApp) && (
                            <button
                              onClick={() => { setWithdrawAppId(primaryApp.id); setWithdrawReason(""); setWithdrawSuccess(false); }}
                              className="text-[11px] text-axis-muted hover:text-red-600 transition-colors"
                            >
                              Decline &amp; Withdraw
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ── Application timeline (if multiple) ── */}
            {currentExtApps.length > 1 && (
              <div className="mb-8">
                <h3 className="text-sm font-semibold text-axis-ink mb-3">All Applications</h3>
                <div className="space-y-2">
                  {currentExtApps.map((app) => {
                    const job = jobsById[app.job_id];
                    return (
                      <Link
                        key={app.id}
                        href={`/thrive/status/${app.id}`}
                        className="flex items-center justify-between p-4 bg-white border border-axis-divider rounded-lg hover:bg-axis-surface transition-colors"
                      >
                        <div>
                          <p className="text-sm font-semibold text-axis-ink">
                            {job?.title || `Job ${app.job_id}`}
                          </p>
                          <p className="text-xs text-axis-muted mt-0.5">
                            {job?.location}
                          </p>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="text-[10px] px-2 py-0.5 bg-axis-burgundy/10 text-axis-burgundy rounded-full font-semibold uppercase">
                            {stageLabel(app.stage)}
                          </span>
                          <span className="text-xs text-axis-magenta font-semibold">View &rarr;</span>
                        </div>
                      </Link>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ── Browse other open roles ── */}
            <div className="mb-8">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-axis-ink flex items-center gap-2">
                  <span className="w-5 h-5 rounded bg-axis-pink-soft flex items-center justify-center text-axis-burgundy text-xs">
                    ◆
                  </span>
                  Explore more open roles at Axis Bank
                </h3>
                <Link
                  href={`/external/intake?name=${encodeURIComponent(candidate?.name || "")}&email=${encodeURIComponent(candidate?.email || "")}`}
                  className="text-axis-magenta text-xs font-semibold tracking-wider hover:underline"
                >
                  BROWSE ALL &amp; UPLOAD CV
                </Link>
              </div>
              <p className="text-xs text-axis-muted mb-4">
                Interested in other opportunities? Upload your CV on the{" "}
                <Link href={`/external/intake?name=${encodeURIComponent(candidate?.name || "")}&email=${encodeURIComponent(candidate?.email || "")}`} className="text-axis-magenta hover:underline font-semibold">
                  careers portal
                </Link>{" "}
                and we'll find the best-fit roles for you.
              </p>
              <div className="grid grid-cols-2 gap-3">
                {jobs.slice(0, 4).map((j) => (
                  <Link
                    key={j.id}
                    href={`/external/intake?name=${encodeURIComponent(candidate?.name || "")}&email=${encodeURIComponent(candidate?.email || "")}`}
                    className="p-4 bg-white border border-axis-divider rounded-lg hover:border-axis-magenta/40 hover:bg-axis-surface transition-colors"
                  >
                    <p className="text-sm font-semibold text-axis-ink truncate">{j.title}</p>
                    <p className="text-xs text-axis-muted mt-1">
                      {j.location} &middot; {j.band} band
                    </p>
                  </Link>
                ))}
              </div>
            </div>

            {/* ── Quick links ── */}
            <div className="grid grid-cols-3 gap-4 mb-8">
              <Link
                href={`/external/intake?name=${encodeURIComponent(candidate?.name || "")}&email=${encodeURIComponent(candidate?.email || "")}`}
                className="p-5 bg-white border border-axis-divider rounded-lg hover:border-axis-magenta/40 transition-colors text-center"
              >
                <p className="text-2xl mb-2">📄</p>
                <p className="text-sm font-semibold text-axis-ink">Upload CV</p>
                <p className="text-[11px] text-axis-muted mt-1">Find roles that fit your experience</p>
              </Link>
              <Link
                href="/external/applications"
                className="p-5 bg-white border border-axis-divider rounded-lg hover:border-axis-magenta/40 transition-colors text-center"
              >
                <p className="text-2xl mb-2">📋</p>
                <p className="text-sm font-semibold text-axis-ink">Track Applications</p>
                <p className="text-[11px] text-axis-muted mt-1">Check status of all your applications</p>
              </Link>
              <Link
                href={primaryApp ? `/thrive/status/${primaryApp.id}` : "/external"}
                className="p-5 bg-white border border-axis-divider rounded-lg hover:border-axis-magenta/40 transition-colors text-center"
              >
                <p className="text-2xl mb-2">🎯</p>
                <p className="text-sm font-semibold text-axis-ink">Interview Prep</p>
                <p className="text-[11px] text-axis-muted mt-1">Get ready for your upcoming interview</p>
              </Link>
            </div>
          </div>
        </main>

        {/* ── Withdraw / Decline modal ── */}
        {withdrawAppId && (
          <div className="fixed inset-0 z-[70] flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40" onClick={() => !withdrawSubmitting && setWithdrawAppId(null)} />
            <div className="relative bg-white rounded-xl shadow-2xl border border-axis-divider w-full max-w-md mx-4 p-6">
              {withdrawSuccess ? (
                <div className="text-center py-4">
                  <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-green-50 flex items-center justify-center">
                    <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <p className="text-sm font-semibold text-axis-ink">Application withdrawn</p>
                  <p className="text-xs text-axis-muted mt-1">We wish you the best in your career journey.</p>
                </div>
              ) : (
                <>
                  <button
                    onClick={() => setWithdrawAppId(null)}
                    className="absolute top-3 right-3 text-axis-muted hover:text-axis-ink text-lg"
                  >
                    &times;
                  </button>
                  <h3 className="text-lg font-display text-axis-ink mb-1">
                    Withdraw Application
                  </h3>
                  <p className="text-xs text-axis-muted mb-5">
                    Are you sure you want to withdraw? This action cannot be undone.
                  </p>

                  <label className="block text-xs font-semibold text-axis-ink mb-1.5">
                    Reason for withdrawing
                  </label>
                  <div className="space-y-2 mb-4">
                    {[
                      "Accepted another offer",
                      "Not interested in this role anymore",
                      "Personal / family reasons",
                      "Relocation not feasible",
                      "Compensation expectations not met",
                    ].map((reason) => (
                      <label
                        key={reason}
                        className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border cursor-pointer transition-colors ${
                          withdrawReason === reason
                            ? "border-axis-magenta bg-axis-magenta/5"
                            : "border-axis-divider hover:border-axis-muted"
                        }`}
                      >
                        <input
                          type="radio"
                          name="withdrawReason"
                          value={reason}
                          checked={withdrawReason === reason}
                          onChange={() => setWithdrawReason(reason)}
                          className="accent-axis-magenta"
                        />
                        <span className="text-xs text-axis-ink">{reason}</span>
                      </label>
                    ))}
                    <label
                      className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border cursor-pointer transition-colors ${
                        withdrawReason !== "" && ![
                          "Accepted another offer",
                          "Not interested in this role anymore",
                          "Personal / family reasons",
                          "Relocation not feasible",
                          "Compensation expectations not met",
                        ].includes(withdrawReason)
                          ? "border-axis-magenta bg-axis-magenta/5"
                          : "border-axis-divider hover:border-axis-muted"
                      }`}
                    >
                      <input
                        type="radio"
                        name="withdrawReason"
                        checked={withdrawReason !== "" && ![
                          "Accepted another offer",
                          "Not interested in this role anymore",
                          "Personal / family reasons",
                          "Relocation not feasible",
                          "Compensation expectations not met",
                        ].includes(withdrawReason)}
                        onChange={() => setWithdrawReason("Other: ")}
                        className="accent-axis-magenta"
                      />
                      <span className="text-xs text-axis-ink">Other</span>
                    </label>
                    {withdrawReason.startsWith("Other") && (
                      <textarea
                        placeholder="Please share your reason..."
                        value={withdrawReason.replace("Other: ", "")}
                        onChange={(e) => setWithdrawReason("Other: " + e.target.value)}
                        className="w-full px-3 py-2 text-xs border border-axis-divider rounded-lg focus:outline-none focus:border-axis-magenta/60 resize-none"
                        rows={2}
                      />
                    )}
                  </div>

                  <div className="flex gap-3">
                    <button
                      onClick={() => setWithdrawAppId(null)}
                      className="flex-1 py-2.5 text-sm font-semibold border border-axis-divider text-axis-muted rounded-lg hover:bg-axis-surface transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleWithdraw}
                      disabled={!withdrawReason.trim() || withdrawReason === "Other: " || withdrawSubmitting}
                      className="flex-1 py-2.5 text-sm font-semibold bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
                    >
                      {withdrawSubmitting ? "Withdrawing..." : "Withdraw Application"}
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        <Footer />
      </div>
    );
  }

  // ─── Original internal employee view ─────────────────────────
  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />

      <div className="flex flex-1">
        <LeftRail />

        <main className="flex-1 px-8 py-6 bg-axis-canvas">
          <div className="flex gap-8">
            <div className="flex-1 min-w-0 max-w-[820px]">
              <HeroBanner />
              <NotificationStrip />

              {candidate && (
                <div className="mt-4 text-xs text-axis-muted">
                  Viewing as <strong className="text-axis-ink">{candidate.name}</strong> · {candidate.current_role} · {candidate.current_location} · {candidate.tenure_years.toFixed(1)}y tenure
                </div>
              )}

              <MyApplicationsCard
                candidateId={candidate?.employee_id ?? null}
                candidateEmail={candidate?.email ?? null}
                jobsById={jobsById}
              />

              <div className="mt-6 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-axis-ink flex items-center gap-2">
                  <span className="w-5 h-5 rounded bg-axis-pink-soft flex items-center justify-center text-axis-burgundy text-xs">
                    ◆
                  </span>
                  Job Recommendations for you
                </h2>
                <Link
                  href="/hr"
                  className="text-axis-magenta text-xs font-semibold tracking-wider hover:underline"
                >
                  VIEW ALL
                </Link>
              </div>

              {loading && (
                <p className="mt-6 text-sm text-axis-muted">Loading recommendations…</p>
              )}
              {error && (
                <div className="mt-6 p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
                  We couldn't reach the hiring service right now. Please try again in a moment.
                </div>
              )}

              <div className="mt-4 space-y-4">
                {viewJobs.map((job) => (
                  <JobCard key={job.id} job={job} onApply={handleApplyClick} />
                ))}
              </div>
            </div>

            <RightRail />
          </div>
        </main>
      </div>

      <Footer />

      <ApplyConfirmModal
        open={!!pendingJob}
        job={pendingJob}
        candidate={candidate}
        matchPercent={previewPct}
        matchedSkills={split.matched}
        missingSkills={split.missing}
        submitting={submitting}
        onCancel={() => {
          if (!submitting) setPendingJob(null);
        }}
        onConfirm={handleConfirm}
      />
    </div>
  );
}
