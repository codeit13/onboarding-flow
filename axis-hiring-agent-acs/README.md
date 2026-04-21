# Axis Hiring Agent — POC Frontend

Next.js 14 + Tailwind scaffold for the three-screen visual slice:

1. **`/thrive`** — Thrive portal lookalike (employee entry point, mirrors `thriveuat.axisbank.com`).
2. **`/hr`** — HR partner funnel kanban with seven stages (Applied → Offer/Rejected).
3. **Candidate drawer** — right-slide panel on the HR page with Overview / Checklists / Transcript / Audit tabs.

The autonomous Claude agent will be plugged in behind the `Apply` button on `/thrive` and every state transition on `/hr`.

## Prerequisite — install Node.js

This scaffold is written but **not yet installed** on your machine. The build
machine used to draft it didn't have `node`/`npm` on `PATH`, so neither
`npm install` nor the Vitest suite has been run here. Install Node 20+ before
running anything below:

```bash
brew install node          # or use nvm: nvm install 20 && nvm use 20
node --version             # expect v20.x
```

## Run it

```bash
cd axis-hiring-agent
npm install
npm run test               # Vitest suite (fixtures + 4 component tests)
npm run dev                # Next.js dev server on :3000
```

Open http://localhost:3000 — the landing page links to both `/thrive` and `/hr`.

> **OneDrive note:** this folder lives inside OneDrive. If `npm install` is slow or file-watchers flake, move `axis-hiring-agent/` out of OneDrive — the code has no hard dependency on this path.

## Design system

**One source of truth: `tailwind.config.ts`.**

Every color in every component is a token (`axis.burgundy`, `axis.magenta`, `axis.teal`, `axis.pink-soft`, etc.). No hardcoded hex values anywhere outside that config. When Sumit / Ahmed Kumar share the official Thrive FlutterFlow theme, swap the token values in `tailwind.config.ts` and the whole app re-themes.

The only authoritative value today is `axis.burgundy = #97144C` (Axis Bank's public brand primary). Everything else is calibrated from the Thrive home screenshot.

**Fonts:**
- `font-sans` → Inter (body, UI)
- `font-display` → Fraunces (the "Welcome to thrive" banner only)

Both are pulled from Google Fonts in `app/globals.css`.

## Structure

```
app/
├── page.tsx              landing (links to /thrive and /hr)
├── thrive/page.tsx       Thrive lookalike home
└── hr/page.tsx           HR kanban + drawer host

components/
├── thrive/
│   ├── TopBar.tsx         burgundy app bar with Axis + thrive lockup
│   ├── LeftRail.tsx       narrow icon nav (Home / OLL / UP)
│   ├── HeroBanner.tsx     pink "Welcome to thrive" banner
│   ├── NotificationStrip.tsx
│   ├── JobCard.tsx        89% teal badge + High Skill Match chip + Apply
│   ├── RightRail.tsx      promo + Quick Links grid
│   └── Footer.tsx
└── hr/
    ├── KanbanColumn.tsx
    ├── CandidateCard.tsx
    └── CandidateDrawer.tsx   Overview / Checklists / Transcript / Audit tabs

lib/
└── fixtures.ts            3 JDs (Bhopal/Vadodara/Mysuru) + 5 candidates
                           Seeded to cover every funnel stage

docs/reference/
└── thrive-home.png        (drop the screenshot here for side-by-side diffing)
```

## Diff-against-screenshot discipline

Every PR that touches `components/thrive/*` or `app/thrive/page.tsx` should be visually diff'd against `docs/reference/thrive-home.png`. The whole point of this POC is that Piyush sees the demo and recognises it as "his" portal.

**Known gaps on the first pass** (all cheap to close once we have assets):
- Hero banner uses a CSS-drawn silhouette placeholder — swap for the real people photo when supplied.
- Axis logo is a simple rotated-square stand-in — replace with the official SVG lockup.
- Quick Links icons are generic placeholder squares — replace with the real UP-Catalyst / Transfer / HRespo icon set.
- Left rail icons are traced from memory of the screenshot — verify against the real portal.

None of these affect the layout, typography, or token palette. They're asset swaps.

## What comes next

- Wire `Apply` on `/thrive` to a real `POST /api/apply` endpoint (FastAPI backend).
- Backend agent orchestrator (Python + FastAPI + Claude Agent SDK) with the 20 tools from `AXIS_HIRING_AGENT_PLAN.md` §4.
- Microsoft Graph integration for HR partner + panel calendar reads and Teams meeting creation.
- Plug in the existing Virtual Interview Agent behind `run_virtual_interview`.

See `../AXIS_HIRING_AGENT_PLAN.md` for the full plan.
