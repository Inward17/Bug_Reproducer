"""Node 4 — Deterministic success/failure classifier. Zero LLM calls."""

import re

from agent.state import AgentState, FailureType
from utils.logger import get_logger

log = get_logger(__name__)



# Patterns that indicate the bug WAS reproduced (case-insensitive).
# Checked AFTER confirming it's not a negative ("not reproduced").
_REPRODUCED_PATTERNS = re.compile(
    r'(?i)'                          # case-insensitive
    r'(?:'
    r'reproduced'                    # standalone "REPRODUCED"
    r'|bug\s+(?:was\s+|has\s+been\s+)?reproduced'  # "Bug reproduced", "Bug was reproduced"
    r'|reproduction\s+successful'    # "Reproduction successful"
    r'|successfully\s+reproduced'    # "Successfully reproduced"
    r'|bug\s+confirmed'              # "Bug confirmed"
    r'|issue\s+reproduced'           # "Issue reproduced"
    r'|issue\s+confirmed'            # "Issue confirmed"
    r')'
)

# Patterns that indicate the bug was NOT reproduced (case-insensitive).
_NOT_REPRODUCED_PATTERNS = re.compile(
    r'(?i)'
    r'(?:'
    r'not\s+reproduced'              # "not reproduced", "NOT REPRODUCED"
    r'|could\s+not\s+reproduce'      # "could not reproduce"
    r'|cannot\s+reproduce'           # "cannot reproduce"
    r'|failed\s+to\s+reproduce'      # "failed to reproduce"
    r'|reproduction\s+failed'        # "reproduction failed"
    r'|bug\s+not\s+confirmed'        # "bug not confirmed"
    r'|no\s+bug\s+found'             # "no bug found"
    r')'
)


def evaluate_node(state: AgentState) -> AgentState:
    """Node 4: Deterministic success/failure classifier. Zero LLM calls."""
    result  = state["execution_result"]
    stdout  = result.get("stdout", "")
    stderr  = result.get("stderr", "")

    # Check negative patterns first so "not reproduced" doesn't match "reproduced"
    has_negative = bool(_NOT_REPRODUCED_PATTERNS.search(stdout))
    has_positive = bool(_REPRODUCED_PATTERNS.search(stdout))

    success = has_positive and not has_negative

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
            if has_negative:
                # Script ran correctly, tested the app, and proved the bug is NOT present
                failure_type = FailureType.FALSE_POSITIVE
                result = {**result, "error_type": failure_type.value,
                          "error_message": "Script proved the bug does not exist (False Positive report)."}
            else:
                # Script ran successfully but didn't print any reproduction verdict
                failure_type = FailureType.WRONG_VERIFICATION
                result = {**result, "error_type": failure_type.value,
                          "error_message": f"Script exited successfully but did not print a reproduction verdict. stdout was: {stdout.strip()[-500:]}"}
        else:
            failure_type = FailureType.UNKNOWN
        if "error_type" not in result or result["error_type"] is None:
            result = {**result, "error_type": failure_type.value}

    log.info("evaluate_complete", job_id=state["job_id"], success=success, attempt=state["attempt_count"])
    return {**state, "success": success, "execution_result": result}
