"use client";

/**
 * External candidate intake page.
 *
 * Layout:
 *  - Top: resume upload (PDF / DOCX / TXT). Once parsed, the AI ranks
 *    open jobs against the candidate and the list below re-orders by
 *    match %, with a coloured badge on each card.
 *  - Below: a browsable, filterable list of every open job. Works even
 *    without a resume — search by title, filter by location.
 *  - Once the candidate clicks Apply on any card, the page flips to a
 *    live status panel that polls the orchestrator until R1 is booked.
 */
import { useEffect, useMemo, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { api, Application, Job } from "@/lib/api";

type ParseResult = Awaited<ReturnType<typeof api.externalParseResumeFile>>;
type Match = ParseResult["matches"][number];

const PROCESSING_STEPS = [
  "Reading your resume…",
  "Extracting your skills, roles and tenure…",
  "Understanding your profile…",
  "Matching you against every open Axis role…",
  "Preparing your personalised rationales…",
  "Ranking the strongest matches for you…",
];

export default function ExternalCandidatePage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(true);

  const [resumeText, setResumeText] = useState<string | null>(null);
  const [parseResult, setParseResult] = useState<ParseResult | null>(null);
  const [parsing, setParsing] = useState(false);
  const [parseStep, setParseStep] = useState(0);
  const [uploadName, setUploadName] = useState<string | null>(null);

  const [applying, setApplying] = useState<string | null>(null);
  const [application, setApplication] = useState<Application | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Search / filter state for the browse-all-jobs section.
  const [search, setSearch] = useState("");
  const [locationFilter, setLocationFilter] = useState("");

  // Load all open jobs on mount so the browse view works without a resume.
  useEffect(() => {
    let cancelled = false;
    api
      .listJobs()
      .then((j) => {
        if (!cancelled) setJobs(j);
      })
      .catch((e) => !cancelled && setError(e?.message || "Failed to load jobs"))
      .finally(() => !cancelled && setLoadingJobs(false));
    return () => {
      cancelled = true;
    };
  }, []);

  // Poll the application after apply.
  useEffect(() => {
    if (!application) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const fresh = await api.getApplication(application.id);
        if (!cancelled) setApplication(fresh);
      } catch {
        /* swallow */
      }
    };
    const i = setInterval(tick, 2500);
    return () => {
      cancelled = true;
      clearInterval(i);
    };
  }, [application?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Cycle the processing-status string while the AI call is in flight,
  // so the user can see the agent visibly working.
  useEffect(() => {
    if (!parsing) {
      setParseStep(0);
      return;
    }
    const i = setInterval(() => {
      setParseStep((s) => (s + 1) % PROCESSING_STEPS.length);
    }, 1500);
    return () => clearInterval(i);
  }, [parsing]);

  async function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setParsing(true);
    setParseResult(null);
    setUploadName(file.name);
    try {
      const r = await api.externalParseResumeFile(file);
      setParseResult(r);
      setResumeText(r.resume_text);
    } catch (err: any) {
      setError(err?.message || "Failed to parse resume");
    } finally {
      setParsing(false);
    }
  }

  async function onApply(jobId: string) {
    if (!resumeText) {
      setError(
        "Upload your resume first — Axis needs it on file before you can apply.",
      );
      return;
    }
    setError(null);
    setApplying(jobId);
    try {
      const a = await api.externalApply(resumeText, jobId);
      setApplication(a);
    } catch (e: any) {
      setError(e?.message || "Failed to apply");
    } finally {
      setApplying(null);
    }
  }

  // Build a {jobId → match} map for fast lookup when rendering cards.
  const matchByJobId = useMemo(() => {
    const m = new Map<string, Match>();
    parseResult?.matches.forEach((x) => m.set(x.job_id, x));
    return m;
  }, [parseResult]);

  // Filter + sort the jobs list. If we have a parse result, sort by
  // match %; otherwise leave the original order.
  const visibleJobs = useMemo(() => {
    let list = jobs.filter((j) => {
      if (
        search &&
        !`${j.title} ${j.tags?.join(" ") ?? ""}`
          .toLowerCase()
          .includes(search.toLowerCase())
      )
        return false;
      if (
        locationFilter &&
        !j.location.toLowerCase().includes(locationFilter.toLowerCase())
      )
        return false;
      return true;
    });
    if (parseResult) {
      list = [...list].sort((a, b) => {
        const ma = matchByJobId.get(a.id)?.match_percent ?? -1;
        const mb = matchByJobId.get(b.id)?.match_percent ?? -1;
        return mb - ma;
      });
    }
    return list;
  }, [jobs, search, locationFilter, parseResult, matchByJobId]);

  const allLocations = useMemo(
    () => Array.from(new Set(jobs.map((j) => j.location))).sort(),
    [jobs],
  );

  return (
    <>
      <TopBar />
      <main className="min-h-screen bg-axis-surface py-10 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="h-1 w-20 bg-axis-burgundy rounded mb-6" />
          <h1 className="text-3xl font-display text-axis-ink mb-2">
            Apply to Axis · External candidate
          </h1>
          <p className="text-axis-muted mb-8 max-w-2xl">
            No Axis employee ID needed. Upload your resume and we'll
            rank our open jobs by how well they match your profile. You
            can also browse and filter all open jobs below — apply once
            you've uploaded your resume.
          </p>

          {error ? (
            <div className="mb-6 bg-red-50 border border-red-200 text-red-800 rounded-card p-3 text-sm">
              {error}
            </div>
          ) : null}

          {/* ---- Resume upload ---- */}
          {!application && (
            <section className="bg-axis-canvas border border-axis-divider rounded-card shadow-card p-6 mb-6">
              <h2 className="text-lg font-display text-axis-ink mb-1">
                Upload your resume
              </h2>
              <p className="text-xs text-axis-muted mb-4">
                Accepts PDF, DOCX, or plain text. We'll read it and
                match you against every open Axis job.
              </p>
              <div className="flex items-center gap-3 flex-wrap">
                <label
                  className={`px-4 py-2 text-white text-sm font-semibold rounded cursor-pointer ${
                    parsing
                      ? "bg-axis-magenta/60 cursor-not-allowed"
                      : "bg-axis-magenta"
                  }`}
                >
                  {parsing ? "Analysing…" : "Choose file"}
                  <input
                    type="file"
                    accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
                    onChange={onFileChange}
                    disabled={parsing}
                    className="hidden"
                  />
                </label>
                {uploadName ? (
                  <span className="text-xs text-axis-muted">{uploadName}</span>
                ) : null}
                {parseResult && !parsing ? (
                  <span className="text-xs text-green-700">
                    ✓ Resume reviewed — {parseResult.profile.name} ·{" "}
                    {parseResult.profile.skills.length} skills detected
                  </span>
                ) : null}
              </div>

              {/* Visible processing state — never let the user stare at a
                  frozen screen while the agent is working. */}
              {parsing ? (
                <div className="mt-5 border border-axis-magenta/30 bg-axis-magenta/5 rounded-card p-4">
                  <div className="flex items-center gap-3">
                    <Spinner />
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-axis-ink">
                        Reviewing your resume
                      </p>
                      <p className="text-xs text-axis-muted">
                        {PROCESSING_STEPS[parseStep]}
                      </p>
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-6 gap-1">
                    {PROCESSING_STEPS.map((_, i) => (
                      <div
                        key={i}
                        className={`h-1 rounded ${
                          i <= parseStep
                            ? "bg-axis-magenta"
                            : "bg-axis-divider"
                        }`}
                      />
                    ))}
                  </div>
                </div>
              ) : null}
            </section>
          )}

          {/* ---- Browse + filter all jobs ---- */}
          {!application && (
            <section className="bg-axis-canvas border border-axis-divider rounded-card shadow-card p-6 mb-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-display text-axis-ink">
                  {parseResult
                    ? "Open jobs · ranked by match"
                    : "Open jobs · all"}
                </h2>
                <span className="text-xs text-axis-muted">
                  {visibleJobs.length} of {jobs.length}
                </span>
              </div>

              <div className="grid sm:grid-cols-2 gap-3 mb-4">
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search by title or tag…"
                  className="text-sm bg-axis-surface border border-axis-divider rounded p-2"
                />
                <select
                  value={locationFilter}
                  onChange={(e) => setLocationFilter(e.target.value)}
                  className="text-sm bg-axis-surface border border-axis-divider rounded p-2"
                >
                  <option value="">All locations</option>
                  {allLocations.map((loc) => (
                    <option key={loc} value={loc}>
                      {loc}
                    </option>
                  ))}
                </select>
              </div>

              {parsing ? (
                <ul className="space-y-3">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <li
                      key={i}
                      className="border border-axis-divider rounded p-4 animate-pulse"
                    >
                      <div className="h-4 w-2/3 bg-axis-divider rounded mb-2" />
                      <div className="h-3 w-1/3 bg-axis-divider rounded mb-3" />
                      <div className="h-3 w-full bg-axis-divider rounded" />
                    </li>
                  ))}
                </ul>
              ) : loadingJobs ? (
                <p className="text-sm text-axis-muted">Loading jobs…</p>
              ) : visibleJobs.length === 0 ? (
                <p className="text-sm text-axis-muted">
                  No open jobs match those filters.
                </p>
              ) : (
                <ul className="space-y-3">
                  {visibleJobs.map((j) => {
                    const m = matchByJobId.get(j.id);
                    return (
                      <li
                        key={j.id}
                        className="border border-axis-divider rounded p-4 flex items-start justify-between gap-4"
                      >
                        <div className="flex-1">
                          <p className="font-semibold text-axis-ink">
                            {j.title}
                          </p>
                          <p className="text-xs text-axis-muted mb-2">
                            {j.location} · {j.band} · {j.function}
                          </p>
                          {j.required_skills?.length ? (
                            <p className="text-xs text-axis-muted">
                              <strong>Required:</strong>{" "}
                              {j.required_skills.slice(0, 5).join(", ")}
                            </p>
                          ) : null}
                          {m ? (
                            <p className="text-xs text-axis-muted mt-1">
                              {m.rationale}
                            </p>
                          ) : null}
                        </div>
                        <div className="text-right flex flex-col items-end">
                          {m ? (
                            <p
                              className={`text-2xl font-display ${
                                m.match_percent >= 75
                                  ? "text-axis-magenta"
                                  : "text-axis-muted"
                              }`}
                            >
                              {Math.round(m.match_percent)}%
                            </p>
                          ) : (
                            <p className="text-xs text-axis-muted">
                              Upload resume<br />for match
                            </p>
                          )}
                          <button
                            type="button"
                            onClick={() => onApply(j.id)}
                            disabled={!resumeText || applying === j.id}
                            className="mt-2 px-3 py-1.5 text-xs font-semibold bg-axis-magenta text-white rounded disabled:opacity-50"
                          >
                            {applying === j.id ? "Applying…" : "Apply"}
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          )}

          {/* ---- Live application status ---- */}
          {application ? (
            <ApplicationStatus
              application={application}
              candidateEmail={parseResult?.profile.email ?? ""}
            />
          ) : null}
        </div>
      </main>
    </>
  );
}

function Spinner() {
  return (
    <span
      className="inline-block w-5 h-5 rounded-full border-2 border-axis-magenta border-t-transparent animate-spin"
      aria-label="Loading"
    />
  );
}

function ApplicationStatus({
  application,
  candidateEmail,
}: {
  application: Application;
  candidateEmail: string;
}) {
  const [confirming, setConfirming] = useState<number | null>(null);
  const [slotError, setSlotError] = useState<string | null>(null);

  async function onConfirmSlot(index: number) {
    setConfirming(index);
    setSlotError(null);
    try {
      await api.confirmSlot(application.id, index, "R1");
    } catch (e: any) {
      setSlotError(
        e?.message ||
          "We couldn't confirm that slot right now. Please try again.",
      );
    } finally {
      setConfirming(null);
    }
  }

  const status = application.agent_status;
  const isWaiting = status === "waiting_candidate";
  const proposedR1 = application.proposed_r1_slots ?? [];
  const r1 = application.interviews?.find((i) => i.round === "R1");

  // Humanised status label — no backend jargon.
  const friendlyStatus = (() => {
    if (r1?.meeting_slot) return "Round 1 booked";
    if (isWaiting && proposedR1.length > 0) return "Pick your Round 1 slot";
    if (status === "running") return "Reviewing your profile…";
    return "In progress";
  })();

  return (
    <section className="bg-axis-canvas border border-axis-divider rounded-card shadow-card p-6 mb-6">
      <div className="flex items-start justify-between gap-4 mb-1">
        <h2 className="text-lg font-display text-axis-ink">
          Your application is live
        </h2>
        <span className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold bg-axis-pink-soft px-2 py-1 rounded">
          {friendlyStatus}
        </span>
      </div>
      <p className="text-sm text-axis-muted mb-5">
        Thanks for applying — we've received your resume and the hiring team
        is reviewing it. You'll see every update right here.
      </p>

      {proposedR1.length > 0 && isWaiting ? (
        <div className="mb-4">
          <p className="text-sm font-semibold text-axis-ink mb-1">
            Choose your preferred Round 1 interview slot
          </p>
          <p className="text-xs text-axis-muted mb-3">
            We've also sent these times to{" "}
            <strong className="text-axis-ink">{candidateEmail}</strong>. Pick
            the one that works for you and we'll send a Teams meeting invite
            instantly.
          </p>
          {slotError && (
            <div className="mb-3 p-2 rounded bg-axis-pink-soft border border-axis-magenta text-xs text-axis-burgundy">
              {slotError}
            </div>
          )}
          <div className="grid sm:grid-cols-3 gap-3">
            {proposedR1.map((s, i) => {
              const start = new Date(s.start);
              const end = new Date(s.end);
              const dateLabel = start.toLocaleDateString(undefined, {
                weekday: "short",
                day: "numeric",
                month: "short",
              });
              const timeLabel = `${start.toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
              })} – ${end.toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
              })}`;
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => onConfirmSlot(i)}
                  disabled={confirming !== null}
                  className="group text-left border border-axis-divider rounded-card p-4 hover:border-axis-magenta hover:bg-axis-pink-soft/40 transition disabled:opacity-50 disabled:cursor-wait"
                >
                  <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold mb-1">
                    Option {i + 1}
                  </p>
                  <p className="text-sm font-semibold text-axis-ink">
                    {dateLabel}
                  </p>
                  <p className="text-xs text-axis-muted">{timeLabel}</p>
                  <p className="mt-3 text-xs font-semibold text-axis-magenta group-hover:underline">
                    {confirming === i ? "Confirming…" : "Confirm this slot →"}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      {r1?.meeting_slot ? (
        <div className="mt-4 p-4 bg-axis-cream border border-axis-cream-border rounded-card">
          <p className="text-sm font-semibold text-axis-ink">
            ✓ Round 1 interview booked
          </p>
          <p className="text-xs text-axis-muted mt-1">
            {new Date(r1.meeting_slot.start).toLocaleString()} —{" "}
            {new Date(r1.meeting_slot.end).toLocaleTimeString(undefined, {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
          {r1.teams_join_url ? (
            <a
              href={r1.teams_join_url}
              target="_blank"
              rel="noreferrer"
              className="inline-block mt-3 px-3 py-1.5 text-xs font-semibold bg-axis-magenta text-white rounded hover:bg-axis-burgundy transition"
            >
              Join Teams meeting →
            </a>
          ) : null}
          <p className="text-[11px] text-axis-muted mt-3">
            A calendar invite has been sent to{" "}
            <strong className="text-axis-ink">{candidateEmail}</strong>. Keep
            an eye on your inbox for joining instructions.
          </p>
        </div>
      ) : null}
    </section>
  );
}
