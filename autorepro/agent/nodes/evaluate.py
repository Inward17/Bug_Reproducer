"""Node 4 — Deterministic success/failure classifier. Zero LLM calls."""

import re

from agent.common import PAGE_TEXT_PREFIX, parse_verdict
from agent.state import AgentState, FailureType
from utils.logger import get_logger

log = get_logger(__name__)

# Steps that change the page. A report whose steps include one of these describes a bug
# that appears only after an action, so evidence visible on first load can't prove it.
_ACTION_STEP = re.compile(
    # "check" is left out on purpose: "check that the page shows X" is an observation.
    r'\b(click|press|tap|submit|enter|type|fill|select|choose|toggle|upload|drag|'
    r'hover|scroll|log ?in|sign ?in|add|remove|delete|save|send)\b', re.IGNORECASE)
# Shorter evidence ("OK", "a") is too likely to be on any page to mean anything.
_MIN_EVIDENCE_CHARS = 4


def _baseline_page_text(stdout: str) -> str | None:
    """The PAGE_TEXT line printed right after the first navigation, before any action."""
    for line in (stdout or "").splitlines():
        if line.startswith(PAGE_TEXT_PREFIX):
            return line[len(PAGE_TEXT_PREFIX):].strip()
    return None


def _needs_action(analysis: dict | None) -> bool:
    steps = (analysis or {}).get("inferred_steps") or []
    # The first step is the navigation itself.
    return any(_ACTION_STEP.search(str(step)) for step in steps[1:])


def _evidence_before_action(verdict: dict, stdout: str, analysis: dict | None) -> str | None:
    """Return the evidence if it was already on the page before the reproduction steps.

    Refine is asked to pick a different verification condition after each miss, and the
    only thing graded is whether the script says reproduced=true. Without this check it can
    drift to a condition that holds on the untouched page ("'Sign in' is visible") and
    report a bug it never triggered.
    """
    evidence = str(verdict.get("evidence") or "").strip()
    baseline = _baseline_page_text(stdout)
    if len(evidence) < _MIN_EVIDENCE_CHARS or baseline is None or not _needs_action(analysis):
        return None
    return evidence if evidence.lower() in baseline.lower() else None


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

    # The exit code is the crash signal. error_type can be set on a clean exit too (a page
    # that printed a network error string), and it must not veto a verdict on its own.
    success = verdict is not None and verdict["reproduced"] and exit_code == 0

    stale = (_evidence_before_action(verdict, stdout, state.get("analysis"))
             if success else None)
    if stale is not None:
        success = False
        result = {**result,
                  "error_type": FailureType.EVIDENCE_BEFORE_ACTION.value,
                  "error_message": (
                      f"The script reported reproduced=true with evidence {stale[:200]!r}, but "
                      "that text was already on the page right after it loaded, before any "
                      "reproduction step ran. It can't prove the bug. Check for something that "
                      "only appears after the action.")}
    elif success:
        result = {**result, "error_type": None, "error_message": None}
    elif result.get("error_type") is None:
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
