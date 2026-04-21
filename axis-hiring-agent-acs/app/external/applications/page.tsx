"use client";

/**
 * External candidate applications tracker.
 *
 * The candidate enters their email and we list every application they've
 * filed with Axis. Each row links into the shared status page so they can
 * pick up wherever they left off (slot confirm, R1 interview, etc.).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { api, Application, FunnelStage } from "@/lib/api";

const STORAGE_KEY = "axis_external_email_v1";

const STAGE_LABELS: Record<FunnelStage, string> = {
  applied: "Applied — under review",
  screened: "Screened — scheduling Round 1",
  r1_scheduled: "Round 1 scheduled",
  r1_done: "Round 1 complete",
  r2_scheduled: "Round 2 scheduled",
  offer_negotiation: "Offer Discussion Team negotiating CTC",
  offer: "Offer extended",
  offer_accepted: "Offer accepted — onboarding started",
  pre_joining: "Pre-joining — getting ready for Day 1",
  joined: "Joined Axis Bank",
  offer_declined: "Offer declined",
  rejected: "Closed",
};

export default function ExternalApplicationsPage() {
  const [email, setEmail] = useState("");
  const [apps, setApps] = useState<Application[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pre-fill from prior session if any.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        setEmail(saved);
      }
    } catch {
      /* ignore */
    }
  }, []);

  async function load(e?: React.FormEvent) {
    e?.preventDefault();
    if (!email.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const list = await api.externalApplications(email.trim());
      setApps(list);
      try {
        localStorage.setItem(STORAGE_KEY, email.trim());
      } catch {
        /* ignore */
      }
    } catch (err: any) {
      setError(err?.message || "Could not load applications");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <TopBar />
      <main className="min-h-screen bg-axis-surface py-10 px-6">
        <div className="max-w-3xl mx-auto">
          <div className="h-1 w-20 bg-axis-burgundy rounded mb-6" />
          <h1 className="text-3xl font-display text-axis-ink mb-2">
            Track your applications
          </h1>
          <p className="text-axis-muted mb-6">
            Enter the email you applied with — we'll show every Axis role
            you're currently in process for and where you stand.
          </p>

          <form
            onSubmit={load}
            className="bg-axis-canvas border border-axis-divider rounded-card shadow-card p-5 mb-6 flex items-end gap-3"
          >
            <div className="flex-1">
              <label className="block text-xs font-semibold text-axis-ink mb-1">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="priya@example.com"
                required
                className="w-full text-sm bg-axis-surface border border-axis-divider rounded p-2"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="px-5 py-2.5 text-sm font-semibold bg-axis-burgundy text-white rounded-btn hover:bg-axis-burgundy-dark transition disabled:opacity-50"
            >
              {loading ? "Loading…" : "Show my applications"}
            </button>
          </form>

          {error ? (
            <div className="mb-6 bg-red-50 border border-red-200 text-red-800 rounded-card p-3 text-sm">
              {error}
            </div>
          ) : null}

          {apps !== null ? (
            apps.length === 0 ? (
              <div className="bg-axis-canvas border border-axis-divider rounded-card p-5 text-sm text-axis-muted">
                We don't have any applications on file for {email}. Want to{" "}
                <Link
                  href="/external/intake"
                  className="text-axis-magenta hover:underline"
                >
                  apply now
                </Link>
                ?
              </div>
            ) : (
              <ul className="space-y-3">
                {apps.map((a) => (
                  <li
                    key={a.id}
                    className="bg-axis-canvas border border-axis-divider rounded-card p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1">
                        <p className="text-sm font-semibold text-axis-ink">
                          Application {a.id}
                        </p>
                        <p className="text-xs text-axis-muted">
                          {STAGE_LABELS[a.stage] || a.stage} · Match{" "}
                          {Math.round(a.match_percent)}%
                        </p>
                        {a.search_query ? (
                          <p className="text-[11px] text-axis-muted mt-1 italic">
                            Searched: "{a.search_query}"
                          </p>
                        ) : null}
                      </div>
                      <Link
                        href={`/thrive/status/${a.id}`}
                        className="px-3 py-1.5 text-xs font-semibold bg-axis-burgundy text-white rounded-btn hover:bg-axis-burgundy-dark transition"
                      >
                        Open →
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )
          ) : null}
        </div>
      </main>
      <Footer />
    </>
  );
}
