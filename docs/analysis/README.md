# AutoRepro — Analysis Reports

An independent review of the `Bug_Reproducer` repository (state of `main` at `76ea269`).

| Report | What's inside |
|---|---|
| [01 — Project Analysis](01-project-analysis.md) | What the system is, architecture diagram, module map, request lifecycle, metrics, strengths, scorecard |
| [02 — Bug Analysis](02-bug-analysis.md) | 37 findings (24 bugs, 6 security, 6 deployment/repo, 1 test-quality), each with file:line, severity, evidence, fix |
| [03 — Upgrade Roadmap](03-upgrade-roadmap.md) | Phased plan: stabilise, secure, re-architect, product features, AI quality; quick-win checklist |
| [04 — What the Project Lacks](04-missing-capabilities.md) | Gap analysis with an impact/effort priority matrix and the "first 5 things" |
| [verify_bugs.py](verify_bugs.py) | A script that re-runs the verifiable findings against the code. No API keys or Docker needed |

## Headline findings

1. **False "Bug Reproduced" results.** A script that crashes after printing a step such as
   *"Checking whether the bug is reproduced"* is marked successful (B01). `NOT_REPRODUCED` counts as
   success too (B02).
2. **The self-refinement loop mostly doesn't run.** The most common first failure ("Bug not
   reproduced") is classified `FalsePositive`, which ends the job after one attempt (B04).
3. **Fail-fast in the wrong places.** An unreachable or erroring page (B05), or a fenced JSON reply
   (B06), fails the job with zero attempts. A bug *about* a 500 page can never be reproduced.
4. **Lost data.** Every API job loses `created_at` (B07). Failure reasons are never shown (B08), and
   exceptions wipe attempt history (B10).
5. **Not safe on the public internet as deployed.** There's no auth, SSRF to cloud metadata with a
   read-back path, a bypassable sandbox scanner with full egress, and the Docker socket in a root
   container (S01–S04). The production compose also can't run sandboxes correctly as committed (D01, D02).

## Reproducing the findings

```bash
cd autorepro
pip install -r requirements-dev.txt
python ../docs/analysis/verify_bugs.py
```

Each line prints `CONFIRMED` (the bug is still present) or `fixed`. That makes the script usable as a
regression checklist while the fixes land.
