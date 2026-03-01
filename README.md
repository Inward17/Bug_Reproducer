# AutoRepro 🤖🐛

An AI debugging assistant that converts vague bug reports into verified **Selenium reproduction scripts** via an autonomous LangGraph agent loop — fully runnable inside an isolated Docker sandbox.

## Overview

AutoRepro accepts a natural-language bug report and autonomously **generates → executes → evaluates → refines** a Selenium browser-automation script until the bug is reliably reproduced.

### Core Features

- 🧠 Multi-LLM support — **Ollama (local)**, Anthropic Claude, OpenAI, Google Gemini
- 🔄 Autonomous self-refinement loop (up to 5 attempts by default)
- 🐳 Safe execution in isolated Docker sandboxes (Chromium + Selenium)
- 🌐 Web UI dashboard for submitting bug reports & viewing results
- 📸 Screenshot capture during script execution
- 📁 Artifact API for downloading generated scripts & screenshots
- 📋 Job history panel with status tracking

## Architecture

```
Bug Report ──▶ Analyze ──▶ Generate Script ──▶ Execute in Docker
                                                    │
                                        ┌───────────┘
                                        ▼
                                   Evaluate Result
                                        │
                               ┌────────┴────────┐
                               ▼                  ▼
                          ✅ Success          ❌ Refine
                          (save result)       (loop back)
```

| Step | Description |
|------|-------------|
| **Analyze** | Parses the bug report into structured JSON analysis |
| **Generate** | Writes a Selenium Python script based on the analysis |
| **Execute** | Runs the script inside a Docker container with headless Chromium |
| **Evaluate** | Checks if the bug was successfully reproduced |
| **Refine** | If failed, rewrites the script using error feedback & attempt history |

## Tech Stack

| Component | Technology |
|-----------|------------|
| Agent Framework | LangGraph |
| LLM Providers | Ollama, Anthropic, OpenAI, Google Gemini |
| Default Model | `qwen2.5-coder:3b` (via Ollama) |
| Backend API | FastAPI + Uvicorn |
| Sandbox | Docker (Chromium + Selenium) |
| Frontend | Vanilla HTML/CSS/JS with Inter & JetBrains Mono fonts |
| Testing | Pytest |

## Setup & Running

**Prerequisites:** Docker daemon running, Python 3.11+, and [Ollama](https://ollama.com) installed (for default local LLM).

### 1. Pull the default model (Ollama)

```bash
ollama pull qwen2.5-coder:3b
```

### 2. Build the Docker sandbox

```bash
cd autorepro
docker build -t autorepro-sandbox:latest ./sandbox
```

### 3. Install dependencies & run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start the API server (uses Ollama by default)
uvicorn api.main:app --port 8000
```

Open **http://localhost:8000** in your browser to access the Web UI.

### Alternative LLM Providers

```bash
# Anthropic Claude
LLM_PROVIDER=anthropic LLM_MODEL=claude-sonnet-4-20250514 ANTHROPIC_API_KEY=sk-ant-... uvicorn api.main:app --port 8000

# OpenAI
LLM_PROVIDER=openai LLM_MODEL=gpt-4o OPENAI_API_KEY=sk-... uvicorn api.main:app --port 8000

# Google Gemini
LLM_PROVIDER=google LLM_MODEL=gemini-2.0-flash GOOGLE_API_KEY=... uvicorn api.main:app --port 8000
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | LLM provider (`ollama`, `anthropic`, `openai`, `google`) |
| `LLM_MODEL` | `qwen2.5-coder:3b` | Model name for the chosen provider |
| `MAX_ATTEMPTS` | `5` | Max refinement attempts per job |
| `SANDBOX_TIMEOUT_SECONDS` | `60` | Timeout for each script execution |
| `SANDBOX_MEMORY_MB` | `512` | Memory limit for Docker sandbox |
| `SANDBOX_IMAGE` | `autorepro-sandbox:latest` | Docker image for the sandbox |
| `DATA_DIR` | `./data` | Directory for job data & artifacts |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DEMO_MODE` | `false` | Enable demo mode |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/reproduce` | Submit a bug report for reproduction |
| `GET` | `/result/{job_id}` | Get job status & results |
| `GET` | `/result/{job_id}/script` | Download the generated script |
| `GET` | `/result/{job_id}/screenshot/{filename}` | View a captured screenshot |
| `GET` | `/jobs` | List all jobs |
| `GET` | `/health` | Health check |

## Example Usage

### Via Web UI

Navigate to `http://localhost:8000`, fill in the bug description and target URL, then click **Start Reproduction**.

### Via cURL

```bash
# Submit a bug report
curl -X POST http://localhost:8000/reproduce \
  -H "Content-Type: application/json" \
  -d '{
    "bug_report": "Login always shows Invalid credentials even with correct username and password",
    "target_url": "http://host.docker.internal:8080/login"
  }'

# Response: {"job_id":"abc-123", "status":"processing"}

# Check results
curl http://localhost:8000/result/abc-123
```

## Project Structure

```
autorepro/
├── agent/            # LangGraph agent (nodes, graph, orchestrator)
│   ├── nodes/        # Individual agent nodes (analyze, generate, execute, evaluate, refine)
│   ├── graph.py      # LangGraph wiring
│   ├── orchestrator.py  # Public entrypoint
│   └── state.py      # Agent state definition
├── api/              # FastAPI application
│   ├── main.py       # App factory & static file serving
│   ├── routes.py     # API endpoint handlers
│   └── schemas.py    # Pydantic request/response models
├── prompts/          # LLM prompt templates
├── sandbox/          # Docker sandbox (Dockerfile + security policies)
├── static/           # Web UI (HTML, CSS, JS)
├── storage/          # Job & artifact persistence
├── tests/            # Test suite
├── utils/            # Config, logging, ID generation
└── requirements.txt  # Python dependencies
```

## License

MIT
