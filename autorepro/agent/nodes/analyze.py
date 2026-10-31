"""Node 1 — LLM bug analysis: parse bug report into structured AnalysisResult JSON."""

from pathlib import Path

from agent.common import extract_json_object, extract_text
from agent.state import AgentState
from utils.llm import get_llm
from utils.logger import get_logger

log = get_logger(__name__)

REQUIRED_KEYS = {"inferred_steps", "target_elements", "expected_behavior",
                 "success_condition", "risk_factors"}


def _get_llm():
    """Return the configured LLM instance."""
    return get_llm(temperature=0)


def _normalise(analysis: dict, bug_report: str) -> dict:
    """Fill in optional keys the prompt asks for but models sometimes drop."""
    variants = analysis.get("bug_variants")
    if not isinstance(variants, list) or not variants:
        # generate.txt tells the script to check every variant; without this a model that
        # skipped the key silently downgraded the run to a single verification strategy.
        analysis["bug_variants"] = [{
            "interpretation": f"Primary reading of the report: {bug_report[:160]}",
            "success_condition": analysis.get("success_condition", ""),
        }]
    return analysis


def analyze_node(state: AgentState) -> AgentState:
    """Node 1: Parse bug report into structured AnalysisResult JSON."""
    project_root = Path(__file__).resolve().parent.parent.parent
    template = (project_root / "prompts" / "analyze.txt").read_text(encoding="utf-8")
    prompt   = template.format(bug_report=state["bug_report"], target_url=state["target_url"])
    llm      = _get_llm()
    last_error = "unknown"

    for attempt in range(2):
        response = llm.invoke(prompt)
        content  = extract_text(response.content)
        try:
            # Models wrap JSON in ```json fences even when told not to, so parse leniently.
            analysis = extract_json_object(content)
            missing = REQUIRED_KEYS - analysis.keys()
            if missing:
                raise ValueError(f"Missing keys: {missing}")
            log.info("analyze_success", job_id=state["job_id"])
            return {**state, "analysis": _normalise(analysis, state["bug_report"])}
        except ValueError as e:  # includes json.JSONDecodeError
            last_error = str(e)
            log.warning("analyze_parse_error", attempt=attempt, error=last_error)
            if attempt == 0:
                prompt += (f"\n\nYour previous response could not be used ({last_error}). "
                           "Return ONLY raw JSON with every required key.")

    raise RuntimeError(f"analyze_node: LLM returned unusable JSON after 2 attempts ({last_error})")
