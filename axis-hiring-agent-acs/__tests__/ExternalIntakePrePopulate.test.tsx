import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// ---- next/navigation mock with controllable searchParams ------------------

let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/external/intake",
  useSearchParams: () => mockSearchParams,
}));

// ---- api mock (only listJobs is called on mount) --------------------------

vi.mock("@/lib/api", () => ({
  api: {
    listJobs: vi.fn().mockResolvedValue([]),
    externalIntake: vi.fn(),
  },
  // Re-export the type name so the import in the page doesn't break.
  ExternalIntakeResponse: undefined,
}));

// ---- Import the page under test AFTER mocks --------------------------------

import ExternalIntakePage from "@/app/external/intake/page";

// ---- Tests -----------------------------------------------------------------

describe("ExternalIntakePage — pre-populate from query params", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("pre-populates name and email when URL has ?name=Rohan+Desai&email=rohan@test.com", () => {
    mockSearchParams = new URLSearchParams(
      "name=Rohan+Desai&email=rohan@test.com",
    );
    render(<ExternalIntakePage />);

    const nameInput = screen.getByPlaceholderText("Priya Sharma") as HTMLInputElement;
    const emailInput = screen.getByPlaceholderText("priya@example.com") as HTMLInputElement;

    expect(nameInput.value).toBe("Rohan Desai");
    expect(emailInput.value).toBe("rohan@test.com");
  });

  it("starts with empty fields when there are no query params", () => {
    mockSearchParams = new URLSearchParams();
    render(<ExternalIntakePage />);

    const nameInput = screen.getByPlaceholderText("Priya Sharma") as HTMLInputElement;
    const emailInput = screen.getByPlaceholderText("priya@example.com") as HTMLInputElement;

    expect(nameInput.value).toBe("");
    expect(emailInput.value).toBe("");
  });

  it("still validates required fields — shows error when name/email are blank", async () => {
    mockSearchParams = new URLSearchParams();
    render(<ExternalIntakePage />);

    // Submit the form without filling anything.
    const form = screen.getByRole("button", { name: /Find my matches/i }).closest("form")!;
    fireEvent.submit(form);

    // The component calls e.preventDefault and checks for name+email before
    // calling the API.  It sets an error string.
    await waitFor(() =>
      expect(
        screen.getByText(/please enter your name and email/i),
      ).toBeInTheDocument(),
    );
  });
});
