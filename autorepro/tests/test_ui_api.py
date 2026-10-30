"""API fields the dashboard relies on: live stage, attempts, errors, job summaries.

Run with: python -m pytest tests/test_ui_api.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from agent import orchestrator
from api.main import app
from storage import jobs as job_store
from utils import config
from utils.llm import clear_cache

BUG = "Login always shows invalid credentials even with a valid password"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Isolated data dir, mock LLM, simulated sandbox, stubbed page fetch."""
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock")
    monkeypatch.setattr(config, "DEMO_MODE", True)
    monkeypatch.setattr(job_store, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr("sandbox.runner.time.sleep", lambda _s: None)

    page = MagicMock(text="<html><title>Login</title><input id='username'></html>")
    page.raise_for_status = lambda: None
    monkeypatch.setattr("utils.net.requests.get", lambda *a, **k: page)

    clear_cache()
    yield TestClient(app)
    clear_cache()


def test_completed_job_exposes_dashboard_fields(client):
    job_id = client.post("/reproduce", json={"bug_report": BUG, "target_url": "http://example.com/login"}).json()["job_id"]
    res = client.get(f"/result/{job_id}").json()

    assert res["status"] == "done"
    assert res["success"] is True
    assert res["created_at"], "created_at written by the API must survive the final save"
    assert res["bug_report"] == BUG
    assert res["target_url"] == "http://example.com/login"
    assert res["max_attempts"] == config.MAX_ATTEMPTS
    assert res["stage"] is None
    assert set(res["analysis"]) >= {"inferred_steps", "success_condition"}
    assert len(res["attempts"]) == 1
    attempt = res["attempts"][0]
    assert attempt["attempt"] == 1
    assert attempt["exit_code"] == 0
    assert "AUTOREPRO_RESULT" in attempt["stdout"]
    assert attempt["simulated"] is True, "DEMO_MODE results must be marked simulated"
    assert res["simulated"] is True
    assert attempt["script"]


def test_unreachable_page_still_runs_the_pipeline(client, monkeypatch):
    """A page that can't be fetched from the API host is not a reason to abandon the job.

    The page may be reachable only from the sandbox network, and a 4xx/5xx page is often
    the reported symptom itself.
    """
    def unreachable(*_a, **_k):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("utils.net.requests.get", unreachable)
    job_id = client.post("/reproduce", json={"bug_report": BUG, "target_url": "http://example.com/login"}).json()["job_id"]
    res = client.get(f"/result/{job_id}").json()

    assert res["status"] == "done"
    assert res["attempt_count"] >= 1, "the script must still be generated and run"
    assert res["created_at"]


def test_failed_job_reports_error_stage_and_keeps_progress(client, monkeypatch):
    def boom():
        raise RuntimeError("generate exploded")

    # The graph is compiled at import time, so break what the node itself calls.
    monkeypatch.setattr("agent.nodes.generate._get_llm", boom)
    job_id = client.post("/reproduce", json={"bug_report": BUG, "target_url": "http://example.com/login"}).json()["job_id"]
    res = client.get(f"/result/{job_id}").json()

    assert res["status"] == "failed"
    assert "generate exploded" in res["error"]
    assert res["stage"] == "generate", "stage should point at the node that failed"
    assert res["analysis"], "analysis from the completed analyze node should be kept"
    assert res["created_at"]


def test_orchestrator_persists_each_stage(client, monkeypatch):
    stages = []
    real_save = job_store.save

    def recording_save(job_id, data):
        stages.append((data.get("status"), data.get("stage")))
        real_save(job_id, data)

    monkeypatch.setattr(job_store, "save", recording_save)
    orchestrator.run_agent(BUG, "http://example.com/login")

    processing = [stage for status, stage in stages if status == "processing"]
    assert processing == [None, "analyze", "inspect", "generate", "execute", "evaluate", "evaluate"]
    assert stages[-1] == ("done", None)


def test_jobs_summary_is_light_and_newest_first(client):
    job_store.save("old", {"job_id": "old", "status": "done", "created_at": "2026-01-01T00:00:00+00:00",
                           "history": [{"script": "x" * 1000}], "dom_context": "<html>"})
    job_store.save("new", {"job_id": "new", "status": "processing", "created_at": "2026-02-01T00:00:00+00:00"})

    rows = client.get("/jobs?summary=true").json()
    assert [r["job_id"] for r in rows] == ["new", "old"]
    assert "history" not in rows[0] and "dom_context" not in rows[1]

    full = client.get("/jobs").json()
    assert any("history" in j for j in full), "plain /jobs keeps returning full records"


def test_processing_result_includes_progress(client):
    job_store.save("busy", {"job_id": "busy", "status": "processing", "stage": "execute", "attempt_count": 2,
                            "max_attempts": 5, "bug_report": BUG, "target_url": "http://example.com",
                            "created_at": "2026-02-01T00:00:00+00:00",
                            "history": [{"attempt": 1, "script": "s", "result": {"exit_code": 1, "error_type": "Timeout"}}]})
    res = client.get("/result/busy").json()

    assert res["status"] == "processing"
    assert res["stage"] == "execute"
    assert res["attempt_count"] == 2
    assert res["attempts"][0]["error_type"] == "Timeout"
