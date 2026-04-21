"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type Candidate, type HrPartner, type PanelMemberListed } from "@/lib/api";
import { PERSONA_HOME, PERSONA_LABEL, PersonaRole, usePersona } from "@/lib/persona";
import { ConfirmDialog } from "@/components/ConfirmDialog";

export function PersonaSwitcher() {
  const router = useRouter();
  const [persona, setPersona] = usePersona();
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [hrPartners, setHrPartners] = useState<HrPartner[]>([]);
  const [panellists, setPanellists] = useState<PanelMemberListed[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [pendingReset, setPendingReset] = useState(false);
  const [pendingWipe, setPendingWipe] = useState(false);
  const [pendingOfferSeed, setPendingOfferSeed] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [cands, hrs, panels] = await Promise.all([
          api.listCandidates(),
          api.hrPartners(),
          api.panelMembers(),
        ]);
        setCandidates(cands);
        setHrPartners(hrs);
        setPanellists(panels);
        setLoaded(true);
      } catch (e) {
        console.error("PersonaSwitcher failed to load directories", e);
        setLoaded(true);
      }
    })();
  }, []);

  const onRoleChange = (role: PersonaRole) => {
    let identity = persona.identity;
    let displayName = persona.displayName;

    if (role === "employee" && candidates.length) {
      identity = candidates[0].id;
      displayName = candidates[0].name;
    } else if (role === "hr_partner" && hrPartners.length) {
      identity = hrPartners[0].user_id;
      displayName = hrPartners[0].name;
    } else if (role === "panel" && panellists.length) {
      identity = panellists[0].user_id;
      displayName = panellists[0].name;
    } else if (role === "offer_team") {
      // The Offer Discussion Team is a small fixed back-office cell —
      // no roster API yet, so seed a single demo identity here.
      identity = "offer-team-lead";
      displayName = "Neha Iyer · Offer Discussion Lead";
    } else if (role === "engagement_manager") {
      identity = "onboarding-lead";
      displayName = "Meera Sharma · Onboarding Lead";
    }
    const next = { role, identity, displayName };
    setPersona(next);
    router.push(PERSONA_HOME[role]);
  };

  const onIdentityChange = (identity: string) => {
    let displayName = identity;
    if (persona.role === "employee") {
      const c = candidates.find((x) => x.id === identity);
      if (c) displayName = c.name;
    } else if (persona.role === "hr_partner") {
      const h = hrPartners.find((x) => x.user_id === identity);
      if (h) displayName = h.name;
    } else {
      const p = panellists.find((x) => x.user_id === identity);
      if (p) displayName = p.name;
    }
    setPersona({ ...persona, identity, displayName });
  };

  const identityOptions = () => {
    if (persona.role === "employee") {
      return candidates.map((c) => ({
        value: c.id,
        label: `${c.name} · ${c.current_role}`,
      }));
    }
    if (persona.role === "hr_partner") {
      return hrPartners.map((h) => ({
        value: h.user_id,
        label: `${h.name} · ${h.jobs.length} req`,
      }));
    }
    if (persona.role === "offer_team") {
      return [
        { value: "offer-team-lead", label: "Neha Iyer · Offer Discussion Lead" },
      ];
    }
    if (persona.role === "engagement_manager") {
      return [
        { value: "onboarding-lead", label: "Meera Sharma · Onboarding Lead" },
      ];
    }
    return panellists.map((p) => ({
      value: p.user_id,
      label: `${p.name} · ${p.role}`,
    }));
  };

  return (
    <div className="relative z-50 bg-axis-ink text-white text-xs px-4 py-2 flex items-center gap-4 flex-wrap shadow-sm">
      <span className="font-semibold tracking-wide uppercase text-axis-muted-light">
        Demo persona
      </span>

      <div className="flex items-center gap-1">
        {(Object.keys(PERSONA_LABEL) as PersonaRole[]).map((role) => (
          <button
            key={role}
            onClick={() => onRoleChange(role)}
            className={`px-3 py-1 rounded transition ${
              persona.role === role
                ? "bg-axis-magenta text-white"
                : "bg-transparent text-axis-muted-light hover:bg-white/10"
            }`}
          >
            {PERSONA_LABEL[role]}
          </button>
        ))}
      </div>

      {loaded && (
        <>
          <span className="text-axis-muted-light">·</span>
          <label className="flex items-center gap-2">
            <span className="text-axis-muted-light">logged in as</span>
            <select
              value={persona.identity}
              onChange={(e) => onIdentityChange(e.target.value)}
              className="bg-axis-ink border border-white/20 rounded px-2 py-1 text-white"
            >
              {identityOptions().map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      <div className="flex-1" />

      <button
        onClick={() => setPendingWipe(true)}
        className="px-3 py-1 text-axis-muted-light hover:text-white"
        title="Wipe all applications (keeps jobs + candidates, creates NO pre-seeded applications — the kanban will be empty so you can drive one end-to-end yourself)"
      >
        Wipe only
      </button>

      <button
        onClick={() => setPendingOfferSeed(true)}
        className="px-3 py-1 text-axis-muted-light hover:text-white"
        title="Wipe everything AND pre-seed ONE application (Priya Nair) parked at Offer — waiting for candidate to accept. Use this to demo the post-offer onboarding chat + WhatsApp warm-keep flow without driving a candidate through the whole funnel first."
      >
        Wipe + offer-ready
      </button>

      <button
        onClick={() => setPendingReset(true)}
        className="px-3 py-1 text-axis-muted-light hover:text-white"
        title="Reseed demo data (resets everything, seeds 5 applications across all stages)"
      >
        Reset & seed
      </button>

      <ConfirmDialog
        open={pendingReset}
        title="Reset and reseed all demo data?"
        message={
          <>
            This wipes every application, interview, transcript, panel vote
            and audit-log entry currently in memory and re-seeds the demo
            with 5 fresh applications (one parked at every funnel stage).
            Use this only between demo runs.
          </>
        }
        consequences={[
          "All in-progress applications across every persona are deleted.",
          "All Microsoft Graph events created so far are NOT cancelled — run scripts/wipe_tenant_calendars.py if you need a clean tenant.",
          "You'll be returned to the home page after the reset completes.",
        ]}
        confirmLabel="Wipe and reseed"
        tone="danger"
        onConfirm={async () => {
          await api.demoSeedFlow();
          setPendingReset(false);
          router.refresh();
        }}
        onCancel={() => setPendingReset(false)}
      />

      <ConfirmDialog
        open={pendingWipe}
        title="Wipe ALL applications?"
        message={
          <>
            This deletes every application, interview, transcript, panel vote
            and audit log entry currently in memory, but keeps the 8 seeded
            jobs, the candidate directory, and the panel roster intact.
            <br />
            <br />
            Use this when you want to drive <strong>one clean run</strong> as
            a candidate end-to-end without any pre-seeded applications
            cluttering the kanban.
          </>
        }
        consequences={[
          "All 5 pre-seeded applications (Priya, Rohan, Ananya, Karthik, Vikram) are deleted.",
          "Jobs, candidates and panel rosters are preserved — you can immediately apply as any candidate.",
          "Microsoft Graph events previously created are NOT cancelled — run scripts/wipe_tenant_calendars.py if you need a clean tenant.",
          "You'll be returned to the home page after the wipe completes.",
        ]}
        confirmLabel="Wipe applications"
        tone="danger"
        onConfirm={async () => {
          await api.demoReset();
          setPendingWipe(false);
          router.push("/");
          router.refresh();
        }}
        onCancel={() => setPendingWipe(false)}
      />

      <ConfirmDialog
        open={pendingOfferSeed}
        title="Wipe + seed one offer-ready application?"
        message={
          <>
            This wipes every application in memory (same as Wipe only),
            then pre-seeds <strong>one</strong> application for{" "}
            <strong>Priya Nair</strong> (Sr Branch Manager Flagship, Pune
            West) all the way through to the <strong>Offer</strong> stage —
            final offer rolled out, waiting for the candidate to click
            Accept / Decline.
            <br />
            <br />
            Use this to demo the post-offer onboarding chat and WhatsApp
            warm-keep engagement flow without first driving a candidate
            through screening, R1, and R2.
          </>
        }
        consequences={[
          "All other applications are deleted.",
          "Rohan Verma / Rohan Desai is NOT touched as a candidate — she's reserved for the screening-to-L1 demo path.",
          "A real Teams R2 meeting was created for Priya as part of the drive-through — previous Graph events are NOT cancelled.",
          "After completion, log in as Priya Nair and open the application to see the offer / onboarding chat.",
        ]}
        confirmLabel="Wipe and seed offer-ready"
        tone="danger"
        onConfirm={async () => {
          const r = await api.demoWipePlusOffer();
          setPendingOfferSeed(false);
          // Send the operator to the candidate status page of the seeded
          // application so they can immediately drive the Accept flow.
          router.push(`/thrive/status/${r.application_id}`);
          router.refresh();
        }}
        onCancel={() => setPendingOfferSeed(false)}
      />
    </div>
  );
}
