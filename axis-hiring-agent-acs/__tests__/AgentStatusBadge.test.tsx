import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentStatusBadge } from "@/components/agent/AgentStatusBadge";

describe("AgentStatusBadge", () => {
  it("renders the human label for every known status", () => {
    const cases: { status: any; label: string }[] = [
      { status: "idle", label: "Idle" },
      { status: "running", label: "Running" },
      { status: "waiting_hr", label: "Waiting on Business Partner" },
      { status: "waiting_candidate", label: "Waiting on candidate" },
      { status: "waiting_panel", label: "Waiting on panel" },
      { status: "done", label: "Done" },
    ];
    for (const c of cases) {
      const { unmount } = render(<AgentStatusBadge status={c.status} />);
      expect(screen.getByText(`Agent · ${c.label}`)).toBeInTheDocument();
      unmount();
    }
  });

  it("animates when running (pulse class)", () => {
    const { container } = render(<AgentStatusBadge status="running" />);
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
  });
});
