# Axis Hiring Demo — Local Setup Guide

One-time install to run the full demo (frontend + backend + virtual interviewer) on your local machine, exactly mirroring Siddharth's working setup.

---

## Pre-requisites

- **Python 3.9** (exact major/minor — use pyenv if your system Python differs)
- **Node.js 18+ LTS** (or 20 LTS)
- **Git**
- **macOS or Linux** (Windows untested — use WSL2 if on Windows)

Ports 8100, 3101, and 8101 must be free.

---

## One-time setup (~20 min)

### 1. Clone all four repos into a single parent folder

Use a **non-synced** folder (not OneDrive / Dropbox / iCloud) to avoid `.venv` and `node_modules` chaos.

```bash
mkdir ~/axis-demo && cd ~/axis-demo
git clone https://github.com/siddharthgoyalxebia/axis-hiring-agent-backend-acs.git
git clone https://github.com/siddharthgoyalxebia/axis-hiring-agent-acs.git
git clone https://github.com/siddharthgoyalxebia/virtual-interviewer.git
git clone https://github.com/siddharthgoyalxebia/axis-demo-assets.git
```

### 2. Check out the known-good branches

The stable demo snapshot lives on specific branches:

```bash
cd ~/axis-demo/axis-hiring-agent-backend-acs && git checkout candidate-engagement/backend
cd ~/axis-demo/axis-hiring-agent-acs && git checkout candidate-engagement/frontend
# virtual-interviewer defaults to main
# axis-demo-assets defaults to main
```

Optional: pin to the exact demo tag for absolute safety:
```bash
cd ~/axis-demo/axis-hiring-agent-backend-acs && git checkout pre-demo-backup-20260414-2327
cd ~/axis-demo/axis-hiring-agent-acs && git checkout pre-demo-backup-20260414-2327
```

### 3. Paste secrets from 1Password into .env files

Siddharth will share a 1Password vault with three secure notes. Copy each into the right file:

| 1Password note | Destination file |
|---|---|
| `axis-hiring-agent-backend-acs/.env` | `~/axis-demo/axis-hiring-agent-backend-acs/.env` |
| `axis-hiring-agent-acs/.env.local` | `~/axis-demo/axis-hiring-agent-acs/.env.local` |
| `virtual-interviewer/.env` | `~/axis-demo/virtual-interviewer/.env` |

**Never commit these `.env` files** — all three repos have `.env*` in `.gitignore`.

### 4. Seed runtime data so your demo starts pre-populated

```bash
mkdir -p ~/axis-demo/axis-hiring-agent-backend-acs/data
cp ~/axis-demo/axis-demo-assets/backend-data-seed/*.json ~/axis-demo/axis-hiring-agent-backend-acs/data/
```

This gives you the same applications, candidates, and bulk-screening pools Siddharth uses.

### 5. Copy test CVs to your Desktop

The bulk-screening demo flow expects test CVs at `~/Desktop/test-cvs`:

```bash
cp -R ~/axis-demo/axis-demo-assets/test-cvs ~/Desktop/test-cvs
```

### 6. Install dependencies

**Terminal 1 — Backend:**
```bash
cd ~/axis-demo/axis-hiring-agent-backend-acs
python3 -m venv .venv
source .venv/bin/activate       # Windows (WSL): source .venv/bin/activate
pip install -r requirements.txt
```

**Terminal 2 — Virtual Interviewer:**
```bash
cd ~/axis-demo/virtual-interviewer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Terminal 3 — Frontend:**
```bash
cd ~/axis-demo/axis-hiring-agent-acs
npm install
```

### 7. Start all three services

**Terminal 1 — Backend:**
```bash
cd ~/axis-demo/axis-hiring-agent-backend-acs && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8100
```
⚠️ **Do NOT use `--reload` during a live demo.** File-system events (OneDrive / editor save) can wipe in-memory state mid-request.

**Terminal 2 — Virtual Interviewer:**
```bash
cd ~/axis-demo/virtual-interviewer && source .venv/bin/activate
# Start command — ping Siddharth for the exact invocation. Typically:
# python main.py
# or
# uvicorn main:app --host 127.0.0.1 --port 8101
```

**Terminal 3 — Frontend:**
```bash
cd ~/axis-demo/axis-hiring-agent-acs
npm run dev
```

### 8. Health check

Open a 4th terminal and run:
```bash
curl -s -o /dev/null -w "backend:  %{http_code}\n" http://localhost:8100/jobs
curl -s -o /dev/null -w "frontend: %{http_code}\n" http://localhost:3101
curl -s -o /dev/null -w "vi:       %{http_code}\n" http://localhost:8101
```

All three should return `200`. If any fail — check the respective terminal for errors.

### 9. Open the app

http://localhost:3101

You should see the Axis Bank Thrive portal with the **Demo Persona** switcher in the top-left.

---

## Pulling future updates from Siddharth

When Siddharth pushes a fix:

```bash
cd ~/axis-demo/axis-hiring-agent-backend-acs && git pull
# Restart uvicorn (Terminal 1) so the change loads

cd ~/axis-demo/axis-hiring-agent-acs && git pull
# Next.js hot-reloads automatically, no restart needed

cd ~/axis-demo/virtual-interviewer && git pull
# Restart VI if you pulled
```

---

## Demo golden path

1. **HR persona** → Bulk Screening → upload the 6 test CVs from `~/Desktop/test-cvs` against a BM job
2. **Click "Wipe + offer-ready"** (top-right) → wait ~60s → Priya Nair lands at `stage=offer / waiting_candidate_acceptance`
3. **Switch to Candidate (Thrive)** → open Priya's application → **Accept Offer**
4. **Switch to Onboarding Team** → Refresh → Priya's row appears → expand timeline
5. Click **Send now** on Buddy Introduction / Document Checklist / Life at Axis → verify rich WhatsApp copy arrives
6. Candidate replies → response auto-tags to correct touchpoint → use inline **Reply on WhatsApp** to respond

---

## Restore point

If anything breaks, reset to the pre-demo snapshot:

```bash
cd ~/axis-demo/axis-hiring-agent-backend-acs && git reset --hard pre-demo-backup-20260414-2327
cd ~/axis-demo/axis-hiring-agent-acs && git reset --hard pre-demo-backup-20260414-2327
# Re-seed data
cp ~/axis-demo/axis-demo-assets/backend-data-seed/*.json ~/axis-demo/axis-hiring-agent-backend-acs/data/
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `curl` to 8100 fails | Backend crashed | Check Terminal 1 for stack trace |
| `npm run dev` fails | Wrong Node version | `node -v` — must be 18+ |
| Bulk screening hangs | Claude API key missing or over limit | Check `.env` has `ANTHROPIC_API_KEY=sk-ant-...` |
| WhatsApp not sending | Twilio creds missing | Check `.env` has `TWILIO_*` vars |
| `stage=applied/waiting_hr` stuck | HR didn't advance | In HR persona, click "Advance to R1" |
| No candidates appear | Seed data missing | Re-run step 4 (copy data from `backend-data-seed/`) |

For anything else — ping Siddharth with the exact error and the terminal where it appeared.

---

## Ports reference

| Port | Service |
|---|---|
| 8100 | FastAPI backend |
| 3101 | Next.js frontend |
| 8101 | Virtual Interviewer |
