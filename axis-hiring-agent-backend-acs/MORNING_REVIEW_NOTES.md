# Morning Review — End-to-End Validation (2026-04-07)

You asked me to walk both the internal and external candidate flows
end-to-end while you slept, verify Teams + Outlook on Graph, and fix
UI/UX issues. Here is what I found and what I changed.

## TL;DR

- **Both flows go all the way to OFFER**, with real Teams meetings
  created on Graph and real Outlook emails sent.
- **All 81 backend tests pass.** Frontend `tsc --noEmit` is clean.
- **3 issues found and fixed** before the demo (details below).
- **2 demo gotchas** you should know about but I did not auto-fix.

---

## Internal flow (Rohan Desai → BDM Bhopal) ✓

```
applied → screened → r1_scheduled → r1_done → r2_scheduled → OFFER
```

- POST `/apply` returned match 88.3% in <1s.
- Calendar intersection ran against `rohan.desai@Xebia192.onmicrosoft.com`
  + `meera.nair@Xebia192.onmicrosoft.com` — both real Graph mailboxes,
  3 common slots returned.
- Outreach email sent (real Graph send) with the 3 slots.
- After confirm-slot, a real Teams meeting was created — verified the
  `teams_join_url` is a `https://teams.microsoft.com/...` join link.
- R1 scored 91/100, advance.
- HR-approved panel `panel-bdm-central`, picked R2 slot, real R2 Teams
  meeting created.
- 3 panel votes (88/100 hire each) → orchestrator went to `offer`,
  rationale `R1 91, R2 avg 88`.

## External flow (Siddharth Goyal docx → Branch Manager Pune) ✓

```
upload .docx → Claude match → applied → screened → r1_scheduled →
r1_done → r2_scheduled → OFFER
```

- POST `/external/parse-resume-file` with the rich .docx returned
  `source: claude` (~19s end-to-end), 20 skills extracted, top match 95%
  Branch Manager Flagship with an evidence-based rationale citing the
  candidate's ₹820cr book and audit clearance.
- Apply route created an external candidate with `candidate_kind: "external"`.
- Orchestrator branched correctly: only HR partner's calendar was
  intersected (no fake candidate calendar lookup).
- Real Outlook email sent to the external email address (and bounced
  Undeliverable, see "demo gotcha #1" below — that's what's *supposed*
  to happen for an unverified address; the send is real).
- After confirm-slot, real R1 Teams meeting created on Graph.
- After R2 scheduling + 3 panel votes (90/100), orchestrator hit `offer`.

## Graph integration ✓

`curl /debug/calendar?application_id=app-…` shows real Microsoft Graph
event IDs (`AAMkADY4...`) for both R1 and R2 meetings, with real Teams
join URLs starting with `https://teams.microsoft.com/l/meetup-join/...`.

`curl /debug/emails` shows real outbound mail and real `[in]` traffic
including bounce-backs (`MicrosoftExchange329e71ec88ae4615...`) — this
proves the agent is genuinely talking to Outlook, not a stub.

The inbox poller is running as a daemon thread; manual tick via
`POST /external/poll-inbox` returned `{dispatched: 1}`.

---

## Issues found and fixed

### 1. R1 score collapsed for any JD other than corporate-salary

**What was wrong:** the `_strong_transcript()` in `app/orchestrator.py`
was hard-coded to talk about CASA cross-sell + corporate salary
acquisition. Any candidate applying to a *different* JD (e.g. Branch
Manager Flagship, Wealth RM) had their R1 transcript score the JD
required-skills rubric at ~41/100 because the canned answers didn't
mention any of that JD's required skills. This made the external
flow score 41 and reject Siddharth even though Claude had matched
him at 95%.

**Fix:** rewrote `_strong_transcript(jd)` to walk the JD's
`required_skills` and emit one substantive Q&A per skill with
quantified evidence (₹ amounts, %, NPS lift, audit pass rate). The
rubric scorer now hits coverage + depth + evidence + reinforcement
on every required skill for any JD. Re-validated: external flow
now scores 97/100 for the same candidate against the same JD.

**File:** `app/orchestrator.py:93-180`, `:643`

### 2. Panel vote score scale was ambiguous (`/10` vs `/100`)

**What was wrong:** the panel feedback page rendered peer votes as
`{f.score}/10` while the slider, the form, the HR detail page, and
the orchestrator's verdict logic all use 0–100. A panellist looking
at "your peers voted 88/10" would think the system was broken.

**Fix:**
- `app/panel/feedback/[appId]/page.tsx`: peer-vote display switched
  to `{score}/100`. Slider label now reads `Overall score: 88/100`
  with `0 · no_hire | 70 · advance bar | 100 · strong_hire` anchors
  underneath so panellists know exactly how to vote.
- `app/hr/applications/[appId]/page.tsx`: same `/10 → /100` fix.

### 3. Frontend type mismatch on `parseResult.source`

**What was wrong:** the external page added a `Parsed by Claude`
banner that read `parseResult.source`, but the return type of
`api.externalParseResumeFile` did not include the `source` field.
`tsc --noEmit` failed with TS2339, blocking the Next.js build.

**Fix:** added `source: "claude" | "deterministic"` to the return
type in `lib/api.ts:541-573`. tsc clean.

### 4. Home page persona count

Cosmetic — copy still said "Three personas" after the External
Candidate card was added. Fixed to "Four personas".

---

## Demo gotchas you should know about (not auto-fixed)

### Gotcha 1 — Email bounces from `@axisbank.test` and `@stub.local`

A bunch of seed candidates and panel members have stub email
addresses (`vikram.shah@axisbank.test`, `rajesh.menon@stub.local`,
etc.). Real Graph send IS firing for them — they bounce back as
"Undeliverable" from `MicrosoftExchange329e71ec88ae4615...`. The
bounces fill up the polled inbox feed.

**Why I left it:** the bounces actually *prove* Graph is real, not
mocked. But if you want a clean demo, swap the seed addresses for
real Xebia192 mailboxes. The two real ones already in the system
are `rohan.desai@Xebia192.onmicrosoft.com`,
`meera.nair@Xebia192.onmicrosoft.com`,
`suresh.kumar@Xebia192.onmicrosoft.com`,
`axis-hiring-agent@Xebia192.onmicrosoft.com`.

For the **internal demo**, prefer Rohan Desai (EMP10234) — his
email is real and the meeting invite will land in his inbox.

### Gotcha 2 — External candidate email address

Sample resume uses `siddharth.goyal@xebia.com`, which bounces. For
the live demo, edit the .docx (or set `AXIS_DEMO_EXTERNAL_EMAIL`)
to a real mailbox you control so the candidate side of the email
thread is visible during the walkthrough.

---

## Suggested demo script

1. **Open `/`** — show the four-persona landing.
2. **Reset & seed** from the top bar so the funnel is populated.
3. **Internal flow** — `/thrive`, apply as Rohan Desai to BDM Bhopal,
   watch the orchestrator advance through the funnel; confirm slots,
   start R1, show the AI report, switch to `/panel`, vote, watch the
   stage flip to `offer`.
4. **External flow** — `/external`, upload `Siddharth_Goyal_Resume.docx`,
   show the visible Claude processing UI (rotating status strings + spinner),
   show Claude-source banner + ranked jobs, click Apply on the top match,
   walk the same R1/R2 path. The `Demo helper · simulate the email reply`
   panel lets you advance the orchestrator without waiting for real mail.
5. **Show `/hr` and `/panel`** to prove every persona sees the same
   underlying state.

---

## Test status

- Backend pytest: `81 passed in 0.27s`
- Frontend `tsc --noEmit`: clean
- Backend uvicorn: running on :8000 with `--reload`
- All providers: `GraphCalendarProvider`, `GraphMessagingProvider`
  (verified via `/health`)
