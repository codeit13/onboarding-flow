import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ApplyConfirmModal } from "@/components/thrive/ApplyConfirmModal";
import type { Candidate, Job } from "@/lib/api";

const job: Job = {
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
};

const candidate: Candidate = {
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
};

describe("ApplyConfirmModal", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <ApplyConfirmModal
        open={false}
        job={job}
        candidate={candidate}
        matchPercent={88}
        matchedSkills={["sales", "liabilities"]}
        missingSkills={["kyc"]}
        submitting={false}
        onCancel={() => undefined}
        onConfirm={() => undefined}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows the JD title, the match %, matched and missing skills, and the next-steps narrative", () => {
    render(
      <ApplyConfirmModal
        open
        job={job}
        candidate={candidate}
        matchPercent={88}
        matchedSkills={["sales", "liabilities"]}
        missingSkills={["kyc"]}
        submitting={false}
        onCancel={() => undefined}
        onConfirm={() => undefined}
      />,
    );
    expect(screen.getByText("Business Development Manager")).toBeInTheDocument();
    expect(screen.getByText("88%")).toBeInTheDocument();
    expect(screen.getByText(/Matched skills/)).toBeInTheDocument();
    expect(screen.getByText("✓ sales")).toBeInTheDocument();
    expect(screen.getByText("kyc")).toBeInTheDocument();
    expect(screen.getByText(/Screen your profile against the JD/)).toBeInTheDocument();
    expect(screen.getByText(/Propose 3 Round 1 interview slots/)).toBeInTheDocument();
    expect(screen.getByText(/Run the Round 1 AI interview/)).toBeInTheDocument();
    expect(screen.getByText(/Coordinate Round 2 with the hiring panel/)).toBeInTheDocument();
  });

  it("calls onConfirm when the primary CTA is clicked", () => {
    const onConfirm = vi.fn();
    render(
      <ApplyConfirmModal
        open
        job={job}
        candidate={candidate}
        matchPercent={88}
        matchedSkills={["sales"]}
        missingSkills={[]}
        submitting={false}
        onCancel={() => undefined}
        onConfirm={onConfirm}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Submit application to AI agent/i }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("disables the CTA and shows a busy label while submitting", () => {
    render(
      <ApplyConfirmModal
        open
        job={job}
        candidate={candidate}
        matchPercent={88}
        matchedSkills={[]}
        missingSkills={[]}
        submitting
        onCancel={() => undefined}
        onConfirm={() => undefined}
      />,
    );
    const cta = screen.getByRole("button", { name: /Submitting to agent/i });
    expect(cta).toBeDisabled();
  });
});
