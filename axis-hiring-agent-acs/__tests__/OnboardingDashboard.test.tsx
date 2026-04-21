import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { EngagementDashboard, EngagementJourney, EngagementTouchpoint } from "@/lib/api";

// ---- Hoisted values (accessible inside vi.mock factories) -----------------

const { mockGetEngagementDashboard, dashboardData } = vi.hoisted(() => {
  const touchpoint1: EngagementTouchpoint = {
    id: "tp-1",
    kind: "welcome_whatsapp",
    channel: "whatsapp",
    scheduled_at: "2026-04-09T09:00:00Z",
    sent_at: "2026-04-09T09:01:00Z",
    delivered_at: "2026-04-09T09:02:00Z",
    read_at: null,
    candidate_response: null,
    status: "delivered",
    template_id: null,
    whatsapp_message_id: null,
    error_message: null,
  };

  const touchpoint2: EngagementTouchpoint = {
    id: "tp-2",
    kind: "buddy_intro",
    channel: "email",
    scheduled_at: "2026-04-10T09:00:00Z",
    sent_at: null,
    delivered_at: null,
    read_at: null,
    candidate_response: null,
    status: "pending",
    template_id: null,
    whatsapp_message_id: null,
    error_message: null,
  };

  const touchpoint3: EngagementTouchpoint = {
    id: "tp-3",
    kind: "document_checklist",
    channel: "whatsapp",
    scheduled_at: "2026-04-11T09:00:00Z",
    sent_at: "2026-04-11T09:00:00Z",
    delivered_at: "2026-04-11T09:01:00Z",
    read_at: "2026-04-11T09:05:00Z",
    candidate_response: null,
    status: "read",
    template_id: null,
    whatsapp_message_id: null,
    error_message: null,
  };

  const lowRiskJourney: EngagementJourney = {
    id: "eng-1",
    application_id: "app-001",
    candidate_name: "Priya Sharma",
    candidate_email: "priya@axisbank.test",
    candidate_phone: "+919876543210",
    whatsapp_opted_in: true,
    offer_accepted_at: "2026-04-08T10:00:00Z",
    expected_joining_date: "2026-05-01T00:00:00Z",
    buddy_name: "Amit Kumar",
    buddy_email: "amit@axisbank.test",
    touchpoints: [touchpoint1, touchpoint2],
    sentiment_score: 85,
    risk_level: "low",
    status: "active",
    created_at: "2026-04-08T10:00:00Z",
    updated_at: "2026-04-09T09:02:00Z",
  };

  const highRiskJourney: EngagementJourney = {
    id: "eng-2",
    application_id: "app-002",
    candidate_name: "Rahul Mehta",
    candidate_email: "rahul@axisbank.test",
    candidate_phone: "+919876500000",
    whatsapp_opted_in: true,
    offer_accepted_at: "2026-04-05T10:00:00Z",
    expected_joining_date: "2026-04-15T00:00:00Z",
    buddy_name: null,
    buddy_email: null,
    touchpoints: [touchpoint3],
    sentiment_score: 30,
    risk_level: "high",
    status: "active",
    created_at: "2026-04-05T10:00:00Z",
    updated_at: "2026-04-11T09:05:00Z",
  };

  const _dashboardData: EngagementDashboard = {
    total_active_journeys: 2,
    at_risk_count: 1,
    upcoming_touchpoints_24h: [
      {
        journey_id: "eng-1",
        candidate_name: "Priya Sharma",
        touchpoint_id: "tp-2",
        kind: "buddy_intro",
        scheduled_at: "2026-04-10T09:00:00Z",
      },
    ],
    completion_rate_percent: 50,
    journeys: [lowRiskJourney, highRiskJourney],
  };

  return {
    mockGetEngagementDashboard: vi.fn(),
    dashboardData: _dashboardData,
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
  usePathname: () => "/onboarding",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/persona", () => ({
  usePersona: () => [
    { role: "engagement_manager", identity: "em-001", displayName: "Engagement Manager" },
    vi.fn(),
  ],
  readPersona: () => ({
    role: "engagement_manager",
    identity: "em-001",
    displayName: "Engagement Manager",
  }),
  PERSONA_LABEL: {
    employee: "Candidate (Thrive)",
    hr_partner: "Business Partner",
    panel: "Interview Panel",
    offer_team: "Offer Discussion Team",
    engagement_manager: "Onboarding Team",
  },
  PERSONA_HOME: {
    employee: "/thrive",
    hr_partner: "/hr",
    panel: "/panel",
    offer_team: "/offer-team",
    engagement_manager: "/onboarding",
  },
}));

vi.mock("@/components/RoleGate", () => ({
  RoleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/api", () => ({
  getEngagementDashboard: mockGetEngagementDashboard,
  sendTouchpoint: vi.fn(),
  skipTouchpoint: vi.fn(),
  updateEngagementJourney: vi.fn(),
}));

vi.mock("@/lib/hooks/useAutoRefresh", () => ({
  useAutoRefresh: () => ({
    data: dashboardData,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

// ---------- Import the component under test AFTER mocks are registered ------
import OnboardingPage from "@/app/onboarding/page";

// ---------- Tests -----------------------------------------------------------

describe("OnboardingDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetEngagementDashboard.mockResolvedValue(dashboardData);
  });

  it("renders dashboard header", async () => {
    render(<OnboardingPage />);
    await waitFor(() =>
      expect(
        screen.getByText("Candidate Engagement Dashboard"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText("Monitor and manage post-offer candidate journeys"),
    ).toBeInTheDocument();
  });

  it("shows stat cards with correct data", async () => {
    render(<OnboardingPage />);
    await waitFor(() =>
      expect(screen.getByText("Active Journeys")).toBeInTheDocument(),
    );
    // total_active_journeys = 2
    expect(screen.getByText("2")).toBeInTheDocument();
    // at_risk_count = 1 and upcoming_touchpoints_24h = 1 — both render "1"
    expect(screen.getByText("Candidates at Risk")).toBeInTheDocument();
    expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(1);
    // upcoming_touchpoints_24h has 1 entry
    expect(screen.getByText("Upcoming in 24h")).toBeInTheDocument();
    // completion_rate_percent = 50
    expect(screen.getByText("Completion Rate")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("shows at-risk candidates section when there are at-risk journeys", async () => {
    render(<OnboardingPage />);
    await waitFor(() =>
      expect(
        screen.getByText("Candidates needing attention"),
      ).toBeInTheDocument(),
    );
    // High risk journey candidate name appears in both at-risk section and journeys table
    expect(screen.getAllByText("Rahul Mehta").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("high").length).toBeGreaterThanOrEqual(1);
  });

  it("shows journey table with all journeys", async () => {
    render(<OnboardingPage />);
    await waitFor(() =>
      expect(screen.getByText("All journeys")).toBeInTheDocument(),
    );
    // Both candidate names should appear in the table
    expect(screen.getByText("Priya Sharma")).toBeInTheDocument();
    // Rahul Mehta already asserted to be present — also check table headers
    expect(screen.getByText("Candidate")).toBeInTheDocument();
    expect(screen.getByText("Phone")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Risk")).toBeInTheDocument();
    expect(screen.getByText("Joining Date")).toBeInTheDocument();
    expect(screen.getByText("Touchpoints")).toBeInTheDocument();
    expect(screen.getByText("Actions")).toBeInTheDocument();
  });

  it("no AI language on the page", async () => {
    render(<OnboardingPage />);
    await waitFor(() =>
      expect(
        screen.getByText("Candidate Engagement Dashboard"),
      ).toBeInTheDocument(),
    );
    const bodyText = document.body.textContent || "";
    const aiRegex = /\bAI\b/;
    expect(aiRegex.test(bodyText)).toBe(false);
  });
});
