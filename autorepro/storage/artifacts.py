"""Script and screenshot persistence helpers."""

import re
from pathlib import Path

from utils import config
from utils.id_generator import require_job_id

SCREENSHOT_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*\.png$')


def artifacts_root() -> Path:
    """Return the root artifacts directory, creating it if needed."""
    root = Path(config.DATA_DIR) / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def artifacts_dir(job_id: str) -> Path:
    """Return a job's artifacts directory, creating it. For write paths only."""
    path = artifacts_root() / require_job_id(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def existing_artifacts_dir(job_id: str) -> Path | None:
    """Return a job's artifacts directory only if it already exists.

    Read endpoints use this: calling artifacts_dir() on a GET used to create a directory
    for any ID a caller invented.
    """
    try:
        path = artifacts_root() / require_job_id(job_id)
    except ValueError:
        return None
    return path if path.is_dir() else None


def screenshot_path(job_id: str, filename: str) -> Path | None:
    """Resolve a screenshot inside a job's directory, or None if it isn't one.

    Only a plain ``*.png`` name is accepted, and the resolved path must stay inside the
    job directory — so neither "../.." nor a backslash on Windows can escape, and
    non-image artifacts (dom.html, attempt_N.py) are never served.
    """
    job_dir = existing_artifacts_dir(job_id)
    if job_dir is None or not SCREENSHOT_NAME.match(filename):
        return None
    candidate = (job_dir / filename).resolve()
    if candidate.parent != job_dir.resolve() or not candidate.is_file():
        return None
    return candidate


def save_final_script(job_id: str, script: str) -> Path:
    """Save the final reproduction script for a job."""
    path = artifacts_dir(job_id) / "final.py"
    path.write_text(script, encoding="utf-8")
    return path
