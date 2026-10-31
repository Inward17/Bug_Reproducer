"""Node 5 — LLM script refinement: rewrite script based on failure feedback."""

import json
from pathlib import Path

from agent.common import PAGE_TEXT_PREFIX, extract_text, fix_url, parse_script
from agent.state import AgentState, FailureType
from utils.llm import get_llm
from utils.logger import get_logger

log = get_logger(__name__)

# The model emits this line when the history convinces it the bug genuinely isn't there.
BUG_ABSENT_SENTINEL = "AUTOREPRO_CONCLUSION=BUG_ABSENT"
# Don't trust that conclusion until at least two different strategies have been tried.
MIN_ATTEMPTS_FOR_ABSENT = 2


def _get_llm():
    """Return the configured LLM instance with moderate temperature for variation."""
    return get_llm(temperature=0.3)


# The history grew by a full script plus console output per attempt (~29 KB by attempt 5
# on a tiny page), which pushed the bug report and rules out of a small model's context.
# The latest attempts stay verbatim; older ones keep only what they tried and what the
# page showed.
FULL_HISTORY_ATTEMPTS = 2
MAX_OUTPUT_CHARS = 2000


def _tail(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Keep both ends: PAGE_TEXT is printed first, the verdict and traceback come last."""
    text = text or ""
    if len(text) <= limit:
        return text
    head = limit // 4
    return text[:head] + "\n[...truncated...]\n" + text[-(limit - head):]


def _summarise(h: dict) -> str:
    result = h.get("result", {})
    page_text = [line for line in (result.get("stdout") or "").splitlines()
                 if line.startswith(PAGE_TEXT_PREFIX)]
    return (f"=== ATTEMPT {h['attempt']} (summary) ===\n"
            f"Error type: {result.get('error_type', 'N/A')}\n"
            f"Error message: {str(result.get('error_message') or '')[:300]}\n"
            f"Refinement note: {h.get('refinement_note', 'N/A')}\n"
            f"Page text seen: {page_text[0][:300] if page_text else 'none'}\n")


def _render_history(history: list) -> str:
    """Recent attempts in full and older ones summarised, so the model can't repeat a
    mistake without the history crowding out the rest of the prompt."""
    cutoff = len(history) - FULL_HISTORY_ATTEMPTS
    parts = []
    for i, h in enumerate(history):
        if i < cutoff:
            parts.append(_summarise(h))
            continue
        result = h.get("result", {})
        parts.append(
            f"=== ATTEMPT {h['attempt']} ===\n"
            f"Error type: {result.get('error_type', 'N/A')}\n"
            f"Refinement note: {h.get('refinement_note', 'N/A')}\n\n"
            f"--- Script ---\n{h.get('script', 'N/A')}\n\n"
            f"--- stdout ---\n{_tail(result.get('stdout', ''))}\n\n"
            f"--- stderr ---\n{_tail(result.get('stderr', ''))}\n"
        )
    return "\n".join(parts) if parts else "No previous attempts."


def refine_node(state: AgentState) -> AgentState:
    """Node 5: LLM rewrites the script based on failure feedback."""
    project_root = Path(__file__).resolve().parent.parent.parent
    template = (project_root / "prompts" / "refine.txt").read_text(encoding="utf-8")
    prompt   = template.format(
        bug_report=state["bug_report"],
        previous_script=state["script"],
        failure_json=json.dumps(state["execution_result"], indent=2),
        full_history=_render_history(state["history"]),
        dom_context=state.get("dom_context") or "Not available",
        target_url=state["target_url"],
    )
    llm = _get_llm()
    note, script = "", None

    # Same validate-and-retry contract as generate_node. Running a script that failed
    # ast.parse only burned an attempt on a bogus "SecurityViolation".
    for attempt in range(2):
        content = extract_text(llm.invoke(prompt).content)
        note, script = parse_script(content)
        if script is not None:
            break
        log.warning("refine_syntax_error", job_id=state["job_id"], attempt=attempt)
        if attempt == 0:
            prompt += ("\n\nYour previous reply did not contain a valid Python script. "
                       "Return your explanation first, then the COMPLETE script in a "
                       "```python fenced block.")

    concluded_absent = (BUG_ABSENT_SENTINEL in content
                        and state["attempt_count"] >= MIN_ATTEMPTS_FOR_ABSENT)

    if script is None:
        log.error("refine_no_valid_script", job_id=state["job_id"])
        script = state["script"]  # keep the last runnable script rather than shipping prose
    else:
        script = fix_url(script, state["target_url"])

    updated_history = list(state["history"])
    if updated_history:
        updated_history[-1] = {**updated_history[-1], "refinement_note": note}

    patch: AgentState = {**state, "script": script, "history": updated_history}

    if concluded_absent:
        log.info("refine_bug_absent", job_id=state["job_id"], attempt=state["attempt_count"])
        patch["bug_absent"] = True
        patch["execution_result"] = {
            **state["execution_result"],
            "error_type": FailureType.FALSE_POSITIVE.value,
            "error_message": (f"After {state['attempt_count']} attempts with different "
                              "strategies, the agent concluded the reported bug is not "
                              "present on this page."),
        }
    else:
        log.info("refine_complete", job_id=state["job_id"], attempt=state["attempt_count"])

    return patch
