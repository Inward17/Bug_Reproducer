# 04 — What the Project Lacks

This is a gap analysis against what a team would expect from a bug-reproduction tool they rely on.
Each gap is rated by **impact** (how much it limits real use) and **effort** to close.

## Priority matrix

| Gap | Impact | Effort | Priority |
|---|---|---|---|
| Trustworthy verdict (no false positives) | 🔴 High | Low | **P0** |
| Error visibility and live progress | 🔴 High | Low | **P0** |
| Behavioural tests + CI | 🔴 High | Low | **P0** |
| Authentication, multi-user, quotas | 🔴 High | Medium | **P0 before public use** |
| Real sandbox isolation and egress control | 🔴 High | Medium | **P0 before public use** |
| Durable job queue and storage | 🟠 Med-High | Medium | P1 |
| Logged-in / stateful targets | 🔴 High | Medium | P1 |
| Rich evidence (trace, video, console, network) | 🟠 Medium | Medium | P1 |
| Exportable regression tests | 🟠 Medium | Low | P1 |
| Issue-tracker integrations | 🟠 Medium | Medium | P2 |
| Evaluation benchmark for prompts and models | 🟠 Medium | Medium | P1 |
| Observability and cost tracking | 🟡 Medium | Low | P2 |
| Multi-browser / device matrix | 🟡 Low-Med | Low | P3 |

---

## 1. Correctness and trust

- **No machine-readable verdict.** Success is inferred from free-text stdout (see B01–B03), so users
  can't trust a green badge.
- **No confidence measure.** A single run is treated as proof. There's no re-run, no flakiness
  detection, and no "reproduced 4/5".
- **No negative control.** Nothing checks that the script *wouldn't* report the bug on a healthy page,
  and the demo itself can't fail (B18).
- **No evaluation dataset.** There's no way to measure whether a prompt change improves or regresses
  accuracy.

## 2. Product capabilities

- **Can't handle authenticated apps.** There's no credentials, cookie or session support, and most
  production bugs live behind login.
- **Single URL, single page context.** Inspect sees one static page. Multi-step flows (cart, then
  checkout, then payment) aren't grounded after the first navigation.
- **Bug reports can only be text.** There's no screenshots, screen recordings, HAR, console logs,
  environment (browser, OS, viewport) or reproduction steps template.
- **No outputs beyond a script.** There's no pytest or Playwright test export, no CI snippet, and no
  minimised steps for the bug ticket.
- **No integrations.** There's no GitHub, Jira, Linear or Slack. Users copy and paste in both
  directions.
- **No projects or environments.** There's no grouping, saved base URLs, or staging versus production.
- **No re-run, cancel, delete or compare** of jobs.

## 3. User experience

- No live stage or attempt progress, and the attempt counter is dead code (B16).
- Failed jobs show no reason and stay labelled "Processing" in history (B08).
- No per-attempt drill-down (script, stdout, stderr, refinement note, screenshots per attempt).
- No search, filters, deep links (`#/job/<id>`), keyboard shortcuts or theme toggle.
- Validation errors appear as `[object Object]` in an `alert()`.
- No onboarding help for the `host.docker.internal` networking subtlety, which is the most common setup
  pitfall.

> The `ui-uogrades` branch fixes most of these in the frontend and adds the minimal API fields it needs.

## 4. Engineering and quality

- **No CI**, linting (ruff), formatting, type checking (mypy/pyright) or pre-commit hooks.
- **Tests check strings, not behaviour.** There are no API, orchestrator or end-to-end tests.
- **Duplicated logic.** `_extract_text` appears 3 times, `_fix_url` twice, and failure classification
  twice (`feedback_parser` and `evaluate`).
- **Dead code.** `_local_run`, `update_status`, `JobResultResponse`, the `prior_failures` plumbing in
  generate (history is always empty there), and the inspect fallback message.
- **Config by module-level `os.getenv`.** There's no validation and nothing can be reloaded, and
  `storage/jobs.JOBS_DIR` is frozen at import time, which makes tests awkward.
- **No `pyproject.toml`, lockfile or version.** The dependencies are two major versions behind on
  LangChain and LangGraph.
- **The repo needs cleanup.** There's a broken FlameGraph gitlink, committed IDE and MCP configs, and
  `.gitignore` contradicts the committed files. Commit messages like "bug2" (×3) make history hard to
  use.

## 5. Operations and scalability

- **Work runs inside the API process** (Starlette `BackgroundTasks`). There's no queue, no concurrency
  cap, and nothing survives a restart, so jobs stay in `processing` forever.
- **File-based storage.** `/jobs` reads every JSON file on every call, with no indexing, retention or
  cleanup. Artifacts grow without limit.
- **No observability.** Logs only, with no metrics, tracing, LLM call tracing or cost per job.
- **The health check is fake** (B24), so orchestration can't detect a dead Docker daemon.
- **The production deployment doesn't work as committed** (D01–D04), and there's no HTTPS, reverse
  proxy or backups.

## 6. Security

- No authentication or authorisation, `CORS *`, and every job is visible to everyone (S01).
- SSRF from the API host, with a read-back path (S02). TLS verification is disabled in inspect.
- A deny-list "sandbox" that's easy to bypass, with unrestricted egress (S03).
- The Docker socket is mounted into a root container (S04).
- There's no prompt-injection boundary for page content (S05).
- There's no secret scanning, and real infrastructure hostnames are committed (S06).

## 7. Documentation

- The README describes features that don't match the code: the `/health` Docker check, "integration
  tests", `env.production.template`, and Windows-only `.\sandbox` paths shown for every OS.
- There's no architecture decision record, no threat model, no `CONTRIBUTING.md` and no API schema
  docs beyond the FastAPI defaults.
- There's no changelog or versioning.

---

## The 5 things to do first

1. **Fix the verdict contract and the refine routing** (B01–B04). Everything else depends on results
   being true.
2. **Persist progress, return errors, and stream stages to the UI** (B05–B10, B16).
3. **Add behavioural tests + GitHub Actions** so the fixes stay fixed.
4. **Lock it down before exposing it**: auth, SSRF guard, a hardened sandbox, no Docker socket in the API.
5. **Support logged-in targets and Playwright traces.** This is the step from demo to daily tool.
