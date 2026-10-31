"""FastAPI endpoint handlers for AutoRepro API."""

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from agent.orchestrator import run_agent
from api.schemas import JobCreatedResponse, ReproduceRequest
from storage import jobs as job_store
from storage.artifacts import existing_artifacts_dir, screenshot_path
from utils import config
from utils.id_generator import new_job_id
from utils.net import BlockedTargetError, check_target


def require_api_key(
    x_api_key: str | None = Header(default=None),
    autorepro_api_key: str | None = Cookie(default=None),
) -> None:
    """Enforce the shared API key, when one is configured.

    With API_KEY unset the API is open, which is only appropriate on localhost.
    The cookie is accepted as well because a browser can't put a header on an
    ``<img src>`` request, and the screenshot route serves those.
    """
    if not config.API_KEY:
        return
    if config.API_KEY not in (x_api_key, autorepro_api_key):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "A valid X-API-Key header is required."},
        )


router = APIRouter(dependencies=[Depends(require_api_key)])

_SUMMARY_KEYS = (
    "job_id", "status", "success", "stage", "attempt_count", "max_attempts",
    "bug_report", "target_url", "error", "created_at", "completed_at",
)


def _attempt_summaries(job: dict) -> list[dict]:
    """Per-attempt details for the UI's attempt timeline."""
    attempts = []
    for h in job.get("history", []):
        result = h.get("result", {})
        attempts.append({
            "attempt": h.get("attempt"),
            "error_type": result.get("error_type"),
            "error_message": result.get("error_message"),
            "exit_code": result.get("exit_code"),
            "duration_seconds": result.get("duration_seconds"),
            "simulated": result.get("simulated", False),
            "refinement_note": h.get("refinement_note"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "script": h.get("script", ""),
        })
    return attempts


def _screenshot_urls(job_id: str) -> list[str]:
    """Screenshot URLs for a job, in attempt then step order."""
    job_dir = existing_artifacts_dir(job_id)
    if job_dir is None:
        return []
    names = sorted(p.name for p in job_dir.glob("*.png"))
    return [f"/result/{job_id}/screenshot/{name}" for name in names]


def _load_job(job_id: str) -> dict:
    """Load a job or raise a 404. Never creates anything on disk."""
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "No job with that ID exists."},
        )
    return job


@router.post("/reproduce", response_model=JobCreatedResponse, status_code=202)
def reproduce(request: ReproduceRequest, background_tasks: BackgroundTasks):
    """Accept a bug report and start asynchronous reproduction.

    The handlers in this module are plain ``def`` on purpose: they resolve DNS and read
    job files, and FastAPI runs sync handlers in a thread pool. As ``async def`` they
    blocked the event loop, stalling every other request while one ran.
    """
    target_url = str(request.target_url)
    try:
        # Reject an unfetchable target now, with a clear error, instead of failing a job.
        check_target(target_url)
    except BlockedTargetError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "TARGET_NOT_ALLOWED", "message": str(e)},
        ) from e

    job_id = new_job_id()
    job_store.save(job_id, {
        "job_id": job_id,
        "status": "processing",
        "stage": "analyze",
        "bug_report": str(request.bug_report),
        "target_url": target_url,
        "created_at": datetime.now(UTC).isoformat(),
    })
    background_tasks.add_task(run_agent, str(request.bug_report), target_url, job_id)
    return JobCreatedResponse(job_id=job_id, status="processing")


@router.get("/result/{job_id}")
def get_result(job_id: str):
    """Get the current status/result of a reproduction job."""
    job = _load_job(job_id)

    if job.get("status") == "processing":
        return {
            "job_id": job_id,
            "status": "processing",
            "stage": job.get("stage"),
            "attempt_count": job.get("attempt_count", 0),
            "max_attempts": job.get("max_attempts"),
            "bug_report": job.get("bug_report"),
            "target_url": job.get("target_url"),
            "analysis": job.get("analysis") or None,
            "attempts": _attempt_summaries(job),
            "screenshot_urls": _screenshot_urls(job_id),
            "created_at": job.get("created_at"),
        }

    logs = ""
    for h in job.get("history", []):
        result = h.get("result", {})
        logs += result.get("stdout", "")
        if result.get("stderr"):
            logs += f"\n[stderr attempt {h.get('attempt', '?')}]\n{result['stderr']}\n"

    execution_result = job.get("execution_result", {})

    return {
        "job_id": job_id,
        "status": job.get("status", "unknown"),
        "success": job.get("success"),
        "bug_absent": job.get("bug_absent", False),
        "simulated": bool(execution_result.get("simulated")),
        "attempt_count": job.get("attempt_count"),
        "final_script": job.get("final_script") or job.get("script"),
        "screenshot_urls": _screenshot_urls(job_id),
        "logs": logs,
        "error_type": execution_result.get("error_type"),
        "error_message": execution_result.get("error_message"),
        "stderr": execution_result.get("stderr"),
        "error": job.get("error"),
        "stage": job.get("stage"),
        "max_attempts": job.get("max_attempts"),
        "bug_report": job.get("bug_report"),
        "target_url": job.get("target_url"),
        "analysis": job.get("analysis") or None,
        "attempts": _attempt_summaries(job),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
    }


@router.get("/result/{job_id}/script")
def get_script(job_id: str):
    """Download the final reproduction script as a .py file."""
    _load_job(job_id)
    job_dir = existing_artifacts_dir(job_id)
    path = job_dir / "final.py" if job_dir else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Script not yet available")
    return FileResponse(str(path), media_type="text/plain", filename="reproduction.py")


@router.get("/result/{job_id}/screenshot/{filename}")
def get_screenshot(job_id: str, filename: str):
    """Serve a screenshot image captured during execution."""
    path = screenshot_path(job_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(str(path), media_type="image/png")


@router.get("/jobs")
def list_jobs(
    summary: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List jobs, newest first. `?summary=true` returns light rows for the history panel."""
    jobs = job_store.list_all()[offset:offset + limit]
    if not summary:
        return jobs
    return [{key: job.get(key) for key in _SUMMARY_KEYS} for job in jobs]
