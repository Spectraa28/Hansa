# Development baselines

## Confirmed-contract baseline

Any ready Python import supported by the runner can use its onboarding adapter for a baseline. A current confirmed task contract and a stored adapter are required. This does not establish compatibility with arbitrary languages, streaming clients, unavailable services or source-only dependencies; see [AGENT.md](AGENT.md) and [RUNNER.md](RUNNER.md).

A completed baseline can be passed to the read-only [investigation job](AGENT.md#investigation). It reads per-run accounting from our database, investigates the relevant source, and saves evidence-backed hypotheses. Trace acceptance is queued until finalized readback succeeds; see [TRACING.md](TRACING.md). Investigation does not change the baseline or run a candidate.

Start a background job with the owner's login cookie and CSRF token:

```text
POST /github/imports/{import_id}/baseline
X-CSRF-Token: <session CSRF token>
Content-Type: application/json

{"repetitions": 2}
```

The response is `202` with a `baseline_id` and the initial report. Repetitions are 1–5, default 1. Read a particular job at `GET /github/imports/{import_id}/baseline-jobs/{baseline_id}`. Poll `GET /github/imports/{import_id}/baseline-jobs/{baseline_id}/events?after=N` for ordered `started`, `build`, `run`, `task`, and `finished` events (up to 200 per response). The existing `GET /github/imports/{import_id}/baseline` still returns the latest persisted report, including partial results. Reads require the owner, use no-store caching, and launch no work.

Onboarding and contract baselines share a single process-local job lock. `409` means another job is running, the contract is absent/draft/stale, or the adapter is missing; `503` means the model gateway is unconfigured. Run only one API/controller process. Do not run the separate airline CLI concurrently with API jobs. Backend startup marks interrupted baseline reports failed; it does not clean up containers abandoned by a controller crash.

The job freezes the confirmed contract version and the stored adapter content/hash, prepares a dependency image, and sends only each task's `input` to that adapter in Docker. Expected values and rules stay in the controller. It stops with saved partial results if the contract version or confirmed configuration changes. Build/image, fixed SHA, configuration revision, contract content/version, and adapter hash/job ID are retained.

Scoring checks:

- Required fields use JSON pointers, including escaped object keys and array indices. Missing fields fail, including missing fields declared `null`.
- Types distinguish booleans from integers/numbers. Exact values and `expected_output` use recursive JSON equality; numeric `1` equals `1.0`, and neither equals `true`. Expected output compares the whole value, including keys and array order.
- Automatic rules in task facts/evidence and contract behavior/failure requirements are checked against each output. The contract has no conditional-rule syntax; a rule must be applicable to each task where it is declared.
- Human-review requirements are always recorded as `needs_review`, never automatically passed or failed. A task with automatic failures is `failed`; one with successful automatic checks and pending review is `needs_review` (`passed: null`); otherwise it is `passed`. `automatic_passed` records the automatic result separately. Execution failures also fail the task.

Each repetition persists its output, status/reason, requirement results, run ID/stop reason, model calls, input/output tokens, known/unknown cost and usage, wall time, outside allowed/denied connections and hosts, and Neatlogs trace ID/status. Repetitions have means/spreads and individual `runs`; every trace ID is listed in `trace_ids`. `pass_rate` stays null when human review is pending. A completed job can contain failed tasks or tasks needing review; job completion is not correctness. Top-level counts distinguish `passed`, `failed`, and `needs_review` tasks.

The saved contract's budgets apply across all tasks and repetitions together. The controller passes the remaining call/spend allowance and elapsed-time allowance (at most 300 seconds per execution) to each run. It admits no further work after unknown cost/usage or an observed token, outside-call or spend overrun. Spend admission is soft and may overshoot on the last call; token/outside-call bounds are checked after each run, not enforced inside it. Outside calls are proxy connections, not a count of every local tool invocation. Build time is excluded; the controller's time allowance includes run setup and trace export. These are development checks, not protected evaluation or a hard billing cap.

### Local proof

For an already-onboarded, labelled `examples/web_lookup` import:

```sh
uv run python -m scripts.prove_baseline FIXTURE_IMPORT_ID
```

This writes and confirms a three-task contract (capital, arithmetic, live page fetch), starts the normal baseline background job with two repetitions, reads the saved report and every trace back, and saves private evidence in ignored `var/baseline-proof.json`. It requires the confirmed `claude-haiku` selection and configured Neatlogs. It permits at most 18 model calls, 900 seconds after build, and a $0.12 soft recorded-spend threshold. No new onboarding or automatic retry of the baseline occurs.

To retry only readback/export, use `--baseline-id BASELINE_ID`; it makes no model calls. The proof saves the result before attempting remote readback, retains individual read errors, and retries only `not_found` four times with three-second waits. A readback error fails the proof script, never the persisted baseline.

Verified October 11 on fixture import `bb45c0af-b444-4b6a-89e2-b860fb3327c4`, baseline `9dae9b91b3484775a4042891194e9484`: all six executions completed and passed their automatic checks. Three tasks remain `needs_review`, with zero automatic failures. Exact answers were `Paris` and `4`; both live-page runs fetched `https://example.com` and returned its title and a quotation. Totals: eight real Haiku calls, 5,198 input and 270 output tokens, $0.0072028 LiteLLM-reported cost, two outside connections, and 27.200688 seconds of execution wall time. All six trace IDs were acknowledged by Neatlogs and saved. At readback, five returned `not_found` despite bounded retries and one returned `processing`/`pending` with no finalized spans; finalized remote trace coverage is not yet verified for this baseline. The prior fixture smoke trace remained readable. This is a local fixture proof, not a real GitHub-agent baseline, protected evaluation, or optimization result.

Validation: the Docker-enabled full suite passed 254 tests in 97.04 seconds; final focused baseline/proof checks passed 27 tests after adding proof-contract and readback-recovery checks.

## Reading a baseline

Read the most recent saved report using the application login cookie:

```text
GET /github/imports/{import_id}/baseline
```

The endpoint returns `401` when signed out and `404` for another owner's import or no recorded report. It never launches work or returns model keys. Each task reports the mean for calls, tokens, cost and wall time, the `[min, max]` spread across repetitions, a `pass_rate` and the individual `runs`. An unknown cost in any repetition leaves that task's cost unknown.

The baseline saves after each task and reports `status=running` until completion. Runs use filtered internet access when `RUNNER_INTERNET` is true (the default); see [RUNNER.md](RUNNER.md).

## History: the Swarm airline example

The first real agent Hansa measured was the airline example in a fork of `openai/swarm` at `6af0b4caf37dca4526dfd98e9fbd8ce36e7eeb22`. It was first run through a hand-written adapter and a dedicated script that replayed the upstream single-turn eval cases, then through a six-conversation development contract.

That Swarm-specific code was removed on October 11 once onboarding could write an adapter for any imported agent: the reviewed `airline_adapter.py`, the `airline` baseline path, `scripts/baseline_airline.py`, `scripts/prove_airline_conversations.py`, `examples/contracts/swarm_airline.json` and their tests. They remain in the Git history. Swarm is now imported and measured like any other repository, and the saved result of the six-conversation run is the read-only demo in the frontend.

## Current verification

On October 11, `RUNNER_DOCKER_TEST=1 .venv/bin/python -m pytest -q` passed **204 tests in 102.58 seconds**. Real Docker tests covered lifecycle/isolation, public binary-wheel download and hashed offline dependency installation. Baseline tests use synthetic cases and mocked runner results; they verify scoring, adapter invocation, metric storage, owner authentication and deletion, not real Swarm/model behavior. The local application started successfully with the baseline GET route. No Swarm fork/import is present and no paid baseline calls were made in this change.
