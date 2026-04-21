import type { FunnelStage } from "@/lib/api";

export const STAGE_ORDER: FunnelStage[] = [
  "applied",
  "screened",
  "r1_scheduled",
  "r1_done",
  "r2_scheduled",
  "offer_negotiation",
  "offer",
  "offer_accepted",
  "pre_joining",
  "joined",
];

export const STAGE_LABEL: Record<FunnelStage, string> = {
  applied: "Applied",
  screened: "Screened",
  r1_scheduled: "R1 Scheduled",
  r1_done: "R1 Done",
  r2_scheduled: "R2 Scheduled",
  offer_negotiation: "Offer Negotiation",
  offer: "Offer",
  offer_accepted: "Offer Accepted",
  pre_joining: "Pre-Joining",
  joined: "Joined",
  offer_declined: "Offer Declined",
  rejected: "Rejected",
};

// HR's kanban only shows columns where HR actually has work to do or
// observable signal — pre-R1 stages are hidden because the candidate is
// still completing their part of the application (slot pick + R1 interview).
export const STAGE_KANBAN: FunnelStage[] = [
  "screened",
  "r1_scheduled",
  "r1_done",
  "r2_scheduled",
  "offer_negotiation",
  "offer",
  "offer_accepted",
  "pre_joining",
  "joined",
  "rejected",
];
