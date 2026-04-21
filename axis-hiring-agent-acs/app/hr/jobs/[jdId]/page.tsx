"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { RoleGate } from "@/components/RoleGate";
import { AgentStatusBadge } from "@/components/agent/AgentStatusBadge";
import {
  api,
  type Application,
  type Candidate,
  type ChecklistItem,
  type Job,
} from "@/lib/api";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";
import { STAGE_LABEL } from "@/lib/stages";

type Tab = "overview" | "panel" | "pipeline" | "checklists";
type Round = "R1" | "R2";
type Phase = "pre" | "post";

/**
 * Job Description detail page.
 *
 * Four tabs:
 *   - Overview   — JD facts, full description, required + nice-to-have skills.
 *   - Panel      — the panel composition seeded for this JD (HM, interviewers,
 *                  HR partner). Read-only; the seed file is the source of
 *                  truth in the demo.
 *   - Pipeline   — live list of every application against this JD with stage
 *                  + agent status, click into any of them.
 *   - Checklists — the existing checklist template editor (R1/R2 × pre/post)
 *                  with custom item add.
 *
 * Pipeline tab polls every 4s; everything else is one-shot.
 */
export default function HRJobDetailPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <HRJobDetailContent />
    </RoleGate>
  );
}

function HRJobDetailContent() {
  const params = useParams<{ jdId: string }>();
  const [tab, setTab] = useState<Tab>("overview");

  const [job, setJob] = useState<Job | null>(null);
  const [jobErr, setJobErr] = useState<string | null>(null);

  // One-shot job load.
  useEffect(() => {
    let cancelled = false;
    api
      .getJob(params.jdId)
      .then((j) => !cancelled && setJob(j))
      .catch((e) => !cancelled && setJobErr(e?.message || String(e)));
    return () => {
      cancelled = true;
    };
  }, [params.jdId]);

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <HRSubNav />
      <main className="flex-1 px-8 py-6 max-w-6xl w-full mx-auto">
        <Link
          href="/hr/jobs"
          className="text-axis-magenta text-xs font-medium hover:underline"
        >
          ← Back to requisitions
        </Link>

        {jobErr && (
          <div className="mt-6 p-4 bg-axis-pink-soft border border-axis-magenta rounded text-sm text-axis-burgundy">
            {jobErr}
          </div>
        )}
        {!job && !jobErr && (
          <p className="mt-6 text-sm text-axis-muted">Loading…</p>
        )}

        {job && (
          <>
            <div className="mt-4 bg-axis-canvas border border-axis-divider rounded-card shadow-card p-6">
              <p className="text-xs uppercase tracking-wider text-axis-magenta font-semibold">
                {job.job_id} · {job.function || "Open requisition"}
              </p>
              <h1 className="text-2xl font-display text-axis-ink mt-1">
                {job.title}
              </h1>
              <p className="text-sm text-axis-muted mt-1">
                {job.location} · {job.band}
                {job.positions && job.positions > 1
                  ? ` · ${job.positions} positions`
                  : ""}{" "}
                · shortlist threshold {job.shortlist_threshold}%
              </p>
              <div className="mt-3 flex flex-wrap gap-1">
                {job.tags.map((t) => (
                  <span
                    key={t}
                    className="text-[10px] px-2 py-0.5 bg-axis-surface border border-axis-divider rounded"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>

            <div className="mt-6 border-b border-axis-divider flex gap-4">
              {(["overview", "panel", "pipeline", "checklists"] as Tab[]).map(
                (t) => (
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
                ),
              )}
            </div>

            <div className="mt-4">
              {tab === "overview" && <OverviewTab job={job} />}
              {tab === "panel" && <PanelTab job={job} />}
              {tab === "pipeline" && <PipelineTab jobId={job.id} />}
              {tab === "checklists" && <ChecklistsTab jdId={params.jdId} />}
            </div>
          </>
        )}
      </main>
      <Footer />
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tab: Overview
// ──────────────────────────────────────────────────────────────────────

function OverviewTab({ job }: { job: Job }) {
  return (
    <div className="bg-axis-canvas border border-axis-divider rounded-card p-5 text-sm space-y-4">
      <div>
        <p className="text-xs uppercase text-axis-muted font-semibold">
          Description
        </p>
        <p className="text-axis-ink-soft mt-1 whitespace-pre-wrap">
          {job.description || "No long-form description provided."}
        </p>
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <div>
          <p className="text-xs uppercase text-axis-muted font-semibold">
            Required skills ({job.required_skills.length})
          </p>
          <div className="mt-1 flex flex-wrap gap-1">
            {job.required_skills.map((s) => (
              <span
                key={s}
                className="text-[10px] px-2 py-0.5 bg-axis-cream rounded"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
        <div>
          <p className="text-xs uppercase text-axis-muted font-semibold">
            Nice to have ({job.nice_to_have_skills?.length || 0})
          </p>
          <div className="mt-1 flex flex-wrap gap-1">
            {(job.nice_to_have_skills || []).map((s) => (
              <span
                key={s}
                className="text-[10px] px-2 py-0.5 bg-axis-surface border border-axis-divider rounded"
              >
                {s}
              </span>
            ))}
            {(!job.nice_to_have_skills ||
              job.nice_to_have_skills.length === 0) && (
              <span className="text-[10px] text-axis-muted-light italic">
                none configured
              </span>
            )}
          </div>
        </div>
      </div>
      <div>
        <p className="text-xs uppercase text-axis-muted font-semibold">
          Match scoring
        </p>
        <p className="text-axis-ink-soft mt-1">
          The agent shortlists candidates whose skill overlap (plus a tenure
          boost) is at least <strong>{job.shortlist_threshold}%</strong>.
          Anyone below is auto-rejected with a regret email.
        </p>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tab: Panel
// ──────────────────────────────────────────────────────────────────────

function PanelTab({ job }: { job: Job }) {
  if (job.panel.length === 0) {
    return (
      <div className="bg-axis-canvas border border-axis-divider rounded-card p-5 text-sm text-axis-muted">
        No panel configured for this requisition. The orchestrator will not be
        able to schedule R1/R2 until panellists are seeded.
      </div>
    );
  }
  return (
    <div className="bg-axis-canvas border border-axis-divider rounded-card p-5">
      <p className="text-xs uppercase text-axis-muted font-semibold mb-3">
        {job.panel.length} panellist{job.panel.length === 1 ? "" : "s"}
      </p>
      <ul className="space-y-2">
        {job.panel.map((p) => (
          <li
            key={p.user_id}
            className="flex items-center justify-between gap-3 p-3 border border-axis-divider rounded"
          >
            <div className="min-w-0">
              <p className="text-sm font-semibold text-axis-ink truncate">
                {p.name}
              </p>
              <p className="text-[10px] text-axis-muted truncate">
                {p.user_id}
              </p>
            </div>
            <span
              className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${
                p.role === "hiring_manager"
                  ? "bg-axis-pink-soft border-axis-magenta text-axis-burgundy"
                  : p.role === "hr_partner"
                  ? "bg-axis-cream border-axis-cream-border text-axis-ink"
                  : "bg-axis-surface border-axis-divider text-axis-ink-soft"
              }`}
            >
              {p.role.replace("_", " ")}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[11px] text-axis-muted italic">
        Panel composition is seeded from the JD fixture and approved per
        application via the <code>pre-r2-2</code> blocking checklist item.
      </p>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tab: Pipeline
// ──────────────────────────────────────────────────────────────────────

function PipelineTab({ jobId }: { jobId: string }) {
  const loadApps = useCallback(() => api.listApplications("hr"), []);
  const loadCands = useCallback(() => api.listCandidates(), []);

  const { data: appsData } = useAutoRefresh<Application[]>(loadApps, 4000);
  const { data: candsData } = useAutoRefresh<Candidate[]>(loadCands, 30000);

  const apps = (appsData ?? []).filter((a) => a.job_id === jobId);
  const candById = useMemo(() => {
    const m = new Map<string, Candidate>();
    (candsData ?? []).forEach((c) => m.set(c.id, c));
    return m;
  }, [candsData]);

  if (apps.length === 0) {
    return (
      <div className="bg-axis-canvas border border-axis-divider rounded-card p-5 text-sm text-axis-muted">
        No applications against this requisition yet.
      </div>
    );
  }

  return (
    <div className="bg-axis-canvas border border-axis-divider rounded-card overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-axis-surface text-[10px] uppercase tracking-wider text-axis-muted">
          <tr>
            <th className="text-left px-4 py-2">Candidate</th>
            <th className="text-left px-4 py-2">Match</th>
            <th className="text-left px-4 py-2">Stage</th>
            <th className="text-left px-4 py-2">Agent</th>
            <th className="text-left px-4 py-2">Updated</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {apps.map((a) => {
            const c = candById.get(a.candidate_id);
            const blocked = a.pending_blocking_items.length > 0;
            return (
              <tr
                key={a.id}
                className="border-t border-axis-divider hover:bg-axis-surface"
              >
                <td className="px-4 py-2">
                  <p className="text-axis-ink font-semibold">
                    {c?.name || a.candidate_id}
                  </p>
                  <p className="text-[10px] text-axis-muted">
                    {c?.current_role}
                  </p>
                </td>
                <td className="px-4 py-2 text-axis-ink-soft tabular-nums">
                  {a.match_percent.toFixed(0)}%
                </td>
                <td className="px-4 py-2 text-axis-ink-soft">
                  {STAGE_LABEL[a.stage]}
                </td>
                <td className="px-4 py-2">
                  <AgentStatusBadge status={a.agent_status} />
                </td>
                <td className="px-4 py-2 text-[10px] text-axis-muted-light">
                  {new Date(a.updated_at).toLocaleString()}
                </td>
                <td className="px-4 py-2 text-right">
                  {blocked && (
                    <span className="text-[10px] text-axis-burgundy font-semibold mr-2">
                      Blocked
                    </span>
                  )}
                  <Link
                    href={`/hr/applications/${a.id}`}
                    className="text-axis-magenta text-[10px] uppercase tracking-wider hover:underline"
                  >
                    Open →
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tab: Checklists
// ──────────────────────────────────────────────────────────────────────

function ChecklistsTab({ jdId }: { jdId: string }) {
  const [round, setRound] = useState<Round>("R1");
  const [phase, setPhase] = useState<Phase>("pre");
  const [items, setItems] = useState<ChecklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState({ label: "", blocking: false });
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const cl = await api.getChecklist(jdId, round, phase);
      setItems(cl.items);
      setError(null);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [jdId, round, phase]);

  useEffect(() => {
    load();
  }, [load]);

  const addItem = async () => {
    if (!draft.label.trim()) return;
    setSaving(true);
    try {
      const newItem: ChecklistItem = {
        id: `custom_${Date.now()}`,
        label: draft.label.trim(),
        blocking: draft.blocking,
        done: false,
      };
      await api.customiseChecklist(jdId, round, phase, [newItem]);
      setDraft({ label: "", blocking: false });
      setBanner(`Added "${newItem.label}" to ${round} ${phase}.`);
      await load();
      setTimeout(() => setBanner(null), 2500);
    } catch (e: any) {
      alert(`Add failed: ${e?.message || e}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-axis-canvas border border-axis-divider rounded-card p-5">
      <div className="flex gap-2 flex-wrap">
        {(["R1", "R2"] as Round[]).map((r) => (
          <button
            key={r}
            onClick={() => setRound(r)}
            className={`px-3 py-1.5 text-xs rounded ${
              round === r
                ? "bg-axis-magenta text-white"
                : "border border-axis-divider text-axis-ink-soft"
            }`}
          >
            {r}
          </button>
        ))}
        <span className="w-4" />
        {(["pre", "post"] as Phase[]).map((p) => (
          <button
            key={p}
            onClick={() => setPhase(p)}
            className={`px-3 py-1.5 text-xs rounded ${
              phase === p
                ? "bg-axis-magenta text-white"
                : "border border-axis-divider text-axis-ink-soft"
            }`}
          >
            {p}-interview
          </button>
        ))}
      </div>

      {error && (
        <p className="mt-3 text-xs text-axis-burgundy">{error}</p>
      )}
      {banner && (
        <div className="mt-4 p-3 bg-axis-cream border border-axis-cream-border rounded text-sm text-axis-ink">
          {banner}
        </div>
      )}

      <div className="mt-5">
        <p className="text-xs uppercase text-axis-muted font-semibold">
          Current items ({items.length})
        </p>
        {loading && <p className="text-sm text-axis-muted mt-2">Loading…</p>}
        <ul className="mt-2 space-y-2">
          {items.map((it) => (
            <li
              key={it.id}
              className="flex items-start gap-2 text-sm bg-axis-surface border border-axis-divider rounded p-2"
            >
              <span className="text-axis-ink flex-1">{it.label}</span>
              {it.blocking && (
                <span className="text-[10px] px-1.5 py-0.5 bg-axis-pink-soft text-axis-burgundy rounded font-semibold">
                  BLOCKING
                </span>
              )}
            </li>
          ))}
          {!loading && items.length === 0 && (
            <li className="text-sm text-axis-muted">No items yet.</li>
          )}
        </ul>
      </div>

      <div className="mt-6 pt-4 border-t border-axis-divider">
        <p className="text-xs uppercase text-axis-muted font-semibold">
          Add custom item
        </p>
        <p className="text-[11px] text-axis-muted-light mt-1">
          Customisations apply to every future application against this JD.
          Existing in-flight applications keep their original items.
        </p>
        <div className="mt-2 flex flex-col gap-2">
          <input
            type="text"
            value={draft.label}
            onChange={(e) => setDraft({ ...draft, label: e.target.value })}
            placeholder="e.g. Verify referee contact on file"
            className="border border-axis-divider rounded px-3 py-2 text-sm"
          />
          <label className="flex items-center gap-2 text-xs text-axis-ink-soft">
            <input
              type="checkbox"
              checked={draft.blocking}
              onChange={(e) =>
                setDraft({ ...draft, blocking: e.target.checked })
              }
            />
            Mark as blocking (agent cannot advance until the Business Partner ticks this)
          </label>
          <button
            onClick={addItem}
            disabled={saving || !draft.label.trim()}
            className="self-start px-4 py-2 rounded bg-axis-magenta text-white text-xs font-semibold hover:bg-axis-burgundy disabled:opacity-40"
          >
            {saving ? "Adding…" : "Add item"}
          </button>
        </div>
      </div>
    </div>
  );
}
