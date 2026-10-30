# 02 — Bug Analysis

Every finding below has a file and line reference. **✅ Verified** means it was reproduced by running the
real code (see [`verify_bugs.py`](verify_bugs.py), which re-runs most of them in about 3 s with the mock
LLM). **📖 Code-read** means it was found by reading the code, because it needs Docker or a real
deployment that wasn't available.

Severity: **Critical** = wrong results or remote compromise · **High** = core feature broken in common
cases · **Medium** = wrong behaviour in realistic edge cases · **Low** = hygiene, latent issues.

## Summary

| ID | Severity | Area | Title | Status |
|---|---|---|---|---|
| B01 | Critical | Verdict | Crashed scripts reported as "Bug Reproduced" | ✅ |
| B02 | High | Verdict | `NOT_REPRODUCED` counts as success | ✅ |
| B03 | High | Verdict | Echoed page text pollutes the verdict channel | ✅ |
| B04 | High | Agent loop | The refine loop never runs for wrong-verification failures | ✅ |
| B05 | High | Inspect | Any DOM-fetch error aborts the whole job (0 attempts) | ✅ |
| B06 | High | Analyze | Fenced JSON (```json) makes analyze fail the job | ✅ |
| B07 | High | Storage | `created_at` is erased when every API job finishes | ✅ |
| B08 | High | API/UI | Failed jobs: error never returned; UI shows "Processing" forever | ✅ |
| B09 | Medium | Agent loop | `MAX_ATTEMPTS ≥ 8` crashes with `GraphRecursionError` | ✅ |
| B10 | Medium | Orchestrator | Exceptions discard all attempt history | ✅ |
| B11 | Medium | Generate | `_safe_val` doubles every `{`/`}` the LLM sees | ✅ |
| B12 | Medium | Generate/Refine | `_fix_url` rewrites *every* localhost navigation | ✅ |
| B13 | Medium | Refine | Invalid scripts are executed anyway; prose lines become code | ✅ |
| B14 | Medium | Classification | Network errors misclassified; any 5xx-looking number in stdout counts as "NetworkError" | ✅ |
| B15 | Medium | Evidence | Screenshots from all attempts are mixed and mis-ordered | 📖 |
| B16 | Medium | API/UI | No live progress (attempt counter is dead code) | ✅ |
| B17 | Medium | Demo mode | `DEMO_MODE` always "succeeds"; `_local_run` is dead | 📖 |
| B18 | Medium | Demo | Demo page always contains the bug text, so the demo can't fail | 📖 |
| B19 | Low | Portability | `read_text()` without encoding (Windows CP-1252) | 📖 |
| B20 | Low | Sandbox | Every Docker error reported as a timeout | 📖 |
| B21 | Medium | API | Path traversal: read endpoints create dirs, `chmod 777`, serve files from `data/` | ✅ |
| B22 | Low | API | `/jobs` dumps every full record, unsorted, unpaginated | ✅ |
| B23 | Low | UI | `[object Object]` errors, overlapping polls, `innerHTML` with filenames | ✅ |
| B24 | Low | API | `/health` doesn't check Docker (README says it does) | 📖 |
| S01 | Critical* | Security | No auth + `CORS *` on a public EC2 host | 📖 |
| S02 | Critical* | Security | SSRF via inspect, with a read-back path through `dom.html` | 📖 |
| S03 | High | Security | AST deny-list is bypassable; sandbox has full egress | ✅ |
| S04 | High | Security | Docker socket mounted into a root API container | 📖 |
| S05 | Medium | Security | Prompt injection from target page content | 📖 |
| S06 | Low | Security | Real EC2 hostname hard-coded in README/setup.sh | 📖 |
| D01 | High | Deploy | Prod compose: sandbox bind-mounts and `host.docker.internal` broken in the container | 📖 |
| D02 | High | Deploy | `.env.production.template` is gitignored, so `setup.sh` fails | 📖 |
| D03 | Medium | Deploy | `setup.sh` heredoc: `set -e` lost, `read` eats script lines | 📖 |
| D04 | Medium | Deploy | `autorepro/docker-compose.yml` builds a context with no Dockerfile | 📖 |
| D05 | Low | Repo | Broken FlameGraph gitlink (no `.gitmodules`) | 📖 |
| D06 | Low | Repo | `.gitignore` contradicts committed files | 📖 |
| T01 | Medium | Tests | Most "bug fix" tests grep source strings; no CI | 📖 |

\* Critical *for the documented public EC2 deployment*. Lower when run on localhost only.

---

## Verdict and evaluation

### B01 — Crashed scripts are reported as "Bug Reproduced" (Critical, ✅)
**Where:** `agent/nodes/evaluate.py:14-25, 49-52`

`success = has_positive and not has_negative`. Neither the exit code nor `error_type` is checked, and
`_REPRODUCED_PATTERNS` matches the bare word `reproduced` anywhere in stdout. The generate prompt tells
the LLM to *"Print 'Step N: <action>'"* (`prompts/generate.txt:85`), so lines like
`Step 5: Checking whether the bug is reproduced` are common.

```
stdout = "Step 4: Checking whether the bug is reproduced\n"
stderr = "Traceback ... NoSuchElementException"   exit_code = 1
→ success = True   # UI: "✅ Bug Reproduced"
```
**Fix:** use a machine-readable verdict. Require an exact sentinel line (for example
`^AUTOREPRO_VERDICT=REPRODUCED$`), or better, a JSON line `AUTOREPRO_RESULT {"reproduced": true, "evidence": "..."}`,
**and** `exit_code == 0`. Never match free text.

### B02 — `NOT_REPRODUCED` counts as success (High, ✅)
`not\s+reproduced` doesn't match `NOT_REPRODUCED` / `NOT-REPRODUCED`, but `reproduced` does, so
`success = True`. "Unable to reproduce" isn't covered by the negative list either. Same fix as B01.

### B03 — Echoed page text pollutes the verdict channel (High, ✅)
**Where:** `prompts/generate.txt:28,106-107` and `evaluate.py:49-50`

The prompt makes every script `print(f"Page text after action: {visible_text[:500]}")` to the same
stdout the verdict regex scans. If the page says *"Your issue confirmed"* or *"Bug confirmed"*, the job
succeeds. If it says *"No bug found"* or *"not reproduced"* (a bug tracker, a QA dashboard), the attempt
is flagged `FalsePositive` and the job **ends**. **Fix:** a structured verdict line (B01), with page text
logged to a separate artifact or prefixed and excluded from matching.

### B04 — The refine loop never runs for wrong-verification failures (High, ✅)
**Where:** `agent/graph.py:19-22`, `agent/nodes/evaluate.py:63-68`, `prompts/generate.txt:47`, `prompts/refine.txt:26-32`

The template script prints `"Bug not reproduced - none of the expected conditions were found"` when
verification misses. With exit code 0, evaluate classifies that as `FalsePositive`, and the router
returns `end_failure` right away. Diagnosis #1 in `refine.txt` (*"If stdout contains 'Bug not reproduced'
→ your verification logic is wrong… try different conditions"*) is unreachable. The most common
first-attempt failure, a wrong condition, gets **no** refinement, so `MAX_ATTEMPTS=5` only applies to
crashes.

**Fix:** treat "not reproduced" as `WrongVerification` and refine it. Only conclude "bug not present"
once N attempts with *different* strategies agree, or when the LLM explicitly concludes so in refine.

---

## Agent pipeline

### B05 — Any DOM-fetch error aborts the job (High, ✅)
**Where:** `agent/nodes/inspect.py:152-174`

`resp.raise_for_status()` plus a bare `raise` in the `except`. The fallback message on line 173 is dead
code. Consequences:
- A bug report about a page that **returns 500/404/403** can *never* be reproduced. The very symptom
  kills the job.
- Pages behind login, bot protection, or reachable only from the sandbox network: the job fails with
  `attempt_count = 0`.

Verified: target `http://127.0.0.1:9/login` gives `status=failed, attempt_count=0, history=[]`.
**Fix:** log, keep the fallback `dom_context`, and continue. Fetch with Selenium inside the sandbox, so
the network view matches the execution environment.

### B06 — Fenced JSON fails analyze, and with it the whole job (High, ✅)
**Where:** `agent/nodes/analyze.py:45-61`

`json.loads(content)` runs on the raw reply. Gemini, Claude and GPT routinely wrap JSON in ```` ```json ````,
even when told not to. Both tries fail, `RuntimeError` is raised, and the job fails. **Fix:** strip
fences and extract the first `{…}` block. Better: use provider-native structured output
(`llm.with_structured_output(AnalysisModel)`) with a Pydantic schema.

### B07 — `created_at` is erased when every API job finishes (High, ✅)
**Where:** `agent/orchestrator.py:36-64` + `api/routes.py:21-27`

The route writes `created_at`. Then the orchestrator (with `caller_provided_job=True`) never saves
initial state, builds `result` from `final_state`, which has no `created_at`, and **replaces** the file.
Verified: every finished API job has `created_at: null`. History sorting in the UI breaks, and the result
card shows "📅 —". **Fix:** merge into the existing record: `job_store.save(id, {**job_store.get(id), **result})`.

### B08 — Failed jobs: error hidden, UI shows "Processing" forever (High, ✅)
**Where:** `api/routes.py:59-71`, `static/app.js:298-303`

The orchestrator stores `error`, but `/result` never returns it. In history, any status other than
`done` (including `failed`) is labelled **Processing**. Users never learn *why* a job failed.

### B09 — `MAX_ATTEMPTS ≥ 8` crashes (Medium, ✅)
LangGraph's default `recursion_limit` is 25. Steps = 5 + 3·(attempts−1), so 8 attempts needs 26. Verified:
`MAX_ATTEMPTS=8` gives `failed: Recursion limit of 25 reached`. **Fix:**
`compiled.invoke(state, {"recursion_limit": 5 + 3 * MAX_ATTEMPTS + 5})`.

### B10 — Exceptions discard all progress (Medium, ✅)
`orchestrator.py:55-62` builds the failure record from `initial_state`, so scripts, stdout and
screenshots metadata from completed attempts are lost (`history=[]`). Combined with B05, B06 and B09,
many real failures leave nothing to debug. **Fix:** stream the graph (`compiled.stream`), keep the last
state, and persist it after each node.

### B11 — `_safe_val` doubles every brace the LLM sees (Medium, ✅)
**Where:** `agent/nodes/generate.py:63-81`

`str.format` does **not** re-parse substituted values, so escaping them is wrong. The analysis JSON
reaches the LLM as `{{ "inferred_steps": … }}`, and DOM handlers like `onclick="f({x:1})"` become
`f({{x:1}})`. That's noisy and misleading, and it nudges models toward emitting `{{…}}` in f-strings.
(`refine.py` correctly does *not* escape, which shows the inconsistency.) **Fix:** remove `_safe_val`,
or switch to `string.Template` / Jinja.

### B12 — `_fix_url` rewrites every localhost navigation (Medium, ✅)
**Where:** `generate.py:56-60`, `refine.py:73-77` (duplicated)

Every `driver.get("http://localhost…")` is replaced with the target URL, so a flow
`login → driver.get(".../dashboard")` becomes two loads of `/login`. The replacement also interpolates
`target_url` into a regex replacement string unescaped (`\1`, `\g` in URLs). **Fix:** rewrite only the
host part (localhost to the target's host), or only the first navigation. Use a function replacement.

### B13 — Refine executes invalid scripts; prose becomes code (Medium, ✅)
**Where:** `agent/nodes/refine.py:59-70, 122-125`

A `SyntaxError` is only logged, then the script runs. `security.check` turns it into
`SecurityViolation` and an attempt is burned. Strategy 2 of `_extract_script` starts the script at the
first line beginning with `from ` / `import `, which matches prose such as *"from the logs I see…"*
(verified). **Fix:** use a fenced-block or structured output, then validate with `ast.parse` and retry
once, as `generate_node` does.

### B14 — Failure classification is wrong in common cases (Medium, ✅)
**Where:** `sandbox/feedback_parser.py:11-28`, `agent/nodes/evaluate.py:54-62` (duplicated logic)

| Input | Got | Expected |
|---|---|---|
| stdout `Found 512 items` + traceback | `NetworkError` | `Unknown` / real exception |
| stderr `ConnectionRefusedError` | `Unknown` | `NetworkError` |
| stderr `net::ERR_CONNECTION_REFUSED` | `Unknown` | `NetworkError` |
| chained tracebacks | first exception's message | last (root) exception |

The checks look at stdout for network errors, which Selenium reports on stderr. `\b5\d{2}\b` matches any
number from 500 to 599. **Fix:** parse the final exception class from the traceback, and match
`ERR_CONNECTION_REFUSED|ERR_NAME_NOT_RESOLVED|ConnectionRefusedError` on stderr. Detect HTTP status
from structured output, not free text.

### B15 — Screenshot evidence mixes attempts (Medium, 📖)
**Where:** `sandbox/runner.py:54,67,99`, `api/routes.py:44-47`, `static/app.js:219`

All attempts share `/screenshots` (the job dir). `step_1_page_loaded.png` from attempt 3 silently
overwrites attempt 1's, while `failure_<ts>.png` files from earlier attempts accumulate. The "Proof of
Execution" timeline therefore mixes attempts. Lexicographic sorting also puts `step_10` before `step_2`.
`dom.html`, `attempt_N.py` and `final.py` sit in the same folder. **Fix:** mount
`artifacts/<job>/attempt_<n>/`, store a per-attempt manifest, and sort naturally.

### B16 — No live progress (Medium, ✅)
`/result` returns only `{job_id, status}` while processing (`routes.py:41-42`), and the orchestrator
doesn't persist intermediate state anyway. `updateStatus()` in `app.js:156-162` (the "Attempt N"
counter) can never fire. A 5-attempt job is a blind 2–5 minute spinner.

### B17 — `DEMO_MODE` always "succeeds" (Medium, 📖)
`runner.run` sends demo mode to `_demo_run`, which reports success whenever the script text contains
`print("REPRODUCED")`, and the prompts require that in every script. The docstring at `runner.py:49`
promises a visible local browser. That's `_local_run` (`runner.py:106-170`), which is never called.

### B18 — The demo can't fail (Medium, 📖)
`tests/demo_server.py:128`: the always-visible "bug explainer" panel contains `"Invalid credentials"`.
Any script that checks `"Invalid credentials" in body.text` (exactly what the prompts recommend)
succeeds even **before** submitting the form. The flagship demo doesn't show that reproduction works.
**Fix:** move the explainer to a different page, or reword it.

---

## API, storage, UI

### B19 — Unspecified encodings (Low, 📖)
`storage/jobs.py:29,42`, `sandbox/runner.py:46` and the prompt loads use `read_text()` without
`encoding=`. On Windows (CP-1252) this is the read-side twin of the write crash fixed in `9b06286`.

### B20 — Every Docker error reported as a timeout (Low, 📖)
`runner.py:78-82` catches *all* exceptions from `container.wait()` (connection resets, API errors) and
re-raises `SandboxTimeoutError`. `container.kill()` on an already exited container raises too, which
masks the original error.

### B21 — Path traversal and directory creation on read endpoints (Medium, ✅)
`artifacts_dir()` does `mkdir` + `chmod 0o777` and is called by `GET /result/{id}` and
`GET /result/{id}/screenshot/{f}`, with no check that the job exists or that the ID is a UUID. Verified:
`GET /result/does-not-exist/screenshot/a.png` creates `data/artifacts/does-not-exist/`. With
`%2E%2E` as the ID it resolves to `data/`: verified, `GET /result/%2E%2E/screenshot/secret.txt` returned
the contents of `data/secret.txt` and left `data/` at mode `777`. **Fix:** validate `job_id` as a UUID,
check the job exists, whitelist `^[\w.-]+\.png$` filenames, and never `mkdir` on reads. The screenshot
endpoint also serves *any* file in the dir (`dom.html`, `*.py`) as `image/png`.

### B22 — `/jobs` returns everything (Low, ✅)
Full records (scripts, all stdout, DOM context, analysis) for every job: unsorted (filesystem order),
unpaginated, read from disk on every call. One unreadable file causes a 500. The UI calls it after every
job.

### B23 — Frontend defects (Low, ✅)
- A 422 validation error shows `Error: [object Object]`, because FastAPI's `detail` is an array (`app.js:82-83`).
- `setInterval` with an async callback lets polls overlap on slow responses. Polling never stops for
  stuck jobs.
- `innerHTML` with screenshot URLs and filenames (`app.js:226-230`). Filenames are chosen by
  LLM-generated code, which can be influenced by the target page (S05), so a name containing
  `" onerror="…` becomes an XSS vector in the dashboard.
- An `alert()` for errors, no deep links, and the result for a failed job shows no reason.

### B24 — `/health` is static (Low, 📖)
The README says it "verifies Docker daemon connectivity". `api/main.py:52-55` returns `{"status":"ok"}`
unconditionally, so the compose health check can't detect a broken Docker socket.

---

## Security

### S01 — No authentication, `CORS *`, public host (Critical for the EC2 deployment)
`api/main.py:33-38`. Anyone who finds `:8000` can run unlimited jobs (LLM spend, Chromium containers,
which also makes denial of service trivial since there's no concurrency cap) and read every job via `/jobs`.

### S02 — SSRF with a read-back path (Critical for the EC2 deployment, 📖)
`inspect.py:152` fetches any user URL from the **API host** with `verify=False`. Pydantic `HttpUrl`
accepts `http://169.254.169.254/...` and internal IPs (verified). A plain-text response has no
interactive tags, so `_fetch_dom_via_sandbox` renders it and writes the full page to `dom.html`. That
file can then be downloaded via `GET /result/{id}/screenshot/dom.html` (B21). On an EC2 instance with
IMDSv1 and an instance role, this chain can leak temporary AWS credentials. The generated script can
reach the same targets from the sandbox.
**Fix:** a URL allow-list or deny private, link-local and loopback ranges after DNS resolution; enforce
IMDSv2 on the instance; never serve non-image artifacts from the screenshot route.

### S03 — The deny-list sandbox is bypassable, with full egress (High, ✅)
`sandbox/security.py`. All of these pass `check()` (verified):
`import importlib; importlib.import_module('o'+'s')`, `import ctypes`, `import urllib.request`,
`io.FileIO('/etc/passwd')`, `getattr(__builtins__, 'ev'+'al')`. Meanwhile the container runs with
`network_mode="bridge"` + `host-gateway` (`runner.py:70-72`), and no `cap_drop`, `read_only`,
`pids_limit` or `no-new-privileges`. Treat the AST check as lint, not as a security boundary.
**Fix:** harden the container (drop all capabilities, read-only rootfs, tmpfs, pids limit, seccomp,
gVisor/Firecracker if possible) and put egress behind a proxy that only allows the target host.

### S04 — Docker socket in a root container (High, 📖)
Both compose files mount `/var/run/docker.sock`, and the API image runs as root. Any RCE in the API
(dependency, deserialisation, future code) gives root on the host. **Fix:** a separate least-privilege
runner service (or a rootless/socket-proxy setup such as `tecnativa/docker-socket-proxy` limited to
container create, start, wait and remove), with the API as non-root.

### S05 — Prompt injection from page content (Medium, 📖)
DOM text, titles and attributes go into the generate and refine prompts unfenced. Combined with S03, a
hostile target page can steer the LLM into writing exfiltration code. Delimit untrusted content, tell
the model it is data, and rely on the sandbox rather than the prompt.

### S06 — Infrastructure details committed (Low)
`setup.sh:98` and `README.md:596,611` hard-code `ec2-3-239-28-71.compute-1.amazonaws.com`. That's wrong for
anyone else running the script, and it advertises a live target.

---

## Deployment and repo

### D01 — The production compose can't run sandboxes correctly (High, 📖)
`docker-compose.prod.yml` runs the API **inside** a container that talks to the host daemon.
- `runner._resolve_bind_source` needs `HOST_DATA_DIR`, but it isn't set, so the bind sources are
  `/app/data/artifacts/<job>/attempt_1.py`, which the host daemon doesn't have. Docker auto-creates a
  *directory* there, and `python /scripts/script.py` fails. Screenshots are never seen by the API.
- `inspect._host_url` rewrites `host.docker.internal` to `localhost`, which inside the API container is
  the container itself. The API service also has no `extra_hosts: host.docker.internal:host-gateway`.

**Fix:** add `HOST_DATA_DIR=${PWD}/data` (absolute) and `extra_hosts`, and make the rewrite conditional
(don't rewrite when running in a container).

### D02 — The production env template isn't in the repo (High, 📖)
`.gitignore` has `.env.*`, so `.env.production.template` was never committed. `setup.sh:58` copies it,
and the README calls it `env.production.template` (another name). Add a `!.env.production.template`
rule and commit it.

### D03 — `setup.sh` runs most of its body in a `newgrp docker <<heredoc` (Medium, 📖)
The new shell doesn't inherit `set -e`, and `read -r` (the "press ENTER" step) reads from the heredoc,
so it consumes the next script line instead of waiting for the user.

### D04 — The dev compose is broken (Medium, 📖)
`autorepro/docker-compose.yml` uses `build: .`, but `autorepro/` has no Dockerfile. It passes only
`ANTHROPIC_API_KEY`, while the default provider is Ollama.

### D05 — Broken submodule (Low)
`autorepro/tools/FlameGraph` is a gitlink (mode 160000) with no `.gitmodules`. `git submodule update`
fails and the directory is empty.

### D06 — `.gitignore` contradictions (Low)
`.vscode/`, `generated-diagrams/` and `*.md` are ignored, but `.vscode/settings.json` and the diagram
are committed. `updated_mcp_config.json` (personal IDE/MCP config with a Homebrew PATH) is committed.
`sandbox/Dockerfile:4` writes a `debian.sources.tmp` that nothing uses.

### T01 — Test quality (Medium, 📖)
`tests/test_bug_fixes.py` mostly asserts that strings exist in source files (`"wait_result = container.wait(" in source`,
`'result.get("error_type")' in source`). Those tests pass for broken code and fail for harmless
refactors. There are no tests for `evaluate_node` behaviour, the routes, the orchestrator, inspect, or
an end-to-end mock run, and no CI workflow. Every bug in this file except S01–S06 could be caught by a
cheap behavioural unit test.

---

## Suggested fix order

1. **B01–B04** (verdict contract and loop): this is the product's correctness. Roughly one day.
2. **B05–B10** (fail-soft pipeline, persistence, progress).
3. **S01–S04 + D01/D02** before anything is reachable from the internet.
4. The remaining Medium and Low items, adding a behavioural test with each fix.
