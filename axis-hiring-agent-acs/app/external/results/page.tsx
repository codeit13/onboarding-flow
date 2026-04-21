"use client";

/**
 * External candidate results page (Q2 demo refresh).
 *
 * Reads the intake response stashed in localStorage by /external/intake
 * and renders TWO ranked sections:
 *
 *   Section A — "Jobs matching your search"
 *               (Claude semantic NL search vs the candidate's typed query)
 *
 *   Section B — "AI-recommended for you"
 *               (Claude resume matcher vs the candidate's parsed profile)
 *
 * On Apply we POST to /external/apply with the candidate's resume_text +
 * the chosen job_id + provenance (search vs ai) + the extracted
 * compensation block. Then we route to /external/status/[appId] which
 * mirrors the internal /thrive/status experience.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { TopBar } from "@/components/thrive/TopBar";
import { writePersona } from "@/lib/persona";
import {
  api,
  ExternalIntakeResponse,
  ExternalRecommendation,
  Job,
} from "@/lib/api";

const STORAGE_KEY = "axis_external_intake_v1";

type Stash = ExternalIntakeResponse & { _ts: number };

type Tab = "matches" | "browse";

export default function ExternalResultsPage() {
  const router = useRouter();
  const [stash, setStash] = useState<Stash | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("matches");

  // Browse-all-jobs state — LinkedIn-style filters over the full open
  // Axis req list. Independent of the curated sections above; lets the
  // candidate explore beyond what we picked for them.
  const [allJobs, setAllJobs] = useState<Job[] | null>(null);
  const [browseKeyword, setBrowseKeyword] = useState("");
  const [browseLocation, setBrowseLocation] = useState("");
  const [browseFunction, setBrowseFunction] = useState("");

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setStash(JSON.parse(raw));
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    api
      .listJobs()
      .then(setAllJobs)
      .catch(() => setAllJobs([]));
  }, []);

  const compensation = stash?.profile?.compensation ?? null;

  async function onApply(
    rec: ExternalRecommendation,
    source: "search" | "ai",
  ) {
    if (!stash) return;
    setApplying(`${source}:${rec.job_id}`);
    setError(null);
    try {
      const app = await api.externalApply(stash.resume_text, rec.job_id, {
        // Forward the intake-form identity so the backend doesn't fall
        // back to the resume-regex email and lose this candidate from
        // the tracker page.
        name: stash.profile?.name || null,
        email: stash.profile?.email || null,
        searchQuery: stash.search_query || null,
        recommendationSource: source,
        compensation: compensation || null,
      });
      // CRITICAL: when an external candidate clicks Apply we know they
      // are explicitly acting as that candidate. Force-switch the
      // browser persona to `employee` with the freshly-created
      // candidate identity BEFORE we navigate, otherwise the
      // /external/status → /thrive/status redirect chain will hit the
      // RoleGate (which only allows `employee`) and bounce the user
      // back to /hr (Business Partner) if their previous persona was
      // anything else. This was a demo blocker — the candidate would
      // submit an application and immediately land in the HR funnel.
      writePersona({
        role: "employee",
        identity: app.candidate_id,
        displayName: stash.profile?.name || "Candidate",
      });
      router.push(`/external/status/${app.id}`);
    } catch (err: any) {
      setError(err?.message || "Failed to apply");
      setApplying(null);
    }
  }

  if (!stash) {
    return (
      <>
        <TopBar />
        <main className="min-h-screen bg-axis-surface py-10 px-6">
          <div className="max-w-3xl mx-auto">
            <p className="text-sm text-axis-muted mb-4">
              No intake data found. Please start from the intake page.
            </p>
            <a
              href="/external/intake"
              className="px-4 py-2 text-sm font-semibold bg-axis-magenta text-white rounded inline-block"
            >
              Start intake →
            </a>
          </div>
        </main>
      </>
    );
  }

  const profile = stash.profile;

  return (
    <>
      <TopBar />
      <main className="min-h-screen bg-axis-surface py-12 px-6">
        <div className="max-w-5xl mx-auto">
          {/* ============ Page header ============ */}
          <header className="mb-10">
            <div className="h-1 w-20 bg-axis-burgundy rounded mb-6" />
            <h1 className="text-4xl font-display text-axis-ink mb-3 leading-tight">
              Hi {profile.name?.split(" ")[0] || "there"} — here's what we found for you
            </h1>
            <p className="text-base text-axis-muted max-w-2xl">
              We looked at our open Axis roles two ways: against what you
              told us you want, and against your resume. Pick any role
              below to start your application.
            </p>
          </header>

          {/* ============ Profile + comp summary card ============ */}
          <section className="bg-white border border-axis-divider rounded-2xl shadow-sm p-6 mb-10">
            <div className="grid sm:grid-cols-2 gap-8">
              <div>
                <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold mb-2">
                  Your profile
                </p>
                <p className="text-base text-axis-ink font-semibold">
                  {profile.name}
                </p>
                <p className="text-xs text-axis-muted mt-0.5">{profile.email}</p>
                <p className="text-xs text-axis-muted mt-2">
                  {profile.current_role} · {profile.current_location} ·{" "}
                  {profile.tenure_years.toFixed(1)} yrs experience
                </p>
                {profile.skills?.length ? (
                  <p className="text-xs text-axis-muted mt-3 leading-relaxed">
                    <span className="font-semibold text-axis-ink">Top skills:</span>{" "}
                    {profile.skills.slice(0, 6).join(", ")}
                    {profile.skills.length > 6 ? "…" : ""}
                  </p>
                ) : null}
              </div>
              <div className="sm:border-l sm:border-axis-divider sm:pl-8">
                {compensation ? (
                  <>
                    <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold mb-2">
                      Current compensation
                    </p>
                    <p className="text-base text-axis-ink font-semibold">
                      {fmtINR(compensation.current_ctc)} CTC
                      {compensation.pay_period
                        ? ` · ${compensation.pay_period}`
                        : ""}
                    </p>
                    {compensation.employer ? (
                      <p className="text-xs text-axis-muted mt-0.5">
                        {compensation.employer}
                      </p>
                    ) : null}
                    <ul className="text-xs text-axis-muted mt-3 grid grid-cols-2 gap-x-6 gap-y-1">
                      {compensation.basic ? (
                        <li>Basic <span className="text-axis-ink font-medium">{fmtINR(compensation.basic)}</span></li>
                      ) : null}
                      {compensation.hra ? (
                        <li>HRA <span className="text-axis-ink font-medium">{fmtINR(compensation.hra)}</span></li>
                      ) : null}
                      {compensation.variable ? (
                        <li>Variable <span className="text-axis-ink font-medium">{fmtINR(compensation.variable)}</span></li>
                      ) : null}
                      {compensation.special_allowance ? (
                        <li>Special <span className="text-axis-ink font-medium">{fmtINR(compensation.special_allowance)}</span></li>
                      ) : null}
                    </ul>
                  </>
                ) : (
                  <>
                    <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold mb-2">
                      No salary slip on file
                    </p>
                    <p className="text-xs text-axis-muted">
                      You can upload one any time during the application.
                    </p>
                  </>
                )}
              </div>
            </div>
          </section>

          {error ? (
            <div className="mb-8 bg-red-50 border border-red-200 text-red-800 rounded-2xl p-4 text-sm">
              {error}
            </div>
          ) : null}

          {/* ============ Tab bar ============ */}
          <div className="flex border-b border-axis-divider mb-8">
            <button
              type="button"
              onClick={() => setActiveTab("matches")}
              className={`px-6 py-3 text-sm font-semibold transition-colors relative ${
                activeTab === "matches"
                  ? "text-axis-burgundy"
                  : "text-axis-muted hover:text-axis-ink"
              }`}
            >
              Match Results
              {activeTab === "matches" && (
                <span className="absolute bottom-0 left-0 right-0 h-[3px] bg-axis-burgundy rounded-t" />
              )}
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("browse")}
              className={`px-6 py-3 text-sm font-semibold transition-colors relative ${
                activeTab === "browse"
                  ? "text-axis-burgundy"
                  : "text-axis-muted hover:text-axis-ink"
              }`}
            >
              All Open Positions
              {allJobs != null && (
                <span className="ml-1.5 text-xs font-normal text-axis-muted">
                  ({allJobs.length})
                </span>
              )}
              {activeTab === "browse" && (
                <span className="absolute bottom-0 left-0 right-0 h-[3px] bg-axis-burgundy rounded-t" />
              )}
            </button>
          </div>

          {/* ============ Tab 1: Match Results ============ */}
          {activeTab === "matches" && (
            <>
              {/* Section A: search matches */}
              {stash.search_query ? (
                <section className="mb-12">
                  <SectionHeader
                    eyebrow="Matched to your search"
                    title={`Jobs matching "${stash.search_query}"`}
                    subtitle="Roles ranked against the description you typed in."
                  />
                  {stash.search_matches.length > 0 ? (
                    <div className="space-y-4">
                      {stash.search_matches.map((m) => (
                        <RecCard
                          key={`s-${m.job_id}`}
                          rec={m}
                          onApply={() => onApply(m, "search")}
                          applying={applying === `search:${m.job_id}`}
                          accent="magenta"
                        />
                      ))}
                    </div>
                  ) : (
                    <EmptyState message="No open Axis roles matched your search exactly. Try the recommendations below." />
                  )}
                </section>
              ) : null}

              {/* Section B: resume-based recommendations */}
              <section className="mb-12">
                <SectionHeader
                  eyebrow="Picked for you"
                  title="Recommended based on your resume"
                  subtitle="Roles where your background lines up most closely with what we're hiring for."
                />
                {stash.ai_recommendations.length > 0 ? (
                  <div className="space-y-4">
                    {stash.ai_recommendations.slice(0, 8).map((m) => (
                      <RecCard
                        key={`a-${m.job_id}`}
                        rec={m}
                        onApply={() => onApply(m, "ai")}
                        applying={applying === `ai:${m.job_id}`}
                        accent="burgundy"
                      />
                    ))}
                  </div>
                ) : (
                  <EmptyState message="We couldn't surface a strong recommendation right now. Try browsing all open positions." />
                )}
              </section>
            </>
          )}

          {/* ============ Tab 2: All Open Positions ============ */}
          {activeTab === "browse" && (
            <BrowseAllJobs
              jobs={allJobs}
              keyword={browseKeyword}
              setKeyword={setBrowseKeyword}
              location={browseLocation}
              setLocation={setBrowseLocation}
              functionFilter={browseFunction}
              setFunctionFilter={setBrowseFunction}
              applying={applying}
              onApply={(job) =>
                onApply(
                  {
                    job_id: job.id,
                    job_title: job.title,
                    location: job.location,
                    match_percent: 0,
                    rationale: "Browsed from all open positions",
                    matched_skills: [],
                    missing_skills: [],
                  },
                  "search",
                )
              }
            />
          )}
        </div>
      </main>
    </>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="bg-white border border-dashed border-axis-divider rounded-2xl p-8 text-center">
      <p className="text-sm text-axis-muted">{message}</p>
    </div>
  );
}

function BrowseAllJobs({
  jobs,
  keyword,
  setKeyword,
  location,
  setLocation,
  functionFilter,
  setFunctionFilter,
  applying,
  onApply,
}: {
  jobs: Job[] | null;
  keyword: string;
  setKeyword: (s: string) => void;
  location: string;
  setLocation: (s: string) => void;
  functionFilter: string;
  setFunctionFilter: (s: string) => void;
  applying: string | null;
  onApply: (job: Job) => void;
}) {
  const locations = useMemo(() => {
    if (!jobs) return [];
    return Array.from(new Set(jobs.map((j) => j.location))).sort();
  }, [jobs]);
  const functions = useMemo(() => {
    if (!jobs) return [];
    return Array.from(
      new Set(jobs.map((j) => j.function || "Other")),
    ).sort();
  }, [jobs]);

  const filtered = useMemo(() => {
    if (!jobs) return [];
    const k = keyword.trim().toLowerCase();
    return jobs.filter((j) => {
      if (location && j.location !== location) return false;
      if (functionFilter && (j.function || "Other") !== functionFilter)
        return false;
      if (k) {
        const hay = [
          j.title,
          j.location,
          j.function || "",
          j.description || "",
          (j.required_skills || []).join(" "),
          (j.nice_to_have_skills || []).join(" "),
          (j.tags || []).join(" "),
        ]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(k)) return false;
      }
      return true;
    });
  }, [jobs, keyword, location, functionFilter]);

  return (
    <section>
      <div className="mb-5">
        <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold mb-1">
          Explore everything
        </p>
        <h2 className="text-2xl font-display text-axis-ink leading-tight">
          All open positions at Axis Bank
        </h2>
        <p className="text-sm text-axis-muted mt-1 max-w-2xl">
          Search across every open role — filter by keyword, location or
          function.
        </p>
      </div>

      <div className="bg-white border border-axis-divider rounded-2xl shadow-sm p-6">
        <div className="grid sm:grid-cols-3 gap-3 mb-5">
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="Keyword (title, skill, team)"
            className="px-3 py-2.5 text-sm border border-axis-divider rounded-lg bg-axis-surface text-axis-ink focus:outline-none focus:border-axis-magenta"
          />
          <select
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className="px-3 py-2.5 text-sm border border-axis-divider rounded-lg bg-axis-surface text-axis-ink focus:outline-none focus:border-axis-magenta"
          >
            <option value="">All locations</option>
            {locations.map((loc) => (
              <option key={loc} value={loc}>
                {loc}
              </option>
            ))}
          </select>
          <select
            value={functionFilter}
            onChange={(e) => setFunctionFilter(e.target.value)}
            className="px-3 py-2.5 text-sm border border-axis-divider rounded-lg bg-axis-surface text-axis-ink focus:outline-none focus:border-axis-magenta"
          >
            <option value="">All functions</option>
            {functions.map((fn) => (
              <option key={fn} value={fn}>
                {fn}
              </option>
            ))}
          </select>
        </div>

        <p className="text-xs text-axis-muted mb-4 font-semibold">
          {jobs == null
            ? "Loading open positions…"
            : `${filtered.length} of ${jobs.length} open positions`}
        </p>

        {filtered.length > 0 ? (
          <ul className="space-y-3">
            {filtered.map((job) => (
              <li
                key={job.id}
                className="border border-axis-divider rounded-xl p-5 flex items-start justify-between gap-4 hover:border-axis-magenta/40 hover:bg-axis-surface/30 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-axis-ink">{job.title}</p>
                  <p className="text-xs text-axis-muted mt-0.5">
                    {job.location}
                    {job.function ? ` · ${job.function}` : ""}
                    {job.band ? ` · ${job.band}` : ""}
                  </p>
                  {job.required_skills?.length ? (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {job.required_skills.slice(0, 5).map((s) => (
                        <span
                          key={s}
                          className="text-[11px] px-2 py-0.5 rounded-full bg-axis-surface border border-axis-divider text-axis-ink"
                        >
                          {s}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={() => onApply(job)}
                  disabled={applying === `search:${job.id}`}
                  className="mt-1 px-4 py-2 text-xs font-semibold bg-axis-magenta text-white rounded-lg disabled:opacity-50 whitespace-nowrap hover:bg-axis-burgundy transition-colors"
                >
                  {applying === `search:${job.id}` ? "Applying…" : "Apply →"}
                </button>
              </li>
            ))}
          </ul>
        ) : jobs != null ? (
          <p className="text-sm text-axis-muted">
            No positions match your filters. Try clearing them.
          </p>
        ) : null}
      </div>
    </section>
  );
}

function SectionHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle: string | null;
}) {
  return (
    <div className="mb-5">
      <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold mb-1">
        {eyebrow}
      </p>
      <h2 className="text-2xl font-display text-axis-ink leading-tight">
        {title}
      </h2>
      {subtitle ? (
        <p className="text-sm text-axis-muted mt-1 max-w-2xl">{subtitle}</p>
      ) : null}
    </div>
  );
}

function RecCard({
  rec,
  onApply,
  applying,
  accent,
}: {
  rec: ExternalRecommendation;
  onApply: () => void;
  applying: boolean;
  accent: "magenta" | "burgundy";
}) {
  const accentText =
    accent === "magenta" ? "text-axis-magenta" : "text-axis-burgundy";
  const accentBg =
    accent === "magenta"
      ? "bg-axis-magenta/10 border-axis-magenta/30"
      : "bg-axis-burgundy/10 border-axis-burgundy/30";

  return (
    <div className="bg-white border border-axis-divider rounded-2xl shadow-sm hover:shadow-md transition-shadow p-6">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-5">
        <div className="flex-1 min-w-0">
          <p className="text-base font-semibold text-axis-ink">
            {rec.job_title}
          </p>
          <p className="text-xs text-axis-muted mt-0.5">{rec.location}</p>
          <p className="text-sm text-axis-ink/80 mt-3 leading-relaxed">
            {rec.rationale}
          </p>
          {rec.matched_skills.length > 0 ? (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {rec.matched_skills.slice(0, 6).map((s) => (
                <span
                  key={s}
                  className="text-[11px] px-2 py-0.5 rounded-full bg-axis-surface border border-axis-divider text-axis-ink"
                >
                  {s}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex sm:flex-col items-center sm:items-end gap-4 sm:gap-3 sm:min-w-[120px]">
          <div
            className={`px-3 py-2 rounded-xl border ${accentBg} text-center`}
          >
            <p className={`text-2xl font-display leading-none ${accentText}`}>
              {Math.round(rec.match_percent)}%
            </p>
            <p className="text-[9px] uppercase tracking-wider text-axis-muted mt-1 font-semibold">
              Match
            </p>
          </div>
          <button
            type="button"
            onClick={onApply}
            disabled={applying}
            className="px-4 py-2 text-xs font-semibold bg-axis-magenta text-white rounded-lg disabled:opacity-50 whitespace-nowrap hover:bg-axis-burgundy transition-colors"
          >
            {applying ? "Applying…" : "Apply →"}
          </button>
        </div>
      </div>
    </div>
  );
}

function fmtINR(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(2)} L`;
  return `₹${n.toLocaleString("en-IN")}`;
}
