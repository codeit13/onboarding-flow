import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { HRSubNav } from "@/components/hr/HRSubNav";

let pathname = "/hr";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

describe("HRSubNav", () => {
  it("renders every section link", () => {
    pathname = "/hr/dashboard";
    render(<HRSubNav />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Funnel")).toBeInTheDocument();
    expect(screen.getByText("Requisitions")).toBeInTheDocument();
    expect(screen.getByText("Candidates")).toBeInTheDocument();
    expect(screen.getByText("Ops console")).toBeInTheDocument();
  });

  it("highlights the funnel link on /hr exactly", () => {
    pathname = "/hr";
    const { container } = render(<HRSubNav />);
    const funnel = container.querySelector('a[href="/hr"]');
    expect(funnel?.className).toContain("border-axis-magenta");
  });

  it("keeps the funnel link active on /hr/applications/<id>", () => {
    pathname = "/hr/applications/app-123";
    const { container } = render(<HRSubNav />);
    const funnel = container.querySelector('a[href="/hr"]');
    expect(funnel?.className).toContain("border-axis-magenta");
  });

  it("activates Requisitions on /hr/jobs/<id>", () => {
    pathname = "/hr/jobs/job-590321";
    const { container } = render(<HRSubNav />);
    const reqs = container.querySelector('a[href="/hr/jobs"]');
    expect(reqs?.className).toContain("border-axis-magenta");
  });
});
