"""Container lifecycle management — runs Selenium scripts in isolated Docker containers."""

import os
import shutil
import threading
import time
from pathlib import Path

import docker
from docker.errors import APIError, DockerException, ImageNotFound

from agent.common import VERDICT_PREFIX, parse_verdict
from sandbox.feedback_parser import parse
from sandbox.security import check
from utils import config
from utils.logger import get_logger

log = get_logger(__name__)

# One semaphore per process. Each sandbox is a Chromium container, so an unbounded
# burst of jobs is an easy way to OOM the host.
# ponytail: process-local cap; needs a shared limiter once the API runs more than one worker.
_slots = threading.Semaphore(config.MAX_CONCURRENT_SANDBOXES)


class SandboxTimeoutError(Exception):
    """Raised when container execution exceeds the configured timeout."""
    pass


class ContainerError(Exception):
    """Raised when container fails to start or encounters a runtime error."""
    pass


def _resolve_bind_source(path: Path) -> Path:
    """Resolve a bind source path that the host Docker daemon can actually see."""
    local_path = path.resolve()
    host_data_dir = os.getenv("HOST_DATA_DIR", "").strip()
    if not host_data_dir:
        return local_path

    local_data_dir = Path(config.DATA_DIR).resolve()
    try:
        relative = local_path.relative_to(local_data_dir)
    except ValueError:
        # Paths outside DATA_DIR are assumed to already be host-visible.
        return local_path

    return Path(host_data_dir).resolve() / relative


def _collect_outputs(attempt_dir: Path, job_dir: Path, attempt: int) -> list[str]:
    """Move an attempt's files into the job directory, prefixing screenshots.

    Each attempt gets its own mount, so attempt 3's ``step_1_page_loaded.png`` no longer
    overwrites attempt 1's. The prefix keeps the evidence timeline in order under a
    natural sort.
    """
    collected = []
    for item in sorted(attempt_dir.iterdir()):
        if not item.is_file():
            continue
        if item.suffix.lower() == ".png":
            target = job_dir / f"a{attempt}_{item.name}"
            collected.append(f"/screenshots/{target.name}")
        else:
            target = job_dir / item.name
        shutil.move(str(item), str(target))
    shutil.rmtree(attempt_dir, ignore_errors=True)
    return collected


def run(script_path: str, job_id: str, attempt: int = 1) -> dict:
    """Run a Selenium script in an isolated Docker container. Returns ExecutionResult dict."""
    local_script_path = Path(script_path).resolve()
    script_content = local_script_path.read_text(encoding="utf-8")
    check(script_content)

    if config.DEMO_MODE:
        return _demo_run(script_content, job_id)

    client = docker.from_env()
    job_dir = Path(config.DATA_DIR) / "artifacts" / job_id
    attempt_dir = job_dir / f"attempt_{attempt}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(attempt_dir, 0o777)  # the container runs as uid 1000, not as us
    except OSError:
        pass

    container = None
    start = time.time()

    # Chromium needs a writable /tmp and home even with a read-only root filesystem.
    hardening = {}
    if config.SANDBOX_READ_ONLY:
        hardening = {
            "read_only": True,
            "tmpfs": {"/tmp": "size=256m,exec", "/home/sandbox": "size=64m,exec"},
        }

    with _slots:
        try:
            container = client.containers.run(
                image=config.SANDBOX_IMAGE,
                volumes={
                    str(_resolve_bind_source(local_script_path)): {"bind": "/scripts/script.py", "mode": "ro"},
                    str(_resolve_bind_source(attempt_dir)):       {"bind": "/screenshots",       "mode": "rw"},
                },
                mem_limit=f"{config.SANDBOX_MEMORY_MB}m",
                nano_cpus=1_000_000_000,
                pids_limit=config.SANDBOX_PIDS_LIMIT,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                network_mode="bridge",
                extra_hosts={"host.docker.internal": "host-gateway"},
                user="1000",
                detach=True,
                auto_remove=False,
                **hardening,
            )

            try:
                wait_result = container.wait(timeout=config.SANDBOX_TIMEOUT_SECONDS)
            except (APIError, DockerException):
                raise  # a daemon problem is not a script timeout
            except Exception as e:
                # docker-py surfaces the wait timeout as a requests ReadTimeout.
                try:
                    container.kill()
                except Exception:
                    pass
                raise SandboxTimeoutError(
                    f"Container exceeded {config.SANDBOX_TIMEOUT_SECONDS}s timeout") from e

            stdout    = container.logs(stdout=True,  stderr=False).decode("utf-8", errors="replace")
            stderr    = container.logs(stdout=False, stderr=True).decode("utf-8",  errors="replace")
            exit_code = wait_result["StatusCode"]

        except ImageNotFound as e:
            raise ContainerError(
                f"Sandbox image {config.SANDBOX_IMAGE!r} is missing. Build it with: "
                f"docker build -t {config.SANDBOX_IMAGE} ./sandbox") from e
        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    duration = round(time.time() - start, 2)
    result   = parse(stdout, stderr, exit_code)
    # save_screenshot() doesn't print its path, so the files on disk are the real list.
    from_disk = _collect_outputs(attempt_dir, job_dir, attempt)
    result["screenshot_paths"] = from_disk
    result["duration_seconds"] = duration
    log.info("container_run_complete", job_id=job_id, attempt=attempt,
             exit_code=exit_code, duration=duration)
    return result


def _demo_run(script_content: str, job_id: str) -> dict:
    """Simulate an execution for DEMO_MODE, without Docker or a browser.

    It replays the verdict the script would print, so the pipeline can be demonstrated
    end to end. It proves nothing about the target application, and the result is
    marked ``simulated`` so the UI and the API never present it as evidence.
    """
    log.info("demo_mode_execution", job_id=job_id)
    time.sleep(2.5)

    # A simulator cannot know what the page does, so it only checks the one thing it can:
    # does the script honour the verdict contract? If not, the attempt is refined, exactly
    # as a real run would be.
    emits_verdict = VERDICT_PREFIX in script_content

    lines = [
        "SIMULATED RUN — DEMO_MODE is on. No browser started, no page visited.",
        "This output is generated, not observed. It is not evidence of a real bug.",
        "Setting up Chrome driver...",
        "Navigating to target page...",
        "Executing test steps...",
    ]
    if emits_verdict:
        lines.append(f'{VERDICT_PREFIX} {{"reproduced": true, "variant": "simulated", '
                     f'"evidence": "SIMULATED — DEMO_MODE did not run a browser"}}')
    else:
        lines.append("Script printed no AUTOREPRO_RESULT verdict line.")

    stdout = "\n".join(lines) + "\n"
    result = parse(stdout, "", 0)
    result["duration_seconds"] = 2.5
    result["simulated"] = True
    verdict = parse_verdict(stdout)
    log.info("demo_run_complete", job_id=job_id,
             reproduced=bool(verdict and verdict["reproduced"]))
    return result
