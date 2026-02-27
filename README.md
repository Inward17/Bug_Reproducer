# AutoRepro 🤖🐛

An AI debugging assistant that converts vague bug reports into verified Selenium reproduction scripts via an autonomous LangGraph execution-refinement loop.

## Overview

AutoRepro accepts a natural-language bug report and autonomously generates, executes, evaluates, and refines a Selenium browser-automation script until the bug is reliably reproduced. The entire loop runs inside an isolated Docker sandbox.

**Core features:**
- Turns text bug reports into runnable Python/Selenium scripts
- Autonomous self-refinement loop using Anthropic Claude / OpenAI
- Safe execution in isolated Docker sandboxes
- Artifact API for accessing generated scripts and screenshots

## How it Works

1. **Analyze**: parses the bug report into a structured JSON analysis
2. **Generate**: writes a Selenium Python script based on the analysis
3. **Execute**: runs the script inside a Docker container (Chromium + Selenium)
4. **Evaluate**: checks if the bug was successfully reproduced
5. **Refine**: if failed, the LLM rewrites the script using detailed error feedback and attempt history

## Setup & Running

Requires Docker daemon running and Python 3.11+.

### 1. Build Sandbox
```bash
cd autorepro
docker build -t autorepro-sandbox:latest ./sandbox
```

### 2. Install & Run
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run with Mock LLM (No API key needed)
# In Terminal 1 (Demo buggy server):
LLM_PROVIDER=mock python tests/demo_server.py

# In Terminal 2 (AutoRepro API):
LLM_PROVIDER=mock uvicorn api.main:app --port 8000
```

*To use an actual LLM, set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=sk-ant-...`.*

## Example Usage

```bash
# Submit a bug report
curl -X POST http://localhost:8000/reproduce \
  -H "Content-Type: application/json" \
  -d '{"bug_report": "Login always shows Invalid credentials even with correct username and password", "target_url": "http://host.docker.internal:8080/login"}'

# Response: {"job_id":"abc-123", "status":"processing"}

# Check results (after ~15 seconds)
curl http://localhost:8000/result/abc-123
```
