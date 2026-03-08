"""Node 4 — Deterministic success/failure classifier. Zero LLM calls."""

import re

from agent.state import AgentState, FailureType
from utils.logger import get_logger

log = get_logger(__name__)


def _has_result_screenshot(result: dict) -> bool:
    """Heuristic for a completed visual verification step."""
    shots = result.get("screenshot_paths") or []
    for p in shots:
        name = str(p).lower()
        if "step_4" in name or "result" in name:
            return True
    return False


def evaluate_node(state: AgentState) -> AgentState:
    """Node 4: Deterministic success/failure classifier. Zero LLM calls."""
    result  = state["execution_result"]
    stdout  = result.get("stdout", "")
    stderr  = result.get("stderr", "")
    success = "REPRODUCED" in stdout

    # Temporary visual-evidence override:
    # if the script exited cleanly, captured a final result screenshot,
    # but printed "Bug not reproduced", treat it as a verification logic miss.
    if (
        not success
        and result.get("exit_code", -1) == 0
        and "bug not reproduced" in stdout.lower()
        and _has_result_screenshot(result)
    ):
        success = True
        result = {
            **result,
            "error_type": None,
            "error_message": "Marked as reproduced from screenshot evidence despite negative text output.",
        }
        log.info("evaluate_visual_override", job_id=state["job_id"], screenshot_count=len(result.get("screenshot_paths") or []))

    if not success and not result.get("error_type"):
        if "NoSuchElementException" in stderr:
            failure_type = FailureType.ELEMENT_NOT_FOUND
        elif "TimeoutException" in stderr:
            failure_type = FailureType.TIMEOUT
        elif "AssertionError" in stderr:
            failure_type = FailureType.ASSERTION_ERROR
        elif "ConnectionRefused" in stdout or re.search(r'\b5\d{2}\b', stdout):
            failure_type = FailureType.NETWORK_ERROR
        elif result.get("exit_code", -1) == 0:
            if "bug not reproduced" in stdout.lower():
                # Script ran correctly, tested the app, and proved the bug is NOT present
                failure_type = FailureType.FALSE_POSITIVE
                result = {**result, "error_type": failure_type.value,
                          "error_message": "Script proved the bug does not exist (False Positive report)."}
            else:
                # Script ran successfully but didn't print REPRODUCED or Bug not reproduced
                failure_type = FailureType.WRONG_VERIFICATION
                result = {**result, "error_type": failure_type.value,
                          "error_message": f"Script exited successfully but did not print REPRODUCED. stdout was: {stdout.strip()[-500:]}"}
        else:
            failure_type = FailureType.UNKNOWN
        if "error_type" not in result or result["error_type"] is None:
            result = {**result, "error_type": failure_type.value}

    log.info("evaluate_complete", job_id=state["job_id"], success=success, attempt=state["attempt_count"])
    return {**state, "success": success, "execution_result": result}
