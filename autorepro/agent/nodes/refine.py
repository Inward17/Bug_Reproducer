"""Node 5 — LLM script refinement: rewrite script based on failure feedback."""

import ast
import json
from pathlib import Path

from agent.state import AgentState
from utils import config
from utils.logger import get_logger

log = get_logger(__name__)


def _get_llm():
    """Return the configured LLM instance with moderate temperature for variation."""
    if config.LLM_PROVIDER == "mock":
        from utils.mock_llm import MockLLM
        return MockLLM()
    if config.LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=config.LLM_MODEL, temperature=0.3)
    if config.LLM_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=config.LLM_MODEL, temperature=0.3)
    if config.LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=config.LLM_MODEL, temperature=0.3)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=config.LLM_MODEL, temperature=0.3)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def _extract_script(content: str) -> tuple[str, str]:
    """Separate LLM explanation text from the Python script.

    Returns (refinement_note, script_code).
    """
    lines = content.strip().splitlines()
    python_start_keywords = ('import ', 'from ', 'def ', 'class ', 'try:', '#!', '#', 'driver')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and any(stripped.startswith(kw) for kw in python_start_keywords):
            note = " ".join(lines[:i]).strip() if i > 0 else ""
            script = "\n".join(lines[i:])
            return note or content[:200], _strip_fences(script)
    # Fallback: treat entire content as script
    return content[:200], _strip_fences(content)


def refine_node(state: AgentState) -> AgentState:
    """Node 5: LLM rewrites the script based on failure feedback."""
    history_summary = "\n".join(
        f"Attempt {h['attempt']}: error_type={h['result'].get('error_type')}, note={h.get('refinement_note', 'N/A')}"
        for h in state["history"]
    )
    project_root = Path(__file__).resolve().parent.parent.parent
    template = (project_root / "prompts" / "refine.txt").read_text()
    prompt   = template.format(
        previous_script=state["script"],
        failure_json=json.dumps(state["execution_result"], indent=2),
        history_summary=history_summary,
    )
    llm      = _get_llm()
    response = llm.invoke(prompt)
    content  = response.content.strip()

    refinement_note, corrected_script = _extract_script(content)

    try:
        ast.parse(corrected_script)
    except SyntaxError:
        log.warning("refine_syntax_error", job_id=state["job_id"])

    updated_history = list(state["history"])
    if updated_history:
        updated_history[-1] = {**updated_history[-1], "refinement_note": refinement_note}

    log.info("refine_complete", job_id=state["job_id"], attempt=state["attempt_count"])
    return {**state, "script": corrected_script, "history": updated_history}
