# Swarm airline baseline

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
