"""Script and screenshot persistence helpers."""

import os
from pathlib import Path

from utils import config


def artifacts_dir(job_id: str) -> Path:
    """Return the artifacts directory for a job, creating it if needed."""
    artifacts_root = Path(config.DATA_DIR) / "artifacts"
    artifacts_root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(artifacts_root, 0o777)
    except OSError:
        pass

    p = Path(config.DATA_DIR) / "artifacts" / job_id
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o777)
    except OSError:
        pass
    return p


def save_final_script(job_id: str, script: str) -> Path:
    """Save the final reproduction script for a job."""
    p = artifacts_dir(job_id) / "final.py"
    p.write_text(script, encoding="utf-8")
    return p
