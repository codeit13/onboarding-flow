import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { PanelMemberListed, PanelPendingItem, PanelHistoryItem } from "@/lib/api";

// ---- Hoisted mocks --------------------------------------------------------

const {
  mockApi,
  mockPanelMembers,
  mockPanelPending,
  mockPanelHistory,
  mockPersona,
} = vi.hoisted(() => {
  const _mockPanelMembers: PanelMemberListed[] = [
    {
      user_id: "panel-user-1",
      name: "Rohan Mehta",
      email: "rohan@axis.com",
      role: "hiring_manager",
      jobs: [
        { id: "job-1", title: "Business Development Manager" },
        { id: "job-2", title: "Relationship Manager" },
        { id: "job-3", title: "Branch Manager" },
      ],
    },
  ];

  const _mockPanelPending: PanelPendingItem[] = [];
  const _mockPanelHistory: PanelHistoryItem[] = [];

  return {
    mockApi: {
      panelMembers: vi.fn().mockResolvedValue(_mockPanelMembers),
      panelPending: vi.fn().mockResolvedValue(_mockPanelPending),
      panelHistory: vi.fn().mockResolvedValue(_mockPanelHistory),
    },
    mockPanelMembers: _mockPanelMembers,
    mockPanelPending: _mockPanelPending,
    mockPanelHistory: _mockPanelHistory,
    mockPersona: {
      role: "panel" as const,
      displayName: "Rohan Mehta",
      identity: "panel-user-1",
    },
  };
});

vi.mock("@/lib/api", () => ({ api: mockApi }));
vi.mock("@/lib/persona", () => ({
  usePersona: () => [mockPersona, vi.fn()],
}));
vi.mock("@/components/RoleGate", () => ({
  RoleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import PanelQueuePage from "@/app/panel/page";

// ---------------------------------------------------------------------------
// Bug 7 — Role text should be human-readable, JDs collapsed to count
// ---------------------------------------------------------------------------

describe("Bug 7: Panel member role/JD display", () => {
  it("renders role with spaces instead of underscores", async () => {
    render(<PanelQueuePage />);
    await waitFor(() => {
      expect(screen.getByText("hiring manager")).toBeTruthy();
    });
  });

  it("shows JD count instead of listing all titles", async () => {
    render(<PanelQueuePage />);
    await waitFor(() => {
      expect(screen.getByText(/3 active requisitions/)).toBeTruthy();
    });
  });

  it("does not render full JD title list inline", async () => {
    render(<PanelQueuePage />);
    await waitFor(() => {
      expect(screen.queryByText(/Business Development Manager.*Relationship Manager.*Branch Manager/)).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// Bug 9 — Empty queue should have icon and descriptive text
// ---------------------------------------------------------------------------

describe("Bug 9: Empty panel queue UI", () => {
  it("shows 'Your queue is clear' heading when no pending items", async () => {
    render(<PanelQueuePage />);
    await waitFor(() => {
      expect(screen.getByText("Your queue is clear")).toBeTruthy();
    });
  });

  it("shows descriptive empty state text", async () => {
    render(<PanelQueuePage />);
    await waitFor(() => {
      expect(
        screen.getByText(/No Round 2 interviews need your feedback/),
      ).toBeTruthy();
    });
  });
});

// ---------------------------------------------------------------------------
// Bug 8 — Loading spinner while history loads
// ---------------------------------------------------------------------------

describe("Bug 8: Loading spinner for submitted votes", () => {
  it("shows loading text before history data arrives", async () => {
    // Make the history loader hang so loading state is visible
    mockApi.panelHistory.mockImplementation(
      () => new Promise(() => {}), // never resolves
    );

    render(<PanelQueuePage />);
    await waitFor(() => {
      expect(
        screen.getByText(/Loading your submitted votes/),
      ).toBeTruthy();
    });
  });
});
