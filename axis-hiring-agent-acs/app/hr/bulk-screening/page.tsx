"use client";

/**
 * HR Bulk CV Screening dashboard — lists all past screening batches
 * and provides a CTA to start a new one.
 *
 * Filters: requisition (multi-select), candidate name, date range,
 *          status, mode, shortlisted-only toggle, sort.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { api, type BulkPoolSummary } from "@/lib/api";

export default function BulkScreeningPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <BulkScreeningContent />
    </RoleGate>
  );
}

type SortKey = "date_desc" | "date_asc" | "cvs_desc" | "shortlisted_desc";

function BulkScreeningContent() {
  const [pools, setPools] = useState<BulkPoolSummary[]>([]);
  const [loading, setLoading] = useState(true);

  // Filter state
  const [selectedReqs, setSelectedReqs] = useState<Set<string>>(new Set());
  const [candidateSearch, setCandidateSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [reqDropdownOpen, setReqDropdownOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [modeFilter, setModeFilter] = useState<string>("all");
  const [shortlistedOnly, setShortlistedOnly] = useState(false);
  const [sortBy, setSortBy] = useState<SortKey>("date_desc");

  useEffect(() => {
    api.candidatePools().then((p) => {
      setPools(p);
      setLoading(false);
    });
  }, []);

  // Unique requisition titles across all pools (includes closed ones)
  const allRequisitions = useMemo(() => {
    const titles = new Set<string>();
    pools.forEach((p) => titles.add(p.job_title));
    return Array.from(titles).sort();
  }, [pools]);

  // Stats for quick chips
  const stats = useMemo(() => {
    const s = { done: 0, processing: 0, pending_review: 0, failed: 0, single_jd: 0, auto_map: 0, withShortlisted: 0 };
    pools.forEach((p) => {
      if (p.status === "done") s.done++;
      else if (p.status === "processing") s.processing++;
      else if (p.status === "pending_review") { s.pending_review++; s.processing++; }
      else s.failed++;
      if (p.mode === "auto_map") s.auto_map++;
      else s.single_jd++;
      if (p.shortlisted > 0) s.withShortlisted++;
    });
    return s;
  }, [pools]);

  // Filtered + sorted pools
  const filtered = useMemo(() => {
    let result = pools;

    // Requisition filter
    if (selectedReqs.size > 0) {
      result = result.filter((p) => selectedReqs.has(p.job_title));
    }

    // Candidate name search
    const q = candidateSearch.trim().toLowerCase();
    if (q) {
      result = result.filter((p) =>
        p.candidate_names?.some((name) => name.toLowerCase().includes(q)),
      );
    }

    // Date range
    if (dateFrom) {
      const from = new Date(dateFrom);
      result = result.filter((p) => new Date(p.created_at) >= from);
    }
    if (dateTo) {
      const to = new Date(dateTo);
      to.setHours(23, 59, 59, 999);
      result = result.filter((p) => new Date(p.created_at) <= to);
    }

    // Status (pending_review is grouped with processing)
    if (statusFilter !== "all") {
      if (statusFilter === "processing") {
        result = result.filter((p) => p.status === "processing" || p.status === "pending_review");
      } else {
        result = result.filter((p) => p.status === statusFilter);
      }
    }

    // Mode
    if (modeFilter !== "all") {
      result = result.filter((p) => p.mode === modeFilter);
    }

    // Shortlisted only
    if (shortlistedOnly) {
      result = result.filter((p) => p.shortlisted > 0);
    }

    // Sort
    const sorted = [...result];
    switch (sortBy) {
      case "date_desc":
        sorted.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        break;
      case "date_asc":
        sorted.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
        break;
      case "cvs_desc":
        sorted.sort((a, b) => b.total - a.total);
        break;
      case "shortlisted_desc":
        sorted.sort((a, b) => b.shortlisted - a.shortlisted);
        break;
    }

    return sorted;
  }, [pools, selectedReqs, candidateSearch, dateFrom, dateTo, statusFilter, modeFilter, shortlistedOnly, sortBy]);

  const hasActiveFilters =
    selectedReqs.size > 0 ||
    candidateSearch.trim() !== "" ||
    dateFrom !== "" ||
    dateTo !== "" ||
    statusFilter !== "all" ||
    modeFilter !== "all" ||
    shortlistedOnly;

  const toggleReq = (title: string) => {
    setSelectedReqs((prev) => {
      const next = new Set(prev);
      if (next.has(title)) next.delete(title);
      else next.add(title);
      return next;
    });
  };

  const clearFilters = () => {
    setSelectedReqs(new Set());
    setCandidateSearch("");
    setDateFrom("");
    setDateTo("");
    setStatusFilter("all");
    setModeFilter("all");
    setShortlistedOnly(false);
    setSortBy("date_desc");
  };

  return (
    <>
      <TopBar />
      <HRSubNav />
      <main className="min-h-screen bg-axis-surface py-10 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="flex items-center justify-between mb-8">
            <div>
              <div className="h-1 w-16 bg-axis-burgundy rounded mb-4" />
              <h1 className="text-2xl font-display text-axis-ink">
                Bulk CV Screening
              </h1>
              <p className="text-axis-muted text-sm mt-1">
                Upload resumes in bulk and let AI rank candidates against any open role.
              </p>
            </div>
            <Link
              href="/hr/bulk-screening/new"
              className="px-5 py-2 text-sm font-semibold bg-axis-magenta text-white rounded hover:bg-axis-burgundy transition-colors"
            >
              New screening batch
            </Link>
          </div>

          {/* ---- Filter bar ---- */}
          {!loading && pools.length > 0 && (
            <div className="mb-6 bg-axis-canvas border border-axis-divider rounded-card p-4 space-y-3">
              {/* Row 1: primary filters */}
              <div className="flex flex-wrap items-end gap-4">
                {/* Requisition multi-select dropdown */}
                <div className="relative">
                  <label className="block text-[10px] font-semibold text-axis-muted uppercase tracking-wide mb-1">
                    Requisition
                  </label>
                  <button
                    onClick={() => setReqDropdownOpen(!reqDropdownOpen)}
                    className="flex items-center gap-2 px-3 py-1.5 text-xs border border-axis-divider rounded bg-white hover:border-axis-magenta/40 transition-colors min-w-[200px] text-left"
                  >
                    <span className="flex-1 truncate">
                      {selectedReqs.size === 0
                        ? "All requisitions"
                        : `${selectedReqs.size} selected`}
                    </span>
                    <svg
                      className={`w-3 h-3 text-axis-muted transition-transform ${reqDropdownOpen ? "rotate-180" : ""}`}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                  {reqDropdownOpen && (
                    <>
                      <div
                        className="fixed inset-0 z-10"
                        onClick={() => setReqDropdownOpen(false)}
                      />
                      <div className="absolute z-20 mt-1 w-80 max-h-60 overflow-y-auto bg-white border border-axis-divider rounded shadow-lg">
                        {allRequisitions.map((title) => (
                          <label
                            key={title}
                            className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-axis-surface cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={selectedReqs.has(title)}
                              onChange={() => toggleReq(title)}
                              className="accent-axis-magenta"
                            />
                            <span className="truncate">{title}</span>
                          </label>
                        ))}
                      </div>
                    </>
                  )}
                </div>

                {/* Candidate name search */}
                <div>
                  <label className="block text-[10px] font-semibold text-axis-muted uppercase tracking-wide mb-1">
                    Candidate Name
                  </label>
                  <input
                    type="text"
                    placeholder="Search by name..."
                    value={candidateSearch}
                    onChange={(e) => setCandidateSearch(e.target.value)}
                    className="px-3 py-1.5 text-xs border border-axis-divider rounded bg-white focus:outline-none focus:border-axis-magenta/60 w-48"
                  />
                </div>

                {/* Date from */}
                <div>
                  <label className="block text-[10px] font-semibold text-axis-muted uppercase tracking-wide mb-1">
                    From
                  </label>
                  <input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => setDateFrom(e.target.value)}
                    className="px-3 py-1.5 text-xs border border-axis-divider rounded bg-white focus:outline-none focus:border-axis-magenta/60"
                  />
                </div>

                {/* Date to */}
                <div>
                  <label className="block text-[10px] font-semibold text-axis-muted uppercase tracking-wide mb-1">
                    To
                  </label>
                  <input
                    type="date"
                    value={dateTo}
                    onChange={(e) => setDateTo(e.target.value)}
                    className="px-3 py-1.5 text-xs border border-axis-divider rounded bg-white focus:outline-none focus:border-axis-magenta/60"
                  />
                </div>
              </div>

              {/* Row 2: status, mode, shortlisted toggle, sort, clear */}
              <div className="flex flex-wrap items-center gap-3 pt-1 border-t border-axis-divider/50">
                {/* Status filter */}
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-semibold text-axis-muted uppercase tracking-wide">Status:</span>
                  {(["all", "done", "processing", "failed"] as const).map((s) => {
                    const active = statusFilter === s;
                    const count = s === "all" ? pools.length : s === "done" ? stats.done : s === "processing" ? stats.processing : stats.failed;
                    const colors = active
                      ? s === "done"
                        ? "bg-green-100 text-green-800 border-green-300"
                        : s === "processing"
                          ? "bg-amber-100 text-amber-800 border-amber-300"
                          : s === "failed"
                            ? "bg-red-100 text-red-800 border-red-300"
                            : "bg-axis-magenta/10 text-axis-magenta border-axis-magenta/30"
                      : "bg-white text-axis-muted border-axis-divider hover:border-axis-magenta/30";
                    return (
                      <button
                        key={s}
                        onClick={() => setStatusFilter(s)}
                        className={`px-2 py-0.5 text-[10px] font-medium rounded-full border transition-colors ${colors}`}
                      >
                        {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)} ({count})
                      </button>
                    );
                  })}
                </div>

                <div className="w-px h-4 bg-axis-divider" />

                {/* Mode filter */}
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-semibold text-axis-muted uppercase tracking-wide">Mode:</span>
                  {([
                    { key: "all", label: "All" },
                    { key: "single_jd", label: "Single JD" },
                    { key: "auto_map", label: "Auto-map" },
                  ] as const).map(({ key, label }) => {
                    const active = modeFilter === key;
                    const count = key === "all" ? pools.length : key === "single_jd" ? stats.single_jd : stats.auto_map;
                    return (
                      <button
                        key={key}
                        onClick={() => setModeFilter(key)}
                        className={`px-2 py-0.5 text-[10px] font-medium rounded-full border transition-colors ${
                          active
                            ? "bg-axis-magenta/10 text-axis-magenta border-axis-magenta/30"
                            : "bg-white text-axis-muted border-axis-divider hover:border-axis-magenta/30"
                        }`}
                      >
                        {label} ({count})
                      </button>
                    );
                  })}
                </div>

                <div className="w-px h-4 bg-axis-divider" />

                {/* Shortlisted only toggle */}
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={shortlistedOnly}
                    onChange={(e) => setShortlistedOnly(e.target.checked)}
                    className="accent-axis-magenta w-3 h-3"
                  />
                  <span className="text-[10px] font-medium text-axis-muted">
                    Has shortlisted ({stats.withShortlisted})
                  </span>
                </label>

                {/* Spacer */}
                <div className="flex-1" />

                {/* Sort */}
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-semibold text-axis-muted uppercase tracking-wide">Sort:</span>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as SortKey)}
                    className="px-2 py-0.5 text-[10px] border border-axis-divider rounded bg-white focus:outline-none focus:border-axis-magenta/60"
                  >
                    <option value="date_desc">Newest first</option>
                    <option value="date_asc">Oldest first</option>
                    <option value="cvs_desc">Most CVs</option>
                    <option value="shortlisted_desc">Most shortlisted</option>
                  </select>
                </div>

                {/* Clear filters */}
                {hasActiveFilters && (
                  <button
                    onClick={clearFilters}
                    className="px-2 py-0.5 text-[10px] text-axis-magenta hover:underline font-medium"
                  >
                    Clear all
                  </button>
                )}
              </div>

              {/* Active filter count */}
              {hasActiveFilters && (
                <p className="text-[10px] text-axis-muted">
                  Showing {filtered.length} of {pools.length} batches
                </p>
              )}
            </div>
          )}

          {loading ? (
            <div className="text-sm text-axis-muted py-12 text-center">
              Loading batches...
            </div>
          ) : pools.length === 0 ? (
            <div className="bg-axis-canvas border border-axis-divider rounded-card p-8 text-center">
              <p className="text-axis-muted">No screening batches yet.</p>
              <p className="text-xs text-axis-muted mt-1">
                Click "New screening batch" to upload CVs and start scoring.
              </p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="bg-axis-canvas border border-axis-divider rounded-card p-8 text-center">
              <p className="text-axis-muted">No batches match your filters.</p>
              <button
                onClick={clearFilters}
                className="text-xs text-axis-magenta hover:underline mt-1"
              >
                Clear all filters
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {filtered.map((p) => (
                <Link
                  key={p.pool_id}
                  href={p.status === "pending_review" ? `/hr/bulk-screening/${p.pool_id}/review` : `/hr/bulk-screening/${p.pool_id}`}
                  className="block bg-axis-canvas border border-axis-divider rounded-card shadow-card p-4 hover:border-axis-magenta/40 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-semibold text-axis-ink">
                          {p.job_title}
                        </p>
                        {p.mode === "auto_map" && (
                          <span className="text-[9px] px-1.5 py-0.5 bg-indigo-50 text-indigo-600 rounded-full border border-indigo-200">
                            Auto-map
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-axis-muted mt-0.5">
                        {p.total} CVs uploaded &middot;{" "}
                        {p.shortlisted} shortlisted &middot;{" "}
                        {new Date(p.created_at).toLocaleDateString("en-IN", {
                          day: "numeric",
                          month: "short",
                          year: "numeric",
                        })}
                      </p>
                      {p.candidate_names?.length > 0 && (
                        <p className="text-[10px] text-axis-muted/70 mt-0.5 truncate max-w-lg">
                          {p.candidate_names.join(", ")}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      {p.status === "pending_review" ? (
                        <span className="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">
                          Review Pending
                        </span>
                      ) : p.status === "processing" ? (
                        <span className="text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                          Processing ({p.progress_pct.toFixed(0)}%)
                        </span>
                      ) : p.status === "done" ? (
                        <span className="text-xs px-2 py-0.5 rounded bg-green-50 text-green-700 border border-green-200">
                          Done
                        </span>
                      ) : (
                        <span className="text-xs px-2 py-0.5 rounded bg-red-50 text-red-700 border border-red-200">
                          Failed
                        </span>
                      )}
                      <span className="text-axis-muted text-xs">&rarr;</span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </main>
      <Footer />
    </>
  );
}
