# =============================================================
# AutoRepro — API Container
# Python 3.11 slim base, matching the sandbox image version.
# Build context: repo root (autorepro/ subdirectory is the app).
# =============================================================

FROM python:3.11-slim

# Install curl (needed for the health check in docker-compose)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer — only rebuilds on requirements change)
COPY autorepro/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY autorepro/ .

# Create data directories (overridden by volume mount in production)
RUN mkdir -p data/jobs data/artifacts

EXPOSE 8000

# Run with uvicorn — host 0.0.0.0 required inside Docker
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
