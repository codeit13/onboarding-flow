"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { HRSubNav } from "@/components/hr/HRSubNav";
import { RoleGate } from "@/components/RoleGate";
import { api, type Panel, type PanelMember } from "@/lib/api";

/**
 * Panel Configurations admin page (DESIGN-001 chunk 2).
 *
 * HR partners land here to onboard new interview panels, manage existing
 * ones, and set the role scopes that drive which panels get surfaced when
 * a candidate clears R1 on a given JD. Role scopes are matched against
 * JD function/band in the backend (``panels_for_job``) — ``"*"`` matches
 * every JD, ``"Retail Banking"`` matches by function, ``"Retail Banking/DM"``
 * matches by function+band.
 */
export default function PanelsAdminPage() {
  return (
    <RoleGate allow={["hr_partner"]}>
      <PanelsAdminContent />
    </RoleGate>
  );
}

type DraftMember = { user_id: string; name: string; role: PanelMember["role"] };
type DraftPanel = {
  name: string;
  members: DraftMember[];
  role_scopes: string;
  location: string;
  default_size: number;
  active: boolean;
};

const EMPTY_DRAFT: DraftPanel = {
  name: "",
  members: [{ user_id: "", name: "", role: "interviewer" }],
  role_scopes: "",
  location: "",
  default_size: 3,
  active: true,
};

function PanelsAdminContent() {
  const [panels, setPanels] = useState<Panel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<DraftPanel>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setError(null);
    api
      .listPanels()
      .then(setPanels)
      .catch((e) => setError(e?.message || String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const startCreate = () => {
    setEditingId("__new__");
    setDraft(EMPTY_DRAFT);
  };

  const startEdit = (p: Panel) => {
    setEditingId(p.id);
    setDraft({
      name: p.name,
      members: p.members.map((m) => ({
        user_id: m.user_id,
        name: m.name,
        role: m.role,
      })),
      role_scopes: p.role_scopes.join(", "),
      location: p.location || "",
      default_size: p.default_size,
      active: p.active,
    });
  };

  const cancel = () => {
    setEditingId(null);
    setDraft(EMPTY_DRAFT);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: draft.name.trim(),
        members: draft.members
          .map((m) => ({
            user_id: m.user_id.trim(),
            name: m.name.trim(),
            role: m.role,
          }))
          .filter((m) => m.user_id && m.name),
        role_scopes: draft.role_scopes
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        location: draft.location.trim() || null,
        default_size: draft.default_size,
        active: draft.active,
      };
      if (!payload.name) throw new Error("Panel name is required");
      if (payload.members.length === 0)
        throw new Error("At least one member is required");
      if (editingId === "__new__") {
        await api.createPanel(payload);
      } else if (editingId) {
        await api.updatePanel(editingId, payload);
      }
      cancel();
      load();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (p: Panel) => {
    if (!confirm(`Delete panel "${p.name}"? This cannot be undone.`)) return;
    try {
      await api.deletePanel(p.id);
      load();
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  };

  const addMember = () =>
    setDraft((d) => ({
      ...d,
      members: [...d.members, { user_id: "", name: "", role: "interviewer" }],
    }));

  const removeMember = (idx: number) =>
    setDraft((d) => ({
      ...d,
      members: d.members.filter((_, i) => i !== idx),
    }));

  const updateMember = (idx: number, patch: Partial<DraftMember>) =>
    setDraft((d) => ({
      ...d,
      members: d.members.map((m, i) => (i === idx ? { ...m, ...patch } : m)),
    }));

  return (
    <div className="min-h-screen flex flex-col bg-axis-canvas">
      <TopBar />
      <HRSubNav />
      <main className="flex-1 px-8 py-6 max-w-6xl w-full mx-auto">
        <Link
          href="/hr"
          className="text-axis-magenta text-xs font-medium hover:underline"
        >
          ← Back to Business Partner console
        </Link>

        <div className="mt-4 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-display text-axis-ink">
              Panel Configurations
            </h1>
            <p className="text-sm text-axis-muted mt-1">
              Onboard new interview panels, manage role scopes, and control
              which panels appear for each JD when HR approves an R1-cleared
              application.
            </p>
          </div>
          <button
            onClick={startCreate}
            className="px-4 py-2 text-xs font-semibold rounded bg-axis-magenta text-white hover:bg-axis-burgundy"
          >
            + New panel
          </button>
        </div>

        {error && (
          <div className="mt-4 p-3 bg-axis-pink-soft border border-axis-magenta rounded text-xs text-axis-burgundy">
            {error}
          </div>
        )}

        {editingId && (
          <div className="mt-6 bg-axis-canvas border-2 border-axis-magenta rounded-card p-5 shadow-card">
            <h2 className="text-sm font-display text-axis-ink">
              {editingId === "__new__" ? "New panel" : "Edit panel"}
            </h2>
            <div className="mt-3 grid md:grid-cols-2 gap-3">
              <label className="text-xs text-axis-ink-soft">
                Panel name
                <input
                  value={draft.name}
                  onChange={(e) =>
                    setDraft({ ...draft, name: e.target.value })
                  }
                  className="mt-1 w-full border border-axis-divider rounded px-2 py-1.5 text-sm text-axis-ink"
                  placeholder="Central Zone BDM Panel"
                />
              </label>
              <label className="text-xs text-axis-ink-soft">
                Location
                <input
                  value={draft.location}
                  onChange={(e) =>
                    setDraft({ ...draft, location: e.target.value })
                  }
                  className="mt-1 w-full border border-axis-divider rounded px-2 py-1.5 text-sm text-axis-ink"
                  placeholder="Bhopal"
                />
              </label>
              <label className="text-xs text-axis-ink-soft md:col-span-2">
                Role scopes (comma-separated; use * for any JD)
                <input
                  value={draft.role_scopes}
                  onChange={(e) =>
                    setDraft({ ...draft, role_scopes: e.target.value })
                  }
                  className="mt-1 w-full border border-axis-divider rounded px-2 py-1.5 text-sm text-axis-ink"
                  placeholder="Retail Banking/DM, Retail Banking"
                />
              </label>
              <label className="text-xs text-axis-ink-soft">
                Default panel size
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={draft.default_size}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      default_size: Number(e.target.value) || 1,
                    })
                  }
                  className="mt-1 w-full border border-axis-divider rounded px-2 py-1.5 text-sm text-axis-ink"
                />
              </label>
              <label className="text-xs text-axis-ink-soft flex items-center gap-2 mt-5">
                <input
                  type="checkbox"
                  checked={draft.active}
                  onChange={(e) =>
                    setDraft({ ...draft, active: e.target.checked })
                  }
                />
                Active (surfaced to Business Partner on approval)
              </label>
            </div>

            <div className="mt-5">
              <div className="flex items-center justify-between">
                <p className="text-xs uppercase tracking-wider text-axis-muted font-semibold">
                  Members
                </p>
                <button
                  onClick={addMember}
                  className="text-xs text-axis-magenta hover:underline"
                >
                  + Add member
                </button>
              </div>
              <div className="mt-2 space-y-2">
                {draft.members.map((m, idx) => (
                  <div
                    key={idx}
                    className="grid md:grid-cols-[1fr_1fr_140px_auto] gap-2 items-center"
                  >
                    <input
                      value={m.name}
                      onChange={(e) =>
                        updateMember(idx, { name: e.target.value })
                      }
                      placeholder="Full name"
                      className="border border-axis-divider rounded px-2 py-1.5 text-sm text-axis-ink"
                    />
                    <input
                      value={m.user_id}
                      onChange={(e) =>
                        updateMember(idx, { user_id: e.target.value })
                      }
                      placeholder="email or id"
                      className="border border-axis-divider rounded px-2 py-1.5 text-sm text-axis-ink"
                    />
                    <select
                      value={m.role}
                      onChange={(e) =>
                        updateMember(idx, {
                          role: e.target.value as PanelMember["role"],
                        })
                      }
                      className="border border-axis-divider rounded px-2 py-1.5 text-sm text-axis-ink"
                    >
                      <option value="hiring_manager">Hiring manager</option>
                      <option value="interviewer">Interviewer</option>
                      <option value="hr_partner">Business Partner</option>
                    </select>
                    <button
                      onClick={() => removeMember(idx)}
                      disabled={draft.members.length === 1}
                      className="text-xs text-axis-burgundy hover:underline disabled:opacity-30"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-5 flex items-center gap-3">
              <button
                onClick={save}
                disabled={saving}
                className="px-4 py-2 text-xs font-semibold rounded bg-axis-magenta text-white hover:bg-axis-burgundy disabled:opacity-40"
              >
                {saving
                  ? "Saving…"
                  : editingId === "__new__"
                  ? "Create panel"
                  : "Save changes"}
              </button>
              <button
                onClick={cancel}
                className="px-3 py-2 text-xs rounded border border-axis-divider text-axis-ink-soft hover:bg-axis-surface"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="mt-6 space-y-3">
          {panels === null && !error && (
            <p className="text-sm text-axis-muted">Loading panels…</p>
          )}
          {panels && panels.length === 0 && (
            <p className="text-sm text-axis-muted">
              No panels configured yet. Click <strong>+ New panel</strong> to
              add one.
            </p>
          )}
          {panels?.map((p) => (
            <div
              key={p.id}
              className="bg-axis-canvas border border-axis-divider rounded-card p-4 shadow-card"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-semibold text-axis-ink">
                      {p.name}
                    </h3>
                    {!p.active && (
                      <span className="text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded bg-axis-surface text-axis-muted">
                        Inactive
                      </span>
                    )}
                    {p.location && (
                      <span className="text-[10px] text-axis-muted">
                        {p.location}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-axis-ink-soft mt-1">
                    {p.members.map((m) => `${m.name} (${m.role})`).join(" · ")}
                  </p>
                  {p.role_scopes.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {p.role_scopes.map((s) => (
                        <span
                          key={s}
                          className="text-[10px] px-1.5 py-0.5 rounded bg-axis-cream text-axis-ink-soft"
                        >
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <button
                    onClick={() => startEdit(p)}
                    className="text-xs text-axis-magenta hover:underline"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => remove(p)}
                    className="text-xs text-axis-burgundy hover:underline"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </main>
      <Footer />
    </div>
  );
}
