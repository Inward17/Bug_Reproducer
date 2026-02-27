FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

RUN pip install selenium==4.18.0

RUN useradd -m -u 1000 sandbox
USER sandbox
WORKDIR /app

CMD ["python", "/scripts/script.py"]
