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

Validation: the Docker-enabled full suite passed 254 tests in 97.04 seconds; final focused baseline/proof checks passed 27 tests after adding proof-contract and readback-recovery checks. Airline scoring/invocation regressions still pass.

## Swarm airline baseline

### Full conversation development contract

[`examples/contracts/swarm_airline.json`](../examples/contracts/swarm_airline.json) defines six sequential conversations: refund cancellation, flight credits, baggage recovery, baggage-to-cancellation intent change, a different-flight escalation, and a change-flight escalation where seat/fare verification is unavailable. Each checks the exact ordered executed function sequence, terminal action/result and closure flag; full transcripts remain available for human policy review. Ordinary case inputs contain only user turns. Scoring rules remain in the controller. The upstream tools themselves return canned service results; this is real Swarm/model orchestration over demo service functions, not real airline operations or protected evaluation.

The onboarding agent receives this contract and writes the multi-turn adapter. Its stored adapter must preserve active-agent, history and context state between turns, execute the imported tools and derive results from actual tool messages. It must not use the legacy `max_turns=1` adapter below. Review the stored adapter before baseline execution. The UI's per-import baseline model defaults to `claude-sonnet-4.6`; existing saved choices are preserved. Hansa's `AGENT_MODEL` remains separate. Baseline reports freeze and record the selected target model.

The proof CLI uses the running API/controller, creating and revoking a temporary owner session locally. It refuses fixtures, other repositories and unreviewed SHAs. The six-task contract uses two repetitions, up to 160 calls, 300,000 tokens and 1,800 seconds across the baseline, with a $2 soft recorded-spend threshold. Onboarding and investigation each use $1 thresholds. A $1 reserve is left beneath the user's $5 total; this headroom is not a hard billing guarantee. Unknown costs prevent advancing, stage IDs and partial reports persist, and a started stage cannot be paid-rerun automatically. An explicit `--retry` permits a failed onboarding or investigation attempt; every prior report and its cost remains charged to the same $5 pipeline.

```sh
uv run python -m scripts.prove_airline_conversations IMPORT_ID --stage prepare
uv run python -m scripts.prove_airline_conversations IMPORT_ID --stage onboarding
# Review the stored adapter and smoke transcript before continuing.
uv run python -m scripts.prove_airline_conversations IMPORT_ID --stage baseline
uv run python -m scripts.prove_airline_conversations IMPORT_ID --stage investigation
uv run python -m scripts.prove_airline_conversations IMPORT_ID --stage report
```

Private evidence is saved to ignored `var/airline-conversations-IMPORT_ID.json`. `report` refreshes job results and costs without model calls. Passing automatic checks still leaves the declared policy reviews pending.

### Legacy upstream single-turn eval

Status: adapter, binary dependency resolution, persisted per-task metrics and the read endpoint are implemented. No live Swarm baseline has been recorded yet: a real owner-scoped GitHub fork import is required. The controller never executes imported code on the host.

## Fit and evaluation scope

Reviewed upstream revision: `openai/swarm@6af0b4caf37dca4526dfd98e9fbd8ce36e7eeb22`. `swarm/core.py` calls the OpenAI SDK's non-streaming Chat Completions API. Airline tools are local functions; they do not need web access. The example's top-level `configs`/`data` imports need its airline directory on `sys.path`, supplied by the trusted adapter.

The upstream cases are four triage examples and three flight-modification examples. Preserve their conversations and expected functions. Like upstream `eval_utils.py`, use `max_turns=1` and score the first tool result's function name, or an ordinary assistant message when the expected function is `"None"`. Run once per case (`n=1`, compared with upstream's illustrative five repetitions). This is a function-selection development baseline, not full cancellation/refund/baggage resolution or protected evaluation. The original snapshot contains its public development labels; the controller does not send expected labels in task stdin.

## Import and configuration

1. Fork `openai/swarm` into your GitHub account. Give the existing read-only GitHub App access to that fork.
2. Import the fork through `/setup`; it must be a real ready import, not a manually registered local fixture.
3. Inspect and confirm `setup.cfg`, Python `>=3.10`, entrypoint `python examples/airline/main.py`, source model `gpt-4o`, and explicit LiteLLM model `claude-haiku`.
4. Record approval for `transfer_to_flight_modification`, `transfer_to_lost_baggage`, `transfer_to_flight_cancel`, and `transfer_to_flight_change`. These are the only functions the single-turn eval agents can invoke. Downstream service functions are not exercised. Reinspect if the four routing tools do not appear after updating the backend.

The real baseline replaces the interactive entrypoint with a trusted separately mounted adapter. It does not edit the original snapshot or agents/prompts. Only imported code inside the isolated runner container is executed. The adapter also checks that the two eval agents expose exactly the reviewed routing function names.

## Run and read

Use only one controller, with the normal single API process running:

```sh
uv run python -m scripts.baseline_airline IMPORT_ID
```

Add `--repetitions N` (1–5) to run every case N times. Each task then reports the mean for calls, tokens, cost and wall time, the `[min, max]` spread, a `pass_rate`, and the individual `runs`; `passed` means every repetition passed. An unknown cost in any repetition keeps that task's mean cost unknown. Use repetitions whenever tools read live data or the model's output varies, since a single run cannot separate a real change from noise.

Runs use filtered internet access when `RUNNER_INTERNET` is true (the default); see [RUNNER.md](RUNNER.md). Each task reports `external_calls`, `external_denied` and `external_hosts` from the egress sidecar. The airline cases use only local functions, so these should be zero.

Dependencies resolve from the confirmed manifest in a networked container without source or credentials, then install offline. The immutable dependency image, exact resolved distribution versions/hashes, import SHA, snapshot digest, configuration revision, adapter hash, and eval-file hashes are retained for reproduction. A new build can resolve newer allowed versions; comparisons should reuse the recorded immutable image.

Each task has one gateway call, zero SDK retries, a default 1,024 output-token allowance, a 90-second execution timeout and a $0.02 recorded-spend threshold. Seven cases mean at most seven admitted calls. The threshold is a soft admission rule: it can overshoot, and unknown costs do not prevent further admission. Cost is LiteLLM-reported, not invoice-reconciled. No automatic paid reruns occur.

Read the most recent saved report using the existing application login cookie:

```text
GET /github/imports/{import_id}/baseline
```

The endpoint returns `401` when signed out, `404` for another owner's import or no recorded report, and `Cache-Control: no-store`. It never launches work or returns model keys. The report contains pass/fail, expected/actual function, run ID/stop reason, model calls, input/output tokens, known cost, unknown-cost/usage counts, requested/upstream model names and wall time for every task. Wall time excludes dependency build and relay setup. Full outputs/errors remain in private `runner_runs` service storage.

The baseline saves after each task and reports `status=running` until completion. Controller interruption can leave a partial report marked running; automatic controller-crash recovery is not implemented. Deleting an import removes its baseline, run content and dependency records. No browser run button, optimizer, protected evaluator, sponsor export or deployment is added here.

## Current verification

On October 11, `RUNNER_DOCKER_TEST=1 .venv/bin/python -m pytest -q` passed **204 tests in 102.58 seconds**. Real Docker tests covered lifecycle/isolation, public binary-wheel download and hashed offline dependency installation. Baseline tests use synthetic cases and mocked runner results; they verify scoring, adapter invocation, metric storage, owner authentication and deletion, not real Swarm/model behavior. The local application started successfully with the baseline GET route. No Swarm fork/import is present and no paid baseline calls were made in this change.
