"use client";

/**
 * Contact Review Page — intermediate step between upload and scoring.
 *
 * After HR uploads resumes, the system parses them and extracts contact
 * details. This page shows the extracted data in an editable table so HR
 * can fill in missing emails/phones before kicking off AI scoring.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { api, type BulkPoolStatus, type BulkRow } from "@/lib/api";

export default function ContactReviewPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <ReviewContent />
    </RoleGate>
  );
}

type EditableContact = {
  row_id: string;
  file_name: string;
  candidate_name: string;
  candidate_email: string;
  candidate_phone: string;
  status: string;
  error_message?: string | null;
};

function ReviewContent() {
  const params = useParams<{ poolId: string }>();
  const router = useRouter();
  const poolId = params?.poolId;

  const [status, setStatus] = useState<BulkPoolStatus | null>(null);
  const [contacts, setContacts] = useState<EditableContact[]>([]);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Track original auto-extracted values to distinguish from manual edits
  const originalValuesRef = useRef<
    Map<string, { name: string; email: string; phone: string }>
  >(new Map());

  // Build editable contacts from status rows
  const syncContacts = useCallback((rows: BulkRow[]) => {
    setContacts((prev) => {
      // Preserve edits for rows that already exist
      const prevMap = new Map(prev.map((c) => [c.row_id, c]));
      return rows.map((r) => {
        const existing = prevMap.get(r.row_id);
        // Only overwrite if the row just finished parsing (wasn't in prev, or was still queued/parsing)
        if (existing && existing.status !== "queued" && existing.status !== "parsing") {
          return { ...existing, status: r.status };
        }
        // Snapshot original auto-extracted values when a row first arrives as parsed
        if (!originalValuesRef.current.has(r.row_id) && r.status === "parsed") {
          originalValuesRef.current.set(r.row_id, {
            name: r.candidate_name || "",
            email: r.candidate_email || "",
            phone: r.candidate_phone || "",
          });
        }
        return {
          row_id: r.row_id,
          file_name: r.file_name,
          candidate_name: r.candidate_name || "",
          candidate_email: r.candidate_email || "",
          candidate_phone: r.candidate_phone || "",
          status: r.status,
          error_message: r.error_message,
        };
      });
    });
  }, []);

  // Poll for status while pool is still processing (parsing phase)
  const fetchStatus = useCallback(async () => {
    if (!poolId) return;
    try {
      const s = await api.bulkIntakeStatus(poolId);
      setStatus(s);
      syncContacts(s.rows);

      // Stop polling once parsing is complete (pending_review) or pool moved past review
      if (s.status !== "processing") {
        if (pollRef.current) clearInterval(pollRef.current);
      }

      // If pool has moved beyond review, redirect to leaderboard
      if (s.status === "done" || s.status === "failed") {
        router.replace(`/hr/bulk-screening/${poolId}`);
      }
    } catch {}
  }, [poolId, syncContacts, router]);

  useEffect(() => {
    fetchStatus();
    pollRef.current = setInterval(fetchStatus, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchStatus]);

  // Update a single contact field
  const updateField = (rowId: string, field: keyof EditableContact, value: string) => {
    setContacts((prev) =>
      prev.map((c) => (c.row_id === rowId ? { ...c, [field]: value } : c)),
    );
  };

  // Save draft
  const handleSave = async () => {
    if (!poolId) return;
    setSaving(true);
    try {
      await api.updatePoolContacts(
        poolId,
        contacts.map((c) => ({
          row_id: c.row_id,
          candidate_name: c.candidate_name,
          candidate_email: c.candidate_email,
          candidate_phone: c.candidate_phone,
        })),
      );
      setToast("Draft saved successfully.");
      setTimeout(() => setToast(null), 3000);
    } catch (err: any) {
      setToast("Failed to save: " + (err?.message || "Unknown error"));
      setTimeout(() => setToast(null), 5000);
    }
    setSaving(false);
  };

  // Confirm & start scoring
  const handleConfirm = async () => {
    if (!poolId) return;
    setConfirming(true);
    try {
      // Save contacts first
      await api.updatePoolContacts(
        poolId,
        contacts.map((c) => ({
          row_id: c.row_id,
          candidate_name: c.candidate_name,
          candidate_email: c.candidate_email,
          candidate_phone: c.candidate_phone,
        })),
      );
      // Then start scoring
      await api.startPoolScoring(poolId);
      router.push(`/hr/bulk-screening/${poolId}`);
    } catch (err: any) {
      setToast("Failed to start scoring: " + (err?.message || "Unknown error"));
      setTimeout(() => setToast(null), 5000);
      setConfirming(false);
    }
  };

  // Check if a field value is still the original auto-extracted value
  const isAutoExtracted = (rowId: string, field: "name" | "email" | "phone", currentValue: string): boolean => {
    const orig = originalValuesRef.current.get(rowId);
    if (!orig) return false;
    const originalValue = orig[field];
    // Only "auto-extracted" if original was non-empty AND current still matches it
    return originalValue !== "" && currentValue === originalValue;
  };

  // Check if a field value was manually entered by the user
  const isUserEntered = (rowId: string, field: "name" | "email" | "phone", currentValue: string): boolean => {
    if (!currentValue) return false;
    const orig = originalValuesRef.current.get(rowId);
    if (!orig) return false;
    const originalValue = orig[field];
    // "User entered" if original was empty OR current differs from original
    return originalValue === "" || currentValue !== originalValue;
  };

  const isStillParsing = status?.status === "processing";
  const isPendingReview = status?.status === "pending_review";
  const parsedCount = contacts.filter((c) => c.status === "parsed").length;
  const errorCount = contacts.filter((c) => c.status === "error").length;
  const parsingCount = contacts.filter(
    (c) => c.status === "queued" || c.status === "parsing",
  ).length;

  if (!status) {
    return (
      <>
        <TopBar />
        <HRSubNav />
        <main className="min-h-screen bg-axis-surface flex items-center justify-center">
          <div className="flex items-center gap-3">
            <span className="inline-block w-5 h-5 rounded-full border-2 border-axis-magenta border-t-transparent animate-spin" />
            <p className="text-sm text-axis-muted">Loading review data...</p>
          </div>
        </main>
      </>
    );
  }

  // If pool is already past review (processing scoring / done), redirect
  if (status.status !== "processing" && status.status !== "pending_review") {
    router.replace(`/hr/bulk-screening/${poolId}`);
    return null;
  }

  return (
    <>
      <TopBar />
      <HRSubNav />
      <main className="min-h-screen bg-axis-surface py-10 px-6">
        <div className="max-w-7xl mx-auto">
          {/* Back link */}
          <Link
            href="/hr/bulk-screening"
            className="text-xs text-axis-magenta hover:underline"
          >
            &larr; Back to all batches
          </Link>

          {/* Header */}
          <div className="mt-4">
            <div className="h-1 w-16 bg-axis-burgundy rounded mb-4" />
            <h1 className="text-2xl font-display text-axis-ink mb-1">
              Review Candidate Details
            </h1>
            <p className="text-sm text-axis-muted mb-1">
              {status.job_title}
            </p>
            <p className="text-xs text-axis-muted mb-6">
              Verify contact information extracted from resumes. Missing details
              can be entered manually.
            </p>
          </div>

          {/* Parsing progress bar (only when still parsing) */}
          {isStillParsing && (
            <div className="mb-6 bg-axis-canvas border border-axis-divider rounded-card shadow-card p-4">
              <div className="flex items-center gap-3 mb-2">
                <span className="inline-block w-4 h-4 rounded-full border-2 border-axis-magenta border-t-transparent animate-spin" />
                <p className="text-sm font-semibold text-axis-ink">
                  Extracting resume data... {parsedCount + errorCount} of{" "}
                  {contacts.length} complete
                </p>
              </div>
              <div className="w-full h-2 bg-axis-surface rounded-full overflow-hidden">
                <div
                  className="h-full bg-axis-magenta rounded-full transition-all duration-500"
                  style={{
                    width: `${
                      contacts.length > 0
                        ? ((parsedCount + errorCount) / contacts.length) * 100
                        : 0
                    }%`,
                  }}
                />
              </div>
            </div>
          )}

          {/* Toast */}
          {toast && (
            <div className="mb-4 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-card p-3 text-sm">
              {toast}
            </div>
          )}

          {/* Table */}
          <div className="bg-axis-canvas border border-axis-divider rounded-card shadow-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm table-fixed">
                <colgroup>
                  <col className="w-10" />
                  <col className="w-[14%]" />
                  <col className="w-[18%]" />
                  <col className="w-[30%]" />
                  <col className="w-[18%]" />
                  <col className="w-24" />
                </colgroup>
                <thead>
                  <tr className="bg-axis-surface border-b border-axis-divider text-axis-muted text-xs uppercase tracking-wide">
                    <th className="px-4 py-3 text-left">#</th>
                    <th className="px-4 py-3 text-left">File Name</th>
                    <th className="px-4 py-3 text-left">Candidate Name</th>
                    <th className="px-4 py-3 text-left">Email</th>
                    <th className="px-4 py-3 text-left">Phone</th>
                    <th className="px-4 py-3 text-center">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {contacts.map((c, idx) => {
                    const isParsed = c.status === "parsed";
                    const isError = c.status === "error";
                    const isRowParsing =
                      c.status === "queued" || c.status === "parsing";

                    return (
                      <tr
                        key={c.row_id}
                        className={`border-b border-axis-divider last:border-0 ${
                          isError ? "bg-red-50/50" : ""
                        }`}
                      >
                        <td className="px-4 py-3 text-axis-muted">{idx + 1}</td>
                        <td className="px-4 py-3">
                          <span className="text-axis-ink text-xs font-mono truncate block max-w-[180px]" title={c.file_name}>
                            {c.file_name}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {isRowParsing ? (
                            <div className="h-8 w-32 bg-axis-surface animate-pulse rounded" />
                          ) : isError ? (
                            <span className="text-xs text-red-500">
                              {c.error_message || "Parse error"}
                            </span>
                          ) : (
                            <div className="flex items-center gap-1.5">
                              <input
                                type="text"
                                value={c.candidate_name}
                                onChange={(e) =>
                                  updateField(c.row_id, "candidate_name", e.target.value)
                                }
                                className="w-full text-xs bg-axis-surface border border-axis-divider rounded px-2 py-1.5 focus:border-axis-magenta focus:outline-none"
                                placeholder="Name"
                                disabled={!isPendingReview}
                              />
                              {isParsed && c.candidate_name && isAutoExtracted(c.row_id, "name", c.candidate_name) && (
                                <span className="shrink-0 text-[9px] px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded-full">
                                  Auto-extracted
                                </span>
                              )}
                              {isParsed && c.candidate_name && isUserEntered(c.row_id, "name", c.candidate_name) && (
                                <span className="shrink-0 text-[9px] px-1.5 py-0.5 bg-sky-100 text-sky-700 rounded-full">
                                  User entered
                                </span>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {isRowParsing ? (
                            <div className="h-8 w-40 bg-axis-surface animate-pulse rounded" />
                          ) : isError ? null : (
                            <div className="flex items-center gap-1.5">
                              <input
                                type="email"
                                value={c.candidate_email}
                                onChange={(e) =>
                                  updateField(c.row_id, "candidate_email", e.target.value)
                                }
                                className="w-full text-xs bg-axis-surface border border-axis-divider rounded px-2 py-1.5 focus:border-axis-magenta focus:outline-none"
                                placeholder="email@example.com"
                                disabled={!isPendingReview}
                              />
                              {isParsed && c.candidate_email && isAutoExtracted(c.row_id, "email", c.candidate_email) ? (
                                <span className="shrink-0 text-[9px] px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded-full">
                                  Auto-extracted
                                </span>
                              ) : isParsed && c.candidate_email && isUserEntered(c.row_id, "email", c.candidate_email) ? (
                                <span className="shrink-0 text-[9px] px-1.5 py-0.5 bg-sky-100 text-sky-700 rounded-full">
                                  User entered
                                </span>
                              ) : isParsed && !c.candidate_email ? (
                                <span className="shrink-0 text-[9px] px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded-full">
                                  Required
                                </span>
                              ) : null}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {isRowParsing ? (
                            <div className="h-8 w-28 bg-axis-surface animate-pulse rounded" />
                          ) : isError ? null : (
                            <div className="flex items-center gap-1.5">
                              <input
                                type="tel"
                                value={c.candidate_phone}
                                onChange={(e) =>
                                  updateField(c.row_id, "candidate_phone", e.target.value)
                                }
                                className="w-full text-xs bg-axis-surface border border-axis-divider rounded px-2 py-1.5 focus:border-axis-magenta focus:outline-none"
                                placeholder="+91 ..."
                                disabled={!isPendingReview}
                              />
                              {isParsed && c.candidate_phone && isAutoExtracted(c.row_id, "phone", c.candidate_phone) && (
                                <span className="shrink-0 text-[9px] px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded-full">
                                  Auto-extracted
                                </span>
                              )}
                              {isParsed && c.candidate_phone && isUserEntered(c.row_id, "phone", c.candidate_phone) && (
                                <span className="shrink-0 text-[9px] px-1.5 py-0.5 bg-sky-100 text-sky-700 rounded-full">
                                  User entered
                                </span>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-center">
                          {isRowParsing ? (
                            <span className="inline-flex items-center gap-1 text-[10px] text-axis-muted">
                              <span className="inline-block w-3 h-3 rounded-full border-2 border-axis-magenta border-t-transparent animate-spin" />
                              Parsing
                            </span>
                          ) : isError ? (
                            <span className="text-[10px] px-2 py-0.5 bg-red-100 text-red-700 rounded-full">
                              Error
                            </span>
                          ) : c.candidate_email ? (
                            <span className="text-[10px] px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded-full">
                              Ready
                            </span>
                          ) : (
                            <span className="text-[10px] px-2 py-0.5 bg-amber-100 text-amber-700 rounded-full">
                              Missing info
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Action buttons */}
          {isPendingReview && (
            <div className="mt-6 flex items-center justify-between">
              <p className="text-xs text-axis-muted">
                {parsedCount} parsed &middot; {errorCount > 0 ? `${errorCount} errors` : "no errors"}
              </p>
              <div className="flex items-center gap-3">
                <button
                  onClick={handleSave}
                  disabled={saving || confirming}
                  className="px-4 py-2 text-sm font-semibold border border-axis-divider text-axis-ink bg-axis-canvas rounded hover:bg-axis-surface transition-colors disabled:opacity-50"
                >
                  {saving ? "Saving..." : "Save Draft"}
                </button>
                <button
                  onClick={handleConfirm}
                  disabled={saving || confirming}
                  className="px-5 py-2 text-sm font-semibold bg-axis-magenta text-white rounded hover:bg-axis-burgundy transition-colors disabled:opacity-50"
                >
                  {confirming ? (
                    <span className="flex items-center gap-2">
                      <span className="inline-block w-4 h-4 rounded-full border-2 border-white border-t-transparent animate-spin" />
                      Starting screening...
                    </span>
                  ) : (
                    "Confirm & Start Screening \u2192"
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
      <Footer />
    </>
  );
}
