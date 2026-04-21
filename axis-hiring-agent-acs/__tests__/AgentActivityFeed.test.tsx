import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentActivityFeed } from "@/components/agent/AgentActivityFeed";
import type { ActivityItem } from "@/lib/api";

const mk = (overrides: Partial<ActivityItem>): ActivityItem => ({
  id: "x",
  at: "2026-04-06T10:00:00Z",
  kind: "agent",
  title: "Step",
  detail: "Detail line",
  meta: {},
  ...overrides,
});

describe("AgentActivityFeed", () => {
  it("renders the empty label when there are no items", () => {
    render(
      <AgentActivityFeed
        items={[]}
        emptyLabel="Nothing yet."
        defaultCollapsed={false}
      />,
    );
    expect(screen.getByText("Nothing yet.")).toBeInTheDocument();
  });

  it("renders newest items first (the parent passes ascending order)", () => {
    const items = [
      mk({ id: "1", title: "Older", at: "2026-04-06T09:00:00Z" }),
      mk({ id: "2", title: "Newer", at: "2026-04-06T11:00:00Z" }),
    ];
    render(<AgentActivityFeed items={items} defaultCollapsed={false} />);
    const titles = screen.getAllByText(/Older|Newer/).map((el) => el.textContent);
    expect(titles[0]).toBe("Newer");
    expect(titles[1]).toBe("Older");
  });

  it("strips HTML and rewrites Outlook bounce titles", () => {
    const items = [
      mk({
        id: "b1",
        kind: "email_in",
        title: "Undeliverable: Round 1 Interview · BDM-CSR · Priya Nair",
        detail:
          '<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"></head><body><p><b><font color="#000066" size="3" face="Arial">Delivery has failed to these recipients or groups:</font></b></p></body></html>',
      }),
    ];
    render(<AgentActivityFeed items={items} defaultCollapsed={false} />);
    expect(
      screen.getByText(/Email bounced — Round 1 Interview/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Mail server reported a delivery failure/),
    ).toBeInTheDocument();
    // No raw HTML/markup characters anywhere in the rendered output.
    expect(screen.queryByText(/<html/)).toBeNull();
    expect(screen.queryByText(/font color/)).toBeNull();
  });

  it("renders the kind badge for every supported kind", () => {
    const kinds: ActivityItem["kind"][] = [
      "email_out",
      "email_in",
      "calendar",
      "notification",
      "agent",
      "checklist",
    ];
    const items = kinds.map((k, i) =>
      mk({ id: String(i), kind: k, title: `${k}-row`, detail: "" }),
    );
    render(<AgentActivityFeed items={items} defaultCollapsed={false} />);
    for (const k of kinds) {
      expect(screen.getByText(`${k}-row`)).toBeInTheDocument();
    }
  });
});
