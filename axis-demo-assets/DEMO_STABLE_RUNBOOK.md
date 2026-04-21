# Axis Hiring Agent — Stable Demo Runbook

**Frozen baseline:** `demo-stable-2026-04-08`
**Last validated:** 2026-04-08 (15/15 E2E test cases green, golden E2E script @ ~90s)
**Owner:** Siddharth

This is the runbook for bringing up the **immutable, Axis-ready demo build**.
Everything here should be treated as read-only. All new work happens on
`feature/axis-enhancements-r1` and runs on a different set of ports — see
`DEV_WIP_RUNBOOK.md` (TBD) for that.

---

## 1. What's in this baseline

Three services, three repos:

| Service | Repo | Branch/Tag | Port |
|---|---|---|---|
| Frontend (Next.js) | `axis-hiring-agent-acs` | tag `demo-stable-2026-04-08` | **3001** |
| Backend (FastAPI) | `axis-hiring-agent-backend-acs` | tag `demo-stable-2026-04-08` | **8000** |
| Virtual Interviewer sidecar | `virtual-interviewer` | snapshot `_snapshots/virtual-interviewer-demo-stable-2026-04-08.tar.gz` | **8001** |

Live integrations wired up in the demo `.env`:

- Microsoft Graph (real Teams meeting creation + Outlook mail) on tenant `Xebia192.onmicrosoft.com`
- Anthropic Claude (resume parsing, NL job searcher, R1 transcript scoring, panel recommender)
- Virtual Interviewer sidecar (face_recognition gate + 5-question AI interview)

---

## 2. Restoring the stable build from scratch

If someone bricks the working tree, run this to get back to the exact morning demo:

```bash
# Frontend
cd axis-hiring-agent-acs
git fetch --tags
git checkout demo-stable-2026-04-08          # detached HEAD, that's fine
rm -rf .next node_modules
npm install

# Backend
cd ../axis-hiring-agent-backend-acs
git fetch --tags
git checkout demo-stable-2026-04-08          # detached HEAD
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Sidecar (no git repo — restore from the committed tarball)
cd ..
rm -rf virtual-interviewer
tar -xzf _snapshots/virtual-interviewer-demo-stable-2026-04-08.tar.gz
cd virtual-interviewer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then restore `.env` files from OneDrive version history (see §4).

---

## 3. Starting the three services (the exact working incantation)

Use the Claude Preview launch configs — never start services ad-hoc:

```
.claude/launch.json entries for stable:
  "axis-hiring-agent-acs (Next.js frontend)"             -> :3001
  "axis-hiring-agent-backend-acs (FastAPI backend)"      -> :8000
  "virtual-interviewer (AI Interview sidecar)"           -> :8000 (see note)
```

**⚠️ Port collision note:** the `virtual-interviewer` launch config as shipped
defaults to `:8000`, which collides with the backend. For the stable demo run
it manually on `:8001`:

```bash
cd virtual-interviewer
PORT=8001 HOST=127.0.0.1 .venv/bin/python run_axis_sidecar.py
```

Then confirm `.env` (see §4) has:

```
VIRTUAL_INTERVIEWER_URL=http://127.0.0.1:8001
```

Health check all three:

```bash
curl -s http://localhost:8000/health     # backend
curl -s http://localhost:8001/docs       # sidecar (Swagger HTML, HTTP 200)
curl -sI http://localhost:3001           # frontend (HTTP 200)
```

---

## 4. Required environment variables

Location: `axis-hiring-agent-backend-acs/.env` (gitignored)

Required keys — all must be present for the live demo to work:

```
AXIS_CALENDAR_PROVIDER=graph
AXIS_MESSAGING_PROVIDER=graph
AXIS_GRAPH_TENANT_ID=<tenant>
AXIS_GRAPH_CLIENT_ID=<app registration>
AXIS_GRAPH_CLIENT_SECRET=<secret>
AXIS_GRAPH_ORGANISER_UPN=axis-hiring-agent@Xebia192.onmicrosoft.com
AXIS_GRAPH_TIMEZONE=Asia/Kolkata
ANTHROPIC_API_KEY=<key>
AXIS_PANEL_RECOMMENDER=claude
AXIS_PANEL_RECOMMENDER_MODEL=claude-sonnet-4-6
VIRTUAL_INTERVIEWER_URL=http://127.0.0.1:8001
```

**NEVER let Claude edit this file.** Claude only edits `.env.example`. Humans
copy values over. `.env` is backed up via OneDrive version history — use
"Restore" from OneDrive if it ever gets clobbered.

---

## 5. Smoke test — the golden E2E script

Before ANY enhancement ships to main/integration, this must still pass:

```bash
python3 tests/e2e_external_flow.py
```

Expected output:

```
  GOLDEN E2E PASSED  ✅
  app_id: app-xxxxxxxx
  R1 score: ~80   final CTC: 28.5
```

Runtime: ~90 seconds (real Claude + real Graph + real sidecar).

What it validates, in order:

1. Backend `/health` + seeded jobs
2. `/external/intake` — Claude resume parse + NL job ranking
3. `/external/apply` — application creation
4. Orchestrator auto-screens and proposes R1 slots
5. Candidate confirms R1 slot → Graph creates Teams meeting
6. `/start-r1-interview` + `/virtual-interview/start` — face check gate
7. 5 answers submitted + finalise → Claude scores transcript
8. HR approves R2 with panel selection → Graph FindMeetingTimes
9. Candidate confirms R2 slot → Graph creates 2nd Teams meeting
10. 3 panel votes submitted → orchestrator advances to waiting_hr
11. HR R2 decision = offer → stage `offer_negotiation`
12. Offer team rollout with CTC → final stage `offer`

If this breaks, **stop shipping** and diagnose before merging anything.

---

## 6. Known gotchas from the 2026-04-08 demo

- **`.next` cache corruption:** if the frontend shows weird stale behavior
  after a branch switch, `rm -rf axis-hiring-agent-acs/.next && npm run dev`.
- **Stale dev server:** always `kill -9 $(lsof -ti:3001)` before restarting.
  Multiple Next.js servers on 3001 bind in weird ways.
- **Face detection 400:** `No face detected in the photo` means either
  (a) webcam hadn't warmed up before the candidate clicked Start, or
  (b) sidecar on wrong port. Verify `VIRTUAL_INTERVIEWER_URL` and that
  the sidecar is actually on :8001 not :8000.
- **HR R2 decision literal:** payload is `{"decision": "offer"}` (not
  `make_offer`) and `{"decision": "reject"}`. See `HrR2DecisionRequest`.
- **Persona switcher:** frontend stores persona in `localStorage` per
  hostname. `localhost:3001` and `127.0.0.1:3001` are **different origins**
  for storage — pick one and stick with it.

---

## 7. Enhancement workflow (where new Axis requirements go)

1. Start from the tag:
   ```bash
   git checkout feature/axis-enhancements-r1
   ```
2. Do work in small sub-branches off that integration branch:
   ```bash
   git checkout -b feature/axis-enhancements-r1/<slice-name>
   ```
3. Run on **WIP ports** (`:3101` / `:8100` / `:8101`) via the WIP launch
   configs — never touch the stable ports. See `.claude/launch.json`.
4. Merge each slice only after `python3 tests/e2e_external_flow.py`
   still passes green against the WIP backend:
   ```bash
   API_BASE=http://localhost:8100 python3 tests/e2e_external_flow.py
   ```
5. The `demo-stable-2026-04-08` tag is **never moved**. If Axis asks for the
   morning build, `git checkout demo-stable-2026-04-08` and it just works.

---

## 8. Contact and ownership

- Demo owner: Siddharth
- Questions about this runbook: add to the integration branch PR description.
- `feature/axis-enhancements-r1` is the single integration branch for all
  post-demo work. Don't add commits directly to the demo tag.
