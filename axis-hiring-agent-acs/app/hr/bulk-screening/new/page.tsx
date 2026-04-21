"use client";

/**
 * New Bulk Screening — two modes:
 *
 * 1. **Single JD** — pick a role, upload CVs, score all against that JD.
 * 2. **Auto-map** — drop all CVs, AI maps each to the best-fitting open role.
 *
 * On submit we POST multipart to /hr/bulk-intake (with or without job_id),
 * get a pool_id back, and redirect to the leaderboard page which polls for
 * live progress.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { BulkUploadDropzone } from "@/components/hr/BulkUploadDropzone";
import { api, type Job } from "@/lib/api";

export default function NewBulkScreeningPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <NewBulkScreeningContent />
    </RoleGate>
  );
}

type ScreeningMode = "single_jd" | "auto_map";

function NewBulkScreeningContent() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [mode, setMode] = useState<ScreeningMode>("single_jd");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [customCriteria, setCustomCriteria] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listJobs().then(setJobs);
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (mode === "single_jd" && !selectedJobId) {
      setError("Please select a job description to score against.");
      return;
    }
    if (files.length === 0) {
      setError("Please upload at least one CV.");
      return;
    }

    setSubmitting(true);
    try {
      const jobId = mode === "single_jd" ? selectedJobId : null;
      const result = await api.bulkIntake(jobId, files, customCriteria);
      router.push(`/hr/bulk-screening/${result.pool_id}/review`);
    } catch (err: any) {
      setError(err?.message || "Something went wrong.");
      setSubmitting(false);
    }
  }

  return (
    <>
      <TopBar />
      <HRSubNav />
      <main className="min-h-screen bg-axis-surface py-10 px-6">
        <div className="max-w-3xl mx-auto">
          <div className="h-1 w-16 bg-axis-burgundy rounded mb-4" />
          <h1 className="text-2xl font-display text-axis-ink mb-2">
            New Screening Batch
          </h1>
          <p className="text-axis-muted text-sm mb-8">
            Upload CVs and let the AI engine evaluate, rank, and map every
            candidate — against a specific role or across all open positions.
          </p>

          {error && (
            <div className="mb-6 bg-red-50 border border-red-200 text-red-800 rounded-card p-3 text-sm">
              {error}
            </div>
          )}

          <form
            onSubmit={onSubmit}
            className="bg-axis-canvas border border-axis-divider rounded-card shadow-card p-6 space-y-6"
          >
            {/* Mode selector */}
            <div>
              <label className="block text-xs font-semibold text-axis-ink mb-2">
                Screening mode
              </label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setMode("single_jd")}
                  disabled={submitting}
                  className={`p-4 rounded-lg border-2 text-left transition-all ${
                    mode === "single_jd"
                      ? "border-axis-magenta bg-axis-magenta/5 shadow-sm"
                      : "border-axis-divider bg-axis-surface hover:border-axis-muted"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`w-3 h-3 rounded-full border-2 flex items-center justify-center ${
                      mode === "single_jd" ? "border-axis-magenta" : "border-axis-muted"
                    }`}>
                      {mode === "single_jd" && (
                        <span className="w-1.5 h-1.5 rounded-full bg-axis-magenta" />
                      )}
                    </span>
                    <span className="text-sm font-semibold text-axis-ink">
                      Score against a specific role
                    </span>
                  </div>
                  <p className="text-[11px] text-axis-muted ml-5">
                    Select one JD and rank all uploaded CVs against that role
                    with detailed match insights.
                  </p>
                </button>

                <button
                  type="button"
                  onClick={() => setMode("auto_map")}
                  disabled={submitting}
                  className={`p-4 rounded-lg border-2 text-left transition-all ${
                    mode === "auto_map"
                      ? "border-axis-magenta bg-axis-magenta/5 shadow-sm"
                      : "border-axis-divider bg-axis-surface hover:border-axis-muted"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`w-3 h-3 rounded-full border-2 flex items-center justify-center ${
                      mode === "auto_map" ? "border-axis-magenta" : "border-axis-muted"
                    }`}>
                      {mode === "auto_map" && (
                        <span className="w-1.5 h-1.5 rounded-full bg-axis-magenta" />
                      )}
                    </span>
                    <span className="text-sm font-semibold text-axis-ink">
                      Auto-map to all open roles
                    </span>
                  </div>
                  <p className="text-[11px] text-axis-muted ml-5">
                    Drop all resumes — AI scores each CV against every open
                    position and maps them to the best-fitting role
                    automatically.
                  </p>
                  {mode === "auto_map" && (
                    <div className="mt-2 ml-5 text-[10px] text-axis-magenta font-medium">
                      {jobs.length} open role{jobs.length !== 1 ? "s" : ""} will
                      be evaluated
                    </div>
                  )}
                </button>
              </div>
            </div>

            {/* JD picker — only in single_jd mode */}
            {mode === "single_jd" && (
              <div>
                <label className="block text-xs font-semibold text-axis-ink mb-1">
                  Score against this JD
                </label>
                <select
                  value={selectedJobId}
                  onChange={(e) => setSelectedJobId(e.target.value)}
                  disabled={submitting}
                  className="w-full text-sm bg-axis-surface border border-axis-divider rounded p-2"
                >
                  <option value="">Select a role...</option>
                  {jobs.map((j) => (
                    <option key={j.id} value={j.id}>
                      {j.title} &middot; {j.location} &middot; {j.band}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Auto-map info panel */}
            {mode === "auto_map" && jobs.length > 0 && (
              <div className="bg-indigo-50/50 border border-indigo-200 rounded-lg p-4">
                <p className="text-xs font-semibold text-indigo-800 mb-2">
                  Resumes will be scored against {jobs.length} open
                  role{jobs.length !== 1 ? "s" : ""}:
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {jobs.map((j) => (
                    <span
                      key={j.id}
                      className="text-[10px] px-2 py-0.5 bg-white border border-indigo-200 text-indigo-700 rounded-full"
                    >
                      {j.title}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Additional screening criteria — optional free-text guidance
                the HR partner passes to the AI alongside the JD match (e.g.
                intel from the hiring manager about preferred backgrounds,
                hard-blocking requirements, or candidates to avoid). */}
            <div>
              <div className="flex items-baseline justify-between mb-1">
                <label className="block text-xs font-semibold text-axis-ink">
                  Additional screening criteria{" "}
                  <span className="text-axis-muted font-normal">(optional)</span>
                </label>
                <span className="text-[10px] text-axis-muted">
                  Weighed alongside the JD match
                </span>
              </div>
              <p className="text-[11px] text-axis-muted mb-2">
                Share any context from your internal team that the AI should
                factor in — preferred background, hard-blocking requirements,
                red flags, anything specific to this batch.
              </p>
              <textarea
                value={customCriteria}
                onChange={(e) => setCustomCriteria(e.target.value)}
                disabled={submitting}
                rows={3}
                placeholder={
                  "e.g. Prefer candidates from Tier-1 private banks. Must have NRI desk exposure. Avoid those with < 2yr tenure in current role."
                }
                className="w-full text-sm bg-axis-surface border border-axis-divider rounded p-2 focus:border-axis-magenta focus:outline-none"
              />
              <div className="mt-2 flex flex-wrap gap-1.5">
                <span className="text-[10px] text-axis-muted self-center mr-1">
                  Suggestions:
                </span>
                {[
                  "Prefer Tier-1 private bank experience",
                  "Must have NRI / HNI desk exposure",
                  "Minimum 3 years in current role",
                  "Avoid candidates from direct competitors (HDFC, ICICI)",
                  "Prioritise candidates with regional language fluency",
                  "Strong preference for candidates within 30 km of branch",
                ].map((s) => (
                  <button
                    key={s}
                    type="button"
                    disabled={submitting}
                    onClick={() =>
                      setCustomCriteria((prev) =>
                        prev.trim()
                          ? prev.replace(/\.?\s*$/, "") + ". " + s
                          : s,
                      )
                    }
                    className="text-[10px] px-2 py-1 rounded-full border border-axis-divider bg-axis-canvas text-axis-ink-soft hover:border-axis-magenta hover:text-axis-magenta"
                  >
                    + {s}
                  </button>
                ))}
              </div>
            </div>

            {/* Drop zone */}
            <div>
              <label className="block text-xs font-semibold text-axis-ink mb-1">
                Upload CVs (PDF, DOCX, or TXT)
              </label>
              <BulkUploadDropzone
                onFilesChange={setFiles}
                disabled={submitting}
              />
            </div>

            {/* Submit */}
            {submitting ? (
              <div className="border border-axis-magenta/30 bg-axis-magenta/5 rounded-card p-4">
                <div className="flex items-center gap-3">
                  <span className="inline-block w-5 h-5 rounded-full border-2 border-axis-magenta border-t-transparent animate-spin" />
                  <div>
                    <p className="text-sm font-semibold text-axis-ink">
                      {mode === "auto_map"
                        ? `Uploading and mapping ${files.length} CVs across ${jobs.length} open roles...`
                        : `Uploading and starting AI screening...`}
                    </p>
                    <p className="text-xs text-axis-muted">
                      {files.length} files being sent to the AI engine.
                      {mode === "auto_map" &&
                        " Each CV will be scored against every open position."}
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-5 py-2 text-sm font-semibold bg-axis-magenta text-white rounded disabled:opacity-50"
                >
                  {mode === "auto_map"
                    ? `Auto-map & rank (${files.length} file${files.length !== 1 ? "s" : ""})`
                    : `Start AI screening (${files.length} file${files.length !== 1 ? "s" : ""})`}
                </button>
              </div>
            )}
          </form>
        </div>
      </main>
      <Footer />
    </>
  );
}
