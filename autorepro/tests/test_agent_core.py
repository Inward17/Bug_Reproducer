"""Behavioural tests for the agent core: verdict, routing, classification, helpers.

These replace the old test_bug_fixes.py, which asserted that particular strings appeared
in the source files — those passed for broken code and failed on harmless refactors.

Run with: python -m pytest tests/test_agent_core.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import common
from agent.graph import route_after_evaluate, route_after_refine
from agent.nodes import analyze as analyze_mod
from agent.nodes import refine as refine_mod
from agent.nodes.evaluate import evaluate_node
from agent.state import FailureType
from sandbox.feedback_parser import classify, final_exception, parse

VERDICT_TRUE = 'AUTOREPRO_RESULT {"reproduced": true, "variant": "v1", "evidence": "Invalid"}'
VERDICT_FALSE = 'AUTOREPRO_RESULT {"reproduced": false, "variant": "", "evidence": "all ok"}'


def run_evaluate(stdout, stderr="", exit_code=0, error_type=None):
    state = {"job_id": "t", "attempt_count": 1, "max_attempts": 5, "bug_absent": False,
             "execution_result": {"stdout": stdout, "stderr": stderr,
                                  "exit_code": exit_code, "error_type": error_type}}
    return evaluate_node(state)


# ── The verdict contract ──────────────────────────────────────────────────────

@pytest.mark.parametrize("stdout, stderr, exit_code, error_type, expected", [
    # Only a structured verdict plus a clean exit is a success.
    (VERDICT_TRUE, "", 0, None, True),
    # A crash after the verdict is not a reproduction.
    (VERDICT_TRUE, "Traceback\nNoSuchElementException: x", 1, "ElementNotFound", False),
    (VERDICT_TRUE, "", 1, None, False),
    # The script checked and found nothing.
    (VERDICT_FALSE, "", 0, None, False),
    # Free text never decides a run.
    ("Step 4: Checking whether the bug is reproduced\n", "", 0, None, False),
    ("NOT_REPRODUCED\n", "", 0, None, False),
    ("PAGE_TEXT: Your issue confirmed by support\n", "", 0, None, False),
    ("REPRODUCED\n", "", 0, None, False),
    ("Bug reproduced successfully\n", "", 0, None, False),
    # A malformed verdict line is not a verdict.
    ('AUTOREPRO_RESULT {"reproduced": "yes"}', "", 0, None, False),
    ('AUTOREPRO_RESULT not json at all', "", 0, None, False),
])
def test_success_requires_structured_verdict_and_clean_exit(
        stdout, stderr, exit_code, error_type, expected):
    assert run_evaluate(stdout, stderr, exit_code, error_type)["success"] is expected


def test_a_handled_exception_on_stderr_does_not_veto_a_clean_verdict():
    """Scripts that retry a wait log the first TimeoutException and carry on."""
    stderr = ("Traceback (most recent call last):\n  ...\n"
              "selenium.common.exceptions.TimeoutException: Message: retrying\n")
    result = parse(VERDICT_TRUE + "\n", stderr, 0)
    state = run_evaluate(result["stdout"], result["stderr"], 0, result["error_type"])
    assert state["success"] is True
    assert state["execution_result"]["error_type"] is None


def test_success_clears_any_error_type():
    state = run_evaluate(VERDICT_TRUE, "", 0, "NetworkError")
    assert state["success"] is True
    assert state["execution_result"]["error_type"] is None


def test_last_verdict_wins():
    stdout = f"{VERDICT_FALSE}\nretrying\n{VERDICT_TRUE}\n"
    assert run_evaluate(stdout)["success"] is True


def test_no_verdict_is_wrong_verification():
    result = run_evaluate("Step 1: did a thing\n")["execution_result"]
    assert result["error_type"] == FailureType.WRONG_VERIFICATION.value


def test_reproduced_false_is_bug_not_observed():
    result = run_evaluate(VERDICT_FALSE)["execution_result"]
    assert result["error_type"] == FailureType.BUG_NOT_OBSERVED.value
    assert "all ok" in result["error_message"]


def test_evaluate_keeps_an_error_type_the_runner_already_set():
    result = run_evaluate("", "boom", 1, "Timeout")["execution_result"]
    assert result["error_type"] == "Timeout"


# ── Routing ───────────────────────────────────────────────────────────────────

def test_success_ends_the_run():
    state = run_evaluate(VERDICT_TRUE)
    assert route_after_evaluate(state) == "end_success"


@pytest.mark.parametrize("stdout", [VERDICT_FALSE, "Bug not reproduced - nothing matched\n"])
def test_a_run_that_saw_no_bug_is_refined(stdout):
    """The most common first failure must reach refine, not end the job."""
    state = run_evaluate(stdout)
    assert route_after_evaluate(state) == "refine"


def test_attempts_are_capped():
    state = {**run_evaluate(VERDICT_FALSE), "attempt_count": 5, "max_attempts": 5}
    assert route_after_evaluate(state) == "end_failure"


@pytest.mark.parametrize("error_type", ["ContainerError", "InternalError"])
def test_infrastructure_failures_are_not_refined(error_type):
    """A broken sandbox fails every rewrite the same way; don't spend LLM calls on it."""
    state = run_evaluate("", "boom", -1, error_type)
    assert route_after_evaluate(state) == "end_failure"


def test_refine_can_end_the_run_once_it_concludes_the_bug_is_absent():
    state = {**run_evaluate(VERDICT_FALSE), "bug_absent": True}
    assert route_after_evaluate(state) == "end_failure"
    assert route_after_refine(state) == "end_absent"
    assert route_after_refine({**state, "bug_absent": False}) == "execute"


# ── Failure classification ────────────────────────────────────────────────────

@pytest.mark.parametrize("stdout, stderr, exit_code, expected", [
    ("", "Traceback\nselenium.common.exceptions.NoSuchElementException: x", 1, "ElementNotFound"),
    ("", "Traceback\nselenium.common.exceptions.TimeoutException: Message:", 1, "Timeout"),
    ("", "Traceback\nAssertionError: nope", 1, "AssertionError"),
    ("", "net::ERR_CONNECTION_REFUSED", 1, "NetworkError"),
    ("", "ConnectionRefusedError: [Errno 111]", 1, "NetworkError"),
    ("", "net::ERR_NAME_NOT_RESOLVED", 1, "NetworkError"),
    # A number that merely looks like a 5xx status is not a network error.
    ("Found 512 items\n", "Traceback\nValueError: x", 1, "Unknown"),
    ("Order total 599\n", "", 0, None),
    # A clean exit is classified only by network markers, never by a logged traceback.
    ("", "Traceback\nselenium.common.exceptions.TimeoutException: x", 0, None),
    ("PAGE_TEXT: This site can't be reached ERR_CONNECTION_REFUSED", "", 0, "NetworkError"),
    ("", "", 0, None),
    ("", "", 1, "Unknown"),
])
def test_classification_table(stdout, stderr, exit_code, expected):
    assert classify(stdout, stderr, exit_code) == expected


def test_chained_traceback_reports_the_final_exception():
    stderr = (
        "Traceback (most recent call last):\n"
        "  ...\n"
        "ValueError: the original cause\n"
        "\nDuring handling of the above exception, another exception occurred:\n\n"
        "Traceback (most recent call last):\n"
        "  ...\n"
        "RuntimeError: what actually killed it\n"
    )
    assert final_exception(stderr) == ("RuntimeError", "what actually killed it")
    assert parse("", stderr, 1)["error_message"] == "what actually killed it"


def test_chrome_error_page_is_a_network_error_even_when_a_wait_timed_out():
    """Chrome doesn't raise on a refused connection; the later wait does."""
    stdout = ("PAGE_TEXT: This site can't be reached\nhost.docker.internal refused to "
              "connect.\nERR_CONNECTION_REFUSED\n")
    stderr = "Traceback\nselenium.common.exceptions.TimeoutException: Message: \n"
    assert classify(stdout, stderr, 1) == "NetworkError"


@pytest.mark.parametrize("stdout, stderr, expected", [
    ("PAGE_TEXT: This site can't be reached\nThe webpage might be down.\nERR_UNSAFE_PORT\n",
     "Traceback\nTimeoutException: x", "NetworkError"),
    ("", "WebDriverException: Message: unknown error: net::ERR_SSL_PROTOCOL_ERROR", "NetworkError"),
    # An ERR_ token inside ordinary page text is not a browser error page.
    ("PAGE_TEXT: Status code ERR_INVALID_COUPON shown\n", "Traceback\nTimeoutException: x", "Timeout"),
])
def test_any_chrome_network_error_code_is_recognised(stdout, stderr, expected):
    assert classify(stdout, stderr, 1) == expected


def test_selenium_message_prefix_is_stripped():
    stderr = ("Traceback\nselenium.common.exceptions.TimeoutException: Message: \n"
              "Stacktrace:\n#0 0x55d4 <unknown>\n#1 0x55d5 <unknown>\n")
    assert final_exception(stderr) == ("TimeoutException", None)
    out = parse("", stderr, 1)
    assert out["error_message"] == "TimeoutException"
    assert "<unknown>" not in out["stack_trace"]


def test_parse_collects_screenshot_paths_from_stdout():
    out = parse("saved /screenshots/step_1_loaded.png\n", "", 0)
    assert out["screenshot_paths"] == ["/screenshots/step_1_loaded.png"]


# ── Shared helpers ────────────────────────────────────────────────────────────

def test_parse_verdict_ignores_prose_and_reads_the_last_line():
    assert common.parse_verdict("reproduced!\n") is None
    assert common.parse_verdict(f"noise\n{VERDICT_TRUE}\n")["variant"] == "v1"


def test_fix_url_keeps_each_path():
    script = ('driver.get("http://localhost:8080/login")\n'
              'driver.get("http://localhost:8080/dashboard")\n')
    out = common.fix_url(script, "http://host.docker.internal:8080/login")
    assert 'driver.get("http://host.docker.internal:8080/login")' in out
    assert 'driver.get("http://host.docker.internal:8080/dashboard")' in out


def test_fix_url_leaves_other_hosts_alone():
    script = 'driver.get("https://example.com/a")'
    assert common.fix_url(script, "http://target:9/b") == script


def test_fix_url_inserts_the_target_host_literally():
    """Regex-looking characters in the target must not be expanded as backreferences."""
    script = 'driver.get("http://localhost:1/x")'
    out = common.fix_url(script, "http://ho\\1st:9/ignored")
    assert 'driver.get("http://ho\\1st:9/x")' == out


@pytest.mark.parametrize("reply", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    'Here is the analysis:\n```\n{"a": 1}\n```\nHope that helps.',
    'Sure! {"a": 1}',
])
def test_extract_json_object_survives_fences_and_prose(reply):
    assert common.extract_json_object(reply) == {"a": 1}


def test_extract_json_object_handles_braces_inside_strings():
    assert common.extract_json_object('{"a": "}{"}') == {"a": "}{"}


def test_extract_json_object_raises_when_there_is_no_object():
    with pytest.raises(ValueError):
        common.extract_json_object("no json here")


def test_parse_script_rejects_prose_that_merely_starts_with_import():
    note, script = common.parse_script(
        "Selector was wrong.\nfrom the logs the id is #go.\nimport time\n")
    assert script is None
    assert "Selector was wrong." in note


def test_parse_script_takes_the_fenced_block_and_keeps_the_note():
    note, script = common.parse_script(
        "The wait was too short.\n\n```python\nimport time\nprint(1)\n```\n")
    assert script == "import time\nprint(1)"
    assert "wait was too short" in note


def test_extract_text_flattens_bedrock_content_blocks():
    assert common.extract_text([{"type": "text", "text": "a"}, {"text": "b"}]) == "a\nb"
    assert common.extract_text(" plain ") == "plain"


# ── Nodes ─────────────────────────────────────────────────────────────────────

def _reply(content):
    return MagicMock(content=content)


def test_analyze_accepts_fenced_json_and_backfills_variants():
    body = ('{"inferred_steps": [], "target_elements": [], "expected_behavior": "e",'
            ' "success_condition": "s", "risk_factors": []}')
    llm = MagicMock()
    llm.invoke.return_value = _reply(f"```json\n{body}\n```")
    with patch.object(analyze_mod, "_get_llm", return_value=llm):
        state = analyze_mod.analyze_node(
            {"job_id": "t", "bug_report": "a bug report", "target_url": "http://x"})
    assert state["analysis"]["success_condition"] == "s"
    assert len(state["analysis"]["bug_variants"]) == 1


def test_analyze_retries_once_then_fails_loudly():
    llm = MagicMock()
    llm.invoke.return_value = _reply("not json")
    with patch.object(analyze_mod, "_get_llm", return_value=llm):
        with pytest.raises(RuntimeError):
            analyze_mod.analyze_node(
                {"job_id": "t", "bug_report": "a bug report", "target_url": "http://x"})
    assert llm.invoke.call_count == 2


def _refine_state(**over):
    return {"job_id": "t", "bug_report": "b", "script": "print(1)", "target_url": "http://x/",
            "dom_context": "", "attempt_count": 2, "max_attempts": 5, "bug_absent": False,
            "execution_result": {"error_type": "BugNotObserved", "stdout": "", "stderr": ""},
            "history": [{"attempt": 1, "script": "print(1)", "result": {}}], **over}


def test_refine_keeps_the_previous_script_when_the_reply_is_not_code():
    llm = MagicMock()
    llm.invoke.return_value = _reply("I think the selector is wrong, try again.")
    with patch.object(refine_mod, "_get_llm", return_value=llm):
        state = refine_mod.refine_node(_refine_state())
    assert state["script"] == "print(1)"  # never ships prose as a script
    assert llm.invoke.call_count == 2     # asked once more for a fenced block


def test_refine_flags_bug_absent_only_after_two_attempts():
    reply = _reply(f"{refine_mod.BUG_ABSENT_SENTINEL}\nThe page works.\n"
                   "```python\nprint(1)\n```")
    llm = MagicMock()
    llm.invoke.return_value = reply
    with patch.object(refine_mod, "_get_llm", return_value=llm):
        early = refine_mod.refine_node(_refine_state(attempt_count=1))
        late = refine_mod.refine_node(_refine_state(attempt_count=2))
    assert early.get("bug_absent") is False
    assert late["bug_absent"] is True
    assert late["execution_result"]["error_type"] == FailureType.FALSE_POSITIVE.value


def test_mock_refine_keeps_the_target_url():
    """The mock must not quietly "fix" a run by navigating somewhere else."""
    from pathlib import Path as _Path

    from utils.mock_llm import MockLLM
    template = (_Path(__file__).resolve().parent.parent / "prompts" / "refine.txt").read_text(encoding="utf-8")
    prompt = template.format(bug_report="b", previous_script="", failure_json="{}",
                             full_history="", dom_context="", target_url="http://t:1/nope")
    _, script = common.parse_script(MockLLM().invoke(prompt).content)
    assert 'driver.get("http://t:1/nope")' in script
