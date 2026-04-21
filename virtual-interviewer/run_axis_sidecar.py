#!/usr/bin/env python3
"""Axis sidecar launcher for the team's Virtual Interviewer service.

Runs the FastAPI app from app/main.py but skips the `detection` router,
which needs OpenCV / MediaPipe / TensorFlow / Ultralytics (large ML
stack). We don't need proctoring for the Axis demo flow — only the
core interview loop: start → question → answer → evaluate.

All other team code (OpenAIService question generation, Deepgram STT,
face recognition gate on /start, interview_data/ JSON persistence)
is used exactly as shipped in the zip — nothing is rewritten.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))

os.makedirs("interview_data", exist_ok=True)
os.makedirs("mcp_data", exist_ok=True)
os.makedirs("logs", exist_ok=True)

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

required = ["OPENAI_API_KEY", "DEEPGRAM_API_KEY"]
missing = [v for v in required if not os.getenv(v)]
if missing:
    print(f"[sidecar] FATAL: missing env vars: {missing}", file=sys.stderr)
    sys.exit(1)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from app.routers import interview, users  # noqa: E402

app = FastAPI(title="Axis Virtual Interviewer Sidecar")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(interview.router)
app.include_router(users.router)


@app.get("/")
async def root():
    return {"service": "axis-virtual-interviewer-sidecar", "status": "ok"}


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    # --reload picks up question_service.py / interview_service.py edits
    # without an explicit restart — important for the Hindi-language work
    # where stale bytecode silently dropped the language flag and made
    # questions still come through in English even after the candidate
    # picked हिंदी.
    reload_flag = os.getenv("SIDECAR_RELOAD", "1") == "1"
    print(f"[sidecar] Starting on {host}:{port} (reload={reload_flag})")
    if reload_flag:
        uvicorn.run(
            "run_axis_sidecar:app",
            host=host,
            port=port,
            log_level="info",
            reload=True,
            reload_dirs=[str(BASE / "app")],
        )
    else:
        uvicorn.run(app, host=host, port=port, log_level="info")
