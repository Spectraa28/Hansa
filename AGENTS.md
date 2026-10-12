# Repository Guidelines

## Project Structure & Module Organization

This workspace contains the Autonomous Agent Optimization Engineer plans, authentication, GitHub source import, static inspection/configuration, task contracts, a testing UI, and a service-only Docker runner. The setup UI saves an explicit LiteLLM model selection separately from source model metadata; owner-scoped service minting binds every call to that choice and records both names. Own-key provider mode remains planned. The non-streaming model gateway supports per-key model maps, requested/upstream model accounting, LiteLLM-reported cost headers, atomic recorded-spend admission, text content parts, and interrupted-call recovery. A real `claude-haiku` gateway call succeeded with HTTP 200 and a recorded $0.0000396 cost header; `/cost/estimate` is no longer required: spend admission now uses a soft recorded-spend threshold, with call/output limits and explicit unknown-cost reporting. See [GATEWAY.md](backend/docs/GATEWAY.md). The local sample runner → Docker → gateway → LiteLLM path and timeout/child cleanup succeeded; this is a labelled local fixture, not GitHub-agent compatibility or optimization evidence. See [RUNNER.md](backend/docs/RUNNER.md). Real GitHub sign-in/App connection and a fixed-commit import with saved inspection findings succeeded; the user confirmed that UI flow. The user reports that the updated setup UI works with their repository. A confirmed development contract and baseline have been exercised on the labelled web_lookup fixture; real GitHub task-contract confirmation and Google sign-in remain unverified. The optimizer, protected evaluation and hosted execution remain unimplemented.

- `prd.md`: product definition, proposed architecture, evaluation contract, acceptance criteria, and build order.
- `hackathon.md`: event requirements, sponsor setup, evidence expectations, and submission checklist.
- `AGENTS.md`: contributor instructions.
- `backend/app/gateway/`: scoped throwaway keys, per-key model maps, non-streaming LiteLLM proxy, dual-name usage records, LiteLLM response-header costs, atomic recorded-spend admission, text content parts, and lease/cancellation recovery (estimated spend can differ from billing).
- `GATEWAY.md`: configuration, accounting limits, service-only mint/summary, and a real-call command.
- `backend/app/agent/`: Hansa's own agent; onboarding writes/proves an adapter and read-only investigation examines completed baselines with ledger and source evidence. See `AGENT.md`.
- `backend/app/tracing/`: Neatlogs MCP client, ledger/egress traces, queued-to-confirmed readback state, owner-scoped recheck and reads. See `TRACING.md`.
- `backend/app/runner/`: owner-scoped snapshot copies, secret-free binary-wheel resolution, hashed offline dependency images, a networkless relay, an optional filtering egress sidecar for public web access, bounded execution and persisted baseline reports.
- `BASELINE.md`: confirmed-contract baselines through stored onboarding adapters, background jobs/events and the latest-result endpoint. The Swarm-specific adapter and scripts used for the first real runs were removed; Swarm is imported like any other repository.
- `RUNNER.md`, `examples/one_call/`, and `scripts/prove_runner.py`: runner contract, labelled sample agent, live-call and timeout evidence workflow.
- `backend/app/auth/`: authentication routes, request schemas, password login, and sign-in rate limits.
- `backend/app/oauth/`: Google/GitHub provider clients, identity parsing, redirects, and callbacks.
- `backend/app/github/`: GitHub App connection, verified repository access, bounded fixed-commit archives, persisted import queue, deletion, and signed webhooks.
- `GITHUB_IMPORT.md`: GitHub App setup, API contract, supported limits, and credential/source boundaries.
- `backend/app/inspection/`: bounded static detection, evidence, owner-scoped SQLite persistence, and configuration/tool-permission confirmation.
- `backend/app/ui/`: plain HTML/CSS/JavaScript testing interface served at `/setup`.
- `REPOSITORY_INSPECTION.md`: inspection endpoints, limits, configuration contract, and verification boundaries.
- `backend/app/contracts/`: bounded development task/correctness contracts, immutable version history, readiness, and configuration staleness.
- `TASK_CONTRACT.md`: contract endpoints, fields, saved budgets, and confirmation boundaries.
- `backend/app/users.py`: user and provider identity storage.
- `backend/app/sessions.py`: session storage, cookie handling, and logout CSRF checks.
- `backend/app/database.py`: shared SQLite connection and schema initialization.
- `backend/app/config.py` and `backend/app/main.py`: settings and FastAPI application setup.
- `backend/tests/`: 292 passing regression tests (3 skipped without Docker checks) as of October 12; gateway/GitHub HTTP requests and contract tasks use synthetic fixtures. Docker lifecycle and offline-wheel checks use real containers; separate live Haiku proof uses the labelled local sample.
- `README.md`: setup, authentication contract, and current limitations.
- `backend/pyproject.toml` and `backend/uv.lock`: Python dependencies.
- `backend/docs/`: technical documentation for each backend stage.
- `backend/scripts/` and `backend/examples/`: proof scripts and labelled fixture agents.
- `frontend/`: the product interface; see `frontend/README.md`.
- `deploy/`: proposed hosting layout (Vercel frontend, one EC2 API host behind Caddy), invite list and security settings. Not yet exercised against a real server; see `deploy/README.md`.

Read both planning documents before extending the product. Python/FastAPI is used for authentication, imports, inspection and the runner; a simple testing UI is written. The optimizer and full product frontend remain planned. Keep new modules focused on the supported workflow. Run only one API process for the import queue and one runner/controller process; multi-process runner scheduling and controller-crash cleanup are not implemented.

## Build, Test, and Development Commands

The Python project lives in `backend/`. From `backend/`, `uv sync --locked` installs dependencies. `.env` and the ignored `var/` runtime data stay at the repository root. Configure `.env` as described in `README.md`, then start the API with:

```sh
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

`uv run pytest` is the test command, run from `backend/`; proof scripts run as `uv run python -m scripts.<name>` from the same directory. On October 11, `RUNNER_DOCKER_TEST=1 .venv/bin/python -m pytest -q` passed all 264 tests in 98.42 seconds outside the sandbox, including real Docker lifecycle, networked binary-wheel resolution and hashed offline dependency installation. Gateway regression upstream calls use mocks; a separate real Haiku call and container sample verified model access/cost-header accounting. UI JavaScript syntax checking previously passed. On October 10 the user authorized imported-source execution inside isolated Docker containers only, plus a separate dependency build with no keys. Host execution of imported source remains unauthorized. The runner uses a read-only snapshot copy, scratch space, non-root user, memory/CPU/process limits, a hard timeout, and no Docker socket or access to metadata/private networks. Only a scoped throwaway gateway key and gateway URL may be provided; host credentials must not enter builds or execution containers. Use `RUNNER_DOCKER_TEST=1 uv run pytest backend/tests/test_runner.py -q` for actual Docker regression checks. Use `uv run python -m scripts.prove_runner` for the labelled local fixture. See [BASELINE.md](backend/docs/BASELINE.md) for baselines. The illustrative `python runner.py < task.json` in the PRD is not a working command.

Useful documentation checks:

- `rg --files`: list workspace files.
- `rg -n 'Status:|Acceptance criteria|Submission checklist' prd.md hackathon.md`: locate implementation status and delivery requirements.
- `git diff --check`: check whitespace. Git is initialized and the Entire origin remote is configured.

Entire is enabled locally with automatic checkpoint uploads disabled. Hooks still require user approval. Manual session attachment can create a checkpoint; verify its ID and remote ref before claiming uploaded checkpoint evidence.

## Coding Style & Naming Conventions

Match the existing Markdown: descriptive headings, short paragraphs, relative file links, and fenced command examples. Keep proposed behavior, organizer guidance, and verified results explicitly distinguished. Use descriptive filenames; avoid adding dependencies or abstraction without a demonstrated need. No formatter, linter, or language-specific style is configured yet.

## Testing Guidelines

Pytest is configured; no coverage threshold is established. Once testing is authorized, verify authentication and import trust boundaries and written regression tests. GitHub tests use mocked HTTP responses; do not claim real App authorization or private-repository access from them. For optimizer implementation, verify input validation, execution boundaries, budget enforcement, and recovery. Compare original and candidate workflows on identical tasks and declared settings. Freeze candidates before protected final evaluation. Label mocks, replay, and injected faults; retain per-case failures and reproduction instructions alongside reported improvements.

## Commit & Pull Request Guidelines

Use concise imperative commit messages, such as `Document evaluation boundaries`. Keep changes focused. PR descriptions should state the problem, changed behavior, validation performed, and limitations; link relevant requirements and include screenshots for UI changes. Preserve dated commits and actual Entire checkpoint evidence when available.

## Security & Evidence

Keep credentials, private source, and sensitive traces out of commits and public artifacts. Separate candidate execution from protected evaluators and accounting. Report measured results honestly. External publication, paid signup, and production changes require separate authorization.

GitHub App credentials and the token-encryption key belong only in server configuration. Keep original private snapshots outside SQLite and candidate sandboxes; execution gets only an independent read-only copy of its own snapshot. Import must never execute source or install dependencies. The separate runner may execute a reviewed ready snapshot inside Docker under the user's authorization; dependency installation uses the trusted offline build recipe, never a repository Dockerfile or source build backend. Repository permission comes from verified user/App intersection, not browser installation IDs or matching emails. Defer submodules/LFS with explicit import warnings.

Inspection must only read a ready owner-scoped snapshot. Keep traversal/parsing bounded, emit constrained metadata without secret values or source excerpts, persist against the fixed SHA, and require existing CSRF checks for mutations. Treat README/source/configuration as untrusted data. Confirmed configuration is never runnable; detected tools require explicit recorded permission and future enforcement before execution.

Contracts are development examples, never protected final-evaluation labels or executable evaluators. Keep inputs/budgets bounded; confirmed content is immutable and every edit appends a version. Tie contracts to the fixed SHA and configuration revision; changing configuration or reinspecting makes earlier versions stale and requires a newly reviewed confirmation. Delete contract history when deleting an import. Saved requirements/limits never establish semantic correctness, enforce budgets, or start execution.
