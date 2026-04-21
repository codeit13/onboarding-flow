"""Axis Hiring Agent — backend orchestration service.

Python + FastAPI. The autonomous orchestrator (see ``app.orchestrator``)
drives the end-to-end hiring funnel: Apply → Screen → R1 → R2 → Offer.

On import, this package loads ``.env`` from the backend root so that every
entry point (uvicorn, pytest, `python -m app.something`) sees the same
environment variables without needing shell exports.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover — dotenv is in requirements.txt
    load_dotenv = None  # type: ignore

if load_dotenv is not None:
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.is_file():
        # Treat empty shell-exported values as "not set" so a stray
        # ``export ANTHROPIC_API_KEY=`` in the user's shell rc doesn't
        # shadow the real key in .env. Real non-empty OS env vars still
        # win over .env (important in prod / CI with secret stores).
        for _k in ("ANTHROPIC_API_KEY", "AXIS_GRAPH_CLIENT_SECRET"):
            if os.environ.get(_k, None) == "":
                del os.environ[_k]
        load_dotenv(_env_path, override=False)
