"""Public entrypoint — runs the full agent loop and persists the result."""

from datetime import UTC, datetime

from agent.graph import compiled, route_after_evaluate, route_after_refine
from agent.state import AgentState
from storage import jobs as job_store
from storage.artifacts import save_final_script
from utils import config
from utils.id_generator import new_job_id
from utils.logger import get_logger

log = get_logger(__name__)

# Stage that runs after each node completes — lets the UI show live progress.
_NEXT_STAGE = {
    "analyze":  "inspect",
    "inspect":  "generate",
    "generate": "execute",
    "execute":  "evaluate",
    "evaluate": "refine",
    "refine":   "execute",
}


def run_agent(bug_report: str, target_url: str, job_id: str | None = None) -> dict:
    """Public entrypoint. Runs the full agent loop and persists the result."""
    caller_provided_job = job_id is not None
    if job_id is None:
        job_id = new_job_id()

    initial_state: AgentState = {
        "job_id": job_id,
        "bug_report": bug_report,
        "target_url": target_url,
        "attempt_count": 0,
        "max_attempts": config.MAX_ATTEMPTS,
        "analysis": {},
        "dom_context": "",
        "script": "",
        "execution_result": {},
        "success": False,
        "bug_absent": False,
        "history": [],
    }

    # Only save initial state if the API layer hasn't already created the job
    if not caller_provided_job:
        job_store.save(job_id, {
            **initial_state,
            "status": "processing",
            "created_at": datetime.now(UTC).isoformat(),
        })

    # Merge into the existing record so fields written by the API (e.g. created_at) survive
    record = job_store.get(job_id) or {}
    state = dict(initial_state)
    stage = "analyze"
    job_store.save(job_id, {**record, **state, "status": "processing", "stage": stage})

    try:
        # Each graph step = analyze/inspect/generate + 3 per attempt; leave headroom
        run_config = {"recursion_limit": 3 * config.MAX_ATTEMPTS + 10}
        for update in compiled.stream(initial_state, run_config, stream_mode="updates"):
            for node, output in update.items():
                state = {**state, **(output or {})}
                stage = _NEXT_STAGE.get(node)
                # Show the stage the run stopped on, not the one that would have been next.
                if node == "evaluate" and route_after_evaluate(state) != "refine":
                    stage = "evaluate"
                elif node == "refine" and route_after_refine(state) != "execute":
                    stage = "refine"
                job_store.save(job_id, {**record, **state, "status": "processing", "stage": stage})

        result = {
            **record,
            **state,
            "status": "done",
            "stage": None,
            "final_script": state["script"],
            "completed_at": datetime.now(UTC).isoformat(),
        }
        # Persist the final script as a downloadable artifact
        if state.get("script"):
            save_final_script(job_id, state["script"])
    except Exception as e:
        log.error("agent_error", job_id=job_id, error=str(e))
        # Keep whatever progress was made (analysis, attempts) for debugging
        result = {
            **record,
            **state,
            "status": "failed",
            "stage": stage,  # the node that was running when it failed
            "error": str(e),
            "completed_at": datetime.now(UTC).isoformat(),
        }

    job_store.save(job_id, result)
    log.info("agent_complete", job_id=job_id, success=result.get("success"))
    return result
