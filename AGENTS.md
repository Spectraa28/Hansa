# Repository Guidelines

## Project Structure & Module Organization

This workspace contains the Autonomous Agent Optimization Engineer plans, authentication, and GitHub source import. All 37 regression tests passed; real GitHub sign-in and authentication startup succeeded. GitHub App/repository access and Google sign-in remain unverified. The optimizer and execution sandbox are not implemented.

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
- `backend/app/users.py`: user and provider identity storage.
- `backend/app/sessions.py`: session storage, cookie handling, and logout CSRF checks.
- `backend/app/database.py`: shared SQLite connection and schema initialization.
- `backend/app/config.py` and `backend/app/main.py`: settings and FastAPI application setup.
- `backend/tests/`: 37 passing regression tests; GitHub import requests are mocked.
- `README.md`: setup, authentication contract, and current limitations.
- `pyproject.toml` and `uv.lock`: Python dependencies.

Read both planning documents before extending the product. Python/FastAPI is used for authentication, imports, and inspection; a simple testing UI is written. The optimizer, full product frontend, and sandbox remain planned. Keep new modules focused on the supported workflow. Run only one API process for the import queue; startup recovery is not compatible with multiple API workers.

## Build, Test, and Development Commands

From the repository root, `uv sync --locked` installs dependencies. Configure `.env` as described in `README.md`, then start the API with:

```sh
uv run uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

`uv run pytest` is the test command. The user subsequently authorized UI testing: all 45 backend tests passed outside the sandbox, including inspection tests, and JavaScript syntax checking passed. The updated API started with the connector enabled and served the setup page/assets successfully. Live App authorization, import, and browser interactions remain in progress. This authorization does not permit executing imported source or installing its dependencies. The illustrative `python runner.py < task.json` in the PRD is not a working command.

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
