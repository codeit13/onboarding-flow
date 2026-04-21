"use client";

/**
 * NEW external candidate intake page (Q2 demo refresh).
 *
 * Single-screen capture for everything we need before a candidate enters
 * the funnel:
 *  - Name + email (form-of-record identity)
 *  - Natural-language search query ("Branch Manager in Mumbai near Powai")
 *  - Resume upload (PDF / DOCX / TXT)
 *  - Latest salary slip upload (optional, also PDF / DOCX / TXT)
 *
 * On submit we POST everything in one multipart request to
 * /external/intake which runs Claude resume matcher + Claude semantic
 * job searcher + Claude salary extractor in one shot. Result is stashed
 * in localStorage and we route to /external/results which renders the
 * TWO ranked sections (NL search matches + AI recommendations).
 */

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { api, ExternalIntakeResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

const PROCESSING_STEPS = [
  "Reading your resume…",
  "Extracting skills, roles, and tenure…",
  "Parsing your latest salary slip…",
  "Understanding your search query…",
  "Scoring open Axis roles against your stated preference…",
  "Scoring open Axis roles against your qualifications…",
  "Ranking the strongest matches…",
];

const STORAGE_KEY = "axis_external_intake_v1";

export default function ExternalIntakePage() {
  return (
    <Suspense fallback={<div>Loading intake form...</div>}>
      <IntakeForm />
    </Suspense>
  );
}

function IntakeForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Pre-populate from query params when arriving from candidate Thrive portal
  const [name, setName] = useState(searchParams.get("name") || "");
  const [email, setEmail] = useState(searchParams.get("email") || "");
  const [query, setQuery] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [slip, setSlip] = useState<File | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const stepRef = useRef<NodeJS.Timeout | null>(null);

  // Visible processing UI — never silent latency.
  useEffect(() => {
    if (!submitting) {
      setStep(0);
      if (stepRef.current) clearInterval(stepRef.current);
      return;
    }
    stepRef.current = setInterval(() => {
      setStep((s) => (s + 1) % PROCESSING_STEPS.length);
    }, 1500);
    return () => {
      if (stepRef.current) clearInterval(stepRef.current);
    };
  }, [submitting]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!name.trim() || !email.trim()) {
      setError("Please enter your name and email so we can track your application.");
      return;
    }
    if (!resume) {
      setError("Please upload your resume — we need it on file before we can match jobs.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await api.externalIntake({
        resume,
        salarySlip: slip,
        name: name.trim(),
        email: email.trim(),
        searchQuery: query.trim(),
      });
      // Stash the full intake payload for the results page so we don't have
      // to round-trip Claude again.
      const stash: ExternalIntakeResponse & { _ts: number } = {
        ...result,
        _ts: Date.now(),
      };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(stash));
      } catch {
        /* private mode etc — ignore */
      }
      router.push("/external/results");
    } catch (err: any) {
      setError(err?.message || "Something went wrong. Please try again.");
      setSubmitting(false);
    }
  }

  return (
    <>
      <TopBar />
      <main className="min-h-screen bg-axis-surface py-10 px-6">
        <div className="max-w-3xl mx-auto">
          <div className="h-1 w-20 bg-axis-burgundy rounded mb-6" />
          <h1 className="text-3xl font-display text-axis-ink mb-2">
            Apply to Axis
          </h1>
          <p className="text-axis-muted mb-8 max-w-2xl">
            Tell us what you're looking for and upload your latest resume +
            salary slip. We'll read everything, search our open roles two
            ways — by what you said you want AND by your qualifications —
            and show you the strongest matches in seconds.
          </p>

          {error ? (
            <div className="mb-6 bg-red-50 border border-red-200 text-red-800 rounded-card p-3 text-sm">
              {error}
            </div>
          ) : null}

          <form
            onSubmit={onSubmit}
            className="bg-axis-canvas border border-axis-divider rounded-card shadow-card p-6 space-y-6"
          >
            {/* ---- Identity ---- */}
            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-axis-ink mb-1">
                  Full name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Priya Sharma"
                  required
                  disabled={submitting}
                  className="w-full text-sm bg-axis-surface border border-axis-divider rounded p-2"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-axis-ink mb-1">
                  Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="priya@example.com"
                  required
                  disabled={submitting}
                  className="w-full text-sm bg-axis-surface border border-axis-divider rounded p-2"
                />
              </div>
            </div>

            {/* ---- NL search ---- */}
            <div>
              <label className="block text-xs font-semibold text-axis-ink mb-1">
                What kind of role are you looking for?
              </label>
              <textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                rows={3}
                placeholder="e.g. I am looking for a Branch Manager role in any branch in Mumbai near Powai"
                disabled={submitting}
                className="w-full text-sm bg-axis-surface border border-axis-divider rounded p-2"
              />
              <p className="text-[11px] text-axis-muted mt-1">
                Plain English works best. Mention role, city, and any
                preferences — we'll understand the rest.
              </p>
            </div>

            {/* ---- Resume ---- */}
            <div>
              <label className="block text-xs font-semibold text-axis-ink mb-1">
                Resume (PDF, DOCX, or TXT) <span className="text-axis-magenta">*</span>
              </label>
              <input
                type="file"
                accept=".pdf,.docx,.txt"
                onChange={(e) => setResume(e.target.files?.[0] ?? null)}
                disabled={submitting}
                className="text-xs"
              />
              {resume ? (
                <p className="text-[11px] text-axis-muted mt-1">
                  ✓ {resume.name}
                </p>
              ) : null}
            </div>

            {/* ---- Salary slip ---- */}
            <div>
              <label className="block text-xs font-semibold text-axis-ink mb-1">
                Latest salary slip (optional, PDF/DOCX/TXT)
              </label>
              <input
                type="file"
                accept=".pdf,.docx,.txt"
                onChange={(e) => setSlip(e.target.files?.[0] ?? null)}
                disabled={submitting}
                className="text-xs"
              />
              <p className="text-[11px] text-axis-muted mt-1">
                Helps the hiring team think about offer fit early. We extract
                CTC + components automatically — never shown to other applicants.
              </p>
              {slip ? (
                <p className="text-[11px] text-axis-muted mt-1">✓ {slip.name}</p>
              ) : null}
            </div>

            {/* ---- Visible processing ---- */}
            {submitting ? (
              <div className="border border-axis-magenta/30 bg-axis-magenta/5 rounded-card p-4">
                <div className="flex items-center gap-3">
                  <Spinner />
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-axis-ink">
                      Reviewing your application
                    </p>
                    <p className="text-xs text-axis-muted">
                      {PROCESSING_STEPS[step]}
                    </p>
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-7 gap-1">
                  {PROCESSING_STEPS.map((_, i) => (
                    <div
                      key={i}
                      className={`h-1 rounded ${
                        i <= step ? "bg-axis-magenta" : "bg-axis-divider"
                      }`}
                    />
                  ))}
                </div>
              </div>
            ) : null}

            <div className="flex items-center justify-between pt-2">
              <a
                href="/external/applications"
                className="text-xs text-axis-magenta hover:underline"
              >
                Already applied? Track your applications →
              </a>
              <button
                type="submit"
                disabled={submitting}
                className="px-6 py-2.5 text-sm font-semibold bg-axis-burgundy text-white rounded-btn hover:bg-axis-burgundy-dark transition disabled:opacity-50"
              >
                {submitting ? "Analysing…" : "Find my matches →"}
              </button>
            </div>
          </form>
        </div>
      </main>
      <Footer />
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
