"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import { AgentActivityFeed } from "@/components/agent/AgentActivityFeed";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  api,
  type ActivityItem,
  type Application,
  type Job,
} from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";
import { usePersona } from "@/lib/persona";

type Rec = "strong_hire" | "hire" | "no_hire";

/**
 * Panel R2 feedback form.
 *
 * Panellists read the Round 2 Teams transcript and record their feedback
 * MANUALLY — no AI assistance on this page. AI review of the transcript is
 * a separate capability reserved for HR: after every panellist has voted,
 * HR receives the application back and can run an AI comparison of the
 * panel's feedback against Claude's read of the same transcript before
 * making the final offer / reject call.
 *
 * The application + job are fetched once on mount (we don't poll because
 * polling would clobber the form draft state). The activity feed beneath
 * the form polls every 4s so the panellist can watch the agent acknowledge
 * their vote after they submit — and the peer vote list refreshes too.
 */
export default function PanelFeedbackPage() {
  return (
    <RoleGate allow={["panel"]}>
      <PanelFeedbackContent />
    </RoleGate>
  );
}

function PanelFeedbackContent() {
  const params = useParams<{ appId: string }>();
  const router = useRouter();
  const [persona] = usePersona();

  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Poll the application every 4s so peer feedback that other panellists
  // submit while THIS panellist still has the page open shows up live in
  // the "What your peers said" card. We deliberately keep the form draft
  // (score/strengths/concerns/recommendation) in local React state so the
  // background refresh cannot clobber what the panellist is typing.
  const loadApp = useCallback(
    () => api.getApplication(params.appId),
    [params.appId],
  );
  const { data: app, refresh: refreshApp } = useAutoRefresh<Application>(
    loadApp,
    4000,
  );

  // Form fields start empty — the panellist fills them in manually after
  // reading the transcript. No AI pre-fill: that capability is HR-only.
  const [score, setScore] = useState<number | null>(null);
  const [strengths, setStrengths] = useState("");
  const [concerns, setConcerns] = useState("");
  const [recommendation, setRecommendation] = useState<Rec | null>(null);

  // "Selection ≠ commitment": clicking Submit only stages a confirm dialog.
  // The vote is irreversible (audit trail) so the panellist must explicitly
  // acknowledge that.
  const [pendingSubmit, setPendingSubmit] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  // Fetch the JD once we know which job_id this application is bound to.
  useEffect(() => {
    if (!app?.job_id) return;
    let cancelled = false;
    (async () => {
      try {
        const j = await api.getJob(app.job_id);
        if (!cancelled) setJob(j);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [app?.job_id]);

  // Activity feed *does* poll — the panellist wants to see the orchestrator
  // react after they submit.
  const loadActivity = useCallback(
    () => api.listActivity(params.appId),
    [params.appId],
  );
  const { data: activity } = useAutoRefresh<ActivityItem[]>(loadActivity, 4000);

  const r1 = app?.interviews.find((i) => i.round === "R1");
  const r2 = app?.interviews.find((i) => i.round === "R2");
  // Each panellist runs their own 1-on-1 with the candidate, so we show
  // THIS panellist's transcript (falling back to the legacy shared one).
  const r2Transcript =
    (persona.identity &&
      r2?.pasted_transcripts_by_panellist?.[persona.identity]) ||
    r2?.pasted_transcript ||
    "";

  // Has the current panellist already voted on this R2? If so, the page
  // becomes read-only and we hydrate the form with their submitted values.
  // Audit-trail rule: a recorded vote cannot be edited from the UI.
  const myVote = r2?.panel_feedback.find(
    (f) => f.panellist_id === persona.identity,
  );
  const isReadOnly = !!myVote;

  // Hydrate the form once when the app loads (only if this panellist has
  // already voted — then show their recorded values, frozen).
  useEffect(() => {
    if (!r2) return;
    if (myVote) {
      setScore(Math.round(myVote.score));
      setStrengths(myVote.strengths);
      setConcerns(myVote.concerns);
      setRecommendation(myVote.recommendation);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r2?.id, myVote?.panellist_id]);

  const submit = async () => {
    if (!r2) return;
    if (!persona.identity || persona.role !== "panel") {
      alert("Switch to Interview Panel persona first.");
      return;
    }
    if (score == null || recommendation == null) {
      alert("Set a score and pick a recommendation before submitting.");
      return;
    }
    setSubmitting(true);
    try {
      await api.submitPanelFeedback({
        interview_id: r2.id,
        panellist_id: persona.identity,
        score,
        strengths,
        concerns,
        recommendation,
      });
      // Tiny delay so the orchestrator's background tick has a chance to
      // log the wake-up event before the user lands back on the queue.
      setTimeout(() => router.push("/panel"), 600);
    } catch (e: any) {
      alert(`Submit failed: ${e?.message || e}`);
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <main className="flex-1 px-8 py-6 max-w-4xl w-full mx-auto">
        <Link
          href="/panel"
          className="text-axis-magenta text-xs font-medium hover:underline"
        >
          ← Back to panel queue
        </Link>

        {error && (
          <div className="mt-6 p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
            {error}
          </div>
        )}
        {!app && !error && (
          <p className="mt-6 text-sm text-axis-muted">Loading…</p>
        )}

        {app && job && (
          <>
            <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card shadow-card p-6">
              <p className="text-xs uppercase tracking-wider text-axis-magenta font-semibold">
                R2 feedback
              </p>
              <h1 className="text-2xl font-display text-axis-ink mt-1">
                {job.title}
              </h1>
              <p className="text-sm text-axis-muted mt-1">
                Candidate{" "}
                <strong className="text-axis-ink">{app.candidate_id}</strong> ·
                Match{" "}
                <strong className="text-axis-ink">
                  {app.match_percent.toFixed(0)}%
                </strong>
                {r1?.score != null && (
                  <>
                    {" "}
                    · R1 score{" "}
                    <strong className="text-axis-ink">{r1.score}/100</strong>
                  </>
                )}
              </p>
              {r1?.rationale && (
                <p className="text-xs text-axis-ink-soft mt-2">
                  R1 notes: {r1.rationale}
                </p>
              )}
              <p className="mt-3 text-[11px] text-axis-muted italic">
                Read the Round 2 transcript below and record your own
                assessment. The Business Partner will compare all panel feedback before making
                the final call.
              </p>
            </div>

            {/* R1 transcript summary */}
            {r1 && r1.transcript.length > 0 && (
              <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card p-4">
                <p className="text-xs uppercase text-axis-muted font-semibold">
                  R1 transcript
                </p>
                <div className="mt-2 text-xs space-y-1 max-h-48 overflow-y-auto">
                  {r1.transcript.map((t, i) => (
                    <p key={i}>
                      <span
                        className={`font-semibold ${
                          t.speaker === "interviewer"
                            ? "text-axis-magenta"
                            : "text-axis-ink"
                        }`}
                      >
                        {t.speaker}:{" "}
                      </span>
                      <span className="text-axis-ink-soft">{t.text}</span>
                    </p>
                  ))}
                </div>
              </div>
            )}

            {/* Proctoring alerts from R1 AI interview — shown to panel
                so they can factor integrity signals into their R2 verdict. */}
            {(() => {
              const violations =
                r1?.report?.proctoring_violations ?? r1?.proctoring_violations ?? [];
              if (violations.length === 0) return null;
              const critical = violations.filter(
                (v: any) => v.severity === "critical",
              );
              const warnings = violations.filter(
                (v: any) => v.severity === "warning",
              );
              return (
                <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card p-4">
                  <p className="text-xs uppercase text-axis-muted font-semibold">
                    R1 proctoring alerts ({violations.length})
                  </p>
                  <p className="text-[11px] text-axis-ink-soft mt-1 mb-2">
                    Flagged by the AI proctoring system during the Round 1
                    interview. Review these before recording your assessment.
                  </p>
                  {critical.length > 0 && (
                    <div className="mb-2">
                      <ul className="space-y-1">
                        {critical.map((v: any, i: number) => (
                          <li
                            key={`crit-${i}`}
                            className="flex items-start gap-2 text-xs border border-axis-magenta bg-axis-pink-soft rounded p-2"
                          >
                            <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] uppercase font-bold bg-axis-burgundy text-white">
                              {v.type.replace(/_/g, " ")}
                            </span>
                            <span className="text-axis-burgundy">
                              {v.details || v.type.replace(/_/g, " ")} — Q
                              {(v.question_index ?? 0) + 1} at{" "}
                              {new Date(v.timestamp).toLocaleTimeString()}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {warnings.length > 0 && (
                    <div>
                      <ul className="space-y-1">
                        {warnings.map((v: any, i: number) => (
                          <li
                            key={`warn-${i}`}
                            className="flex items-start gap-2 text-xs border border-amber-300 bg-amber-50 rounded p-2"
                          >
                            <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] uppercase font-bold bg-amber-600 text-white">
                              {v.type.replace(/_/g, " ")}
                            </span>
                            <span className="text-amber-800">
                              {v.details || v.type.replace(/_/g, " ")} — Q
                              {(v.question_index ?? 0) + 1} at{" "}
                              {new Date(v.timestamp).toLocaleTimeString()}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Peer feedback already submitted — full visibility.
                Earlier this card only showed name + vote + score. The
                panellist asked to see WHAT their peers actually wrote so
                they can ground their own write-up against the same
                evidence. Full strengths + concerns + timestamp now
                render here, one card per peer. */}
            {r2 && r2.panel_feedback.filter((f) => f.panellist_id !== persona.identity).length > 0 && (
              <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card p-5">
                <p className="text-xs uppercase tracking-wider text-axis-magenta font-semibold">
                  What your peers said ({r2.panel_feedback.filter((f) => f.panellist_id !== persona.identity).length})
                </p>
                <p className="text-[11px] text-axis-muted mt-1 mb-3">
                  Read the rationale from the panellists who have already
                  voted. Their full write-up is below — use it to compare
                  evidence against your own read of the transcript.
                </p>
                <ul className="space-y-3">
                  {r2.panel_feedback
                    .filter((f) => f.panellist_id !== persona.identity)
                    .map((f) => {
                      const tone =
                        f.recommendation === "strong_hire"
                          ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                          : f.recommendation === "hire"
                          ? "bg-axis-cream border-axis-cream-border text-axis-ink"
                          : "bg-axis-pink-soft border-axis-magenta text-axis-burgundy";
                      return (
                        <li
                          key={f.panellist_id}
                          className="border border-axis-divider rounded-card p-3"
                        >
                          <div className="flex items-start justify-between gap-3 mb-2">
                            <div className="min-w-0">
                              <p className="text-sm font-semibold text-axis-ink">
                                {f.panellist_name}
                              </p>
                              <p className="text-[10px] text-axis-muted mt-0.5">
                                Submitted {new Date(f.submitted_at).toLocaleString()}
                              </p>
                            </div>
                            <div className="flex flex-col items-end gap-1 shrink-0">
                              <span className={`text-[10px] px-2 py-0.5 rounded uppercase tracking-wider font-bold border ${tone}`}>
                                {f.recommendation.replace("_", " ")}
                              </span>
                              <span className="text-xs text-axis-ink-soft font-mono">
                                {Math.round(f.score)}/100
                              </span>
                            </div>
                          </div>
                          {f.strengths?.trim() && (
                            <div className="mt-2">
                              <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                                Strengths
                              </p>
                              <p className="text-xs text-axis-ink-soft mt-0.5 whitespace-pre-wrap">
                                {f.strengths}
                              </p>
                            </div>
                          )}
                          {f.concerns?.trim() && (
                            <div className="mt-2">
                              <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                                Concerns
                              </p>
                              <p className="text-xs text-axis-ink-soft mt-0.5 whitespace-pre-wrap">
                                {f.concerns}
                              </p>
                            </div>
                          )}
                        </li>
                      );
                    })}
                </ul>
              </div>
            )}

            {isReadOnly && (
              <div className="mt-4 bg-axis-cream border border-axis-cream-border rounded-card p-4">
                <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold">
                  Read-only · vote submitted
                </p>
                <p className="text-sm text-axis-ink mt-1">
                  You submitted your verdict on{" "}
                  <strong>
                    {myVote
                      ? new Date(myVote.submitted_at).toLocaleString()
                      : "—"}
                  </strong>
                  . Audit-trail rule: panel votes cannot be edited from the
                  UI. Below is what you wrote, frozen.
                </p>
              </div>
            )}

            {/* R2 Teams transcript — read-only. Auto-populated from the
                meeting recording; panellist only reads it. */}
            <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card p-6">
              <p className="text-xs uppercase tracking-wider text-axis-magenta font-semibold">
                R2 Teams transcript
              </p>
              <h2 className="text-base font-display text-axis-ink mt-1">
                Read the meeting transcript
              </h2>
              <p className="text-xs text-axis-muted mt-1">
                This is the verbatim Round 2 interview transcript captured
                from the Teams meeting. Use it to ground your feedback below.
              </p>
              {r2Transcript.trim().length > 0 ? (
                <pre className="mt-3 w-full border border-axis-divider rounded px-3 py-2 text-xs font-mono text-axis-ink whitespace-pre-wrap max-h-96 overflow-y-auto bg-axis-surface/40">
                  {r2Transcript}
                </pre>
              ) : (
                <p className="mt-3 text-xs text-axis-muted italic">
                  The transcript for this meeting is not available yet.
                  Please check back after the meeting has concluded.
                </p>
              )}
            </div>

            {/* Feedback form — manual only, no AI prefill */}
            <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card p-6">
              <p className="text-xs uppercase tracking-wider text-axis-magenta font-semibold">
                Your feedback
              </p>
              <h2 className="text-base font-display text-axis-ink mt-1">
                Record your assessment
              </h2>
              <p className="text-xs text-axis-muted mt-1 mb-4">
                Drag the slider, write out strengths and concerns, and pick a
                recommendation. Your vote goes straight into the audit trail.
              </p>

              <div>
                <label className="text-xs uppercase text-axis-muted font-semibold">
                  Overall score: {score == null ? "—" : `${score}/100`}
                </label>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={score ?? 0}
                  onChange={(e) => setScore(Number(e.target.value))}
                  disabled={isReadOnly}
                  className="w-full mt-1 disabled:opacity-60"
                />
                <div className="flex justify-between text-[10px] text-axis-muted mt-0.5">
                  <span>0 · no_hire</span>
                  <span>70 · advance bar</span>
                  <span>100 · strong_hire</span>
                </div>
                {score == null && (
                  <p className="mt-1 text-[10px] text-axis-muted">
                    Drag the slider to set an overall score.
                  </p>
                )}
              </div>
              <div className="mt-4">
                <label className="text-xs uppercase text-axis-muted font-semibold">
                  Strengths
                </label>
                <textarea
                  value={strengths}
                  onChange={(e) => setStrengths(e.target.value)}
                  rows={3}
                  disabled={isReadOnly}
                  className="w-full border border-axis-divider rounded px-3 py-2 text-sm mt-1 disabled:bg-axis-surface disabled:text-axis-ink-soft"
                  placeholder="What went well..."
                />
              </div>
              <div className="mt-4">
                <label className="text-xs uppercase text-axis-muted font-semibold">
                  Concerns
                </label>
                <textarea
                  value={concerns}
                  onChange={(e) => setConcerns(e.target.value)}
                  rows={3}
                  disabled={isReadOnly}
                  className="w-full border border-axis-divider rounded px-3 py-2 text-sm mt-1 disabled:bg-axis-surface disabled:text-axis-ink-soft"
                  placeholder="Any red flags..."
                />
              </div>
              <div className="mt-4">
                <label className="text-xs uppercase text-axis-muted font-semibold">
                  Recommendation
                </label>
                <div className="mt-1 flex gap-2">
                  {(["strong_hire", "hire", "no_hire"] as Rec[]).map((r) => (
                    <button
                      key={r}
                      onClick={() => setRecommendation(r)}
                      disabled={isReadOnly}
                      className={`px-3 py-1.5 text-xs rounded disabled:opacity-60 disabled:cursor-not-allowed ${
                        recommendation === r
                          ? "bg-axis-magenta text-white"
                          : "border border-axis-divider text-axis-ink-soft"
                      }`}
                    >
                      {r.replace("_", " ")}
                    </button>
                  ))}
                </div>
              </div>
              <div className="mt-6">
                {validationError && (
                  <div className="mb-3 p-2 rounded bg-axis-pink-soft border border-axis-magenta text-xs text-axis-burgundy">
                    {validationError}
                  </div>
                )}
                {isReadOnly ? (
                  <p className="text-[11px] text-axis-muted italic">
                    This vote is locked. Use the panel queue to find your other
                    pending interviews.
                  </p>
                ) : (
                <>
                <button
                  onClick={() => {
                    setValidationError(null);
                    if (!persona.identity || persona.role !== "panel") {
                      setValidationError(
                        "Switch to the Interview Panel persona before submitting.",
                      );
                      return;
                    }
                    if (score == null) {
                      setValidationError(
                        "Set an overall score before submitting (drag the slider).",
                      );
                      return;
                    }
                    if (recommendation == null) {
                      setValidationError(
                        "Pick a recommendation (strong hire / hire / no hire) before submitting.",
                      );
                      return;
                    }
                    if (strengths.trim().length < 10) {
                      setValidationError(
                        "Please write at least one full sentence of strengths before submitting.",
                      );
                      return;
                    }
                    if (concerns.trim().length < 10) {
                      setValidationError(
                        "Please write at least one full sentence of concerns (write 'None' if there are none).",
                      );
                      return;
                    }
                    setPendingSubmit(true);
                  }}
                  disabled={submitting}
                  className="px-4 py-2 rounded bg-axis-magenta text-white text-sm font-semibold hover:bg-axis-burgundy disabled:opacity-40"
                >
                  {submitting ? "Submitting…" : "Review and submit feedback"}
                </button>
                <p className="mt-2 text-[11px] text-axis-muted">
                  You'll get a chance to review your vote before it's
                  recorded. Once every panellist has voted, the application
                  returns to the Business Partner for the final decision.
                </p>
                </>
                )}
              </div>
            </div>

            {/* Live activity context */}
            <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card p-4">
              <p className="text-xs uppercase text-axis-muted font-semibold mb-2">
                Live agent activity
              </p>
              <AgentActivityFeed
                items={activity ?? []}
                maxHeight="max-h-64"
                emptyLabel="No activity yet."
              />
            </div>
          </>
        )}
      </main>
      <Footer />

      <ConfirmDialog
        open={pendingSubmit}
        title="Submit your Round 2 panel vote?"
        message={
          <>
            You're about to record your verdict as{" "}
            <strong className="text-axis-ink">
              {(recommendation ?? "—").replace("_", " ")}
            </strong>{" "}
            with an overall score of{" "}
            <strong className="text-axis-ink">{score ?? "—"}/100</strong>. Once
            submitted, this vote becomes part of the audit trail and cannot
            be edited from the UI.
          </>
        }
        consequences={[
          "Your vote, score, strengths and concerns are visible to the Business Partner and to the other panellists.",
          "If you are the last panellist to vote, the application is routed back to the Business Partner for the final offer / reject decision.",
          "Submitted votes cannot be edited from the UI.",
        ]}
        confirmLabel="Submit my vote"
        tone={recommendation === "no_hire" ? "danger" : "primary"}
        onConfirm={async () => {
          await submit();
          setPendingSubmit(false);
        }}
        onCancel={() => setPendingSubmit(false)}
      />
    </div>
  );
}
