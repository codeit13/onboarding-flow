"use client";

/**
 * Offer Discussion Team — queue + per-application negotiation card.
 *
 * This is the post-R2, pre-OFFER human-gated stage owned by the new
 * Offer Discussion Team persona. When HR clicks "Make offer" on a panel
 * review card, the orchestrator moves the application into
 * FunnelStage.OFFER_NEGOTIATION and pauses WAITING_OFFER_TEAM. This page
 * is where the Offer Discussion Team picks the application up, reads the
 * uploaded salary slip + AI compensation analysis, sets a final CTC, and
 * clicks "Roll out final offer" — which fires
 * comms.final_offer_email and flips the stage to OFFER (terminal-success).
 *
 * The candidate page on /thrive/status/[appId] surfaces a matching
 * "Offer Discussion in progress" narrative so the candidate sees the
 * same stage in human-friendly language.
 */

import { useCallback, useMemo, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import { api, type OfferTeamQueueRow } from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";

function formatINR(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

export default function OfferTeamPage() {
  return (
    <RoleGate allow={["offer_team"]}>
      <OfferTeamContent />
    </RoleGate>
  );
}

function OfferTeamContent() {
  const loadQueue = useCallback(() => api.offerTeamQueue(), []);
  const { data: rows, refresh, error } = useAutoRefresh<OfferTeamQueueRow[]>(
    loadQueue,
    5000,
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [proposedCtc, setProposedCtc] = useState<string>("");
  const [notes, setNotes] = useState<string>("");
  const [toast, setToast] = useState<string | null>(null);

  const selected = useMemo(
    () => rows?.find((r) => r.application_id === selectedId) || null,
    [rows, selectedId],
  );

  const handleRollout = useCallback(async () => {
    if (!selected) return;
    const final = parseFloat(proposedCtc);
    if (!final || Number.isNaN(final) || final <= 0) {
      setToast("Please enter a valid annual CTC in INR (e.g. 1850000).");
      return;
    }
    setBusy(true);
    setToast(null);
    try {
      await api.offerTeamRollout(selected.application_id, {
        final_ctc_lpa: final,
        notes,
        rolled_out_by: "offer-team-lead",
      });
      setToast(
        `Final offer at ${formatINR(final)} rolled out — formal offer letter sent to ${selected.candidate_email}.`,
      );
      setProposedCtc("");
      setNotes("");
      setSelectedId(null);
      await refresh();
    } catch (e: any) {
      setToast(e?.message || "Failed to roll out the offer.");
    } finally {
      setBusy(false);
    }
  }, [selected, proposedCtc, notes, refresh]);

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <main className="flex-1 px-6 py-8 max-w-6xl w-full mx-auto">
        <div className="mb-6">
          <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold">
            Offer Discussion Team
          </p>
          <h1 className="text-3xl font-display text-axis-ink mt-1">
            Negotiate &amp; roll out final offers
          </h1>
          <p className="text-sm text-axis-muted mt-2 max-w-3xl">
            Every application below has cleared R2 and been approved by the Business Partner.
            Read the AI compensation analysis, agree the final CTC with the
            candidate, and click <strong>Roll out final offer</strong> to
            send the formal offer letter. The application then moves to
            the OFFER stage and is closed for this requisition.
          </p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border-l-4 border-red-500 text-red-800 rounded-r-lg text-sm">
            {String(error)}
          </div>
        )}

        {toast && (
          <div className="mb-4 p-3 bg-emerald-50 border-l-4 border-emerald-500 text-emerald-800 rounded-r-lg text-sm">
            {toast}
          </div>
        )}

        <div className="grid lg:grid-cols-3 gap-6">
          {/* Queue */}
          <div className="lg:col-span-1 bg-white rounded-card border border-axis-divider shadow-card overflow-hidden">
            <div className="px-4 py-3 bg-axis-pink-soft border-b border-axis-divider">
              <h3 className="text-xs font-bold uppercase tracking-wider text-axis-burgundy">
                Queue ({rows?.length ?? 0})
              </h3>
            </div>
            <div className="divide-y divide-axis-divider max-h-[640px] overflow-y-auto">
              {(!rows || rows.length === 0) && (
                <p className="p-4 text-xs text-axis-muted italic">
                  No applications waiting on the Offer Discussion Team. When the
                  Business Partner approves an offer after R2, it will land here.
                </p>
              )}
              {rows?.map((r) => (
                <button
                  key={r.application_id}
                  onClick={() => {
                    setSelectedId(r.application_id);
                    setProposedCtc(
                      r.proposed_ctc_lpa
                        ? String(r.proposed_ctc_lpa)
                        : r.current_ctc_lpa
                        ? String(Math.round(r.current_ctc_lpa * 1.18))
                        : "",
                    );
                    setNotes(r.negotiation_notes || "");
                  }}
                  className={
                    "w-full text-left px-4 py-3 hover:bg-axis-pink-soft/40 transition " +
                    (selectedId === r.application_id
                      ? "bg-axis-pink-soft/60"
                      : "")
                  }
                >
                  <div className="text-sm font-bold text-axis-ink">
                    {r.candidate_name}
                  </div>
                  <div className="text-[11px] text-axis-muted mt-0.5">
                    {r.job_title} · {r.job_location}
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[10px]">
                    <span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded font-bold">
                      R1 {r.r1_score?.toFixed(0) ?? "—"}
                    </span>
                    <span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded font-bold">
                      R2 {r.r2_score?.toFixed(0) ?? "—"}
                    </span>
                    {r.rolled_out && (
                      <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded font-bold">
                        rolled out
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Detail */}
          <div className="lg:col-span-2">
            {!selected ? (
              <div className="bg-white rounded-card border border-axis-divider shadow-card p-10 text-center">
                <p className="text-axis-muted text-sm">
                  Select a candidate from the queue to view the AI compensation
                  analysis and roll out the final offer.
                </p>
              </div>
            ) : (
              <div className="bg-white rounded-card border border-axis-divider shadow-card overflow-hidden">
                <div
                  className="p-6 text-white"
                  style={{
                    background:
                      "linear-gradient(135deg, #6b2566 0%, #4a1e47 100%)",
                  }}
                >
                  <p className="text-[10px] uppercase tracking-widest text-white/70 font-bold">
                    Offer Discussion · {selected.application_id}
                  </p>
                  <h2 className="text-2xl font-bold mt-1">
                    {selected.candidate_name}
                  </h2>
                  <p className="text-sm text-white/80 mt-1">
                    {selected.job_title} · {selected.job_location}
                  </p>
                  <p className="text-xs text-white/60 mt-2">
                    Currently at: {selected.candidate_current_role}
                  </p>
                </div>

                <div className="p-6 space-y-6">
                  <div className="grid grid-cols-3 gap-4">
                    <div className="bg-axis-canvas rounded-lg p-4 border border-axis-divider">
                      <div className="text-[10px] uppercase tracking-wider text-axis-muted font-bold">
                        R1 AI score
                      </div>
                      <div className="text-2xl font-bold text-axis-ink mt-1">
                        {selected.r1_score?.toFixed(0) ?? "—"}
                      </div>
                    </div>
                    <div className="bg-axis-canvas rounded-lg p-4 border border-axis-divider">
                      <div className="text-[10px] uppercase tracking-wider text-axis-muted font-bold">
                        R2 panel score
                      </div>
                      <div className="text-2xl font-bold text-axis-ink mt-1">
                        {selected.r2_score?.toFixed(0) ?? "—"}
                      </div>
                    </div>
                    <div className="bg-axis-canvas rounded-lg p-4 border border-axis-divider">
                      <div className="text-[10px] uppercase tracking-wider text-axis-muted font-bold">
                        Current CTC (extracted)
                      </div>
                      <div className="text-lg font-bold text-axis-ink mt-1">
                        {formatINR(selected.current_ctc_lpa)}
                      </div>
                    </div>
                  </div>

                  {/* AI Analysis summary — Round 1 (AI Interview Agent)
                      and Round 2 (panel votes). The Offer Discussion Team
                      asked for this so they walk into the negotiation
                      knowing exactly how strong the candidate's signal
                      was without having to bounce into the BP's
                      application detail page. */}
                  {selected.r1_summary && (
                    <div className="border border-axis-divider rounded-lg p-4 bg-axis-canvas">
                      <div className="flex items-start justify-between gap-3 mb-2">
                        <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold">
                          AI Analysis · Round 1 (AI Interview Agent)
                        </p>
                        <span
                          className={
                            "text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded border " +
                            (selected.r1_summary.recommendation === "advance"
                              ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                              : selected.r1_summary.recommendation === "borderline"
                              ? "bg-amber-50 border-amber-200 text-amber-700"
                              : "bg-axis-pink-soft border-axis-magenta text-axis-burgundy")
                          }
                        >
                          {selected.r1_summary.recommendation} ·{" "}
                          {Math.round(selected.r1_summary.overall_score)}/100
                        </span>
                      </div>
                      <p className="text-sm text-axis-ink font-semibold">
                        {selected.r1_summary.headline}
                      </p>
                      {selected.r1_summary.top_highlights.length > 0 && (
                        <div className="mt-3 space-y-2">
                          {selected.r1_summary.top_highlights.map((h, i) => (
                            <div key={i} className="border-l-2 border-axis-magenta/40 pl-3">
                              <p className="text-xs italic text-axis-ink-soft">
                                "{h.quote}"
                              </p>
                              <p className="text-[11px] text-axis-muted mt-1">
                                {h.why}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                      {selected.r1_summary.red_flags.length > 0 && (
                        <div className="mt-3">
                          <p className="text-[10px] uppercase tracking-wider text-axis-burgundy font-bold">
                            Red flags
                          </p>
                          <ul className="mt-1 space-y-0.5 text-xs text-axis-ink-soft list-disc list-inside">
                            {selected.r1_summary.red_flags.map((rf, i) => (
                              <li key={i}>{rf}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}

                  {selected.r2_summary && selected.r2_summary.votes.length > 0 && (
                    <div className="border border-axis-divider rounded-lg p-4 bg-axis-canvas">
                      <div className="flex items-start justify-between gap-3 mb-2">
                        <p className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold">
                          AI Analysis · Round 2 (Hiring Panel)
                        </p>
                        <span className="text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded border bg-axis-cream border-axis-cream-border text-axis-ink">
                          {selected.r2_summary.tally.strong_hire} strong hire ·{" "}
                          {selected.r2_summary.tally.hire} hire ·{" "}
                          {selected.r2_summary.tally.no_hire} no hire
                        </span>
                      </div>
                      <p className="text-xs text-axis-muted mb-3">
                        Average panel score:{" "}
                        <strong className="text-axis-ink">
                          {selected.r2_summary.average_score != null
                            ? `${Math.round(selected.r2_summary.average_score)}/100`
                            : "—"}
                        </strong>
                      </p>
                      <ul className="space-y-3">
                        {selected.r2_summary.votes.map((v, i) => {
                          const tone =
                            v.recommendation === "strong_hire"
                              ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                              : v.recommendation === "hire"
                              ? "bg-axis-cream border-axis-cream-border text-axis-ink"
                              : "bg-axis-pink-soft border-axis-magenta text-axis-burgundy";
                          return (
                            <li
                              key={i}
                              className="border border-axis-divider rounded-lg p-3"
                            >
                              <div className="flex items-start justify-between gap-3">
                                <p className="text-sm font-semibold text-axis-ink">
                                  {v.panellist_name}
                                </p>
                                <div className="flex items-center gap-2 shrink-0">
                                  <span
                                    className={`text-[10px] px-2 py-0.5 rounded uppercase tracking-wider font-bold border ${tone}`}
                                  >
                                    {v.recommendation.replace("_", " ")}
                                  </span>
                                  <span className="text-[11px] text-axis-ink-soft font-mono">
                                    {Math.round(v.score)}/100
                                  </span>
                                </div>
                              </div>
                              {v.strengths && (
                                <div className="mt-2">
                                  <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                                    Strengths
                                  </p>
                                  <p className="text-xs text-axis-ink-soft mt-0.5 whitespace-pre-wrap">
                                    {v.strengths}
                                  </p>
                                </div>
                              )}
                              {v.concerns && (
                                <div className="mt-2">
                                  <p className="text-[10px] uppercase tracking-wider text-axis-muted font-semibold">
                                    Concerns
                                  </p>
                                  <p className="text-xs text-axis-ink-soft mt-0.5 whitespace-pre-wrap">
                                    {v.concerns}
                                  </p>
                                </div>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  )}

                  <div className="bg-axis-pink-soft/40 border border-axis-magenta/20 rounded-lg p-4">
                    <p className="text-[10px] uppercase tracking-widest text-axis-burgundy font-bold mb-1">
                      AI compensation analysis
                    </p>
                    <p className="text-sm text-axis-ink">
                      {selected.current_ctc_lpa ? (
                        <>
                          The candidate's current CTC is{" "}
                          <strong>{formatINR(selected.current_ctc_lpa)}</strong>{" "}
                          (parsed from the salary slip uploaded at intake). A
                          standard 18–22% hike on a lateral move at this band
                          would put the offer in the{" "}
                          <strong>
                            {formatINR(selected.current_ctc_lpa * 1.18)} –{" "}
                            {formatINR(selected.current_ctc_lpa * 1.22)}
                          </strong>{" "}
                          range. Use this only as a starting point — adjust
                          based on the panel's strength signal and any
                          counter-offers in play.
                        </>
                      ) : (
                        <>
                          No salary slip was uploaded at intake — confirm the
                          candidate's current CTC directly with them before
                          finalising the offer. Cross-reference with Axis
                          internal grade bands for {selected.job_title}.
                        </>
                      )}
                    </p>
                  </div>

                  <div>
                    <label className="block text-[10px] uppercase tracking-widest text-axis-muted font-bold mb-2">
                      Final agreed CTC (₹ per annum)
                    </label>
                    <input
                      type="number"
                      value={proposedCtc}
                      onChange={(e) => setProposedCtc(e.target.value)}
                      placeholder="e.g. 1850000"
                      disabled={busy || selected.rolled_out}
                      className="w-full px-3 py-2 border border-axis-divider rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-axis-magenta/40"
                    />
                    {proposedCtc && !Number.isNaN(parseFloat(proposedCtc)) && (
                      <p className="text-xs text-axis-muted mt-1">
                        = {formatINR(parseFloat(proposedCtc))} per annum
                        {selected.current_ctc_lpa
                          ? ` · ${(
                              ((parseFloat(proposedCtc) -
                                selected.current_ctc_lpa) /
                                selected.current_ctc_lpa) *
                              100
                            ).toFixed(1)}% hike`
                          : ""}
                      </p>
                    )}
                  </div>

                  <div>
                    <label className="block text-[10px] uppercase tracking-widest text-axis-muted font-bold mb-2">
                      Negotiation notes (optional, included in the offer email)
                    </label>
                    <textarea
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      rows={3}
                      disabled={busy || selected.rolled_out}
                      placeholder="e.g. 22% hike + 1.5L joining bonus, variable @ 12%"
                      className="w-full px-3 py-2 border border-axis-divider rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-axis-magenta/40"
                    />
                  </div>

                  <div className="flex items-center justify-between pt-2">
                    <button
                      onClick={() => setSelectedId(null)}
                      disabled={busy}
                      className="text-xs text-axis-muted hover:text-axis-ink underline"
                    >
                      Back to queue
                    </button>
                    <button
                      onClick={handleRollout}
                      disabled={busy || selected.rolled_out}
                      className="px-6 py-3 rounded-xl text-white text-sm font-bold shadow-lg disabled:opacity-50 disabled:cursor-not-allowed transition"
                      style={{
                        background:
                          "linear-gradient(135deg, #6b2566 0%, #4a1e47 100%)",
                      }}
                    >
                      {busy
                        ? "Sending offer letter…"
                        : selected.rolled_out
                        ? "Already rolled out"
                        : "Roll out final offer"}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
}
