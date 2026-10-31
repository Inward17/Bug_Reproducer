"""Helpers shared by the LLM-backed agent nodes.

These used to be copy-pasted into analyze.py, generate.py and refine.py, which is how
`_fix_url` and `_extract_text` drifted apart between the nodes.
"""

import ast
import json
import re
from urllib.parse import urlsplit, urlunsplit

# The contract every generated script follows: exactly one machine-readable verdict line.
VERDICT_PREFIX = "AUTOREPRO_RESULT"
PAGE_TEXT_PREFIX = "PAGE_TEXT:"

_VERDICT_LINE = re.compile(rf'^{VERDICT_PREFIX}\s+(\{{.*\}})\s*$', re.MULTILINE)
_FENCE = re.compile(r'```(?:[A-Za-z0-9_+-]*)\s*\n(.*?)```', re.DOTALL)
_LOCAL_NAV = re.compile(
    r'(driver\.get\(|TARGET_URL\s*=\s*)["\'](https?://(?:localhost|127\.0\.0\.1)(?::\d+)?[^"\']*)["\']'
)


def extract_text(content) -> str:
    """Flatten an LLM response's ``.content`` into plain text.

    ChatBedrockConverse returns a list of content blocks like
    ``[{"type": "text", "text": "..."}]``; other providers return a plain string.
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


def strip_fences(text: str) -> str:
    """Return the last fenced block in ``text``, or the text with stray fences removed."""
    blocks = _FENCE.findall(text)
    if blocks:
        return blocks[-1].strip()
    lines = text.strip().splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].lstrip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _balanced_object(text: str) -> str | None:
    """Return the first brace-balanced ``{...}`` span, ignoring braces inside strings."""
    depth = 0
    start = None
    in_string = False
    escaped = False
    for i, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return text[start:i + 1]
            if depth < 0:
                depth, start = 0, None
    return None


def extract_json_object(text: str) -> dict:
    """Parse the first JSON object out of an LLM reply.

    Models wrap JSON in ```json fences or add a sentence of prose even when told not to;
    treating that as malformed used to fail the whole job.
    """
    for candidate in (strip_fences(text), text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            span = _balanced_object(candidate)
            if span is None:
                continue
            try:
                parsed = json.loads(span)
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("no JSON object found in response")


def is_valid_python(script: str) -> bool:
    """True when ``script`` parses as Python."""
    try:
        ast.parse(script)
    except (SyntaxError, ValueError):
        return False
    return True


def parse_script(content: str) -> tuple[str, str | None]:
    """Split an LLM reply into ``(note, script)``; ``script`` is None when invalid.

    Only a fenced block or a whole-reply-is-code answer counts. The old heuristic
    started the script at the first line beginning with "from "/"import ", which
    turned prose like "from the logs I see..." into the first line of the script.
    """
    blocks = _FENCE.findall(content)
    if blocks:
        script = blocks[-1].strip()
        head = content.split("```", 1)[0].strip()
        note = head or content[:200].strip()
    else:
        script = content.strip()
        # An unfenced reply is either the whole script or entirely prose; if it doesn't
        # parse, treat it as the explanation so the note isn't lost.
        note = "" if is_valid_python(script) else content[:200].strip()
    return note, script if is_valid_python(script) else None


def fix_url(script: str, target_url: str) -> str:
    """Repoint localhost navigations at the target host, keeping each path.

    The sandbox cannot reach the host's localhost. Replacing the whole URL collapsed
    multi-page flows, because a later ``driver.get(".../dashboard")`` became the
    target page again.
    """
    target = urlsplit(target_url)
    if not target.netloc:
        return script

    def repl(match: re.Match) -> str:
        head, url = match.group(1), match.group(2)
        parts = urlsplit(url)
        fixed = urlunsplit((target.scheme or parts.scheme, target.netloc,
                            parts.path, parts.query, parts.fragment))
        return f'{head}"{fixed}"'

    return _LOCAL_NAV.sub(repl, script)


def parse_verdict(stdout: str) -> dict | None:
    """Return the last structured verdict a script printed, or None if it printed none.

    Scripts must emit one line: ``AUTOREPRO_RESULT {"reproduced": bool, ...}``.
    Free text is never a verdict — the previous regex matched the bare word
    "reproduced" anywhere in stdout, so step logs and echoed page text decided runs.
    """
    for raw in reversed(_VERDICT_LINE.findall(stdout or "")):
        try:
            verdict = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(verdict, dict) and isinstance(verdict.get("reproduced"), bool):
            return verdict
    return None
