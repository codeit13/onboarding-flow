import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { Application, EngagementJourney, EngagementTouchpoint, Job } from "@/lib/api";

// ---- Hoisted values (accessible inside vi.mock factories) -----------------

const { mockApi, mockGetEngagementByApplication, offerAcceptedApp, mockJob, engagementJourney } = vi.hoisted(() => {
  const _offerAcceptedApp = {
    id: "app-timeline-1",
    candidate_id: "cand-001",
    job_id: "job-590321",
    match_percent: 90,
    match_rationale: "Excellent fit",
    matched_skills: ["sales", "liabilities"],
    missing_skills: [],
    stage: "offer_accepted" as const,
    agent_status: "engagement_active" as const,
    next_action: "",
    pending_blocking_items: [],
    proposed_r1_slots: [],
    selected_r1_slot_index: null,
    proposed_r2_slots: [],
    selected_r2_slot_index: null,
    r1_started: false,
    created_at: "2026-04-08T10:00:00Z",
    updated_at: "2026-04-10T11:00:00Z",
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

  const touchpoints: EngagementTouchpoint[] = [
    {
      id: "tp-1",
      kind: "welcome_whatsapp",
      channel: "whatsapp",
      scheduled_at: "2026-04-09T09:00:00Z",
      sent_at: "2026-04-09T09:01:00Z",
      delivered_at: "2026-04-09T09:02:00Z",
      read_at: "2026-04-09T09:10:00Z",
      candidate_response: "Thank you! Very excited",
      status: "read",
      template_id: null,
      whatsapp_message_id: null,
      error_message: null,
    },
    {
      id: "tp-2",
      kind: "employee_stories",
      channel: "whatsapp",
      scheduled_at: "2026-04-10T09:00:00Z",
      sent_at: "2026-04-10T09:00:00Z",
      delivered_at: "2026-04-10T09:01:00Z",
      read_at: null,
      candidate_response: null,
      status: "delivered",
      template_id: null,
      whatsapp_message_id: null,
      error_message: null,
    },
    {
      id: "tp-3",
      kind: "benefits_overview",
      channel: "email",
      scheduled_at: "2026-04-11T09:00:00Z",
      sent_at: "2026-04-11T09:00:00Z",
      delivered_at: null,
      read_at: null,
      candidate_response: null,
      status: "sent",
      template_id: null,
      whatsapp_message_id: null,
      error_message: null,
    },
    {
      id: "tp-4",
      kind: "buddy_intro",
      channel: "email",
      scheduled_at: "2026-04-12T09:00:00Z",
      sent_at: null,
      delivered_at: null,
      read_at: null,
      candidate_response: null,
      status: "pending",
      template_id: null,
      whatsapp_message_id: null,
      error_message: null,
    },
    {
      id: "tp-5",
      kind: "document_checklist",
      channel: "whatsapp",
      scheduled_at: "2026-04-13T09:00:00Z",
      sent_at: "2026-04-13T09:00:00Z",
      delivered_at: null,
      read_at: null,
      candidate_response: null,
      status: "failed",
      template_id: null,
      whatsapp_message_id: null,
      error_message: "Delivery failed",
    },
    {
      id: "tp-6",
      kind: "culture_video",
      channel: "portal",
      scheduled_at: "2026-04-14T09:00:00Z",
      sent_at: null,
      delivered_at: null,
      read_at: null,
      candidate_response: null,
      status: "skipped",
      template_id: null,
      whatsapp_message_id: null,
      error_message: null,
    },
  ];

  const _engagementJourney: EngagementJourney = {
    id: "eng-timeline-1",
    application_id: "app-timeline-1",
    candidate_name: "Rohan Verma",
    candidate_email: "rohan@axisbank.test",
    candidate_phone: "+919876543210",
    whatsapp_opted_in: true,
    offer_accepted_at: "2026-04-09T08:00:00Z",
    expected_joining_date: "2026-05-01T00:00:00Z",
    buddy_name: "Amit Kumar",
    buddy_email: "amit@axisbank.test",
    touchpoints,
    sentiment_score: 75,
    risk_level: "low",
    status: "active",
    created_at: "2026-04-09T08:00:00Z",
    updated_at: "2026-04-11T09:00:00Z",
  };

  return {
    mockApi: {
      getApplication: vi.fn(),
      getJob: vi.fn(),
      confirmSlot: vi.fn(),
      confirmCustomR1Slot: vi.fn(),
      startR1Interview: vi.fn(),
    },
    mockGetEngagementByApplication: vi.fn(),
    offerAcceptedApp: _offerAcceptedApp,
    mockJob: _mockJob,
    engagementJourney: _engagementJourney,
  };
});

// ---- Mocks ----------------------------------------------------------------

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
  useParams: () => ({ appId: "app-timeline-1" }),
  usePathname: () => "/thrive/status/app-timeline-1",
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
  acceptOffer: vi.fn(),
  declineOffer: vi.fn(),
  getEngagementByApplication: mockGetEngagementByApplication,
}));

vi.mock("@/lib/hooks/useAutoRefresh", () => ({
  useAutoRefresh: () => ({
    data: offerAcceptedApp,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

// ---------- Import the component under test AFTER mocks are registered ------
import EmployeeStatusPage from "@/app/thrive/status/[appId]/page";

// ---------- Tests -----------------------------------------------------------

describe("EngagementTimeline — post-offer journey rendering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getApplication.mockResolvedValue(offerAcceptedApp);
    mockApi.getJob.mockResolvedValue(mockJob);
    mockGetEngagementByApplication.mockResolvedValue(engagementJourney);
  });

  it("renders the onboarding journey section header", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Your Onboarding Journey")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Here's what's coming up as you prepare to join Axis Bank/),
    ).toBeInTheDocument();
  });

  it("displays the expected joining date", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Your Onboarding Journey")).toBeInTheDocument(),
    );
    // 1 May 2026 in en-IN locale
    expect(screen.getByText(/1 May 2026/)).toBeInTheDocument();
  });

  it("renders all touchpoint labels including new ones", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Your Onboarding Journey")).toBeInTheDocument(),
    );

    // Each touchpoint renders its human-friendly label
    expect(screen.getByText("Welcome message")).toBeInTheDocument();
    expect(screen.getByText("Stories from your future colleagues")).toBeInTheDocument();
    expect(screen.getByText("Your benefits at Axis")).toBeInTheDocument();
    expect(screen.getByText("Meet your buddy")).toBeInTheDocument();
    expect(screen.getByText("Document checklist")).toBeInTheDocument();
    expect(screen.getByText("Life at Axis Bank")).toBeInTheDocument();
  });

  it("shows correct status badges for completed touchpoints", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Your Onboarding Journey")).toBeInTheDocument(),
    );

    // tp-1 status=read -> badge "Read"
    expect(screen.getByText("Read")).toBeInTheDocument();
    // tp-2 status=delivered -> badge "Delivered"
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    // tp-3 status=sent -> badge "Sent"
    expect(screen.getByText("Sent")).toBeInTheDocument();
    // tp-5 status=failed -> badge "Failed"
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("displays candidate response text when available", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Your Onboarding Journey")).toBeInTheDocument(),
    );

    // tp-1 has candidate_response = "Thank you! Very excited"
    expect(
      screen.getByText(/Thank you! Very excited/),
    ).toBeInTheDocument();
  });

  it("timeline dots have correct colors based on status", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Your Onboarding Journey")).toBeInTheDocument(),
    );

    // Get all timeline dots (they are w-3 h-3 rounded-full border-2 elements)
    const dots = document.querySelectorAll(".w-3.h-3.rounded-full.border-2");

    // There should be 6 dots (one per touchpoint)
    expect(dots.length).toBe(6);

    // tp-1 (read) -> completed -> bg-emerald-500 border-emerald-500
    expect(dots[0].className).toContain("bg-emerald-500");
    expect(dots[0].className).toContain("border-emerald-500");

    // tp-2 (delivered) -> completed -> bg-emerald-500 border-emerald-500
    expect(dots[1].className).toContain("bg-emerald-500");

    // tp-3 (sent) -> completed -> bg-emerald-500 border-emerald-500
    expect(dots[2].className).toContain("bg-emerald-500");

    // tp-4 (pending) -> bg-white border-axis-divider
    expect(dots[3].className).toContain("bg-white");
    expect(dots[3].className).toContain("border-axis-divider");

    // tp-5 (failed) -> bg-red-500 border-red-500
    expect(dots[4].className).toContain("bg-red-500");
    expect(dots[4].className).toContain("border-red-500");

    // tp-6 (skipped) -> bg-gray-300 border-gray-300
    expect(dots[5].className).toContain("bg-gray-300");
    expect(dots[5].className).toContain("border-gray-300");
  });

  it("does not show timeline when engagement journey is null", async () => {
    mockGetEngagementByApplication.mockResolvedValue(null);
    render(<EmployeeStatusPage />);

    // Wait for the page to finish loading
    await waitFor(() =>
      expect(screen.queryByText("Your Onboarding Journey")).not.toBeInTheDocument(),
    );
  });

  it("pending touchpoints have no status badge", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Your Onboarding Journey")).toBeInTheDocument(),
    );

    // The "Meet your buddy" touchpoint is pending — it should have no badge next to it
    const buddyLabel = screen.getByText("Meet your buddy");
    const parentRow = buddyLabel.closest(".flex.items-center.gap-2");
    // Should not contain a badge element (badges have text-[10px] class)
    const badge = parentRow?.querySelector(".text-\\[10px\\]");
    expect(badge).toBeNull();
  });

  it("skipped touchpoints render with line-through style", async () => {
    render(<EmployeeStatusPage />);
    await waitFor(() =>
      expect(screen.getByText("Your Onboarding Journey")).toBeInTheDocument(),
    );

    const skippedLabel = screen.getByText("Life at Axis Bank");
    expect(skippedLabel.className).toContain("line-through");
    expect(skippedLabel.className).toContain("text-gray-400");
  });
});
