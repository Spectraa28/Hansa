# Repository inspection and suggested configuration

Status: all 45 backend regression tests passed; JavaScript syntax checking passed, and `/setup` plus its assets returned HTTP 200. The user confirmed the UI import/inspection flow works. SQLite independently confirms GitHub connection, a ready `Spectraa28/VaultLearn` import at SHA `896d8802cc5e27a88fc1be691f491d950ed26bbe`, and saved suggested configuration/findings. Live confirmation of configuration remains unverified; regression coverage includes confirmation and explicit tool permissions. No imported code has been executed or dependencies installed.

## Testing page

After an authorized backend restart, open `http://localhost:8000/setup`. This page provides Google/GitHub or existing email-account login, GitHub App connection/installation links, paginated repository and branch selection, fixed-commit import, static inspection, evidence review, and configuration confirmation. OAuth callbacks still land on the existing JSON endpoints; return to `/setup` and refresh after authorization. Import progress uses manual refresh.

A ready import can be inspected immediately. A previously saved inspection can be retrieved without rescanning. Inspecting again clears its previous confirmation and creates a new inspection revision. The page prefills only unique detected values, leaves missing/multiple values unresolved, and allows corrections. Tool approval checkboxes start unchecked. Confirmed permissions are restored when retrieving saved configuration.

## Authenticated API

All IDs are UUIDs. Only the import owner can access these endpoints. Non-ready imports return `409`; missing or deleted imports return `404`. POST endpoints require the existing session cookie and `X-CSRF-Token`. Inspection requests use the existing rate limiter.

| Method | Endpoint | Result |
| --- | --- | --- |
| POST | `/github/imports/{import_id}/inspection` | Scan source and persist new suggestions |
| GET | `/github/imports/{import_id}/inspection` | Retrieve findings, suggestions, and confirmed configuration |
| POST | `/github/imports/{import_id}/configuration` | Confirm or correct configuration and explicit tool permissions |

Each finding includes `kind`, `value`, `source_file`, `location` (line, TOML key, configuration key, or file), and `confidence` (`explicit` or `inferred`). Source excerpts are never returned. The response includes missing fields, multiple-value conflicts, bounded scan statistics/notices, inspection revision, fixed commit SHA, and `suggested_configuration`. Missing/multiple scalar values become `null`; no model, provider, Python version, or entrypoint is silently chosen. Multiple Python declarations may be compatible; they are reported for review rather than resolved by a dependency solver.

Confirmation accepts:

```json
{
  "revision": "32-character inspection revision from the response",
  "commit_sha": "40-character fixed import SHA from the response",
  "python_version": "3.12",
  "dependency_manifests": ["pyproject.toml"],
  "entrypoint": "agent:main",
  "model_provider": "openai",
  "model_id": "gpt-4o",
  "approved_tools": []
}
```

This example is illustrative, not a model recommendation or verified run. Revisions/SHAs must match the stored inspection; stale writes return `409`. Corrections use constrained identifiers, not arbitrary shell commands. Corrected entrypoints must refer to scanned Python files, or be previously declared/detected entrypoints. Selected manifests and approved tools must appear in the findings. An empty manifest selection explicitly records no selected manifest; it does not establish that dependencies are absent or installed. Fields remain editable after confirmation.

Confirmed configuration records permissions for every detected tool, defaulting to denied, and whether scalar values match detection or were supplied by the user. Unknown tools cannot be granted through this endpoint. New/custom integrations need future reviewed detection/configuration support. No credentials belong in these fields.

## Detection and boundaries

- Python: `.python-version`, `project.requires-python`, and Poetry's Python dependency declaration.
- Dependencies: Python manifests (`pyproject.toml`, setup files, Pipfile, environment.yml, requirements `.txt`/`.in`) and uv/Poetry/Pipenv/PDM/requirements lockfiles. Manifest/lockfile presence does not establish installability, consistency, or safety.
- Entrypoints: PEP 621/Poetry script strings, README Python invocations, and Python main guards. No arbitrary README shell commands are copied into configuration.
- Providers: known SDK imports, configuration provider names, and known environment example key names. Import-based findings are inferred; an SDK can be present but unused.
- Models: bounded model identifiers in literal assignments, call keywords, and supported TOML/JSON/simple YAML or environment-example configuration. Dynamic expressions are not evaluated.
- Tools: known integration imports/calls and `@tool` functions. Detection is heuristic; imports may be unused and custom wrappers may be missed. Absence of findings does not establish absence of tools.

Per scan: at most 4,000 traversed entries, 200 read files, 64 KiB per read file, 2 MiB total read bytes (plus one oversize sentinel read), depth 12, 10,000 AST nodes per Python file, 1,000 configuration containers, 500 findings, and a five-second cooperative deadline. Partial scans are explicitly flagged. Parsing is bounded by input size; the deadline is checked around traversal/AST work and cannot interrupt a single standard-library parse. These are static-inspection bounds, not an execution sandbox.

The scanner never imports repository modules, evaluates expressions, runs commands, resolves dependencies, or fetches network content. It skips symlinks, nonregular files, private `.env` files, credential-named files, and build/dependency directories; file/directory opens use `O_NOFOLLOW`. Source is treated as untrusted data. Only constrained metadata is emitted; key/token/password values and raw configuration/source text are excluded. JSON is parsed as data, TOML with the standard library, Python with AST, and YAML detection only recognizes simple scalar lines.

## Storage and readiness

SQLite `repository_inspections` stores sanitized findings with suggested configuration, optional confirmed configuration, status, SHA, revision, and timestamps. Source remains in the existing private import workspace. Ownership/ready status are checked before scanning, retrieval, and confirmation. Inspection shares the existing import lock with deletion and rechecks the SHA before persistence. Import deletion removes saved inspection/configuration records.

Both suggested and confirmed responses always include `runnable: false`. Confirmation authorizes neither dependency installation nor code/model/tool execution. A later runner must independently enforce approved tool permissions, model access, network boundaries, dependencies, and budgets; detected tools alone never authorize execution. No sandbox runner, evaluator, or optimizer is included in this change.

## LiteLLM model selection

Inspection responses include the fixed `litellm_models` catalog. Configuration accepts optional `litellm_model` restricted to those seven aliases; the setup UI requires an explicit choice. Source `model_provider` and `model_id` remain separate. Selection changes revise the configuration and stale earlier task contracts. Old configurations remain compatible, but a selected-model gateway key requires a saved choice. See [GATEWAY.md](GATEWAY.md) for service-only minting and future own-key boundaries. No execution is enabled.
