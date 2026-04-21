# ============================================================
# Axis Hiring Agent — ACS Backend (FastAPI / Python 3.11)
# ============================================================

# ---- Stage 1: Build / install dependencies ----
FROM python:3.11-slim AS builder

WORKDIR /app

# System-level build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# Create a venv and install Python deps into it
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Clean up compiled artefacts to shrink the layer
RUN find /opt/venv -type f -name '*.pyc' -delete \
 && find /opt/venv -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# ---- Stage 2: Lean production image ----
FROM python:3.11-slim AS runner

WORKDIR /app

# Runtime system deps only (libpq for psycopg2 if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
 && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
COPY . .

# Non-root user for security
RUN addgroup --system --gid 1001 appgroup \
 && adduser  --system --uid 1001 --ingroup appgroup appuser \
 && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Uvicorn in production mode (single worker for in-memory STORE consistency)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
