import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { JobCard, type JobCardView } from "@/components/thrive/JobCard";

const job: JobCardView = {
  id: "job-590321",
  jobId: "590321",
  matchPercent: 88,
  title: "Business Development Manager",
  band: "AM",
  tags: ["Sales", "Liabilities"],
  location: "Bhopal",
  applicants: 3,
  highSkillMatch: true,
};

describe("JobCard", () => {
  it("renders the title, band, location, applicants and match %", () => {
    render(<JobCard job={job} />);
    expect(
      screen.getByText("Business Development Manager"),
    ).toBeInTheDocument();
    expect(screen.getByText("88%")).toBeInTheDocument();
    expect(screen.getByText("Bhopal")).toBeInTheDocument();
    expect(screen.getByText(/Job ID : 590321/)).toBeInTheDocument();
    expect(screen.getByText(/3 applicants/)).toBeInTheDocument();
  });

  it("shows the High Skill Match chip when true", () => {
    render(<JobCard job={job} />);
    expect(screen.getByText("High Skill Match")).toBeInTheDocument();
  });

  it("hides the High Skill Match chip when false", () => {
    render(<JobCard job={{ ...job, highSkillMatch: false }} />);
    expect(screen.queryByText("High Skill Match")).not.toBeInTheDocument();
  });

  it("fires onApply with the job id when Apply is clicked", () => {
    const onApply = vi.fn();
    render(<JobCard job={job} onApply={onApply} />);
    fireEvent.click(screen.getByText("Apply"));
    expect(onApply).toHaveBeenCalledWith("job-590321");
  });
});
