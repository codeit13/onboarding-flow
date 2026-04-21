"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { RoleGate } from "@/components/RoleGate";
import { api, type Application, type Candidate } from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";

/**
 * Candidate directory.
 *
 * Searchable list of every employee in the Thrive directory plus a quick
 * "applications in flight" count beside each row. Polls the application
 * list (cheap) every 4s so the count stays live; the candidate list itself
 * only refreshes every 30s — it almost never changes during the demo.
 */
export default function HRCandidatesPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <HRCandidatesContent />
    </RoleGate>
  );
}

function HRCandidatesContent() {
  const [search, setSearch] = useState("");
  const [bandFilter, setBandFilter] = useState<string>("all");

  const loadCands = useCallback(() => api.listCandidates(), []);
  const loadApps = useCallback(() => api.listApplications("hr"), []);

  const { data: candsData, error } = useAutoRefresh<Candidate[]>(
    loadCands,
    30000,
  );
  const { data: appsData } = useAutoRefresh<Application[]>(loadApps, 4000);

  const cands = candsData ?? [];
  const apps = appsData ?? [];

  const bands = useMemo(() => {
    const set = new Set<string>();
    cands.forEach((c) => c.current_band && set.add(c.current_band));
    return Array.from(set).sort();
  }, [cands]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return cands
      .filter((c) => {
        if (bandFilter !== "all" && c.current_band !== bandFilter) return false;
        if (!q) return true;
        return (
          c.name.toLowerCase().includes(q) ||
          c.email.toLowerCase().includes(q) ||
          c.employee_id.toLowerCase().includes(q) ||
          c.current_role.toLowerCase().includes(q) ||
          c.current_location.toLowerCase().includes(q) ||
          c.skills.some((s) => s.toLowerCase().includes(q))
        );
      })
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [cands, search, bandFilter]);

  const appsByCand = useMemo(() => {
    const m = new Map<string, Application[]>();
    apps.forEach((a) => {
      const arr = m.get(a.candidate_id) ?? [];
      arr.push(a);
      m.set(a.candidate_id, arr);
    });
    return m;
  }, [apps]);

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <HRSubNav />
      <main className="flex-1 px-8 py-6 max-w-7xl w-full mx-auto">
        <div className="flex items-end justify-between mb-6 flex-wrap gap-3">
          <div>
            <p className="text-[10px] text-axis-magenta font-semibold uppercase tracking-wider">
              Candidates
            </p>
            <h1 className="text-2xl font-display text-axis-ink mt-1">
              {visible.length} of {cands.length} employees
            </h1>
            <p className="text-xs text-axis-muted mt-1">
              Internal mobility candidates pulled from Thrive.
            </p>
          </div>
          <div className="flex gap-2">
            <select
              value={bandFilter}
              onChange={(e) => setBandFilter(e.target.value)}
              className="text-xs border border-axis-divider rounded px-2 py-2 bg-axis-canvas"
            >
              <option value="all">All bands</option>
              {bands.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, skill, role, location…"
              className="border border-axis-divider rounded px-3 py-2 text-sm w-80"
            />
          </div>
        </div>

        {error && (
          <div className="p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
            {error}
          </div>
        )}

        <div className="bg-axis-canvas border border-axis-divider rounded-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-axis-surface text-[10px] uppercase tracking-wider text-axis-muted">
              <tr>
                <th className="text-left px-4 py-2">Name</th>
                <th className="text-left px-4 py-2">Current role</th>
                <th className="text-left px-4 py-2">Band</th>
                <th className="text-left px-4 py-2">Tenure</th>
                <th className="text-left px-4 py-2">Last rating</th>
                <th className="text-left px-4 py-2">In flight</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((c) => {
                const inFlight = (appsByCand.get(c.id) ?? []).filter(
                  (a) => a.stage !== "rejected" && a.stage !== "offer",
                ).length;
                return (
                  <tr
                    key={c.id}
                    className="border-t border-axis-divider hover:bg-axis-surface"
                  >
                    <td className="px-4 py-2">
                      <p className="text-axis-ink font-semibold">{c.name}</p>
                      <p className="text-[10px] text-axis-muted">
                        {c.employee_id} · {c.email}
                      </p>
                    </td>
                    <td className="px-4 py-2 text-axis-ink-soft">
                      {c.current_role}
                      <p className="text-[10px] text-axis-muted">
                        {c.current_location}
                      </p>
                    </td>
                    <td className="px-4 py-2 text-axis-ink-soft">
                      {c.current_band || "—"}
                    </td>
                    <td className="px-4 py-2 text-axis-ink-soft tabular-nums">
                      {c.tenure_years.toFixed(1)}y
                    </td>
                    <td className="px-4 py-2 text-axis-ink-soft">
                      {c.last_rating || "—"}
                    </td>
                    <td className="px-4 py-2 tabular-nums">
                      {inFlight > 0 ? (
                        <span className="px-2 py-0.5 bg-axis-pink-soft text-axis-burgundy rounded text-[10px] font-semibold">
                          {inFlight}
                        </span>
                      ) : (
                        <span className="text-axis-muted-light">0</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <Link
                        href={`/hr/candidates/${c.id}`}
                        className="text-axis-magenta text-[10px] uppercase tracking-wider hover:underline"
                      >
                        Open →
                      </Link>
                    </td>
                  </tr>
                );
              })}
              {visible.length === 0 && (
                <tr>
                  <td
                    colSpan={7}
                    className="px-4 py-6 text-center text-sm text-axis-muted"
                  >
                    No candidates match the filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>
      <Footer />
    </div>
  );
}
