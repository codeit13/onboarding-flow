import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { Application, Job } from "@/lib/api";

// ---- Hoisted fixtures -----------------------------------------------------

const { mockListApplicationsForCandidate, mockExternalApplications, job, internalApp, externalApp, duplicateApp } =
  vi.hoisted(() => {
    const _job = {
      id: "job-590321",
      job_id: "590321",
      title: "Business Development Manager",
      function: "Retail Banking",
      band: "AM",
      tags: ["Sales"],
      location: "Bhopal",
      required_skills: ["sales"],
      nice_to_have_skills: [],
      description: "",
      hr_partner_id: "hr1@axisbank.test",
      panel: [],
      shortlist_threshold: 75,
    } as Job;

    function makeApp(overrides: Partial<Application> = {}): Application {
      return {
        id: "app-001",
        candidate_id: "cand-001",
        job_id: "job-590321",
        match_percent: 85,
        match_rationale: "Good match",
        matched_skills: ["sales"],
        missing_skills: [],
        stage: "applied",
        agent_status: "running",
        next_action: "",
        pending_blocking_items: [],
        proposed_r1_slots: [],
        selected_r1_slot_index: null,
        proposed_r2_slots: [],
        selected_r2_slot_index: null,
        r1_started: false,
        created_at: "2026-04-08T10:00:00Z",
        updated_at: "2026-04-08T11:00:00Z",
        events: [],
        interviews: [],
        ...overrides,
      } as Application;
    }

    return {
      mockListApplicationsForCandidate: vi.fn(),
      mockExternalApplications: vi.fn(),
      job: _job,
      internalApp: makeApp({ id: "app-int-001", candidate_kind: "internal" as any }),
      externalApp: makeApp({ id: "app-ext-002", stage: "screened", candidate_kind: "external" as any }),
      duplicateApp: makeApp({ id: "app-int-001", candidate_kind: "external" as any }),
    };
  });

// ---- Mocks ----------------------------------------------------------------

vi.mock("@/lib/api", () => ({
  api: {
    listApplicationsForCandidate: (...args: any[]) =>
      mockListApplicationsForCandidate(...args),
    externalApplications: (...args: any[]) =>
      mockExternalApplications(...args),
  },
}));

// useAutoRefresh mock that actually calls the loader so we can verify
// dual-fetch and dedup logic inside the component's loader callback.
vi.mock("@/lib/hooks/useAutoRefresh", () => ({
  useAutoRefresh: (loader: () => Promise<any>) => {
    const { useState, useEffect } = require("react");
    const [state, setState] = useState<{
      data: any;
      loading: boolean;
      error: string | null;
    }>({ data: null, loading: true, error: null });

    useEffect(() => {
      let cancelled = false;
      loader().then(
        (d: any) => {
          if (!cancelled) setState({ data: d, loading: false, error: null });
        },
        (e: any) => {
          if (!cancelled)
            setState({ data: null, loading: false, error: e?.message ?? String(e) });
        },
      );
      return () => {
        cancelled = true;
      };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    return { ...state, refresh: vi.fn() };
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/thrive",
  useSearchParams: () => new URLSearchParams(),
}));

// ---- Import under test AFTER mocks ----------------------------------------

import { MyApplicationsCard } from "@/components/thrive/MyApplicationsCard";

// ---- Tests -----------------------------------------------------------------

describe("MyApplicationsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches both internal and external applications", async () => {
    mockListApplicationsForCandidate.mockResolvedValue([internalApp]);
    mockExternalApplications.mockResolvedValue([externalApp]);

    render(
      <MyApplicationsCard
        candidateId="EMP10234"
        candidateEmail="rohan@axisbank.test"
        jobsById={{ [job.id]: job }}
      />,
    );

    await waitFor(() => {
      expect(mockListApplicationsForCandidate).toHaveBeenCalledWith("EMP10234");
      expect(mockExternalApplications).toHaveBeenCalledWith("rohan@axisbank.test");
    });

    // Both rows should render.
    await waitFor(() => {
      expect(screen.getAllByText("Business Development Manager").length).toBe(2);
    });
  });

  it("deduplicates applications by app.id", async () => {
    // Internal and duplicate share the same id "app-int-001".
    mockListApplicationsForCandidate.mockResolvedValue([internalApp]);
    mockExternalApplications.mockResolvedValue([duplicateApp, externalApp]);

    render(
      <MyApplicationsCard
        candidateId="EMP10234"
        candidateEmail="rohan@axisbank.test"
        jobsById={{ [job.id]: job }}
      />,
    );

    // After dedup we should have exactly 2 unique apps (app-int-001 + app-ext-002).
    await waitFor(() => {
      expect(screen.getAllByText("Business Development Manager").length).toBe(2);
    });
  });

  it("shows application rows with stage chips", async () => {
    mockListApplicationsForCandidate.mockResolvedValue([internalApp]);
    mockExternalApplications.mockResolvedValue([externalApp]);

    render(
      <MyApplicationsCard
        candidateId="EMP10234"
        candidateEmail="rohan@axisbank.test"
        jobsById={{ [job.id]: job }}
      />,
    );

    await waitFor(() => {
      // internalApp stage = "applied" -> label "Applied"
      expect(screen.getByText("Applied")).toBeInTheDocument();
      // externalApp stage = "screened" -> label "Screened"
      expect(screen.getByText("Screened")).toBeInTheDocument();
    });
  });
});
