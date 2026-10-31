"""Node 2 — LLM script generation: analysis → Python/Selenium script."""

import json
from pathlib import Path

from agent.common import extract_text, fix_url, is_valid_python, strip_fences
from agent.state import AgentState
from utils.llm import get_llm
from utils.logger import get_logger

log = get_logger(__name__)


def _get_llm():
    """Return the configured LLM instance with slight temperature for creativity."""
    return get_llm(temperature=0.2)


def generate_node(state: AgentState) -> AgentState:
    """Node 2: Generate a Python/Selenium script from the structured analysis."""
    prior = "\n".join(
        f"Attempt {h['attempt']}: {h.get('refinement_note', 'No note')}"
        for h in state["history"]
    ) or "None"

    project_root = Path(__file__).resolve().parent.parent.parent
    template = (project_root / "prompts" / "generate.txt").read_text(encoding="utf-8")
    # str.format does not re-parse substituted values, so brace-escaping them was wrong:
    # the model used to receive the analysis as {{"inferred_steps": ...}}.
    prompt   = template.format(
        analysis_json=json.dumps(state["analysis"], indent=2),
        target_url=state["target_url"],
        dom_context=state.get("dom_context") or "Not available",
        prior_failures=prior,
    )
    llm = _get_llm()
    script = ""

    for attempt in range(2):
        response = llm.invoke(prompt)
        script   = fix_url(strip_fences(extract_text(response.content)), state["target_url"])
        if is_valid_python(script):
            log.info("generate_success", job_id=state["job_id"])
            return {**state, "script": script}
        log.warning("generate_syntax_error", job_id=state["job_id"], attempt=attempt)
        if attempt == 0:
            prompt += ("\n\nYour previous reply was not valid Python. "
                       "Return ONLY the corrected script, no prose and no fences.")

    log.error("generate_invalid_script", job_id=state["job_id"])
    return {**state, "script": script}
