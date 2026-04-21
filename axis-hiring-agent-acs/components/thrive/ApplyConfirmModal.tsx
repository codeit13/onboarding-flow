"use client";

import { useEffect, useState } from "react";
import type { Candidate, Job } from "@/lib/api";

/**
 * Guided pre-Apply confirmation.
 *
 * The user explicitly asked for the UI to *guide* them: tell them what's
 * about to happen BEFORE they confirm, and after they confirm tell them what
 * the agent will do next. This modal is the "before" half — it shows:
 *
 *  - which JD they are applying to
 *  - the live match preview against their profile
 *  - which of their skills matched / what's missing
 *  - the exact sequence of steps the agent will run on their behalf
 *  - a single primary CTA: "Submit application to AI agent"
 *
 * The status page handles the "after" half (what's happening now / what's
 * happening next).
 */

interface Props {
  open: boolean;
  job: Job | null;
  candidate: Candidate | null;
  matchPercent: number;
  matchedSkills: string[];
  missingSkills: string[];
  submitting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ApplyConfirmModal({
  open,
  job,
  candidate,
  matchPercent,
  matchedSkills,
  missingSkills,
  submitting,
  onCancel,
  onConfirm,
}: Props) {
  // Lock background scroll while open.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open || !job || !candidate) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="apply-modal-title"
    >
      <div className="bg-axis-canvas rounded-card shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-axis-divider">
          <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
            Step 1 of 2 · Review before you apply
          </p>
          <h2
            id="apply-modal-title"
            className="text-xl font-semibold text-axis-ink mt-1"
          >
            {job.title}
          </h2>
          <p className="text-xs text-axis-muted mt-1">
            Job ID {job.job_id} · {job.location} · Band {job.band}
          </p>
        </div>

        {/* Match summary */}
        <div className="px-6 py-4 border-b border-axis-divider bg-axis-surface">
          <div className="flex items-start gap-4">
            <div className="shrink-0 w-16 h-16 rounded-full bg-axis-teal text-white flex items-center justify-center text-xl font-bold border-2 border-axis-teal-dark">
              {Math.round(matchPercent)}%
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-axis-ink">
                Live skills match against your Thrive profile
              </p>
              <p className="text-xs text-axis-muted mt-0.5">
                Computed from your KRAs, skills catalogue and tenure as{" "}
                <strong className="text-axis-ink">{candidate.name}</strong>.
              </p>
            </div>
          </div>

          {matchedSkills.length > 0 && (
            <div className="mt-3">
              <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                Matched skills ({matchedSkills.length})
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {matchedSkills.map((s) => (
                  <span
                    key={s}
                    className="text-[10px] px-2 py-0.5 rounded bg-axis-pink-soft text-axis-burgundy"
                  >
                    ✓ {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {missingSkills.length > 0 && (
            <div className="mt-3">
              <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                Skills you'll need to demonstrate ({missingSkills.length})
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {missingSkills.map((s) => (
                  <span
                    key={s}
                    className="text-[10px] px-2 py-0.5 rounded border border-axis-divider text-axis-ink-soft"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* What happens next */}
        <div className="px-6 py-4 border-b border-axis-divider">
          <p className="text-xs font-semibold text-axis-ink mb-2">
            What the AI Hiring Agent will do once you submit
          </p>
          <ol className="space-y-2">
            {[
              {
                step: "1",
                title: "Screen your profile against the JD",
                detail:
                  "The agent runs your KRAs and skills through the JD rubric in real time and decides whether you clear the shortlist threshold.",
              },
              {
                step: "2",
                title: "Propose 3 Round 1 interview slots",
                detail:
                  "It checks your Business Partner's calendar, intersects free windows, and emails you 3 candidate slots. You'll pick one from your live status page.",
              },
              {
                step: "3",
                title: "Run the Round 1 AI interview",
                detail:
                  "Once you confirm a slot, the agent books a Teams meeting and runs the conversational interview. You'll see the transcript captured live.",
              },
              {
                step: "4",
                title: "Coordinate Round 2 with the hiring panel",
                detail:
                  "If R1 passes, your Business Partner approves the panel composition and the agent finds a common slot across the panel + you, then books it.",
              },
            ].map((s) => (
              <li key={s.step} className="flex gap-3">
                <span className="shrink-0 w-5 h-5 rounded-full bg-axis-magenta text-white text-[10px] font-bold flex items-center justify-center mt-0.5">
                  {s.step}
                </span>
                <div>
                  <p className="text-xs font-semibold text-axis-ink">{s.title}</p>
                  <p className="text-[11px] text-axis-muted leading-snug mt-0.5">
                    {s.detail}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <div className="mt-3 p-2 rounded bg-axis-cream border border-axis-cream-border text-[11px] text-axis-ink">
            <strong>You stay in control.</strong> The agent will pause and ask
            you whenever a decision needs your input — slot confirmation, panel
            approval, etc. Nothing is auto-confirmed without you.
          </div>
        </div>

        {/* Actions */}
        <div className="px-6 py-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="px-4 py-2 text-xs text-axis-ink-soft hover:text-axis-ink disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={submitting}
            className="px-5 py-2 text-xs font-semibold rounded bg-axis-magenta text-white hover:bg-axis-burgundy disabled:opacity-50 disabled:cursor-wait"
          >
            {submitting ? "Submitting to agent…" : "Submit application to AI agent"}
          </button>
        </div>
      </div>
    </div>
  );
}
