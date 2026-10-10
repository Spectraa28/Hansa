# Repository Guidelines

## Project Structure & Module Organization

This workspace contains the Autonomous Agent Optimization Engineer plans and the first backend authentication slice. Authentication code is written but untested; the optimizer and execution sandbox are not implemented.

- `prd.md`: product definition, proposed architecture, evaluation contract, acceptance criteria, and build order.
- `hackathon.md`: event requirements, sponsor setup, evidence expectations, and submission checklist.
- `AGENTS.md`: contributor instructions.
- `backend/app/auth/`: authentication routes, request schemas, password login, and sign-in rate limits.
- `backend/app/oauth/`: Google/GitHub provider clients, identity parsing, redirects, and callbacks.
- `backend/app/users.py`: user and provider identity storage.
- `backend/app/sessions.py`: session storage, cookie handling, and logout CSRF checks.
- `backend/app/database.py`: shared SQLite connection and schema initialization.
- `backend/app/config.py` and `backend/app/main.py`: settings and FastAPI application setup.
- `backend/tests/`: written security regression tests, not yet executed.
- `README.md`: setup, authentication contract, and current limitations.
- `pyproject.toml` and `uv.lock`: Python dependencies.

Read both planning documents before extending the product. Python/FastAPI is used for authentication; the optimizer, frontend, and sandbox remain planned. Keep new modules focused on the supported workflow.

## Build, Test, and Development Commands

From the repository root, `uv sync --locked` installs dependencies. Configure `.env` as described in `README.md`, then start the API with:

```sh
uv run uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

`uv run pytest` is the test command. The user explicitly requested writing code first and deferring application testing until they authorize it: do not run tests, smoke checks, or the application before that authorization. These commands have not been verified through execution. The illustrative `python runner.py < task.json` in the PRD is not a working command.

Useful documentation checks:

- `rg --files`: list workspace files.
- `rg -n 'Status:|Acceptance criteria|Submission checklist' prd.md hackathon.md`: locate implementation status and delivery requirements.
- `git diff --check`: check whitespace. Git is initialized and the Entire origin remote is configured.

Entire is enabled locally with automatic checkpoint uploads disabled. Hooks still require user approval. Manual session attachment can create a checkpoint; verify its ID and remote ref before claiming uploaded checkpoint evidence.

## Coding Style & Naming Conventions

Match the existing Markdown: descriptive headings, short paragraphs, relative file links, and fenced command examples. Keep proposed behavior, organizer guidance, and verified results explicitly distinguished. Use descriptive filenames; avoid adding dependencies or abstraction without a demonstrated need. No formatter, linter, or language-specific style is configured yet.

## Testing Guidelines

Pytest is configured; no coverage threshold is established. Once testing is authorized, verify authentication trust boundaries and written regression tests. For optimizer implementation, verify input validation, execution boundaries, budget enforcement, and recovery. Compare original and candidate workflows on identical tasks and declared settings. Freeze candidates before protected final evaluation. Label mocks, replay, and injected faults; retain per-case failures and reproduction instructions alongside reported improvements.

## Commit & Pull Request Guidelines

Use concise imperative commit messages, such as `Document evaluation boundaries`. Keep changes focused. PR descriptions should state the problem, changed behavior, validation performed, and limitations; link relevant requirements and include screenshots for UI changes. Preserve dated commits and actual Entire checkpoint evidence when available.

## Security & Evidence

Keep credentials, private source, and sensitive traces out of commits and public artifacts. Separate candidate execution from protected evaluators and accounting. Report measured results honestly. External publication, paid signup, and production changes require separate authorization.
