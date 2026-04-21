import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { Application, Candidate, Job } from "@/lib/api";

// ---- Hoisted values (accessible inside vi.mock factories) -----------------

const { mockApi, externalApp, job, candidate } = vi.hoisted(() => {
  // We cannot import vi inside vi.hoisted, but we CAN use the native fn
  // pattern. vi.hoisted runs before any vi.mock factory, so anything
  // returned here is available to the factories below.

  const fn = (impl?: (...args: any[]) => any) => {
    // Delegate to vitest's vi.fn at call-site — vi is in scope in the
    // outer module but NOT inside the callback. However vitest 2.x does
    // inject vi into the hoisted scope. Fallback: we just build a
    // minimal spy that vitest can later recognise.
    return impl as any; // placeholder; overridden in beforeEach via real vi.fn
  };

  const _job = {
    id: "job-590321",
    job_id: "590321",
    title: "Business Development Manager",
    function: "Retail Banking",
    band: "AM",
    tags: ["Sales", "Liabilities"],
    location: "Bhopal",
    required_skills: ["sales", "liabilities", "kyc"],
    nice_to_have_skills: [],
    description: "",
    hr_partner_id: "hr1@axisbank.test",
    panel: [],
    shortlist_threshold: 75,
  } as Job;

  const _candidate = {
    id: "cand-001",
    employee_id: "EMP10234",
    name: "Rohan Verma",
    email: "rohan@axisbank.test",
    current_role: "Relationship Manager",
    current_band: "AM",
    current_location: "Bhopal",
    tenure_years: 6,
    skills: ["sales", "liabilities"],
    kras: [],
    education: null,
    last_rating: null,
  } as Candidate;

  const _externalApp = {
    id: "app-ext-001",
    candidate_id: "cand-001",
    job_id: "job-590321",
    match_percent: 82,
    match_rationale: "Strong match",
    matched_skills: ["sales", "liabilities"],
    missing_skills: ["kyc"],
    stage: "screened" as const,
    agent_status: "waiting_candidate" as const,
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
  } as Application;

  return {
    mockApi: {
      listJobs: vi.fn(),
      listCandidates: vi.fn(),
      jobsApplicantCounts: vi.fn(),
      externalApplications: vi.fn(),
      apply: vi.fn(),
    },
    externalApp: _externalApp,
    job: _job,
    candidate: _candidate,
  };
});

// ---- Mocks ----------------------------------------------------------------

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push,
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/thrive",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/persona", () => ({
  usePersona: () => [
    { role: "employee", identity: "cand-001", displayName: "Rohan Verma" },
    vi.fn(),
  ],
  readPersona: () => ({
    role: "employee",
    identity: "cand-001",
    displayName: "Rohan Verma",
  }),
  PERSONA_LABEL: {
    employee: "Candidate (Thrive)",
    hr_partner: "Business Partner",
    panel: "Interview Panel",
    offer_team: "Offer Discussion Team",
  },
  PERSONA_HOME: {
    employee: "/thrive",
    hr_partner: "/hr",
    panel: "/panel",
    offer_team: "/offer-team",
  },
}));

vi.mock("@/components/RoleGate", () => ({
  RoleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/api", () => ({
  api: mockApi,
}));

vi.mock("@/lib/hooks/useAutoRefresh", () => ({
  useAutoRefresh: () => ({
    data: [externalApp],
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

// ---------- Import the component under test AFTER mocks are registered ------
import ThriveHomePage from "@/app/thrive/page";

// ---------- Tests -----------------------------------------------------------

describe("ThriveHomePage — external candidate view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.listJobs.mockResolvedValue([job]);
    mockApi.listCandidates.mockResolvedValue([candidate]);
    mockApi.jobsApplicantCounts.mockResolvedValue({ "job-590321": 4 });
    mockApi.externalApplications.mockResolvedValue([externalApp]);
  });

  it('renders "Welcome, Rohan Verma" and NOT "Employee Thrive"', async () => {
    render(<ThriveHomePage />);
    await waitFor(() =>
      expect(screen.getByText(/Welcome, Rohan Verma/)).toBeInTheDocument(),
    );
    expect(screen.queryByText("Employee Thrive")).not.toBeInTheDocument();
  });

  it("shows a hero card with the application job title, stage, and match %", async () => {
    render(<ThriveHomePage />);
    await waitFor(() =>
      expect(screen.getAllByText("Business Development Manager").length).toBeGreaterThanOrEqual(1),
    );
    expect(screen.getByText(/82.*match/i)).toBeInTheDocument();
    expect(screen.getByText("Screened")).toBeInTheDocument();
  });

  it('"Confirm Interview Slot" CTA is visible when stage=screened & agent_status=waiting_candidate', async () => {
    render(<ThriveHomePage />);
    await waitFor(() =>
      expect(screen.getByText(/Confirm Interview Slot/)).toBeInTheDocument(),
    );
  });

  it('does not expose "AI" language in any candidate-facing visible text', async () => {
    render(<ThriveHomePage />);
    await waitFor(() =>
      expect(screen.getByText(/Welcome, Rohan Verma/)).toBeInTheDocument(),
    );
    const bodyText = document.body.textContent || "";
    const aiRegex = /\bAI\b/;
    expect(aiRegex.test(bodyText)).toBe(false);
  });

  it("links to /external/intake with name and email query params", async () => {
    render(<ThriveHomePage />);
    await waitFor(() =>
      expect(screen.getByText(/Welcome, Rohan Verma/)).toBeInTheDocument(),
    );
    // Filter to links that include query params (the TopBar has a bare
    // /external/intake link without params — that's fine, we only care
    // about the candidate-portal links that carry identity).
    const intakeLinks = screen
      .getAllByRole("link")
      .filter((a) => {
        const href = a.getAttribute("href") || "";
        return href.startsWith("/external/intake?");
      });
    expect(intakeLinks.length).toBeGreaterThan(0);
    for (const link of intakeLinks) {
      const href = link.getAttribute("href")!;
      expect(href).toContain("name=Rohan");
      expect(href).toContain("email=rohan");
    }
  });

  it("shows loading spinner while data is being fetched (not the internal view)", async () => {
    mockApi.listJobs.mockReturnValue(new Promise(() => {}));
    mockApi.listCandidates.mockReturnValue(new Promise(() => {}));
    mockApi.jobsApplicantCounts.mockReturnValue(new Promise(() => {}));

    render(<ThriveHomePage />);
    expect(screen.getByText(/Loading your dashboard/)).toBeInTheDocument();
    expect(screen.queryByText("Job Recommendations for you")).not.toBeInTheDocument();
  });
});
