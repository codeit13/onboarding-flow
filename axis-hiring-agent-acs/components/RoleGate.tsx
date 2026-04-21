"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  PERSONA_HOME,
  PERSONA_LABEL,
  PersonaRole,
  usePersona,
} from "@/lib/persona";

/**
 * Client-side role gate.
 *
 * The Axis Bank console multiplexes three personas — employee, HR partner,
 * interview panellist — onto one URL space. Each persona has a distinct
 * mental model of "what am I looking at" so we MUST not let an employee
 * stumble onto the HR funnel or a panellist into the candidate directory.
 *
 * The gate accepts an array of allowed roles. If the active persona is in
 * the list, children render normally. Otherwise we render a friendly
 * interstitial with a CTA back to the persona's home, AND we kick off a
 * router.replace() so the URL doesn't lie about where the user is.
 *
 * Persona is read from localStorage in an effect (see lib/persona.ts), so
 * the very first paint always sees the static default. We hold the gate's
 * children back for one tick to avoid a flash of either unauthorised content
 * OR an unwarranted "wrong persona" interstitial.
 */
export function RoleGate({
  allow,
  children,
}: {
  allow: PersonaRole[];
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [persona] = usePersona();
  const [hydrated, setHydrated] = useState(false);

  // Wait one tick after mount so usePersona's localStorage effect has a
  // chance to populate the real role before we make a decision.
  useEffect(() => {
    setHydrated(true);
  }, []);

  const allowed = allow.includes(persona.role);

  useEffect(() => {
    if (!hydrated) return;
    if (allowed) return;
    router.replace(PERSONA_HOME[persona.role]);
  }, [hydrated, allowed, persona.role, router]);

  if (!hydrated) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center text-sm text-axis-muted">
        Loading…
      </div>
    );
  }

  if (!allowed) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center px-6">
        <div className="max-w-md text-center bg-axis-canvas border border-axis-divider rounded-card shadow-card p-8">
          <p className="text-[10px] uppercase tracking-wider text-axis-magenta font-semibold">
            Wrong persona
          </p>
          <h2 className="text-xl font-display text-axis-ink mt-2">
            This area isn't part of the {PERSONA_LABEL[persona.role]} workspace
          </h2>
          <p className="text-sm text-axis-muted mt-3">
            Switch persona in the dark bar above, or jump to the home that
            matches your current role.
          </p>
          <Link
            href={PERSONA_HOME[persona.role]}
            className="inline-block mt-5 px-4 py-2 rounded bg-axis-magenta text-white text-xs font-semibold hover:bg-axis-burgundy"
          >
            Take me to {PERSONA_LABEL[persona.role]}
          </Link>
          <p className="mt-4 text-[11px] text-axis-muted-light">
            Allowed roles for this page:{" "}
            {allow.map((r) => PERSONA_LABEL[r]).join(", ")}
          </p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
