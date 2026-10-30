"""Path-safety, access-control and sandbox-scanner behaviour.

Run with: python -m pytest tests/test_api_security.py -v
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from api.main import app
from sandbox.security import SecurityError, check
from storage import jobs as job_store
from storage.artifacts import existing_artifacts_dir, screenshot_path
from utils import config
from utils.net import BlockedTargetError, check_target

BUG = "Login always shows invalid credentials even with a valid password"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(job_store, "JOBS_DIR", tmp_path / "jobs")
    return tmp_path


@pytest.fixture
def client(data_dir):
    return TestClient(app)


# ── Path traversal and ID validation ──────────────────────────────────────────

@pytest.mark.parametrize("job_id", [
    "%2E%2E", "..", "%2E%2E%2F%2E%2E", "a/b", "a%5Cb", "", " ",
])
def test_read_endpoints_reject_ids_that_are_not_job_ids(client, data_dir, job_id):
    (data_dir / "probe.txt").write_text("secret")
    res = client.get(f"/result/{job_id}/screenshot/probe.txt")
    assert res.status_code == 404
    assert "secret" not in res.text


def test_reads_never_create_directories(client, data_dir):
    client.get("/result/11111111-1111-4111-8111-111111111111/screenshot/a.png")
    client.get("/result/11111111-1111-4111-8111-111111111111")
    assert not (data_dir / "artifacts" / "11111111-1111-4111-8111-111111111111").exists()


@pytest.mark.parametrize("filename", [
    "../../jobs/x.json", "..%5C..%5Cwin.ini", "dom.html", "final.py",
    "attempt_1.py", ".png", "a.PNG.py",
])
def test_screenshot_route_serves_only_plain_png_names(data_dir, filename):
    job = "22222222-2222-4222-8222-222222222222"
    from storage.artifacts import artifacts_dir
    job_dir = artifacts_dir(job)
    (job_dir / "dom.html").write_text("<html>rendered metadata response</html>")
    (job_dir / "final.py").write_text("print(1)")
    assert screenshot_path(job, filename) is None


def test_screenshot_route_serves_a_real_png(data_dir):
    job = "33333333-3333-4333-8333-333333333333"
    from storage.artifacts import artifacts_dir
    (artifacts_dir(job) / "a1_step_1_loaded.png").write_bytes(b"\x89PNG\r\n")
    assert screenshot_path(job, "a1_step_1_loaded.png") is not None


def test_unknown_job_is_a_404_not_a_new_directory(client):
    assert client.get("/result/44444444-4444-4444-8444-444444444444").status_code == 404
    assert existing_artifacts_dir("44444444-4444-4444-8444-444444444444") is None


def test_job_store_ignores_ids_that_are_not_job_ids(data_dir):
    (data_dir / "secret.json").write_text('{"a": 1}')
    assert job_store.get("../secret") is None
    assert job_store.get("..") is None


# ── Validation errors ─────────────────────────────────────────────────────────

def test_validation_error_is_a_readable_object(client):
    res = client.post("/reproduce", json={"bug_report": "short", "target_url": "http://x"})
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["code"] == "VALIDATION_ERROR"
    assert "bug_report" in detail["message"]


# ── Access control ────────────────────────────────────────────────────────────

def test_api_is_open_when_no_key_is_configured(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    assert client.get("/jobs").status_code == 200


def test_api_key_is_enforced_when_configured(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "s3cret")
    assert client.get("/jobs").status_code == 401
    assert client.get("/jobs", headers={"X-API-Key": "nope"}).status_code == 401
    assert client.get("/jobs", headers={"X-API-Key": "s3cret"}).status_code == 200


def test_health_reports_the_sandbox_runtime(client, monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["docker"] == "ok"


# ── SSRF guard ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.169.254/",
])
def test_metadata_addresses_are_always_refused(url, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_TARGETS", True)
    with pytest.raises(BlockedTargetError):
        check_target(url)


def test_private_targets_follow_the_flag(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_TARGETS", True)
    check_target("http://127.0.0.1:8080/login")  # local demo must keep working

    monkeypatch.setattr(config, "ALLOW_PRIVATE_TARGETS", False)
    with pytest.raises(BlockedTargetError):
        check_target("http://127.0.0.1:8080/login")


def test_docker_host_alias_is_resolved_by_the_sandbox_not_here(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_TARGETS", False)
    check_target("http://host.docker.internal:8080/login")


def test_blocked_target_is_rejected_at_submit_time(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    res = client.post("/reproduce", json={
        "bug_report": BUG, "target_url": "http://169.254.169.254/latest/meta-data/"})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "TARGET_NOT_ALLOWED"


# ── Sandbox scanner (lint, not a boundary) ────────────────────────────────────

@pytest.mark.parametrize("code", [
    "import os",
    "import subprocess",
    "import importlib",
    "import urllib.request",
    "import ctypes",
    "import io",
    "from pathlib import Path",
    "import builtins\nbuiltins.open('/etc/passwd')",
    "f = getattr(__builtins__, 'ev' + 'al')",
    "eval('1')",
    "exec('x=1')",
    "compile('1', 'x', 'eval')",
    "().__class__.__bases__[0].__subclasses__()",
    "open('/etc/passwd')",
    "open()",
    "x = '/etc/passwd'\nopen(x)",
    "open('/screenshots/../etc/passwd')",
    "from . import sibling",
])
def test_scanner_rejects_escape_routes(code):
    with pytest.raises(SecurityError):
        check(code)


def test_scanner_accepts_a_normal_reproduction_script():
    check(
        "import json\n"
        "import time\n"
        "import re\n"
        "from selenium import webdriver\n"
        "from selenium.webdriver.common.by import By\n"
        "from selenium.webdriver.support.ui import WebDriverWait\n"
        "driver = webdriver.Chrome()\n"
        "driver.save_screenshot('/screenshots/step_1.png')\n"
        "with open('/screenshots/dom.html', 'w') as f:\n"
        "    f.write(driver.page_source)\n"
        "print('AUTOREPRO_RESULT ' + json.dumps({'reproduced': True}))\n"
    )


def test_scanner_reports_syntax_errors_as_such():
    with pytest.raises(SecurityError, match="Syntax error"):
        check("def (:")
