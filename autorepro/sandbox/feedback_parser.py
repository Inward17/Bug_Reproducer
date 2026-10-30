"""Normalises raw Docker log output into a structured ExecutionResult dict.

This is the only place execution failures are classified — `evaluate_node` consumes
`error_type` from here instead of re-deriving it from the same strings.
"""

import re

# Selenium/Chrome report unreachable hosts on stderr, not stdout.
_NETWORK_MARKERS = (
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_ADDRESS_UNREACHABLE",
    "ConnectionRefusedError",
    "ConnectionResetError",
    "NewConnectionError",
    "MaxRetryError",
)

# "ValueError: x", "selenium.common.exceptions.TimeoutException: Message: ..."
_EXCEPTION_LINE = re.compile(
    r'^(?:[A-Za-z_][\w.]*\.)?([A-Za-z_]\w*(?:Error|Exception|Exit|Interrupt))\b(?::[ \t]*(.*))?$',
    re.MULTILINE,
)


def final_exception(stderr: str) -> tuple[str | None, str | None]:
    """Return ``(class_name, message)`` of the last exception in a traceback.

    Chained tracebacks ("During handling of the above exception...") list the cause
    first; the last one is the error that actually killed the script.
    """
    matches = _EXCEPTION_LINE.findall(stderr or "")
    if not matches:
        return None, None
    name, message = matches[-1]
    return name, (message.strip() or None)


def classify(stdout: str, stderr: str, exit_code: int) -> str | None:
    """Classify a failed run. Returns None when the run did not fail."""
    haystack = f"{stderr}\n{stdout}"
    if any(marker in haystack for marker in _NETWORK_MARKERS):
        return "NetworkError"

    # A clean exit with a traceback on stderr means the script caught and logged an
    # exception (a retried wait, say) and carried on. That traceback is not the outcome.
    if exit_code == 0:
        return None

    name, _ = final_exception(stderr)
    if name == "NoSuchElementException":
        return "ElementNotFound"
    if name in ("TimeoutException", "TimeoutError"):
        return "Timeout"
    if name == "AssertionError":
        return "AssertionError"
    if name:
        return "Unknown"
    if exit_code != 0:
        return "Unknown"
    return None


def parse(stdout: str, stderr: str, exit_code: int) -> dict:
    """Normalise raw Docker log output into an ExecutionResult dict."""
    error_type = classify(stdout, stderr, exit_code)
    name, error_message = final_exception(stderr)

    stack_trace = None
    if "Traceback" in (stderr or ""):
        stack_trace = "\n".join(stderr.strip().splitlines()[-10:])
    if error_message is None and name:
        error_message = name

    return {
        "stdout":           stdout,
        "stderr":           stderr,
        "exit_code":        exit_code,
        "error_type":       error_type,
        "error_message":    error_message,
        "stack_trace":      stack_trace,
        "screenshot_paths": re.findall(r'/screenshots/[\w_.-]+\.png', stdout or ""),
        "duration_seconds": None,
    }
