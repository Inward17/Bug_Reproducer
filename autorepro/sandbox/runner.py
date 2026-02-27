"""Container lifecycle management — runs Selenium scripts in isolated Docker containers."""

import time
import docker
from pathlib import Path

from sandbox.feedback_parser import parse
from sandbox.security import check, SecurityError
from utils import config
from utils.logger import get_logger

log = get_logger(__name__)


class TimeoutError(Exception):
    """Raised when container execution exceeds the configured timeout."""
    pass


class ContainerError(Exception):
    """Raised when container fails to start or encounters a runtime error."""
    pass


def run(script_path: str, job_id: str) -> dict:
    """Run a Selenium script in an isolated Docker container. Returns ExecutionResult dict."""
    script_content = Path(script_path).read_text()
    check(script_content)

    client = docker.from_env()
    artifacts_dir = Path(config.DATA_DIR) / "artifacts" / job_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    container = None
    start = time.time()

    try:
        container = client.containers.run(
            image=config.SANDBOX_IMAGE,
            volumes={
                str(Path(script_path).resolve()): {"bind": "/scripts/script.py", "mode": "ro"},
                str(artifacts_dir.resolve()):      {"bind": "/screenshots",       "mode": "rw"},
            },
            mem_limit=f"{config.SANDBOX_MEMORY_MB}m",
            nano_cpus=1_000_000_000,
            network_mode="bridge",
            user="1000",
            detach=True,
            auto_remove=False,
        )

        try:
            container.wait(timeout=config.SANDBOX_TIMEOUT_SECONDS)
        except Exception:
            container.kill()
            raise TimeoutError(f"Container exceeded {config.SANDBOX_TIMEOUT_SECONDS}s timeout")

        stdout    = container.logs(stdout=True,  stderr=False).decode("utf-8", errors="replace")
        stderr    = container.logs(stdout=False, stderr=True).decode("utf-8",  errors="replace")
        exit_code = container.wait()["StatusCode"]

    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass

    duration = round(time.time() - start, 2)
    result   = parse(stdout, stderr, exit_code)
    result["duration_seconds"] = duration
    log.info("container_run_complete", job_id=job_id, exit_code=exit_code, duration=duration)
    return result
