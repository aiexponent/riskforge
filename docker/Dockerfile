# RiskForge Docker image for the experimental API server (riskforge serve)
# Stage 1: builder
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md requirements.lock* ./
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir hatchling && \
    if [ -f requirements.lock ]; then \
        pip install --no-cache-dir -c requirements.lock ".[server]"; \
    else \
        pip install --no-cache-dir ".[server]"; \
    fi

# Stage 2: runtime
FROM python:3.11-slim AS runtime

# Security hardening
RUN useradd --create-home --shell /bin/bash riskforge && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        # WeasyPrint system dependencies
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf2.0-0 \
        libffi-dev \
        shared-mime-info \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/src /app/src

# Project data directory (mounted as volume in docker-compose)
RUN mkdir -p /data && chown riskforge:riskforge /data

USER riskforge

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/health')"

CMD ["uvicorn", "riskforge.server.app:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "2"]
