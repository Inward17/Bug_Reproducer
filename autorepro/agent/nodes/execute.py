"""Node 3 — Docker execution: write script to disk and run in sandbox (no LLM)."""

from agent.common import is_valid_python
from agent.state import AgentState
from sandbox import runner
from sandbox.security import SecurityError
from storage.artifacts import artifacts_dir
from utils import config
from utils.logger import get_logger

log = get_logger(__name__)


def _failed(error_type: str, message: str, duration: float = 0) -> dict:
    """An ExecutionResult for a run that never reached the container."""
    return {
        "stdout": "", "stderr": message, "exit_code": -1,
        "error_type": error_type, "error_message": message,
        "stack_trace": None, "screenshot_paths": [], "duration_seconds": duration,
    }


def execute_node(state: AgentState) -> AgentState:
    """Node 3: Write script to disk and run it in the Docker sandbox."""
    attempt_num = state["attempt_count"] + 1
    script_path = artifacts_dir(state["job_id"]) / f"attempt_{attempt_num}.py"
    script_path.write_text(state["script"], encoding="utf-8")

    if not state["script"].strip():
        result = _failed("NoScript", "No script was generated for this attempt.")
    elif not is_valid_python(state["script"]):
        # Don't hand invalid Python to the security scanner — it reports a syntax problem
        # as a "SecurityViolation", which sends refine off diagnosing the wrong thing.
        result = _failed("SyntaxError", "Generated script is not valid Python.")
    else:
        try:
            result = runner.run(str(script_path), state["job_id"], attempt=attempt_num)
        except SecurityError as e:
            result = _failed("SecurityViolation", str(e))
        except runner.SandboxTimeoutError:
            result = _failed("Timeout", "Container timeout", config.SANDBOX_TIMEOUT_SECONDS)
        except runner.ContainerError as e:
            log.error("execute_container_error", job_id=state["job_id"], error=str(e))
            result = _failed("ContainerError", str(e))
        except Exception as e:
            log.error("execute_unexpected_error", job_id=state["job_id"], error=str(e))
            result = _failed("InternalError", str(e))

    new_history = list(state["history"]) + [
        {"attempt": attempt_num, "script": state["script"], "result": result}
    ]
    log.info("execute_complete", job_id=state["job_id"], attempt=attempt_num,
             exit_code=result["exit_code"], error_type=result.get("error_type"))

    return {**state, "attempt_count": attempt_num, "execution_result": result,
            "history": new_history}
