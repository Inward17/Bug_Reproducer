"""Re-run the verifiable findings from 02-bug-analysis.md against the current code.

Usage (from the autorepro/ directory, with requirements-dev.txt installed):

    python ../docs/analysis/verify_bugs.py

Prints CONFIRMED when a bug is still present and "fixed" once it is gone, so it can be
used as a regression checklist. Needs no API keys and no Docker (mock LLM + demo mode).
"""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

DATA_DIR = tempfile.mkdtemp(prefix="autorepro_verify_")
os.environ.update(LLM_PROVIDER="mock", DEMO_MODE="true", DATA_DIR=DATA_DIR)
APP_ROOT = Path.cwd()
if not (APP_ROOT / "agent").is_dir():
    sys.exit("Run this from the autorepro/ directory.")
sys.path.insert(0, str(APP_ROOT))

import structlog  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))

results = []


def check(bug_id, title):
    def wrap(fn):
        try:
            present = bool(fn())
            status = "CONFIRMED" if present else "fixed"
        except Exception as e:  # a crash in the probe itself
            status = f"probe error: {type(e).__name__}: {e}"
        results.append((bug_id, status, title))
        return fn
    return wrap


def _eval(stdout, stderr="", exit_code=0, error_type=None):
    from agent.nodes.evaluate import evaluate_node
    state = {"job_id": "v", "attempt_count": 1, "execution_result": {
        "stdout": stdout, "stderr": stderr, "exit_code": exit_code, "error_type": error_type}}
    return evaluate_node(state)


def _resp(content):
    return type("R", (), {"content": content})()


@check("B01", "crashed script with 'reproduced' in a step log counts as success")
def _():
    return _eval("Step 4: Checking whether the bug is reproduced\n",
                 "Traceback\nNoSuchElementException", 1, "ElementNotFound")["success"]


@check("B02", "NOT_REPRODUCED counts as success")
def _():
    return _eval("NOT_REPRODUCED\n")["success"]


@check("B03", "echoed page text decides the verdict")
def _():
    return _eval("Page text after action: Issue confirmed by support\n")["success"]


@check("B04", "'Bug not reproduced' ends the job without refinement")
def _():
    from agent.graph import route_after_evaluate
    st = _eval("Bug not reproduced - none of the expected conditions were found\n")
    st.update(attempt_count=1, max_attempts=5)
    return route_after_evaluate(st) == "end_failure"


@check("B06", "analyze fails on ```json fenced output")
def _():
    from agent.nodes import analyze
    body = json.dumps({k: [] for k in ["inferred_steps", "target_elements", "risk_factors"]}
                      | {"expected_behavior": "", "success_condition": ""})
    llm = MagicMock()
    llm.invoke.return_value = _resp(f"```json\n{body}\n```")
    with patch.object(analyze, "_get_llm", return_value=llm):
        try:
            analyze.analyze_node({"job_id": "v", "bug_report": "b", "target_url": "u"})
            return False
        except RuntimeError:
            return True


@check("B09", "MAX_ATTEMPTS=8 hits LangGraph's recursion limit")
def _():
    # Same topology and router as agent/graph.py, with stub nodes that never succeed.
    from langgraph.graph import END, StateGraph
    from agent import orchestrator
    from agent.graph import route_after_evaluate
    from agent.state import AgentState
    sg = StateGraph(AgentState)
    for name in ["analyze", "inspect", "generate", "refine"]:
        sg.add_node(name, lambda s: s)
    sg.add_node("execute", lambda s: {**s, "attempt_count": s["attempt_count"] + 1,
                                      "execution_result": {"error_type": "Unknown"}})
    sg.add_node("evaluate", lambda s: {**s, "success": False})
    sg.set_entry_point("analyze")
    for a, b in [("analyze", "inspect"), ("inspect", "generate"), ("generate", "execute"),
                 ("execute", "evaluate"), ("refine", "execute")]:
        sg.add_edge(a, b)
    sg.add_conditional_edges("evaluate", route_after_evaluate,
                             {"end_success": END, "refine": "refine", "end_failure": END})
    with patch.object(orchestrator, "compiled", sg.compile()), \
         patch.object(orchestrator.config, "MAX_ATTEMPTS", 8):
        result = orchestrator.run_agent("a long enough bug report", "http://x")
    return "Recursion limit" in result.get("error", "")


@check("B11", "_safe_val doubles braces in the generate prompt")
def _():
    from agent.nodes import generate
    llm = MagicMock()
    llm.invoke.return_value = _resp("print('REPRODUCED')")
    with patch.object(generate, "_get_llm", return_value=llm):
        generate.generate_node({"job_id": "v", "history": [], "analysis": {"a": 1},
                                "target_url": "http://h/", "dom_context": ""})
    return "{{" in llm.invoke.call_args[0][0].split("Analysis (includes")[1]


@check("B12", "fix_url rewrites a second localhost navigation to the target URL")
def _():
    from agent.common import fix_url
    out = fix_url('driver.get("http://localhost:8080/login")\n'
                  'driver.get("http://localhost:8080/dashboard")', "http://t:8080/login")
    return "/dashboard" not in out


@check("B13", "refine treats prose starting with 'from ' as code")
def _():
    from agent.common import parse_script
    # A reply that is prose plus one import line is not a script. The old heuristic
    # sliced it at the first "from "/"import " line and shipped the prose as code.
    _, script = parse_script("Selector was wrong.\nfrom the logs the id is #go.\nimport time\n")
    return script is not None


@check("B14", "'512 items' in stdout classified as NetworkError / refused connection as Unknown")
def _():
    from sandbox.feedback_parser import parse
    return (parse("Found 512 items\n", "Traceback\nValueError: x", 1)["error_type"] == "NetworkError"
            or parse("", "net::ERR_CONNECTION_REFUSED", 1)["error_type"] == "Unknown")


@check("S03", "AST scanner lets importlib / urllib / ctypes through")
def _():
    from sandbox.security import SecurityError, check as sec
    passed = 0
    for code in ["import importlib", "import urllib.request", "import ctypes",
                 "f = getattr(__builtins__, 'ev' + 'al')"]:
        try:
            sec(code)
            passed += 1
        except SecurityError:
            pass
    return passed > 0


def _api_client():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def _fake_page():
    resp = MagicMock(text="<html><title>t</title><input id='username'></html>")
    resp.raise_for_status = lambda: None
    return resp


@check("B05", "unreachable target fails the job with zero attempts")
def _():
    from storage import jobs
    c = _api_client()
    with patch("sandbox.runner.time.sleep"):
        jid = c.post("/reproduce", json={"bug_report": "Login always shows invalid credentials",
                                         "target_url": "http://127.0.0.1:9/login"}).json()["job_id"]
    job = jobs.get(jid)
    return job["status"] == "failed" and not job.get("history")


@check("B07", "finished API jobs lose created_at")
def _():
    c = _api_client()
    with patch("agent.nodes.inspect.requests.get", return_value=_fake_page()), \
         patch("sandbox.runner.time.sleep"):
        jid = c.post("/reproduce", json={"bug_report": "Login always shows invalid credentials",
                                         "target_url": "http://example.com/login"}).json()["job_id"]
    return c.get(f"/result/{jid}").json().get("created_at") is None


@check("B08", "/result hides the error of a failed job")
def _():
    c = _api_client()
    jid = c.post("/reproduce", json={"bug_report": "Login always shows invalid credentials",
                                     "target_url": "http://127.0.0.1:9/login"}).json()["job_id"]
    res = c.get(f"/result/{jid}").json()
    return res["status"] == "failed" and not res.get("error")


@check("B21", "path traversal: /result/%2E%2E/screenshot/<file> serves files from data/")
def _():
    Path(DATA_DIR, "probe.txt").write_text("secret")
    r = _api_client().get("/result/%2E%2E/screenshot/probe.txt")
    return r.status_code == 200 and r.text == "secret"


@check("B23", "422 validation detail is a list (UI renders [object Object])")
def _():
    r = _api_client().post("/reproduce", json={"bug_report": "short", "target_url": "http://x"})
    return isinstance(r.json().get("detail"), list)


if __name__ == "__main__":
    width = max(len(t) for _, _, t in results)
    for bug_id, status, title in results:
        print(f"{bug_id:<4} {title:<{width}}  {status}")
    confirmed = sum(1 for _, s, _ in results if s == "CONFIRMED")
    print(f"\n{confirmed}/{len(results)} findings still present.")
