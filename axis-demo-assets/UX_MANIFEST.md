# Axis Hiring Agent — UX Manifest

Single-file manifest of the **non-negotiable UX rules** for the Axis
Hiring Agent demo. Distilled from yesterday's full-flow walkthroughs of
the internal candidate flow plus all of the closed and parked items in
[`ISSUES.md`](./ISSUES.md) and the validation log in
[`axis-hiring-agent-backend-acs/MORNING_REVIEW_NOTES.md`](./axis-hiring-agent-backend-acs/MORNING_REVIEW_NOTES.md).

> **How this file is used.** Before any change to a candidate-, HR-, or
> panel-facing surface, Claude must re-read this file and the section in
> `ISSUES.md` for the same surface. Any change that lands without
> matching every applicable rule below is **not done**, regardless of
> what the tests say.

The rules apply to **both** the internal Thrive flow *and* the external
candidate flow (`/external/intake`, `/external/results`,
`/external/status/[appId]` → `/thrive/status/[appId]`,
`/external/applications`). The two flows share the same status page,
the same orchestrator, the same scoring pipeline, and the same Graph
calls — which means a regression on the internal page is automatically
a regression on the external page, and vice versa.

---

## Rule 1 — Real Claude API on the demo path, never deterministic

**Why:** Yesterday's review (MORNING_REVIEW_NOTES §2 + memory note
`feedback_real_claude_api.md`). The deterministic fallbacks exist so
unit tests stay hermetic and so the demo doesn't 500 on a network blip
— they are **never** the path the user sees during the live
walkthrough.

**Enforcement:**

- `ANTHROPIC_API_KEY` MUST be set in `axis-hiring-agent-backend-acs/.env`
  before the demo backend starts. No key → no demo.
- The four AI services that can fall back must default to `claude` and
  must surface `source: "claude" | "deterministic"` on every response so
  the UI can prove which path was taken:
  - `app/services/claude_resume_matcher.py` (`AXIS_RESUME_MATCHER`)
  - `app/services/claude_salary_extractor.py` (`AXIS_SALARY_EXTRACTOR`)
  - `app/services/claude_job_searcher.py` (`AXIS_JOB_SEARCHER`)
  - `app/services/claude_panel_recommender.py` (`AXIS_PANEL_RECOMMENDER`)
- Every UI surface that consumes these responses MUST render a
  visible `· powered by Claude` badge when `source === "claude"` and
  a visible `Token-based fallback (Claude unreachable)` warning when
  `source === "deterministic"`. Already implemented on
  `/external/results` (search section + AI section + comp card) and
  must be preserved.
- Tests force the deterministic path by setting `AXIS_*=deterministic`
  in fixtures. Production demo never sets these.

## Rule 2 — Visible processing UI for every AI call

**Why:** Memory note `feedback_visible_loading_state.md`. A silent 19s
Claude call reads as a broken page; a 19s call with rotating status
strings + a progress bar reads as "the agent is doing the work in
front of me".

**Enforcement:**

- Every call site that hits a Claude-backed endpoint MUST render a
  spinner + descriptive copy + (where the call is multi-stage) a step
  walker that animates while the request is in flight.
- The intake page (`/external/intake`) already implements this: 7-step
  walker, rotating every 1.5s, with a 7-segment progress bar
  highlighted up to the current step. **Do not regress this.**
- The status page (`/thrive/status/[appId]`, shared with external)
  must show "AI Interview Agent is running Round 1 — capturing the
  transcript and scoring against the JD rubric" while
  `r1_started === true && stage === "r1_scheduled"`.
- The HR panel-feedback page must show "Claude is reading the
  transcript…" when the panel-recommender call is in flight.
- Apply → screening transition is the one place this is still missing
  (UX-003 in ISSUES.md, parked). Backend has `AXIS_SCREEN_*_DELAY_SEC`
  env vars; frontend needs to subscribe and render each stage.

## Rule 3 — Identity is what the candidate typed, not what the regex pulled

**Why:** Bug we just fixed. `/external/apply` was re-running
`parse_resume()` on the resume text and silently overwriting the
candidate's email with whatever the regex found in the resume header.
Result: tracker page returned `[]` because the candidate was keyed on
the wrong email.

**Enforcement:**

- `ExternalApplyRequest` carries optional `name` + `email` overrides.
  `lib/api.ts::externalApply` must always forward `stash.profile.name`
  and `stash.profile.email` from the intake response. Backend must
  prefer those overrides over the resume regex when persisting.
- New regression test:
  `tests/test_external_e2e_flow.py::test_tracker_lists_applications_by_email`.
  Don't delete it.

## Rule 4 — Slot picker disappears the moment a slot is booked

**Why:** BUG-003 in ISSUES.md. After R1 was booked the picker stayed
on screen and the page kept asking the candidate to book again.

**Enforcement:**

- Slot picker render condition is **strictly**:
  `stage === "screened" && agent_status === "waiting_candidate" && proposed_r1_slots.length > 0`
  for R1, and the analogous R2 condition for R2.
- The moment `stage === "r1_scheduled"` (or `r2_scheduled`), the
  picker hides and `BookedInterviewCard` takes over showing
  date / time / Teams join URL / Reschedule.
- Same condition applies on the external status page (which is the
  internal status page via redirect). Don't introduce a divergent copy.

## Rule 5 — Backend-restart safety: stale React state must not fire dead actions

**Why:** BUG-006 in ISSUES.md. The status page rendered cached app
data after a backend restart wiped the in-memory store, then fired
actions against a 404 app id.

**Enforcement:**

- Every page that loads an application by id MUST clear cached state
  on a 404 from the loader and render the "this application no longer
  exists — re-apply" empty state with a CTA back to the relevant
  persona home.
- Already implemented on `/thrive/status/[appId]`. The external
  status redirect inherits this. Don't break it.

## Rule 6 — HR approves; the agent orchestrates

**Why:** BUG-007 + DESIGN-001 in ISSUES.md. The original R2-prep flow
made the HR partner manually tick checklist items to do exactly the
orchestration the agent is supposed to do — the opposite of the
product pitch.

**Enforcement:**

- The HR application detail page must NOT render a clickable checklist
  to advance the funnel. The checklist is read-only audit, hidden
  behind a "Why is this paused?" disclosure.
- HR sees a single "Approve and propose panel" green button (with
  per-panel slot preview, BUG-010 fix) and a "Send back to agent" red
  one. Approve → orchestrator computes slots → candidate picks from
  Thrive → invite locks all 3 diaries.
- The post-approval state panel (BUG-015 fix) MUST tell HR the
  orchestrator is now waiting on the candidate, and show which
  3 slots were offered.

## Rule 7 — Panels are visibly distinct, slot previews are real

**Why:** BUG-008, BUG-013 in ISSUES.md. Multiple seeded panels shared
the same member list and the per-panel slot preview was identical
across panels (because stub mailboxes were always-free).

**Enforcement:**

- Each seeded panel in graph mode must have a distinct roster.
- `_stub_busy_blocks` deterministically hashes the stub UPN to a
  morning + afternoon busy block per weekday so different rosters
  produce different intersections. Don't revert.
- HR approval card always renders 3 candidate slot chips per panel
  ("Candidate slot preview") sourced from
  `GET /applications/{id}/r2-slots-by-panel`.

## Rule 8 — Scoring is realistic, not saturated

**Why:** BUG-005 in ISSUES.md. Rubric was saturating at 100/100 across
every skill, which read as hard-coded.

**Enforcement:**

- R1 scorer is the 4-signal rubric (coverage + depth + evidence +
  reinforcement). Per-skill ceiling 99, overall ceiling 97. Don't
  revert to binary keyword match.
- `_strong_transcript(jd)` walks the JD's `required_skills` and emits
  one substantive Q&A per skill with quantified evidence (₹ amounts,
  %, NPS lift). Don't hard-code CASA / corporate-salary phrases — that
  collapses scoring for any other JD (MORNING_REVIEW_NOTES §1).

## Rule 9 — Compensation always wins forward; identity overrides do too

**Why:** Returning external candidates apply to a 2nd JD with a fresh
salary slip. The intake-form data must merge forward into the existing
candidate record without clearing fields.

**Enforcement:**

- `tools/external_intake.apply_external` upserts the candidate by
  email; on second visit, it merges only the **non-empty** fields
  forward. Compensation always wins if the new upload extracted
  something.
- Same rule for `name`, `current_role`, `current_location`,
  `tenure_years`, `skills`. Never clear an existing field with `None`.

## Rule 10 — One success banner per cleared round (UX-001, parked)

**Why:** Parked but explicitly called out. The R1-cleared narrative on
the status page buries the win in plain text.

**Status:** Not yet implemented. When fixed, a strong "✓ Round 1
cleared" success banner (axis-magenta strip + checkmark + next-step
strip) must render whenever `stage === "r1_done"` on
`/thrive/status/[appId]`. Same banner for R2 cleared and for offer
accepted. Do this once on the shared status page so internal *and*
external candidates both get it.

## Rule 11 — `/10` and `/100` never appear on the same screen

**Why:** Yesterday's panel-vote score-scale fix
(MORNING_REVIEW_NOTES §2). Slider, form, peer-vote display, and HR
detail page all render scores in 0–100. The `/10` was confusing.

**Enforcement:** All score displays use `/100`. Slider anchor labels
read `0 · no_hire | 70 · advance bar | 100 · strong_hire`.

## Rule 12 — Validation gauntlet before declaring done

**Why:** ISSUES.md §"Validation gauntlet". Pytest passing alone is not
sufficient — it cannot detect "backend restart wipes the in-memory
store and invalidates the browser's cached app id" type bugs.

**Enforcement:** Before reporting any task complete, Claude MUST run:

| Layer | Command |
|-------|---------|
| Unit | `cd axis-hiring-agent-backend-acs && .venv/bin/python -m pytest -q` |
| Type | `cd axis-hiring-agent-acs && ./node_modules/.bin/tsc --noEmit` |
| Live curl smoke | `curl` against the running uvicorn for the exact user flow being changed |
| Browser walk | The user (or Claude with Chrome MCP) walks the affected screen |

---

## External pages — current rule compliance

| Page | Rule 1 (Claude src) | Rule 2 (visible processing) | Rule 3 (identity) | Rule 4 (slot picker) | Rule 5 (404 safety) | Rule 10 (cleared banner) |
|------|---------------------|------------------------------|--------------------|-----------------------|----------------------|----------------------------|
| `/external/intake` | n/a | ✓ 7-step walker | ✓ form fields are source-of-truth | n/a | n/a | n/a |
| `/external/results` | ✓ Claude badges on search + AI + comp | ✓ inherited from intake submit | ✓ stash carries form name/email | n/a | ✓ no-stash empty state | n/a |
| `/external/applications` (tracker) | n/a | n/a | ✓ queries by typed email | n/a | ✓ empty state | n/a |
| `/external/status/[appId]` (→ shared `/thrive/status/[appId]`) | n/a (no Claude calls here) | ✓ R1-running narrative | ✓ uses persisted candidate | ✓ BUG-003 fix | ✓ BUG-006 fix | ✗ UX-001 parked |

The single open gap is **Rule 10 / UX-001** on the shared status page.
That fix is parked in ISSUES.md and will land in the post-demo UX
pass — it does not block the demo, but Claude MUST flag it the next
time the status page is touched.

---

## L1 / R1 Virtual Interviewer integration

Verified during this session. The team's AI-powered interview agent is
wired into R1 via two parallel paths, both feeding the same
`InterviewRecord.transcript` → `score_interview_transcript()` pipeline:

1. **Virtual Interviewer (text Q&A)** —
   `app/services/virtual_interviewer.py`. Endpoints:
   - `POST /applications/{id}/virtual-interview/start`
   - `GET  /applications/{id}/virtual-interview/status`
   - `POST /applications/{id}/virtual-interview/answer`
   - `POST /applications/{id}/virtual-interview/finalise`

2. **ACS Teams Bot (real-time, agent speaks to candidate over Teams)** —
   `app/services/acs_interview_bot.py`. Endpoints:
   - `POST /applications/{id}/acs-interview/start`
   - `GET  /applications/{id}/acs-interview/status`
   - `POST /applications/{id}/acs-interview/finalise`
   - The bot joins the Teams meeting via the
     `interview.teams_join_url` Graph URL and conducts a real
     conversation; transcript is folded into `InterviewRecord` on
     finalise.

Both paths kick off from the candidate-side "Start interview" button
on `/thrive/status/[appId]` (which is the shared status page used by
both internal and external candidates) → `POST /applications/{id}/start-r1-interview`
→ orchestrator dispatches to whichever path is configured.

**Gap:** Real Teams transcript ingestion via Graph webhook (DESIGN-001
chunk 5) is parked. Fallback for the demo is the paste-into-textarea
flow on the panel feedback page. User accepted this for v1.

---

## Pointers

- Bug + design tracker: [`ISSUES.md`](./ISSUES.md)
- Yesterday's full-flow validation log:
  [`axis-hiring-agent-backend-acs/MORNING_REVIEW_NOTES.md`](./axis-hiring-agent-backend-acs/MORNING_REVIEW_NOTES.md)
- Architecture + rationale:
  [`AXIS_HIRING_AGENT_PLAN.md`](./AXIS_HIRING_AGENT_PLAN.md)
- Memory notes (Claude's persistent feedback log):
  - `feedback_real_claude_api.md`
  - `feedback_visible_loading_state.md`
  - `project_axis_hiring_agent.md`
