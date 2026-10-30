FROM python:3.11-slim

# Debian ships chromium and chromium-driver as a matched pair, so the driver always
# matches the browser. Pinning selenium separately is enough to keep runs reproducible.
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir selenium==4.18.0

RUN useradd -m -u 1000 sandbox
USER sandbox
WORKDIR /app

CMD ["python", "/scripts/script.py"]
