"use client";

import type { AgentStatus } from "@/lib/api";

const STATUS_LABEL: Record<AgentStatus, string> = {
  idle: "Idle",
  running: "Running",
  waiting_hr: "Waiting on Business Partner",
  waiting_candidate: "Waiting on candidate",
  waiting_panel: "Waiting on panel",
  waiting_offer_team: "Waiting on Offer Team",
  waiting_candidate_acceptance: "Awaiting offer acceptance",
  engaging: "Engagement in progress",
  done: "Done",
};

const STATUS_COLOUR: Record<AgentStatus, string> = {
  idle: "bg-axis-surface text-axis-muted border-axis-divider",
  running: "bg-axis-magenta/10 text-axis-magenta border-axis-magenta animate-pulse",
  waiting_hr: "bg-axis-pink-soft text-axis-burgundy border-axis-magenta",
  waiting_candidate: "bg-axis-cream text-axis-ink border-axis-cream-border",
  waiting_panel: "bg-axis-cream text-axis-ink border-axis-cream-border",
  waiting_offer_team: "bg-axis-pink-soft text-axis-burgundy border-axis-magenta",
  waiting_candidate_acceptance: "bg-emerald-50 text-emerald-700 border-emerald-300",
  engaging: "bg-axis-magenta/10 text-axis-magenta border-axis-magenta",
  done: "bg-axis-surface text-axis-muted border-axis-divider",
};

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] font-semibold tracking-wider uppercase px-2 py-1 rounded border ${STATUS_COLOUR[status]}`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${
          status === "running" ? "bg-axis-magenta" : "bg-current opacity-60"
        }`}
      />
      Agent · {STATUS_LABEL[status]}
    </span>
  );
}
