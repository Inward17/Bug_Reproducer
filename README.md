# AutoRepro 🤖🐛

An AI-powered debugging assistant that converts natural-language bug reports into verified **Selenium reproduction scripts** via an autonomous LangGraph agent loop — fully runnable inside an isolated Docker sandbox.

---

## Overview

AutoRepro accepts a bug report (e.g., *"Login always shows Invalid credentials even with correct username and password"*) and autonomously **generates → executes → evaluates → refines** a Selenium browser-automation script until the bug is reliably reproduced — or the maximum number of attempts is exhausted.

### Core Features

- 🧠 **Multi-LLM support** — Ollama (local), Anthropic Claude, OpenAI GPT, Google Gemini
- 🔄 **Autonomous self-refinement loop** — up to 5 attempts with intelligent error diagnosis
- 🐳 **Isolated Docker sandboxes** — Chromium + Selenium in memory-limited containers
- 🌐 **Web UI dashboard** — submit bug reports, view results, browse execution logs & screenshots
- 📸 **Screenshot capture** — automatic failure screenshots for debugging
- 🔒 **AST-based security scanning** — blocks dangerous imports/builtins before execution
- 📁 **Artifact API** — download generated scripts & screenshots via REST

---

## Architecture

### Pipeline Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                        AutoRepro Agent Loop                         │
│                                                                      │
│   Bug Report ──▶ ANALYZE ──▶ GENERATE ──▶ EXECUTE ──▶ EVALUATE      │
│                   (LLM)       (LLM)      (Docker)    (Deterministic) │
│                                                          │           │
│                                               ┌──────────┴────────┐  │
│                                               ▼                   ▼  │
│                                          ✅ Success          ❌ REFINE│
│                                          (save result)        (LLM)  │
│                                                               │      │
│                                                               ▼      │
│                                                          EXECUTE     │
│                                                          (retry)     │
└──────────────────────────────────────────────────────────────────────┘
```

### Node Descriptions

| Node | Type | Description |
|------|------|-------------|
| **Analyze** | LLM | Parses bug report into structured JSON: inferred steps, target CSS selectors, success condition, risk factors |
| **Generate** | LLM | Writes a complete Python/Selenium script from the analysis. Uses verification pattern: trigger bug → check DOM for error evidence → print `REPRODUCED` |
| **Execute** | Docker | Writes script to disk, runs it inside an isolated Docker container with headless Chromium. Captures stdout, stderr, exit code, screenshots |
| **Evaluate** | Deterministic | Checks if `REPRODUCED` appears in stdout. Classifies failures: `Timeout`, `ElementNotFound`, `WrongVerification`, `NetworkError`, `Unknown` |
| **Refine** | LLM | Receives the original bug report, failed script, execution result, and full attempt history. Diagnoses the issue and rewrites the script |

### State Machine (LangGraph)

```python
graph = StateGraph(AgentState)
graph.add_node("analyze",  analyze_node)
graph.add_node("generate", generate_node)
graph.add_node("execute",  execute_node)
graph.add_node("evaluate", evaluate_node)
graph.add_node("refine",   refine_node)

# Flow: analyze → generate → execute → evaluate → (success | refine → execute)
graph.set_entry_point("analyze")
graph.add_edge("analyze",  "generate")
graph.add_edge("generate", "execute")
graph.add_edge("execute",  "evaluate")
graph.add_conditional_edges("evaluate", route_after_evaluate, {
    "end_success": END,
    "refine":      "refine",
    "end_failure": END,
})
graph.add_edge("refine", "execute")
```

---

## Tech Stack

| Component | Technology | Details |
|-----------|------------|---------|
| Agent Framework | **LangGraph** | State machine with conditional edges for the refine loop |
| LLM Providers | **Ollama** (default), Anthropic, OpenAI, Google Gemini | Configurable via env vars |
| Recommended Model | `qwen2.5-coder:7b` | Via Ollama — good balance of quality and speed |
| Backend API | **FastAPI** + Uvicorn | Async endpoints, background task execution |
| Sandbox | **Docker** | Headless Chromium + Selenium 4.18 in isolated containers |
| Security | AST-based static analysis | Blocks `os`, `subprocess`, `socket`, `eval`, `exec` etc. |
| Frontend | Vanilla **HTML/CSS/JS** | Inter + JetBrains Mono fonts, glassmorphism UI |
| Testing | **Pytest** | Unit tests + integration tests with mock LLM |
| Logging | **structlog** | Structured JSON logging |

---

## Project Structure

```
autorepro/
├── agent/                        # LangGraph agent (core logic)
│   ├── __init__.py
│   ├── graph.py                  # LangGraph state machine wiring & conditional edges
│   ├── orchestrator.py           # Public entrypoint — runs full agent loop & persists results
│   ├── state.py                  # AgentState TypedDict & FailureType enum
│   └── nodes/                    # Individual pipeline stages
│       ├── analyze.py            # Node 1: LLM bug report → structured JSON analysis
│       ├── generate.py           # Node 2: LLM analysis → Python/Selenium script
│       ├── execute.py            # Node 3: Write script to disk → run in Docker sandbox
│       ├── evaluate.py           # Node 4: Deterministic success/failure classifier
│       └── refine.py             # Node 5: LLM rewrites script using error feedback
│
├── api/                          # FastAPI REST application
│   ├── main.py                   # App factory, startup checks, static file serving
│   ├── routes.py                 # API endpoint handlers (reproduce, result, jobs, health)
│   └── schemas.py                # Pydantic request/response models
│
├── prompts/                      # LLM prompt templates (plain text with {placeholders})
│   ├── analyze.txt               # Bug report → structured analysis prompt
│   ├── generate.txt              # Analysis → Selenium script prompt (with verification pattern)
│   └── refine.txt                # Failed script → corrected script prompt (with diagnosis guide)
│
├── sandbox/                      # Docker sandbox execution engine
│   ├── Dockerfile                # Chromium + chromedriver + Selenium image definition
│   ├── runner.py                 # Container lifecycle: create, run, collect logs, cleanup
│   ├── security.py               # AST-based static analysis — blocks dangerous code
│   └── feedback_parser.py        # Normalizes raw Docker logs → structured ExecutionResult
│
├── static/                       # Web UI (served by FastAPI)
│   ├── index.html                # Main dashboard page
│   ├── style.css                 # Styling (glassmorphism, gradients, dark theme)
│   └── app.js                    # Frontend logic (job submission, polling, result display)
│
├── storage/                      # Data persistence layer
│   ├── jobs.py                   # JSON file-based job store (save/load/list)
│   └── artifacts.py              # Script & screenshot artifact management
│
├── tests/                        # Test suite
│   ├── demo_server.py            # Flask app simulating a buggy login page (ShopEasy)
│   └── test_bug_fixes.py         # Pytest suite for agent nodes & pipeline
│
├── utils/                        # Shared utilities
│   ├── config.py                 # Central configuration (all env vars with defaults)
│   ├── logger.py                 # structlog configuration
│   ├── id_generator.py           # UUID-based job ID generator
│   └── mock_llm.py               # Mock LLM for testing without API calls
│
├── data/                         # Runtime data (gitignored)
│   ├── jobs/                     # Job JSON files (one per reproduction attempt)
│   └── artifacts/                # Generated scripts & screenshots per job
│
├── docker-compose.yml            # Optional Docker Compose for containerized deployment
├── requirements.txt              # Python dependencies (pinned versions)
└── venv/                         # Python virtual environment
```

---

## Setup & Running

### Prerequisites

- **Python 3.11+**
- **Docker Desktop** (daemon must be running)
- **Ollama** installed ([ollama.com](https://ollama.com)) — for local LLM inference

### 1. Pull the LLM model

```bash
ollama pull qwen2.5-coder:7b
```

> **Note:** The 7B model needs ~6GB GPU VRAM. For lower-end GPUs, use `qwen2.5-coder:3b` instead.

### 2. Build the Docker sandbox image

```bash
cd autorepro
docker build -t autorepro-sandbox:latest ./sandbox
```

> This installs headless Chromium + chromedriver + Selenium inside a slim Python 3.11 image.

### 3. Install Python dependencies

```bash
python -m venv venv

# Windows:
venv\Scripts\activate

# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Start the application

```powershell
# Windows (PowerShell)
$env:LLM_PROVIDER="ollama"; $env:LLM_MODEL="qwen2.5-coder:7b"; uvicorn api.main:app --port 8000
```

```bash
# macOS/Linux
LLM_PROVIDER=ollama LLM_MODEL=qwen2.5-coder:7b uvicorn api.main:app --port 8000
```

### 5. Open the Web UI

Navigate to **http://localhost:8000** in your browser.

### 6. Test with the demo server (optional)

In a separate terminal, start the included buggy demo app:

```bash
python tests/demo_server.py
```

Then in the Web UI, submit:
- **Bug report:** `Login always shows Invalid credentials even with correct username and password`
- **Target URL:** `http://host.docker.internal:8080/login`

---

## Alternative LLM Providers

```bash
# Anthropic Claude
LLM_PROVIDER=anthropic LLM_MODEL=claude-sonnet-4-20250514 ANTHROPIC_API_KEY=sk-ant-... uvicorn api.main:app --port 8000

# OpenAI GPT-4o
LLM_PROVIDER=openai LLM_MODEL=gpt-4o OPENAI_API_KEY=sk-... uvicorn api.main:app --port 8000

# Google Gemini
LLM_PROVIDER=google LLM_MODEL=gemini-2.0-flash GOOGLE_API_KEY=... uvicorn api.main:app --port 8000
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | LLM provider: `ollama`, `anthropic`, `openai`, `google` |
| `LLM_MODEL` | `qwen2.5-coder:3b` | Model name for the chosen provider |
| `MAX_ATTEMPTS` | `5` | Maximum refinement attempts per job |
| `SANDBOX_TIMEOUT_SECONDS` | `60` | Timeout for each Docker script execution |
| `SANDBOX_MEMORY_MB` | `512` | Memory limit for Docker sandbox containers |
| `SANDBOX_IMAGE` | `autorepro-sandbox:latest` | Docker image name for the sandbox |
| `DATA_DIR` | `./data` | Directory for job data & artifacts |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DEMO_MODE` | `false` | Enable simulated execution mode (no Docker needed) |

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/reproduce` | Submit a bug report for reproduction. Body: `{"bug_report": "...", "target_url": "..."}` |
| `GET` | `/result/{job_id}` | Get job status, execution results, history, and script |
| `GET` | `/result/{job_id}/script` | Download the final generated Selenium script |
| `GET` | `/result/{job_id}/screenshot/{filename}` | View a captured failure screenshot |
| `GET` | `/jobs` | List all jobs with status |
| `GET` | `/health` | Health check (verifies Docker daemon connectivity) |
| `GET` | `/` | Serve the Web UI |

---

## How Bug Reproduction Works

AutoRepro's key insight: **"reproducing a bug" means proving the bug EXISTS**, not testing the happy path.

### Example

**Bug report:** *"Login always shows Invalid credentials even with correct username and password"*

**What the LLM generates:**
```python
# 1. Navigate to login page
driver.get("http://host.docker.internal:8080/login")

# 2. Fill in credentials
username_field.send_keys("valid_username")
password_field.send_keys("valid_password")

# 3. Submit the form
login_button.click()

# 4. Check for the BUG (error message), NOT the happy path
if "Invalid" in driver.page_source:
    print("REPRODUCED")  # Bug confirmed!
```

### Failure Classification

When a script fails, the evaluate node classifies the failure type to help the refine node:

| Failure Type | Cause | Refine Strategy |
|-------------|-------|-----------------|
| `Timeout` | Element selector is wrong | Try alternative CSS selectors |
| `ElementNotFound` | Element doesn't exist | Check HTML structure |
| `WrongVerification` | Script ran OK but didn't print REPRODUCED | Fix the verification logic |
| `NetworkError` | Target URL unreachable | Check connectivity |
| `Unknown` | Unexpected error | General debugging |

---

## Security

Generated scripts are statically analyzed via AST before execution:

- **Blocked imports:** `os`, `subprocess`, `socket`, `shutil`, `sys`, `pathlib`
- **Blocked builtins:** `eval()`, `exec()`, `compile()`, `__import__()`
- **File access:** `open()` only allowed for `/screenshots/` paths
- **Container isolation:** 512MB memory limit, 1 CPU core, non-root user (UID 1000)

---

## Prompt Engineering

The system uses three carefully crafted prompt templates:

| Prompt | Purpose | Key Design Decisions |
|--------|---------|---------------------|
| `analyze.txt` | Bug report → JSON | Includes 5 bug-type examples showing correct vs incorrect `success_condition` |
| `generate.txt` | JSON → Selenium script | Provides a verification PATTERN template and emphasizes checking for error behavior |
| `refine.txt` | Failed script → fixed script | Includes a 5-case diagnosis guide and the original bug report for context |

---

## Example Usage

### Via Web UI

1. Open **http://localhost:8000**
2. Enter the bug description and target URL
3. Click **Start Reproduction**
4. Watch real-time progress as the agent works
5. View the generated script, execution logs, and screenshots

### Via cURL

```bash
# Submit a bug report
curl -X POST http://localhost:8000/reproduce \
  -H "Content-Type: application/json" \
  -d '{
    "bug_report": "Login always shows Invalid credentials even with correct username and password",
    "target_url": "http://host.docker.internal:8080/login"
  }'

# Response: {"job_id":"1f2e8c74-...", "status":"processing"}

# Check results
curl http://localhost:8000/result/1f2e8c74-...
```

---

## Testing

```bash
# Run the test suite
pytest tests/ -v

# Run with mock LLM (no API keys needed)
LLM_PROVIDER=mock pytest tests/ -v
```

---

## License

MIT
