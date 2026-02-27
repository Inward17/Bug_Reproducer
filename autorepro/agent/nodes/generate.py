"""Node 2 — LLM script generation: analysis → Python/Selenium script."""

import ast
import json
from pathlib import Path

from agent.state import AgentState
from utils import config
from utils.logger import get_logger

log = get_logger(__name__)


def _get_llm():
    """Return the configured LLM instance with slight temperature for creativity."""
    if config.LLM_PROVIDER == "mock":
        from utils.mock_llm import MockLLM
        return MockLLM()
    if config.LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=config.LLM_MODEL, temperature=0.2)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=config.LLM_MODEL, temperature=0.2)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def generate_node(state: AgentState) -> AgentState:
    """Node 2: Generate a Python/Selenium script from the structured analysis."""
    prior = "\n".join(
        f"Attempt {h['attempt']}: {h.get('refinement_note', 'No note')}"
        for h in state["history"]
    ) or "None"

    template = Path("prompts/generate.txt").read_text()
    prompt   = template.format(
        analysis_json=json.dumps(state["analysis"], indent=2),
        target_url=state["target_url"],
        prior_failures=prior,
    )
    llm = _get_llm()

    for attempt in range(2):
        response = llm.invoke(prompt)
        script   = _strip_fences(response.content)
        try:
            ast.parse(script)
            log.info("generate_success", job_id=state["job_id"])
            return {**state, "script": script}
        except SyntaxError as e:
            log.warning("generate_syntax_error", attempt=attempt, error=str(e))
            if attempt == 0:
                prompt += f"\n\nSyntax error: {e}. Fix it and return ONLY the corrected script."

    return {**state, "script": script}
