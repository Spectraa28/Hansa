# Hansa's agent: onboarding and investigation

Status: onboarding and read-only baseline investigation are implemented. Onboarding was verified on October 11 against a local fixture with real model calls and real containers. Neither has been verified against a real GitHub import. Source editing, candidate execution and comparison are not built.

## What it does

Most agents do not read a task from stdin and print JSON, so the runner cannot execute them as imported. Onboarding closes that gap. The agent reads the repository, works out how the target is started, writes a small adapter file, runs it in the sandbox, reads the failure, and corrects the adapter until a run completes or it reports a specific blocker.

The model decides what to read, what to write and how to respond to a failed run. Controller code in [`backend/app/agent/service.py`](backend/app/agent/service.py) decides what it may touch.

| Tool | Effect |
| --- | --- |
| `list_files`, `search_code`, `read_file` | Bounded, read-only views of a staged snapshot copy. Paths cannot leave the repository; files over 256 KiB and non-UTF-8 files are refused; search is literal text, capped at 40 matches. |
| `write_adapter` | Replaces the single draft adapter (at most 32 KiB). Syntax is checked with `ast.parse`; the adapter is never executed in the controller. |
| `run_smoke` | Runs the draft in the isolated runner with one task object. Returns the stop reason, exit code, parsed output, the tail of stderr, model calls, cost and external hosts. At most 8 per job. |
| `finish` | `ready` is accepted only when the current draft has a completed smoke run; otherwise the agent must run one or finish as `blocked` with a reason. |

A job is limited to 30 model turns. The agent's model calls go through the gateway on their own key (`hansa-onboarding-<job>`, at most 36 calls and a $1.50 recorded-spend threshold), so its cost is reported separately from the target's. Each smoke run uses the runner's normal scoped key for the target. Both keys are revoked when the job ends. One agent job runs at a time.

Investigation shares this loop, metered gateway path, 4096-output-token request limit, retry policy, key expiry (30 minutes), event list, job storage, and process-local lock with onboarding and baselines. Its key is `hansa-investigation-<job>` with the same 36-call/$1.50 soft admission limits. It does not build dependencies, execute the target, or write an adapter. Keys are revoked and the lock remains held until usage, trace export, and final events are saved.

## Investigation

`POST /github/imports/{id}/investigation` accepts `{}` for the latest baseline or `{"baseline_id":"..."}` for a particular report. It requires a completed, owner-scoped baseline, confirmed current configuration, and the same fixed SHA/source digest. A stale report fails before model calls. It returns `202`; status, findings, usage, and events use the existing `agent-jobs` endpoints. Onboarding remains unchanged at its endpoint.

The agent starts with per-task numbers, then inspects the expensive runs and reads the responsible code. Its read-only tools are:

| Tool | Evidence |
| --- | --- |
| `read_baseline(task_id?)` | Database task totals/run IDs; a particular task includes its repetitions and development rules. |
| `read_run(run_id, offset?, limit?)` | Ordered database model calls, requested/served models, tokens, latency, LiteLLM cost/provenance, prompt/tool-schema characters, repeated prefix characters, requested tools, saved outside connections, and inferred gaps. Calls paginate in groups of 1–20; the run is bounded to 1,000 calls. |
| `read_trace(run_id)` | One owner-scoped Neatlogs readback/recheck; queued/unavailable/error state is returned as evidence and does not stop investigation. |
| `list_files`, `search_code`, `read_file` | The same bounded snapshot tools as onboarding. Source reads are refused until baseline numbers have been inspected. |
| `save_finding` | Stores one untested proposal, with verified provenance. At most ten findings, each at most 128 KiB. |
| `finish(summary)` | Saves a conclusion, including `nothing_worth_changing: true` if no findings were saved. It requires inspected run numbers, source lines, and an explanation. |

Each finding contains `waste`, `evidence`, `estimated_saving` with a calculation/assumptions, `behaviour_risk`, and `proposed_change`. The controller requires cited run IDs to belong to this baseline and to have been inspected, requires an attempted trace read for each, and requires every cited source line to have been returned by a source read/search. It attaches the ledger calls, timings, gaps, outside connections, run/trace IDs, trace availability/error, and source file/line/hash itself. Estimates are bounded by known totals over the cited runs; unknown measurements cannot become numeric savings. Findings persist immediately and produce `finding` events, so a later job failure retains already-saved evidence.

These checks enforce provenance, not the truth of the model's interpretation or the safety of its proposed change. Repeated characters are not measured tokens; token/cost estimates must state conversion assumptions. Gaps overlap outside connections. Wall time includes container start/stop and cannot be attributed entirely to Python. A required web call is not waste simply because it costs more. No savings are measured until a future candidate is run and evaluated. Neatlogs is a second view; the database remains authoritative even if Neatlogs reports zero cost, processing, or not_found.

Reproduce the local paid proof without rerunning the baseline:

```sh
AGENT_MODEL=claude-haiku uv run python -m scripts.prove_investigation FIXTURE_IMPORT_ID --baseline-id BASELINE_ID
```

The script refuses unrelated imports, polls the normal job/events, and stores private findings and events in ignored `var/investigation-proof.json`. It rechecks the investigation job's own trace once after finishing. It never retries the paid job automatically.

An adapter is stored per import only after it passes: content, SHA-256, the passing task as an example, a description of the task fields, and the job that produced it. `runner.run(..., adapter="stored")` then executes the import through it. A new onboarding replaces the stored adapter.

## Endpoints

All require the owner's session; the mutation uses the existing CSRF check and rate limiter.

| Method | Endpoint | Behavior |
| --- | --- | --- |
| POST | `/github/imports/{id}/onboarding` | Start a job (`202`). `409` while another job runs or configuration is unconfirmed; `503` without gateway settings. |
| POST | `/github/imports/{id}/investigation` | Start read-only investigation of a completed baseline (`202`); body `{}` or `{"baseline_id":"..."}`. |
| GET | `/github/imports/{id}/agent-jobs/{job_id}` | Status (`running`, `ready`, `blocked`, `failed`) and result, including agent and target usage. |
| GET | `/github/imports/{id}/agent-jobs/{job_id}/events?after=N` | Ordered events after an ID: `started`, `build`, `note`, `tool`, `tool_error`, `adapter`, `smoke`, `finding`, `finished`. |
| GET | `/github/imports/{id}/adapter` | The stored adapter and its example task. |

`note` events are the agent's one-sentence statements of what it is checking, not private reasoning. `adapter` events include the draft code so a reviewer can see every revision.

## Outcomes

- `ready`: onboarding stored an adapter after a valid JSON run; investigation saved its findings or an explicit no-change conclusion.
- `blocked`: the agent or the dependency build found a specific reason the target cannot run here, for example a missing service key, a source-only dependency, or a client that cannot be pointed at the gateway. Nothing is stored.
- `failed`: the job itself broke: a model call failed, the turn limit was reached, or the controller restarted. Running jobs are marked failed on startup.

## Boundaries

- Repository source is sent to the model provider through LiteLLM so the agent can read it. Do not import a repository whose source must stay off third-party services.
- Repository text is treated as data. The prompt tells the agent to ignore instructions found in files; this reduces prompt-injection risk and does not eliminate it. What an injected agent could do is limited to its tools: reading the same snapshot, writing an adapter that runs only in the sandbox, and ending the job.
- The adapter is glue. The prompt forbids changing the target's logic, prompts, tools or model settings, and forbids stubbing the agent. This is an instruction, not an enforced check; review the stored adapter.
- A completed smoke run shows the adapter runs and returns JSON. It does not show the answer is correct. Correctness belongs to the task contract and baseline.
- The user does not yet approve an adapter before it is used.

## Verification

`RUNNER_DOCKER_TEST=1 uv run pytest -q` passed **239 tests** on October 11. The eight agent tests script the model and mock the runner: recovery from a failed run, the guard on `ready`, blockers, the turn limit, the single-job lock, restart recovery, owner scoping, deletion and path confinement.

Live run, reproducible with `AGENT_MODEL=claude-haiku uv run python -m scripts.prove_onboarding`:

- Target: [`examples/web_lookup`](examples/web_lookup), a labelled fixture written for this test: an interactive terminal chat with one live web-fetch tool, using the OpenAI SDK. It is not an agent we did not write.
- The agent read six files, wrote a 33-line adapter and its first smoke run completed. It used 5 model calls (16,156 input and 1,148 output tokens, $0.024 recorded); the target's smoke run cost $0.0008.
- The stored adapter was then run on a question requiring the web tool: 2 model calls, one connection to `example.com` through the egress sidecar, correct page title returned.

This run needed no correction, so recovery from a failed smoke run is verified only by the scripted test, not live. The default `AGENT_MODEL` (`claude-sonnet-4.6`) was not exercised live.

### Investigation verification, October 11

The full Docker-enabled suite passed **264 tests in 98.42 seconds**. After the final tool/prompt refinements, the **13 agent/investigation tests** passed again. These tests cover shared-loop recovery, owner/CSRF scoping, completed/stale baseline checks, observed run/source provenance, unknown costs, estimate bounds, unavailable traces, no-change conclusions, key revocation, and migration of existing jobs/events without breaking foreign keys.

A real `claude-haiku` investigation of the saved `web_lookup` baseline finished with `findings: []` and `nothing_worth_changing: true`. It inspected all six runs and five source files. The baseline's eight calls cost $0.0072028, used 5,198 input and 270 output tokens, and took 27.200688 seconds across the six executions. Live-page tasks accounted for 60.3% of cost and 45.7% of execution wall time: the source requests a tool, fetches the page, and calls the model again with its result. The repeated 249 characters were unchanged system/user context, not a repeatedly appended page. No measured improvement or candidate change is claimed.

The final investigation used 13 model calls, 91,849 input and 2,568 output tokens, and $0.1151579; its persisted 34 events contain `started`, ten `note`, 22 `tool`, and `finished`, without tool errors. Earlier validation attempts remain saved: one failed after invalid task IDs and idle turns; another finished but its narrative confused repeated context and rounded totals. Tool validation/definitions were corrected before the final run. All three paid attempts cost $0.4260751. Private ignored proof files retain the results and complete events; final proof is `var/investigation-proof.json`.

The two live-page Neatlogs IDs remained queued with readback errors `conflict` and `not_found`. The investigation's own trace export failed with HTTP 403 even after the existing content fallbacks, so it has no trace ID. Its job, measurements, source evidence and events remain in our database. This verifies operation without Neatlogs readback, not successful trace confirmation or compatibility with a third-party agent.
