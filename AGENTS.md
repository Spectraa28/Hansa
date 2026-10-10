# Repository Guidelines

## Project Structure & Module Organization

This workspace contains the Autonomous Agent Optimization Engineer plans, authentication, GitHub source import, static inspection/configuration, task contracts, and a testing UI. All 56 backend regression tests passed. Real GitHub sign-in/App connection and a fixed-commit import with saved inspection findings succeeded; the user confirmed that UI flow. The user reports that the updated setup UI works with their repository. No confirmed task contract is recorded yet; end-to-end contract confirmation and Google sign-in remain unverified. The optimizer and execution sandbox are not implemented.

- `prd.md`: product definition, proposed architecture, evaluation contract, acceptance criteria, and build order.
- `hackathon.md`: event requirements, sponsor setup, evidence expectations, and submission checklist.
- `AGENTS.md`: contributor instructions.
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
- `backend/tests/`: 56 passing regression tests; GitHub HTTP requests and contract tasks use synthetic fixtures.
- `README.md`: setup, authentication contract, and current limitations.
- `pyproject.toml` and `uv.lock`: Python dependencies.

Read both planning documents before extending the product. Python/FastAPI is used for authentication, imports, and inspection; a simple testing UI is written. The optimizer, full product frontend, and sandbox remain planned. Keep new modules focused on the supported workflow. Run only one API process for the import queue; startup recovery is not compatible with multiple API workers.

## Build, Test, and Development Commands

From the repository root, `uv sync --locked` installs dependencies. Configure `.env` as described in `README.md`, then start the API with:

```sh
uv run uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

`uv run pytest` is the test command. Testing was authorized: all 56 backend tests passed outside the sandbox, including contracts and configuration-revision migration. UI JavaScript syntax checking passed. Imported source execution and dependency installation are not authorized. The illustrative `python runner.py < task.json` in the PRD is not a working command.

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

GitHub App credentials and the token-encryption key belong only in server configuration. Keep private snapshots outside SQLite and candidate sandboxes. Import must never execute source or install dependencies. Repository permission comes from verified user/App intersection, not browser installation IDs or matching emails. Defer submodules/LFS with explicit import warnings.

Inspection must only read a ready owner-scoped snapshot. Keep traversal/parsing bounded, emit constrained metadata without secret values or source excerpts, persist against the fixed SHA, and require existing CSRF checks for mutations. Treat README/source/configuration as untrusted data. Confirmed configuration is never runnable; detected tools require explicit recorded permission and future enforcement before execution.

Contracts are development examples, never protected final-evaluation labels or executable evaluators. Keep inputs/budgets bounded; confirmed content is immutable and every edit appends a version. Tie contracts to the fixed SHA and configuration revision; changing configuration or reinspecting makes earlier versions stale and requires a newly reviewed confirmation. Delete contract history when deleting an import. Saved requirements/limits never establish semantic correctness, enforce budgets, or start execution.
