# Axis Hiring Agent — Backend

FastAPI + Claude Agent SDK orchestrator for the Axis Bank internal hiring POC.
Stitches together intake, CV scoring, calendar scheduling (HR partner + panel),
Round 1 virtual interview, Round 2 panel, and final recommendation into one
autonomous funnel driven by checklist gates.

## Quick start

```bash
cd axis-hiring-agent-backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q                                   # 66 tests, green
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Hit `http://localhost:8000/health` — you should see `{"status":"ok","jobs":3,"candidates":5}`.

## Layout

```
app/
  models/domain.py          Pydantic v2 domain models + funnel enum
  store.py                  In-memory singleton (swap for Postgres later)
  fixtures.py               3 BDM JDs + 5 internal employees
  tools/
    intake.py               get_employee_profile / list_open_jds / get_jd
    scoring.py              score_cv_against_jd / score_transcript
    routing.py              move_cv (shortlisted vs rejected folders)
    checklists.py           templates, per-JD customisation, tick + gates
    messaging.py            Graph Mail.Send + notifications (outbox list)
    calendar.py             Graph getSchedule / createMeeting (in-memory)
    interview.py            run_virtual_interview + panel feedback collection
    decision.py             consolidate_recommendation + status updates
  agent.py                  The orchestrator — one function per funnel phase
  main.py                   FastAPI routes (/apply, /advance/r1, /advance/r2, ...)

tests/
  conftest.py               autouse reset of store + messaging + calendar + interview
  test_intake.py            Phase 1 — profile + JD resolution
  test_scoring.py           Phase 2 — CV match % + transcript scoring
  test_routing.py           Phase 2 — CV folder routing
  test_messaging.py         Phase 3 — email + HR/panel notifications
  test_calendar.py          Phase 3/6 — free/busy intersection + Teams meetings
  test_checklists.py        Phase 4/5 — templates, customisation, gate logic
  test_interview.py         Phase 5/6 — virtual interview + panel feedback
  test_decision.py          Phase 7 — offer / reject / hold consolidation
  test_agent_e2e.py         Full funnel: happy path, intake reject, R1 reject, panel reject
```

## Agent orchestration contract

`app/agent.py` is the "stitch" the meeting was about. It drives the full funnel
by calling tools in order and writing audit events at every step. The phases:

| Phase | Function                                | Effect                                                                 |
|-------|------------------------------------------|------------------------------------------------------------------------|
| 1-2   | `start_application`                      | Score CV, route to shortlisted/rejected folder, send regret if below  |
| 3-4   | `outreach_and_schedule_r1`               | Find common slot for candidate + HR partner, send email, create Teams |
| 5     | `run_r1`                                 | Run virtual interview, score transcript, post-R1 checklist            |
| 6     | `schedule_r2`                            | Find common slot across full panel + candidate, create Teams          |
| 7     | `finalise`                               | Collect panel feedback, consolidate, stage → OFFER/REJECTED/hold      |

When the Claude Agent SDK wrapper lands, `agent.py` is replaced with a
Claude-driven tool-use loop; the tool functions and observable effects stay
identical, so it's a drop-in swap.

## Seed demo data

```
job-590321  BDM Bhopal    panel: Neha (HR), Suresh (HM), Rajesh, Priya
job-592808  BDM Vadodara  panel: Amit (HR), Meera (HM), Deepak
job-595396  BDM Mysuru    panel: Lakshmi (HR), Vikram (HM), Sneha

cand-001  EMP10234  Rohan Verma    5.2y  5/6 skills   → happy path offer
cand-002  EMP10567  Ananya Iyer    6.8y  5/6 skills   → shortlisted
cand-003  EMP10891  Karthik Reddy  3.4y  3/6 skills   → below threshold
cand-004  EMP11023  Priya Nair     7.1y  6/6 skills   → top match (100%)
cand-005  EMP11544  Vikram Shah    1.5y  1/6 skills   → intake reject
```

## Swapping in real Microsoft Graph

The `calendar` and `messaging` modules are written so the POC in-memory impls
and the real Graph impls share the same function signatures. To flip:

1. Create an Azure AD app registration with `Mail.Send`, `Calendars.ReadWrite`,
   `OnlineMeetings.ReadWrite` delegated scopes on a dedicated test mailbox.
2. Replace the bodies of `get_free_busy`, `create_teams_meeting`, `send_email`
   with `httpx.AsyncClient` calls to `graph.microsoft.com/v1.0/...`.
3. Tests stay green because `conftest.py` still reset the in-memory state —
   integration tests go in `tests/integration/` behind an env flag.
