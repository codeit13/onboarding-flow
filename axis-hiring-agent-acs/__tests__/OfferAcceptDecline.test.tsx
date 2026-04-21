import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Application, Job } from "@/lib/api";

// ---- Hoisted values (accessible inside vi.mock factories) -----------------

const { mockApi, mockAcceptOffer, mockDeclineOffer, mockGetEngagementByApplication, offerApp, mockJob } = vi.hoisted(() => {
  const _offerApp = {
    id: "app-test-1",
    candidate_id: "cand-001",
    job_id: "job-590321",
    match_percent: 90,
    match_rationale: "Excellent fit",
    matched_skills: ["sales", "liabilities"],
    missing_skills: [],
    stage: "offer" as const,
    agent_status: "waiting_candidate_acceptance" as const,
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
    checklists: [],
  } as Application;

  const _mockJob = {
    id: "job-590321",
    job_id: "590321",
    title: "Business Development Manager",
    function: "Retail Banking",
    band: "AM",
    tags: ["Sales"],
    location: "Bhopal",
    required_skills: ["sales", "liabilities"],
    nice_to_have_skills: [],
    description: "",
    hr_partner_id: "hr1@axisbank.test",
    panel: [],
    shortlist_threshold: 75,
  } as Job;

  return {
    mockApi: {
      getApplication: vi.fn(),
      getJob: vi.fn(),
      confirmSlot: vi.fn(),
      confirmCustomR1Slot: vi.fn(),
      startR1Interview: vi.fn(),
    },
    mockAcceptOffer: vi.fn(),
    mockDeclineOffer: vi.fn(),
    mockGetEngagementByApplication: vi.fn(),
    offerApp: _offerApp,
    mockJob: _mockJob,
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
  useParams: () => ({ appId: "app-test-1" }),
  usePathname: () => "/thrive/status/app-test-1",
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
  acceptOffer: mockAcceptOffer,
  declineOffer: mockDeclineOffer,
  getEngagementByApplication: mockGetEngagementByApplication,
}));

vi.mock("@/lib/hooks/useAutoRefresh", () => ({
  useAutoRefresh: () => ({
    data: offerApp,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

// ---------- Import the component under test AFTER mocks are registered ------
import EmployeeStatusPage from "@/app/thrive/status/[appId]/page";

// ---------- Tests -----------------------------------------------------------

describe("OfferAcceptDecline — offer stage UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getApplication.mockResolvedValue(offerApp);
    mockApi.getJob.mockResolvedValue(mockJob);
    mockAcceptOffer.mockResolvedValue({
      id: "eng-1",
      application_id: "app-test-1",
      candidate_name: "Rohan Verma",
      candidate_email: "rohan@axisbank.test",
      candidate_phone: "+919876543210",
      whatsapp_opted_in: true,
      offer_accepted_at: "2026-04-09T10:00:00Z",
      expected_joining_date: "2026-05-01",
      buddy_name: null,
      buddy_email: null,
      touchpoints: [],
      sentiment_score: null,
      risk_level: "low",
      status: "active",
      created_at: "2026-04-09T10:00:00Z",
      updated_at: "2026-04-09T10:00:00Z",
    });
    mockDeclineOffer.mockResolvedValue({ ...offerApp, stage: "offer_declined" });
    mockGetEngagementByApplication.mockResolvedValue(null);
  });

  it("shows offer accept form when stage is offer and status is waiting_candidate_acceptance", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(
        screen.getByText("Accept your offer & start your journey"),
      ).toBeInTheDocument(),
    );
  });

  it("shows WhatsApp number input, joining date picker, and consent checkbox", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByPlaceholderText("+91 98765 43210")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Expected joining date/)).toBeInTheDocument();
    expect(
      screen.getByText(/I'd like to receive onboarding updates via WhatsApp/),
    ).toBeInTheDocument();
  });

  it("validates phone number is required before accepting", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Accept Offer")).toBeInTheDocument(),
    );

    // Leave phone blank, set a date
    const dateInput = document.querySelector('input[type="date"]')!;
    fireEvent.change(dateInput, { target: { value: "2026-05-01" } });

    fireEvent.click(screen.getByText("Accept Offer"));

    await waitFor(() =>
      expect(
        screen.getByText("Please enter your WhatsApp number"),
      ).toBeInTheDocument(),
    );
    expect(mockAcceptOffer).not.toHaveBeenCalled();
  });

  it("validates joining date is required before accepting", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Accept Offer")).toBeInTheDocument(),
    );

    // Fill in phone but leave date blank
    const phoneInput = screen.getByPlaceholderText("+91 98765 43210");
    fireEvent.change(phoneInput, { target: { value: "+919876543210" } });

    fireEvent.click(screen.getByText("Accept Offer"));

    await waitFor(() =>
      expect(
        screen.getByText("Please select your expected joining date"),
      ).toBeInTheDocument(),
    );
    expect(mockAcceptOffer).not.toHaveBeenCalled();
  });

  it("shows decline form when 'I need to decline' is clicked", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("I need to decline")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByText("I need to decline"));

    await waitFor(() =>
      expect(
        screen.getByText(
          "We're sorry to see you go. Could you share why so we can improve?",
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.getByPlaceholderText("Your reason (optional)")).toBeInTheDocument();
    expect(screen.getByText("Confirm Decline")).toBeInTheDocument();
  });

  it("calls acceptOffer with correct params on submit", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Accept Offer")).toBeInTheDocument(),
    );

    // Fill in phone
    const phoneInput = screen.getByPlaceholderText("+91 98765 43210");
    fireEvent.change(phoneInput, { target: { value: "+919876543210" } });

    // Fill in date
    const dateInput = document.querySelector('input[type="date"]')!;
    fireEvent.change(dateInput, { target: { value: "2026-05-01" } });

    fireEvent.click(screen.getByText("Accept Offer"));

    await waitFor(() =>
      expect(mockAcceptOffer).toHaveBeenCalledWith(
        "app-test-1",
        "+919876543210",
        true, // default consent is true
        "2026-05-01",
      ),
    );
  });

  it("calls declineOffer on decline confirmation", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("I need to decline")).toBeInTheDocument(),
    );

    // Open decline form
    fireEvent.click(screen.getByText("I need to decline"));

    await waitFor(() =>
      expect(screen.getByText("Confirm Decline")).toBeInTheDocument(),
    );

    // Optionally enter a reason
    const textarea = screen.getByPlaceholderText("Your reason (optional)");
    fireEvent.change(textarea, { target: { value: "Got a better offer" } });

    fireEvent.click(screen.getByText("Confirm Decline"));

    await waitFor(() =>
      expect(mockDeclineOffer).toHaveBeenCalledWith(
        "app-test-1",
        "Got a better offer",
      ),
    );
  });
});
