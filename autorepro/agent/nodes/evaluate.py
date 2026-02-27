"""Node 4 — Deterministic success/failure classifier. Zero LLM calls."""

from agent.state import AgentState, FailureType
from utils.logger import get_logger

log = get_logger(__name__)


def evaluate_node(state: AgentState) -> AgentState:
    """Node 4: Deterministic success/failure classifier. Zero LLM calls."""
    result  = state["execution_result"]
    stdout  = result.get("stdout", "")
    stderr  = result.get("stderr", "")
    success = "REPRODUCED" in stdout

    if not success:
        if "NoSuchElementException" in stderr:
            failure_type = FailureType.ELEMENT_NOT_FOUND
        elif "TimeoutException" in stderr:
            failure_type = FailureType.TIMEOUT
        elif "AssertionError" in stderr:
            failure_type = FailureType.ASSERTION_ERROR
        elif "ConnectionRefused" in stdout or "5xx" in stdout:
            failure_type = FailureType.NETWORK_ERROR
        else:
            failure_type = FailureType.UNKNOWN
        result = {**result, "error_type": failure_type.value}

    log.info("evaluate_complete", job_id=state["job_id"], success=success, attempt=state["attempt_count"])
    return {**state, "success": success, "execution_result": result}
