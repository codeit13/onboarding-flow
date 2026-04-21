// The job recommendation card — this is the single most important component.
// Clicking Apply is the hook that fires the agent in the real flow.
//
// The card view-model is a flattened projection of the backend Job + a
// preview match score the Thrive page computes locally (mirrors the
// backend `scoring.py` formula). Inlined here so we don't drag a stale
// fixtures module along for the ride.
export type JobCardView = {
  id: string;
  jobId: string;
  matchPercent: number;
  title: string;
  band: string;
  tags: string[];
  location: string;
  applicants: number;
  highSkillMatch: boolean;
};

export function JobCard({
  job,
  onApply,
}: {
  job: JobCardView;
  onApply?: (jobId: string) => void;
}) {
  return (
    <article className="bg-axis-canvas border border-axis-divider rounded-card shadow-card hover:shadow-card-hover transition p-4 relative">
      {/* High Skill Match chip — top right */}
      {job.highSkillMatch && (
        <span className="absolute top-0 right-6 bg-axis-pink-soft text-axis-magenta text-[11px] font-semibold px-3 py-1 rounded-b">
          High Skill Match
        </span>
      )}

      {/* Bookmark + share icons */}
      <div className="absolute top-3 right-3 flex gap-2 text-axis-muted-light">
        <button aria-label="Bookmark" className="hover:text-axis-magenta">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
          </svg>
        </button>
        <button aria-label="Share" className="hover:text-axis-magenta">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
          </svg>
        </button>
      </div>

      <div className="flex items-center gap-5 pr-24">
        {/* Left cluster — teal match % circle */}
        <div className="shrink-0 flex flex-col items-center gap-1">
          <div className="w-[72px] h-[72px] rounded-full border-[3px] border-axis-teal-dark bg-axis-teal flex items-center justify-center text-white font-bold text-xl">
            {job.matchPercent}%
          </div>
          <div className="w-10 h-5 rounded bg-axis-pink-soft" aria-hidden />
        </div>

        {/* Middle cluster — title + meta */}
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-axis-ink text-base leading-snug">{job.title}</h3>
          <div className="flex items-center gap-3 mt-1.5 text-xs text-axis-muted">
            <span className="flex items-center gap-1">
              <UserIcon />
              {job.band}
            </span>
            <span>•</span>
            <span>{job.tags.join(", ")}</span>
            <span>•</span>
            <span className="flex items-center gap-1">
              <LocationIcon />
              {job.location}
            </span>
          </div>
          <p className="text-xs text-axis-muted-light mt-1">
            Job ID : {job.jobId} | {job.applicants} applicant{job.applicants === 1 ? "" : "s"}
          </p>
        </div>
      </div>

      {/* Apply button — bottom right */}
      <div className="flex justify-end mt-3">
        <button
          onClick={() => onApply?.(job.id)}
          className="px-6 py-1.5 border border-axis-magenta text-axis-magenta text-sm font-medium rounded hover:bg-axis-magenta hover:text-white transition"
        >
          Apply
        </button>
      </div>
    </article>
  );
}

function UserIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

function LocationIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}
