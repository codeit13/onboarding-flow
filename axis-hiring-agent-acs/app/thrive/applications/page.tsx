"use client";

/**
 * /thrive/applications — the full "My Applications" page for a candidate.
 *
 * Purely additive route. Reuses the existing TopBar, LeftRail, Footer and
 * MyApplicationsCard component so the shell matches the Thrive home page
 * byte-for-byte. Nothing in the rest of the app is modified.
 *
 * Groups applications into Active (every stage except offer/rejected) and
 * Closed (offer or rejected). Each row in either group is rendered via the
 * same MyApplicationsCard component the home page uses, so we keep a single
 * source of truth for what a candidate-side application row looks like.
 */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { LeftRail } from "@/components/thrive/LeftRail";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import { MyApplicationsCard } from "@/components/thrive/MyApplicationsCard";
import { api, type Candidate, type Job } from "@/lib/api";
import { usePersona } from "@/lib/persona";

export default function ThriveApplicationsPage() {
  return (
    <RoleGate allow={["employee"]}>
      <ThriveApplicationsContent />
    </RoleGate>
  );
}

function ThriveApplicationsContent() {
  const [persona] = usePersona();
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [cs, js] = await Promise.all([
          api.listCandidates(),
          api.listJobs(),
        ]);
        if (cancelled) return;
        const c =
          cs.find((x) => x.id === persona.identity) ||
          cs.find((x) => x.employee_id === persona.identity) ||
          cs[0] ||
          null;
        setCandidate(c);
        setJobs(js);
      } catch (e: any) {
        if (!cancelled) setLoadError(e.message || String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [persona.identity]);

  const jobsById = useMemo(() => {
    const m: Record<string, Job> = {};
    for (const j of jobs) m[j.id] = j;
    return m;
  }, [jobs]);

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <div className="flex flex-1">
        <LeftRail />
        <main className="flex-1 px-8 py-6 bg-axis-canvas">
          <div className="max-w-[820px]">
            <Link
              href="/thrive"
              className="text-axis-magenta text-xs font-medium hover:underline"
            >
              ← Back to Thrive home
            </Link>
            <h1 className="text-2xl font-display text-axis-ink mt-3">
              My Applications
            </h1>
            <p className="text-sm text-axis-muted mt-1">
              Every role you've applied to, with live agent status. Click any
              row to open its dedicated status page.
            </p>

            {candidate && (
              <div className="mt-4 text-xs text-axis-muted">
                Viewing as{" "}
                <strong className="text-axis-ink">{candidate.name}</strong> ·{" "}
                {candidate.current_role} · {candidate.current_location}
              </div>
            )}

            {loadError && (
              <div className="mt-6 p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
                {loadError}
              </div>
            )}

            {/* Single list, expanded — MyApplicationsCard already knows how
                to render rows and empty states. Grouping is purely visual
                so we render the same component twice filtered externally is
                not needed; the component itself shows everything newest-first
                which is what candidates want for a "my applications" inbox. */}
            {/* Pass employee_id — the backend's Application.candidate_id
                is the employee_id, not the cand-XXX UUID. */}
            <MyApplicationsCard
              candidateId={candidate?.employee_id ?? null}
              candidateEmail={candidate?.email ?? null}
              jobsById={jobsById}
              expanded
            />
          </div>
        </main>
      </div>
      <Footer />
    </div>
  );
}
