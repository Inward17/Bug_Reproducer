"""Job CRUD — read/write data/jobs/<id>.json with atomic writes."""

import json
import os
from pathlib import Path

from utils import config
from utils.id_generator import is_job_id, require_job_id
from utils.logger import get_logger

log = get_logger(__name__)

JOBS_DIR = Path(config.DATA_DIR) / "jobs"


def _path(job_id: str) -> Path:
    """Return the path to a job's JSON file, ensuring the directory exists."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    # The ID is a path segment, so it must be a UUID and nothing else.
    return JOBS_DIR / f"{require_job_id(job_id)}.json"


def save(job_id: str, data: dict) -> None:
    """Atomically write job data to disk."""
    target = _path(job_id)
    tmp    = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, target)


def get(job_id: str) -> dict | None:
    """Load a job by ID. Returns None if not found or if the ID is not a job ID."""
    if not is_job_id(job_id):
        return None
    path = _path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("job_unreadable", job_id=job_id, error=str(e))
        return None


def update_status(job_id: str, status: str) -> None:
    """Update just the status field of a job."""
    data = get(job_id)
    if data:
        save(job_id, {**data, "status": status})


def list_all() -> list[dict]:
    """Every persisted job, newest first. Unreadable files are skipped, not fatal."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    for path in JOBS_DIR.glob("*.json"):
        try:
            jobs.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("job_unreadable", path=str(path), error=str(e))
    jobs.sort(key=lambda job: job.get("created_at") or "", reverse=True)
    return jobs
