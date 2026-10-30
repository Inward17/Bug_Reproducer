"""Node 4 — Deterministic success/failure classifier. Zero LLM calls."""

from agent.common import parse_verdict
from agent.state import AgentState, FailureType
from utils.logger import get_logger

log = get_logger(__name__)


def evaluate_node(state: AgentState) -> AgentState:
    """Node 4: Deterministic success/failure classifier. Zero LLM calls.

    A run only succeeds when the script printed a structured verdict saying the bug was
    reproduced *and* exited cleanly. Matching free text meant a script that crashed after
    logging "Step 4: checking whether the bug is reproduced" was reported as a success.
    """
    result    = state["execution_result"]
    stdout    = result.get("stdout", "")
    exit_code = result.get("exit_code", -1)
    verdict   = parse_verdict(stdout)

    crashed = exit_code != 0 or result.get("error_type") is not None
    success = verdict is not None and verdict["reproduced"] and not crashed

    if not success and result.get("error_type") is None:
        if verdict is None:
            failure_type = FailureType.WRONG_VERIFICATION
            message = ("Script exited cleanly but never printed an AUTOREPRO_RESULT verdict line. "
                       f"Last stdout: {stdout.strip()[-500:]}")
        else:
            # The script ran the steps and checked the page, but saw no sign of the bug.
            # This is the most common first-attempt outcome and it needs refinement, not
            # an immediate "bug does not exist" verdict.
            failure_type = FailureType.BUG_NOT_OBSERVED
            message = ("Script completed but reported reproduced=false. "
                       f"Evidence: {str(verdict.get('evidence', ''))[:300]}")
        result = {**result, "error_type": failure_type.value, "error_message": message}

    log.info("evaluate_complete", job_id=state["job_id"], success=success,
             attempt=state["attempt_count"], error_type=result.get("error_type"))
    return {**state, "success": success, "execution_result": result}
