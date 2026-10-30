"""Sandbox runner behaviour with a fake Docker client — no daemon needed.

Run with: python -m pytest tests/test_runner.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sandbox import runner
from storage.artifacts import artifacts_dir
from utils import config

JOB = "55555555-5555-4555-8555-555555555555"
SCRIPT = "import time\nprint('hi')\n"


@pytest.fixture
def job_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DEMO_MODE", False)
    path = artifacts_dir(JOB)
    (path / "attempt_1.py").write_text(SCRIPT, encoding="utf-8")
    return path


def fake_docker(monkeypatch, on_run):
    """Patch docker.from_env; ``on_run(attempt_dir, container)`` plays the script."""
    container = MagicMock()
    container.logs.side_effect = lambda stdout, stderr: b"out\n" if stdout else b""
    container.wait.return_value = {"StatusCode": 0}

    def run(**kwargs):
        attempt_dir = Path(next(src for src, spec in kwargs["volumes"].items()
                                if spec["bind"] == "/screenshots"))
        on_run(attempt_dir, container)
        return container

    client = MagicMock()
    client.containers.run.side_effect = run
    monkeypatch.setattr(runner.docker, "from_env", lambda: client)
    return client, container


def test_screenshots_survive_a_timeout(job_dir, monkeypatch):
    """The failure screenshot is the best evidence a timed-out attempt leaves."""
    def on_run(attempt_dir, container):
        (attempt_dir / "failure_1.png").write_bytes(b"\x89PNG")
        container.wait.side_effect = requests.exceptions.ReadTimeout()

    fake_docker(monkeypatch, on_run)
    with pytest.raises(runner.SandboxTimeoutError):
        runner.run(str(job_dir / "attempt_1.py"), JOB, attempt=1)

    assert (job_dir / "a1_failure_1.png").is_file()
    assert not (job_dir / "attempt_1").exists()


def test_script_written_files_cannot_replace_stored_artifacts(job_dir, monkeypatch):
    (job_dir / "final.py").write_text("the real script", encoding="utf-8")

    def on_run(attempt_dir, _container):
        (attempt_dir / "final.py").write_text("clobbered", encoding="utf-8")
        (attempt_dir / "step_1.png").write_bytes(b"\x89PNG")

    fake_docker(monkeypatch, on_run)
    result = runner.run(str(job_dir / "attempt_1.py"), JOB, attempt=1)

    assert (job_dir / "final.py").read_text(encoding="utf-8") == "the real script"
    assert (job_dir / "a1_final.py").is_file()
    assert result["screenshot_paths"] == ["/screenshots/a1_step_1.png"]


def test_inspect_dom_keeps_its_name_and_reruns_overwrite(job_dir, monkeypatch):
    (job_dir / "inspect_spa.py").write_text(SCRIPT, encoding="utf-8")
    (job_dir / "dom.html").write_text("stale", encoding="utf-8")

    def on_run(attempt_dir, _container):
        (attempt_dir / "dom.html").write_text("fresh", encoding="utf-8")

    fake_docker(monkeypatch, on_run)
    runner.run(str(job_dir / "inspect_spa.py"), JOB, attempt=0)
    assert (job_dir / "dom.html").read_text(encoding="utf-8") == "fresh"


def test_container_is_hardened(job_dir, monkeypatch):
    client, _ = fake_docker(monkeypatch, lambda *_a: None)
    runner.run(str(job_dir / "attempt_1.py"), JOB, attempt=1)
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["cap_drop"] == ["ALL"]
    assert "no-new-privileges" in kwargs["security_opt"]
    assert kwargs["pids_limit"] == config.SANDBOX_PIDS_LIMIT
    assert kwargs["user"] == "1000"
