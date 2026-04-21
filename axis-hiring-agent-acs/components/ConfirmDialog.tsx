"use client";

/**
 * Reusable confirmation dialog.
 *
 * Why this exists
 * ---------------
 * "Selection ≠ commitment." A single click should never trigger a
 * destructive or externally-visible side effect (booking a Teams meeting,
 * sending an email, releasing a blocking gate, submitting an interview
 * vote) without the user explicitly confirming the action in a second
 * step. This component is the canonical confirm primitive — every
 * destructive action across Thrive routes through it.
 *
 * UX guidelines (from Material / Apple HIG / GOV.UK design system)
 * ----------------------------------------------------------------
 *  • Title verb-led ("Confirm Round 1 slot booking")
 *  • Message restates the consequence in concrete terms
 *  • Primary CTA verb-led ("Confirm and book") — never a generic "OK"
 *  • Secondary CTA reads as a true escape hatch ("Cancel")
 *  • Buttons right-aligned, primary on the right (Material convention)
 *  • Pressing Esc dismisses; clicking the backdrop dismisses
 *  • Focus trapped on the primary CTA when the dialog opens
 *  • The trigger button outside the dialog stays disabled while the
 *    confirm action is in flight to prevent double-fire
 *
 * Usage
 * -----
 * const [open, setOpen] = useState(false);
 * <button onClick={() => setOpen(true)}>Book slot</button>
 * <ConfirmDialog
 *   open={open}
 *   title="Confirm Round 1 slot booking"
 *   message="The agent will create a real Teams meeting for Tue 7 Apr 09:00 IST and email Rohan + Meera."
 *   confirmLabel="Confirm and book"
 *   onConfirm={async () => { await api.confirmSlot(...); setOpen(false); }}
 *   onCancel={() => setOpen(false)}
 * />
 */

import { useEffect, useRef, useState } from "react";

export type ConfirmTone = "primary" | "danger";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** Plain text or JSX. Should restate the concrete consequence of confirming. */
  message: React.ReactNode;
  /** Optional bullet list shown below the message — use for "what will happen" steps. */
  consequences?: React.ReactNode[];
  confirmLabel: string;
  cancelLabel?: string;
  tone?: ConfirmTone;
  /** Async onConfirm — dialog stays open and the primary CTA shows a spinner until it resolves. */
  onConfirm: () => Promise<void> | void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  consequences,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "primary",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  // Focus the primary CTA whenever the dialog opens.
  useEffect(() => {
    if (open) {
      setError(null);
      setBusy(false);
      // Defer one tick so the element is mounted.
      const id = setTimeout(() => confirmRef.current?.focus(), 30);
      return () => clearTimeout(id);
    }
  }, [open]);

  // Esc to dismiss.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, busy, onCancel]);

  if (!open) return null;

  const handleConfirm = async () => {
    setError(null);
    setBusy(true);
    try {
      await onConfirm();
    } catch (e: any) {
      setError(e?.message || String(e));
      setBusy(false);
    }
  };

  const primaryClass =
    tone === "danger"
      ? "bg-axis-burgundy hover:bg-axis-burgundy/90"
      : "bg-axis-magenta hover:bg-axis-burgundy";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm px-4"
      onMouseDown={(e) => {
        // Click on backdrop (not inner panel) dismisses, unless busy.
        if (e.target === e.currentTarget && !busy) onCancel();
      }}
    >
      <div className="bg-axis-canvas rounded-card shadow-2xl border border-axis-divider w-full max-w-md overflow-hidden">
        <div className="px-6 pt-5 pb-3">
          <h2
            id="confirm-dialog-title"
            className="text-base font-semibold text-axis-ink"
          >
            {title}
          </h2>
          <div className="mt-2 text-sm text-axis-ink-soft leading-relaxed">
            {message}
          </div>
          {consequences && consequences.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-axis-muted list-disc list-inside">
              {consequences.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          )}
          {error && (
            <div className="mt-3 p-2 rounded bg-axis-pink-soft border border-axis-magenta text-xs text-axis-burgundy">
              {error}
            </div>
          )}
        </div>
        <div className="px-6 py-3 bg-axis-surface flex items-center justify-end gap-2 border-t border-axis-divider">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-4 py-2 text-sm font-medium rounded text-axis-ink-soft hover:bg-axis-canvas border border-transparent disabled:opacity-40"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={handleConfirm}
            disabled={busy}
            className={`px-4 py-2 text-sm font-semibold rounded text-white shadow-card transition disabled:opacity-60 disabled:cursor-wait ${primaryClass}`}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
