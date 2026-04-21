# Axis Demo — Docker Quick Reference

> Run all commands from `d:\Project\axis-demo\` (the repo root).

---

## Quick Start Deployment

To deploy the entire application stack in one go, follow these 3 steps:

1. **Configure Environment**: Ensure `.env` files are present in `./axis-hiring-agent-backend-acs/` and `./virtual-interviewer/`.
2. **Build Images** (Heavy):
   ```powershell
   docker compose --profile acs --profile vi build
   ```
3. **Start Services**:
   ```powershell
   docker compose --profile acs --profile vi up -d
   ```

## Architecture

```
localhost:3000   ←→  acs-frontend  (Next.js)       ─┐
localhost:8100   ←→  acs-backend   (FastAPI)       ─┘ Profile: acs
                                                        axis-net
localhost:3001   ←→  vi-frontend   (xchat-ui)      ─┐
localhost:8101   ←→  vi-backend    (FastAPI + ML)  ─┘ Profile: vi
```

Inter-service communication uses Docker service names over `axis-net`:
- `acs-backend` calls `vi-backend` at `http://vi-backend:8000`
- `acs-frontend` was built with `NEXT_PUBLIC_API_BASE=http://localhost:8100`

---

## Files Created

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Root compose file — all 4 services |
| `axis-hiring-agent-acs/Dockerfile` | ACS frontend image |
| `axis-hiring-agent-backend-acs/Dockerfile` | ACS backend image |
| `virtual-interviewer/Dockerfile` | VI backend image (ML heavy) |
| `virtual-interviewer/xchat-ui/Dockerfile` | xchat-ui image (pre-existing) |
| `*/.dockerignore` | Exclude venvs, node_modules, etc. |

---

## Build Commands

### Build everything
```bash
docker compose build
# PowerShell:  .\docker.ps1 build
```

### Build a single group (profile)
```bash
docker compose --profile acs build   # ACS frontend + backend
docker compose --profile vi  build   # VI frontend + backend
```

### Build a single service
```bash
docker compose build acs-backend
docker compose build acs-frontend
docker compose build vi-backend
docker compose build vi-frontend
```

---

## Start Commands

### Start everything (detached)
```bash
docker compose --profile acs --profile vi up -d
# PowerShell:  .\docker.ps1 up
```

### Start by group
```bash
docker compose --profile acs up -d   # ACS only
docker compose --profile vi  up -d   # VI  only
```

### Start a single service
```bash
docker compose up -d acs-backend
docker compose up -d acs-frontend
docker compose up -d vi-backend
docker compose up -d vi-frontend
```

---

## Build + Start (rebuild & restart in one step)

```bash
docker compose --profile acs --profile vi up -d --build   # all
docker compose --profile acs up -d --build                # ACS
docker compose --profile vi  up -d --build                # VI
docker compose up -d --build acs-backend                  # single
```

---

## Logs

```bash
docker compose logs -f                         # all services
docker compose logs -f acs-backend acs-frontend
docker compose logs -f vi-backend vi-frontend
docker compose logs -f acs-backend             # single
```

---

## Stop

```bash
docker compose --profile acs --profile vi down   # stop + remove containers
docker compose --profile acs down
docker compose --profile vi  down
```

### Full clean (removes images + volumes)
```bash
docker compose --profile acs --profile vi down --rmi all --volumes --remove-orphans
```

---

## Port Reference

| Container | Host URL |
|-----------|----------|
| ACS Frontend | http://localhost:3000 |
| ACS Backend API | http://localhost:8100 |
| VI Frontend (xchat-ui) | http://localhost:3001 |
| VI Backend API | http://localhost:8101 |
| Redis Service | (internal) axis-redis:6379 |

---

## Environment Variables

Each service loads its own `.env` file via `env_file` in `docker-compose.yml`.
Override any variable by adding it under `environment:` in the compose file.

| Service | Env file |
|---------|----------|
| `acs-backend` | `axis-hiring-agent-backend-acs/.env` |
| `vi-backend` | `virtual-interviewer/.env` |
| `acs-frontend` | Build-arg `NEXT_PUBLIC_API_BASE` |
| `vi-frontend` | `NEXT_PUBLIC_VI_API_BASE` env var |

> **Note:** `NEXT_PUBLIC_*` variables are **baked in at build time** for Next.js.
> If you change the API URL, you must rebuild the frontend image.
