"use client";

import { useEffect, useState } from "react";

export type PersonaRole = "employee" | "hr_partner" | "panel" | "offer_team" | "engagement_manager";

export interface PersonaState {
  role: PersonaRole;
  // For employee: candidate id / employee id. For HR partner: user_id of the partner.
  // For panel: user_id of the panellist.
  identity: string;
  // Display name shown in the top bar.
  displayName: string;
}

const DEFAULT_PERSONA: PersonaState = {
  role: "employee",
  identity: "cand-001",
  displayName: "Rohan Verma",
};

const KEY = "axis-hiring-persona";

export function readPersona(): PersonaState {
  if (typeof window === "undefined") return DEFAULT_PERSONA;
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_PERSONA;
    return JSON.parse(raw) as PersonaState;
  } catch {
    return DEFAULT_PERSONA;
  }
}

export function writePersona(p: PersonaState): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(KEY, JSON.stringify(p));
  window.dispatchEvent(new CustomEvent("persona:change", { detail: p }));
}

export function usePersona(): [PersonaState, (p: PersonaState) => void] {
  const [persona, setPersona] = useState<PersonaState>(DEFAULT_PERSONA);

  useEffect(() => {
    setPersona(readPersona());
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<PersonaState>).detail;
      if (detail) setPersona(detail);
    };
    window.addEventListener("persona:change", handler);
    return () => window.removeEventListener("persona:change", handler);
  }, []);

  const update = (p: PersonaState) => {
    writePersona(p);
    setPersona(p);
  };

  return [persona, update];
}

export const PERSONA_LABEL: Record<PersonaRole, string> = {
  employee: "Candidate (Thrive)",
  // Renamed from "HR Partner" → "Business Partner" per stakeholder
  // feedback. The persona ROLE id (`hr_partner`) and route path (`/hr/`)
  // stay unchanged so the API contract is unaffected; only the
  // user-visible label moved.
  hr_partner: "Business Partner",
  panel: "Interview Panel",
  offer_team: "Offer Discussion Team",
  engagement_manager: "Onboarding Team",
};

export const PERSONA_HOME: Record<PersonaRole, string> = {
  employee: "/thrive",
  hr_partner: "/hr",
  panel: "/panel",
  offer_team: "/offer-team",
  engagement_manager: "/onboarding",
};
