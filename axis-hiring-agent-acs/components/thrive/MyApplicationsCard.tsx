"use client";

/**
 * "My Applications" tray for the Thrive employee home page.
 *
 * Purely additive — does not modify any existing page or component. Lists
 * every live application for the currently-logged-in candidate so they can
 * close the tab and come back tomorrow and still find their running
 * applications. Each row deep-links into /thrive/status/[appId] which is
 * the same page the Apply flow already lands on.
 *
 * Controlled by the Thrive home page (which already knows the candidate)
 * so this component does not need to talk to the persona store directly.
 */

import Link from "next/link";
import { useCallback } from "react";
import { api, type Application, type Job } from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";

interface Props {
  candidateId: string | null;
  /** Email of the logged-in user — used to also fetch external applications
   *  (e.g. candidates routed from Bulk CV Screening). */
  candidateEmail?: string | null;
  jobsById: Record<string, Job>;
  /** When true, show every application. When false (default), show top 3
   *  with a "View all →" link to /thrive/applications. */
  expanded?: boolean;
}

/** One-line "what's waiting on the candidate" derived from stage + status.
 *  Deliberately conservative — if the backend already put a next_action on
 *  the app we prefer that. */
function nextStepFor(app: Application): string {
  if (app.next_action) return app.next_action;
  if (app.stage === "applied") return "We're reviewing your profile…";
  if (app.stage === "screened" && app.agent_status === "waiting_candidate")
    return "Pick your Round 1 time →";
  if (app.stage === "screened") return "Finding Round 1 interview times for you…";
  if (app.stage === "r1_scheduled" && !app.r1_started)
    return "Round 1 is on your calendar — join when ready";
  if (app.stage === "r1_scheduled")
    return "Round 1 interview in progress…";
  if (app.stage === "r1_done" && app.agent_status === "waiting_hr")
    return "Round 1 cleared — waiting on your Business Partner to confirm the panel";
  if (app.stage === "r1_done" && app.agent_status === "waiting_candidate")
    return "Pick your Round 2 time →";
  if (app.stage === "r1_done") return "Round 1 cleared — panel is being prepared";
  if (app.stage === "r2_scheduled") return "Round 2 panel interview scheduled";
  if (app.stage === "offer") return "Offer extended 🎉";
  if (app.stage === "rejected") return "Application closed";
  return "We're working on your application.";
}

function stageChipStyle(stage: Application["stage"]): string {
  switch (stage) {
    case "offer":
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "rejected":
      return "bg-axis-pink-soft text-axis-burgundy border-axis-magenta/40";
    case "r1_done":
    case "r2_scheduled":
      return "bg-axis-cream text-axis-ink border-axis-cream-border";
    case "r1_scheduled":
      return "bg-axis-cream text-axis-ink border-axis-cream-border";
    default:
      return "bg-axis-surface text-axis-ink-soft border-axis-divider";
  }
}

function stageLabel(stage: Application["stage"]): string {
  switch (stage) {
    case "applied":
      return "Applied";
    case "screened":
      return "Screened";
    case "r1_scheduled":
      return "R1 scheduled";
    case "r1_done":
      return "R1 cleared";
    case "r2_scheduled":
      return "R2 scheduled";
    case "offer":
      return "Offer";
    case "rejected":
      return "Closed";
    default:
      return stage;
  }
}

export function MyApplicationsCard({
  candidateId,
  candidateEmail,
  jobsById,
  expanded = false,
}: Props) {
  // Stable loader — fetches both internal and external applications, then
  // deduplicates by app.id so a candidate routed from Bulk CV Screening
  // shows up alongside any internal applications.
  const loader = useCallback(() => {
    if (!candidateId && !candidateEmail) return Promise.resolve<Application[]>([]);
    const fetches: Promise<Application[]>[] = [];
    if (candidateId) fetches.push(api.listApplicationsForCandidate(candidateId));
    if (candidateEmail) fetches.push(api.externalApplications(candidateEmail).catch(() => []));
    return Promise.all(fetches).then((results) => {
      const seen = new Set<string>();
      const merged: Application[] = [];
      for (const list of results) {
        for (const app of list) {
          if (!seen.has(app.id)) {
            seen.add(app.id);
            merged.push(app);
          }
        }
      }
      return merged;
    });
  }, [candidateId, candidateEmail]);

  const { data, loading, error } = useAutoRefresh<Application[]>(loader, 4000);

  // Newest application first.
  const sorted = (data ?? [])
    .slice()
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
  const visible = expanded ? sorted : sorted.slice(0, 3);

  return (
    <div className="mt-6 bg-axis-canvas border border-axis-divider rounded-card shadow-card overflow-hidden">
      <div className="flex items-center justify-between px-5 py-4 border-b border-axis-divider">
        <h2 className="text-base font-semibold text-axis-ink flex items-center gap-2">
          <span className="w-5 h-5 rounded bg-axis-pink-soft flex items-center justify-center text-axis-burgundy text-xs">
            ◆
          </span>
          My Applications
          {sorted.length > 0 && (
            <span className="text-xs font-normal text-axis-muted">
              ({sorted.length})
            </span>
          )}
        </h2>
        {!expanded && sorted.length > 3 && (
          <Link
            href="/thrive/applications"
            className="text-axis-magenta text-xs font-semibold tracking-wider hover:underline"
          >
            VIEW ALL
          </Link>
        )}
      </div>

      {loading && sorted.length === 0 && (
        <p className="px-5 py-6 text-sm text-axis-muted">
          Loading your applications…
        </p>
      )}

      {error && (
        <p className="px-5 py-4 text-xs text-axis-burgundy bg-axis-pink-soft">
          {error}
        </p>
      )}

      {!loading && !error && sorted.length === 0 && (
        <div className="px-5 py-8 text-center">
          <p className="text-sm text-axis-muted">
            You haven't applied to anything yet.
          </p>
          <p className="text-xs text-axis-muted mt-1">
            Scroll down and tap <strong>Apply</strong> on any role below — it
            will show up here so you can check back anytime.
          </p>
        </div>
      )}

      {visible.length > 0 && (
        <ul className="divide-y divide-axis-divider">
          {visible.map((app) => {
            const job = jobsById[app.job_id];
            const title = job?.title ?? `Job ${app.job_id}`;
            const loc = job?.location ?? "";
            const jobRef = job?.job_id ?? app.job_id;
            return (
              <li key={app.id}>
                <Link
                  href={`/thrive/status/${app.id}`}
                  className="flex items-start gap-4 px-5 py-4 hover:bg-axis-surface transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="text-sm font-semibold text-axis-ink truncate">
                        {title}
                      </p>
                      <span
                        className={`text-[10px] uppercase tracking-wider font-semibold border px-2 py-0.5 rounded ${stageChipStyle(
                          app.stage,
                        )}`}
                      >
                        {stageLabel(app.stage)}
                      </span>
                    </div>
                    <p className="text-xs text-axis-muted mt-1 truncate">
                      Job ID <span className="text-axis-ink">{jobRef}</span>
                      {loc ? (
                        <>
                          {" · "}
                          <span className="text-axis-ink">{loc}</span>
                        </>
                      ) : null}
                      {" · "}
                      Match{" "}
                      <span className="text-axis-ink">
                        {app.match_percent.toFixed(0)}%
                      </span>
                    </p>
                    <p className="text-xs text-axis-magenta font-medium mt-2 truncate">
                      {nextStepFor(app)}
                    </p>
                  </div>
                  <div className="shrink-0 flex flex-col items-end gap-2">
                    {/* AgentStatusBadge intentionally hidden on the
                        candidate-facing view — the "AGENT · WAITING ON …"
                        chip is internal jargon. The human next-step copy
                        above (nextStepFor) tells candidates what's
                        happening without leaking the orchestrator model. */}
                    <span className="text-[10px] text-axis-muted">
                      Open →
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
