"""Node 5 — LLM script refinement: rewrite script based on failure feedback."""

import ast
import json
import re
from pathlib import Path

from agent.state import AgentState
from utils.llm import get_llm
from utils.logger import get_logger

log = get_logger(__name__)


def _extract_text(content) -> str:
    """Safely extract text from an LLM response's .content field.

    ChatBedrockConverse returns a list of content blocks like
    [{"type": "text", "text": "..."}], while other providers return
    a plain string. This handles both.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts).strip()
    return str(content).strip()


def _get_llm():
    """Return the configured LLM instance with moderate temperature for variation."""
    return get_llm(temperature=0.3)


def _extract_script(content: str) -> tuple[str, str]:
    """Separate LLM explanation text from the Python script.

    The LLM often returns markdown like:
        ### Explanation\n...\n```python\n<code>\n```
    We extract the code from within the fences.
    Returns (refinement_note, script_code).
    """
    # Strategy 1: Extract code from ```python ... ``` fences
    fence_pattern = re.compile(r'```(?:python)?\s*\n(.*?)\n```', re.DOTALL)
    matches = fence_pattern.findall(content)
    if matches:
        # Use the last (most likely corrected) code block
        script = matches[-1].strip()
        # Everything before the first fence is the note
        first_fence = content.find('```')
        note = content[:first_fence].strip() if first_fence > 0 else content[:200]
        return note, script

    # Strategy 2: Look for lines starting with Python keywords
    lines = content.strip().splitlines()
    python_start_keywords = ('import ', 'from ', 'def ', 'class ', 'try:', 'driver')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and any(stripped.startswith(kw) for kw in python_start_keywords):
            note = " ".join(lines[:i]).strip() if i > 0 else ""
            script = "\n".join(lines[i:])
            return note or content[:200], script

    # Fallback: treat entire content as script
    return content[:200], content.strip()


def _fix_url(script: str, target_url: str) -> str:
    """Ensure the script uses the exact target URL, not LLM-rewritten variants."""
    import re
    pattern = re.compile(r'(driver\.get\(|TARGET_URL\s*=\s*)["\']https?://(?:localhost|127\.0\.0\.1)[^"\']*["\']')
    return pattern.sub(rf'\1"{target_url}"', script)


def refine_node(state: AgentState) -> AgentState:
    """Node 5: LLM rewrites the script based on failure feedback."""
    # Build full history with complete script and console output per attempt
    full_history_parts = []
    for h in state["history"]:
        attempt_num = h["attempt"]
        script_code = h.get("script", "N/A")
        result = h.get("result", {})
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        error_type = result.get("error_type", "N/A")
        note = h.get("refinement_note", "N/A")

        part = (
            f"=== ATTEMPT {attempt_num} ===\n"
            f"Error type: {error_type}\n"
            f"Refinement note: {note}\n\n"
            f"--- Script ---\n{script_code}\n\n"
            f"--- stdout ---\n{stdout}\n\n"
            f"--- stderr ---\n{stderr}\n"
        )
        full_history_parts.append(part)

    full_history = "\n".join(full_history_parts) if full_history_parts else "No previous attempts."

    project_root = Path(__file__).resolve().parent.parent.parent
    template = (project_root / "prompts" / "refine.txt").read_text()
    prompt   = template.format(
        bug_report=state["bug_report"],
        previous_script=state["script"],
        failure_json=json.dumps(state["execution_result"], indent=2),
        full_history=full_history,
        dom_context=state.get("dom_context", "Not available"),
        target_url=state["target_url"],
    )
    llm      = _get_llm()
    response = llm.invoke(prompt)
    content  = _extract_text(response.content)

    refinement_note, corrected_script = _extract_script(content)
    corrected_script = _fix_url(corrected_script, state["target_url"])

    try:
        ast.parse(corrected_script)
    except SyntaxError:
        log.warning("refine_syntax_error", job_id=state["job_id"])

    updated_history = list(state["history"])
    if updated_history:
        updated_history[-1] = {**updated_history[-1], "refinement_note": refinement_note}

    log.info("refine_complete", job_id=state["job_id"], attempt=state["attempt_count"])
    return {**state, "script": corrected_script, "history": updated_history}

