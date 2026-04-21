"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { RoleGate } from "@/components/RoleGate";
import { AgentActivityFeed } from "@/components/agent/AgentActivityFeed";
import { api, type ActivityItem } from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";

type Tab = "feed" | "emails" | "calendar" | "notifications" | "health";

type EmailRow = Awaited<ReturnType<typeof api.debugEmails>>[number];
type CalRow = Awaited<ReturnType<typeof api.debugCalendar>>[number];
type NotifRow = Awaited<ReturnType<typeof api.debugNotifications>>[number];
type Health = Awaited<ReturnType<typeof api.health>>;

/**
 * Operations / agent observability console.
 *
 * The control room view of every side-effect the autonomous agent has
 * performed: outbound + inbound emails, calendar invites, push
 * notifications, and a unified activity feed across all of them.
 *
 * Backed by the `/debug/*` and `/health` endpoints which expose the mock
 * provider state directly. When `AXIS_CALENDAR_PROVIDER=graph` is set, the
 * calendar tab shows real Microsoft Graph events instead of the mock store.
 */
export default function OpsConsolePage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <OpsConsoleContent />
    </RoleGate>
  );
}

function OpsConsoleContent() {
  const [tab, setTab] = useState<Tab>("feed");
  const [resetMsg, setResetMsg] = useState<string | null>(null);

  const loadFeed = useCallback(() => api.listActivity(undefined, 200), []);
  const loadEmails = useCallback(() => api.debugEmails(), []);
  const loadCal = useCallback(() => api.debugCalendar(), []);
  const loadNotif = useCallback(() => api.debugNotifications(), []);
  const loadHealth = useCallback(() => api.health(), []);

  const { data: feed, refresh: refreshFeed } = useAutoRefresh<ActivityItem[]>(
    loadFeed,
    4000,
  );
  const { data: emails, refresh: refreshEmails } = useAutoRefresh<EmailRow[]>(
    loadEmails,
    4000,
  );
  const { data: cal, refresh: refreshCal } = useAutoRefresh<CalRow[]>(
    loadCal,
    4000,
  );
  const { data: notif, refresh: refreshNotif } = useAutoRefresh<NotifRow[]>(
    loadNotif,
    4000,
  );
  const { data: health, refresh: refreshHealth } = useAutoRefresh<Health>(
    loadHealth,
    8000,
  );

  const refreshAll = () => {
    refreshFeed();
    refreshEmails();
    refreshCal();
    refreshNotif();
    refreshHealth();
  };

  const onReset = async () => {
    if (!confirm("Reseed demo data? This wipes all in-memory state.")) return;
    try {
      const r = await api.demoSeedFlow();
      setResetMsg(`Reseeded · ${r.applications.length} applications fired.`);
      refreshAll();
      setTimeout(() => setResetMsg(null), 4000);
    } catch (e: any) {
      setResetMsg(`Reset failed: ${e?.message || e}`);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <HRSubNav />
      <main className="flex-1 px-8 py-6 max-w-6xl w-full mx-auto">
        <div className="flex items-end justify-between mb-6 flex-wrap gap-3">
          <div>
            <p className="text-[10px] text-axis-magenta font-semibold uppercase tracking-wider">
              Ops console
            </p>
            <h1 className="text-2xl font-display text-axis-ink mt-1">
              Agent observability
            </h1>
            <p className="text-xs text-axis-muted mt-1">
              Every side-effect the autonomous agent has produced — emails sent
              and received, Teams meetings scheduled, push notifications fired.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={refreshAll}
              className="text-xs px-3 py-1 rounded border border-axis-divider text-axis-ink-soft hover:bg-axis-surface"
            >
              Refresh
            </button>
            <button
              onClick={onReset}
              className="text-xs px-3 py-1 rounded border border-axis-magenta text-axis-magenta hover:bg-axis-pink-soft"
            >
              Reset &amp; reseed
            </button>
          </div>
        </div>

        {resetMsg && (
          <div className="mb-4 p-3 bg-axis-cream border border-axis-cream-border rounded text-sm text-axis-ink">
            {resetMsg}
          </div>
        )}

        {/* Health strip */}
        {health && (
          <div className="mb-6 grid grid-cols-2 md:grid-cols-5 gap-3">
            <Stat label="Status" value={health.status} />
            <Stat label="Jobs" value={String(health.jobs)} />
            <Stat label="Candidates" value={String(health.candidates)} />
            <Stat label="Applications" value={String(health.applications)} />
            <Stat
              label="Calendar"
              value={health.calendar_provider}
              tone={health.calendar_provider === "graph" ? "positive" : "neutral"}
            />
          </div>
        )}

        <div className="border-b border-axis-divider flex gap-4">
          {(
            ["feed", "emails", "calendar", "notifications", "health"] as Tab[]
          ).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`text-xs font-semibold uppercase tracking-wider py-2 border-b-2 ${
                tab === t
                  ? "border-axis-magenta text-axis-magenta"
                  : "border-transparent text-axis-muted"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="mt-4">
          {tab === "feed" && (
            <div className="bg-axis-canvas border border-axis-divider rounded-card p-5">
              <AgentActivityFeed
                items={feed ?? []}
                maxHeight="max-h-[70vh]"
                emptyLabel="No agent activity yet."
                defaultCollapsed={false}
              />
            </div>
          )}

          {tab === "emails" && <EmailsTable rows={emails ?? []} />}
          {tab === "calendar" && <CalendarTable rows={cal ?? []} />}
          {tab === "notifications" && <NotifTable rows={notif ?? []} />}
          {tab === "health" && (
            <pre className="bg-axis-canvas border border-axis-divider rounded-card p-5 text-xs text-axis-ink-soft overflow-x-auto">
              {JSON.stringify(health, null, 2)}
            </pre>
          )}
        </div>

        <p className="mt-6 text-[11px] text-axis-muted-light">
          Need to inspect a specific application?{" "}
          <Link href="/hr" className="text-axis-magenta hover:underline">
            Open the Business Partner funnel
          </Link>{" "}
          and pick a card.
        </p>
      </main>
      <Footer />
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────────────

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "positive";
}) {
  const cls =
    tone === "positive"
      ? "border-axis-cream-border bg-axis-cream"
      : "border-axis-divider bg-axis-canvas";
  return (
    <div className={`p-3 rounded-card border ${cls}`}>
      <p className="text-[10px] uppercase tracking-wider text-axis-muted">
        {label}
      </p>
      <p className="text-axis-ink font-semibold mt-0.5 truncate">{value}</p>
    </div>
  );
}

function EmailsTable({ rows }: { rows: EmailRow[] }) {
  if (rows.length === 0) {
    return (
      <Empty msg="No emails recorded. Apply to a JD on /thrive to fire the agent." />
    );
  }
  return (
    <div className="bg-axis-canvas border border-axis-divider rounded-card overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-axis-surface text-[10px] uppercase tracking-wider text-axis-muted">
          <tr>
            <th className="text-left px-3 py-2">When</th>
            <th className="text-left px-3 py-2">Direction</th>
            <th className="text-left px-3 py-2">From</th>
            <th className="text-left px-3 py-2">To</th>
            <th className="text-left px-3 py-2">Subject</th>
          </tr>
        </thead>
        <tbody>
          {rows
            .slice()
            .reverse()
            .map((e) => (
              <tr
                key={e.id}
                className="border-t border-axis-divider hover:bg-axis-surface align-top"
              >
                <td className="px-3 py-2 text-axis-muted-light tabular-nums whitespace-nowrap">
                  {new Date(e.at).toLocaleString()}
                </td>
                <td className="px-3 py-2">
                  <span
                    className={`text-[9px] px-1.5 py-0.5 rounded font-semibold ${
                      e.direction === "outbound"
                        ? "bg-axis-cream text-axis-ink"
                        : "bg-axis-pink-soft text-axis-burgundy"
                    }`}
                  >
                    {e.direction}
                  </span>
                </td>
                <td className="px-3 py-2 text-axis-ink-soft truncate max-w-[160px]">
                  {e.from}
                </td>
                <td className="px-3 py-2 text-axis-ink-soft truncate max-w-[160px]">
                  {e.to}
                </td>
                <td className="px-3 py-2 text-axis-ink">
                  <p className="font-medium">{e.subject}</p>
                  <p className="text-axis-muted-light line-clamp-2 mt-0.5">
                    {e.body.slice(0, 200)}
                  </p>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

function CalendarTable({ rows }: { rows: CalRow[] }) {
  if (rows.length === 0) {
    return <Empty msg="No calendar invites recorded yet." />;
  }
  return (
    <div className="bg-axis-canvas border border-axis-divider rounded-card overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-axis-surface text-[10px] uppercase tracking-wider text-axis-muted">
          <tr>
            <th className="text-left px-3 py-2">Subject</th>
            <th className="text-left px-3 py-2">Organiser</th>
            <th className="text-left px-3 py-2">Attendees</th>
            <th className="text-left px-3 py-2">Slot</th>
            <th className="text-left px-3 py-2">Teams</th>
            <th className="text-left px-3 py-2">State</th>
          </tr>
        </thead>
        <tbody>
          {rows
            .slice()
            .reverse()
            .map((e) => (
              <tr
                key={e.id}
                className="border-t border-axis-divider hover:bg-axis-surface align-top"
              >
                <td className="px-3 py-2 text-axis-ink font-medium">
                  {e.subject}
                </td>
                <td className="px-3 py-2 text-axis-ink-soft">{e.organiser_id}</td>
                <td className="px-3 py-2 text-axis-muted-light">
                  {e.attendees.join(", ")}
                </td>
                <td className="px-3 py-2 text-axis-ink-soft tabular-nums whitespace-nowrap">
                  {new Date(e.start).toLocaleString()} →{" "}
                  {new Date(e.end).toLocaleTimeString()}
                </td>
                <td className="px-3 py-2">
                  {e.teams_join_url ? (
                    <a
                      href={e.teams_join_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-axis-magenta underline"
                    >
                      Join ↗
                    </a>
                  ) : (
                    <span className="text-axis-muted-light">—</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {e.cancelled ? (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-axis-pink-soft text-axis-burgundy font-semibold">
                      cancelled
                    </span>
                  ) : (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-axis-cream text-axis-ink font-semibold">
                      booked
                    </span>
                  )}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

function NotifTable({ rows }: { rows: NotifRow[] }) {
  if (rows.length === 0) {
    return <Empty msg="No push notifications fired yet." />;
  }
  return (
    <div className="bg-axis-canvas border border-axis-divider rounded-card overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-axis-surface text-[10px] uppercase tracking-wider text-axis-muted">
          <tr>
            <th className="text-left px-3 py-2">When</th>
            <th className="text-left px-3 py-2">To</th>
            <th className="text-left px-3 py-2">Message</th>
            <th className="text-left px-3 py-2">App</th>
          </tr>
        </thead>
        <tbody>
          {rows
            .slice()
            .reverse()
            .map((n) => (
              <tr
                key={n.id}
                className="border-t border-axis-divider hover:bg-axis-surface align-top"
              >
                <td className="px-3 py-2 text-axis-muted-light tabular-nums whitespace-nowrap">
                  {new Date(n.at).toLocaleString()}
                </td>
                <td className="px-3 py-2 text-axis-ink-soft">{n.to}</td>
                <td className="px-3 py-2 text-axis-ink">{n.message}</td>
                <td className="px-3 py-2 text-axis-muted-light">
                  {n.application_id ? (
                    <Link
                      href={`/hr/applications/${n.application_id}`}
                      className="text-axis-magenta hover:underline"
                    >
                      {n.application_id}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div className="p-6 bg-axis-canvas border border-axis-divider rounded-card text-sm text-axis-muted">
      {msg}
    </div>
  );
}
