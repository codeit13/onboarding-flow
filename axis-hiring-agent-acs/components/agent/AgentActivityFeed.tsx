"use client";

import { useMemo, useState } from "react";
import type { ActivityItem, ActivityKind } from "@/lib/api";

/**
 * Live "What the agent is doing" feed.
 *
 * Renders the unified ActivityItem stream returned by `/activity`. Each row
 * shows the timestamp, an icon-style kind badge, the title, and (if present)
 * the detail line. The feed is presentation-only — the parent owns polling.
 *
 * Used by every persona view (Thrive employee status, HR kanban side panel,
 * HR application detail page, Panel feedback context). One canonical
 * component → one canonical look.
 *
 * UX (2026-04-07 feedback): the activity stream can balloon to dozens of
 * rows (every email, calendar check, checklist tick) and visually drowns
 * the page. Default behaviour is now COLLAPSED — we render a one-line
 * "What the agent is doing — N updates" summary card that the user can
 * click to expand. Pass ``defaultCollapsed={false}`` only on dedicated
 * activity-only views (e.g. the Activity tab on the HR app page).
 */
export function AgentActivityFeed({
  items,
  emptyLabel = "Agent hasn't logged anything yet.",
  maxHeight = "max-h-[480px]",
  defaultCollapsed = true,
  collapsedTitle = "What the agent is doing — live",
}: {
  items: ActivityItem[];
  emptyLabel?: string;
  maxHeight?: string;
  defaultCollapsed?: boolean;
  collapsedTitle?: string;
}) {
  const [open, setOpen] = useState(!defaultCollapsed);
  // Most recent first — backend already sorts ascending, so reverse here.
  // We also clean every row's title + detail so the feed never leaks raw
  // HTML, MIME headers, or bounce gibberish into the customer-facing UI.
  const sorted = useMemo(
    () =>
      [...items].reverse().map((it) => ({
        ...it,
        title: prettifyTitle(it.title),
        detail: prettifyDetail(it.detail),
      })),
    [items],
  );

  // Header bar — always visible. Click to expand/collapse the feed.
  // Even when there are zero items we still render the header so the
  // section has a stable footprint and the empty-state copy isn't a
  // surprise full-width block.
  const header = (
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      className="w-full flex items-center justify-between gap-3 text-left"
      aria-expanded={open}
    >
      <span className="flex items-center gap-2 min-w-0">
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            sorted.length > 0 ? "bg-axis-magenta animate-pulse" : "bg-axis-divider"
          }`}
          aria-hidden="true"
        />
        <span className="text-sm font-semibold text-axis-ink truncate">
          {collapsedTitle}
        </span>
        <span className="text-[10px] uppercase tracking-wider text-axis-muted">
          {sorted.length} update{sorted.length === 1 ? "" : "s"}
        </span>
      </span>
      <span className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold shrink-0">
        {open ? "Hide ▲" : "Show ▼"}
      </span>
    </button>
  );

  if (sorted.length === 0) {
    return (
      <div>
        {header}
        {open && (
          <div className="mt-2 text-xs text-axis-muted-light italic px-1 py-4">
            {emptyLabel}
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      {header}
      {open && (
        <ol className={`mt-3 space-y-2 overflow-y-auto ${maxHeight} pr-1`}>
          {sorted.map((it) => (
            <li
              key={it.id}
              className="flex gap-3 text-xs border-b border-axis-divider pb-2 last:border-b-0"
            >
              <span className="text-axis-muted-light w-28 shrink-0 tabular-nums">
                {formatTimestamp(it.at)}
              </span>
              <KindBadge kind={it.kind} />
              <div className="flex-1 min-w-0">
                <p className="text-axis-ink font-medium truncate">{it.title}</p>
                {it.detail && (
                  <p className="text-axis-ink-soft mt-0.5 line-clamp-2">{it.detail}</p>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const KIND_LABEL: Record<ActivityKind, string> = {
  email_out: "EMAIL→",
  email_in: "EMAIL←",
  calendar: "MEET",
  notification: "NOTE",
  agent: "AGENT",
  checklist: "CHECK",
};

const KIND_COLOUR: Record<ActivityKind, string> = {
  email_out: "bg-axis-cream text-axis-ink",
  email_in: "bg-axis-pink-soft text-axis-burgundy",
  calendar: "bg-axis-magenta/10 text-axis-magenta",
  notification: "bg-axis-surface text-axis-ink-soft",
  agent: "bg-axis-burgundy/10 text-axis-burgundy",
  checklist: "bg-axis-cream-border/30 text-axis-ink-soft",
};

function KindBadge({ kind }: { kind: ActivityKind }) {
  return (
    <span
      className={`text-[9px] font-semibold tracking-wider px-1.5 py-0.5 rounded h-fit shrink-0 ${KIND_COLOUR[kind]}`}
    >
      {KIND_LABEL[kind]}
    </span>
  );
}

/**
 * Strip HTML tags, decode common entities, collapse whitespace.
 * Used to scrub email-bounce bodies and other raw payloads before they
 * land in the customer-facing activity feed.
 */
function stripHtml(input: string | undefined | null): string {
  if (!input) return "";
  let s = String(input);
  // Drop <style>...</style> and <script>...</script> blocks entirely.
  s = s.replace(/<style[\s\S]*?<\/style>/gi, " ");
  s = s.replace(/<script[\s\S]*?<\/script>/gi, " ");
  // Drop HTML comments and CDATA-ish blocks.
  s = s.replace(/<!--[\s\S]*?-->/g, " ");
  // Drop any remaining tags.
  s = s.replace(/<[^>]+>/g, " ");
  // Decode the handful of entities that show up in Outlook bounces.
  const entities: Record<string, string> = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
    "&hellip;": "…",
    "&mdash;": "—",
    "&ndash;": "–",
  };
  s = s.replace(
    /&(nbsp|amp|lt|gt|quot|#39|apos|hellip|mdash|ndash);/g,
    (m) => entities[m] ?? " ",
  );
  // Numeric entities: &#1234;
  s = s.replace(/&#(\d+);/g, (_, n) => {
    try {
      return String.fromCharCode(parseInt(n, 10));
    } catch {
      return " ";
    }
  });
  // Drop residual MIME / Content-Type / boundary preambles that sneak in.
  s = s.replace(/Content-Type:[^\n]*/gi, " ");
  s = s.replace(/charset=[^\s;]+/gi, " ");
  s = s.replace(/face="[^"]*"/gi, " ");
  s = s.replace(/size="\d+"/gi, " ");
  s = s.replace(/color="[^"]*"/gi, " ");
  // Collapse whitespace.
  s = s.replace(/\s+/g, " ").trim();
  return s;
}

/**
 * Title cleaner. Replaces hostile prefixes with friendly ones, then
 * strips HTML and trims to a reasonable length.
 */
function prettifyTitle(raw: string): string {
  const cleaned = stripHtml(raw);
  if (!cleaned) return "Agent activity";
  // Outlook delivery failure notices → friendlier label.
  const undelivMatch = cleaned.match(/^Undeliverable:\s*(.+)$/i);
  if (undelivMatch) {
    return `Email bounced — ${undelivMatch[1].trim()}`;
  }
  // Truncate runaway titles.
  return cleaned.length > 180 ? cleaned.slice(0, 177) + "…" : cleaned;
}

/**
 * Detail cleaner. Strips HTML, drops common bounce boilerplate, and
 * keeps the result short and readable.
 */
function prettifyDetail(raw: string | undefined): string {
  const cleaned = stripHtml(raw);
  if (!cleaned) return "";
  // Common Outlook bounce phrases → one short sentence.
  if (
    /Delivery has failed to these recipients|could not be delivered|recipient'?s mailbox is full/i.test(
      cleaned,
    )
  ) {
    return "Mail server reported a delivery failure for this recipient.";
  }
  return cleaned.length > 220 ? cleaned.slice(0, 217) + "…" : cleaned;
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
