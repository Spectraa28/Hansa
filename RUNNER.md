# Docker runner

The service executes one JSON task against a ready, owner-scoped Python snapshot. It never imports or executes repository Python in the API/worker process. There is no browser execution endpoint. Configuration/contract confirmation still does not start a run or establish correctness.

## Prerequisites and interface

Use a trusted local Linux Docker Engine, the local `python:3.12-slim` image, and confirmed Python `3.12` configuration with a LiteLLM model selection. Docker must support the default seccomp policy, cgroup memory/CPU/PID limits, and network namespace sharing. Docker access grants host-level privileges to the controller; execution containers receive no Docker socket. Run only one runner/controller process. The service serializes local builds/runs; multi-process scheduling is not implemented.

The application exposes `app.state.runner` internally:

```python
build = runner.build(user_id, import_id, wheelhouse=reviewed_wheel_directory)
result = runner.run(
    user_id, import_id, build["build_id"], {"message": "one task"},
    timeout_seconds=60, max_calls=10, max_spend_usd=0.01,
    memory_mb=256, cpus=1.0, pids=64,
)
saved = runner.get(user_id, import_id, result["run_id"])
```

The entrypoint must already consume JSON from stdin and emit exactly one JSON value on stdout. Supported invocations are `python relative_file.py`, `python -m module`, and `module:function`; module functions are invoked without arguments and must implement that stdin/stdout protocol themselves. Logs belong on stderr. No automatic framework adapter is generated.

Task JSON uses the existing data-only bounds (16 KiB, finite numbers, depth/node limits, no credential/executable fields). Runtime accepts 0.1–300 seconds, 64–4096 MiB, 0.1–4 CPUs, and 8–256 PIDs. A fresh key binds all requests to the confirmed model and enforces the supplied call/spend/expiry limits. Dollar-budget admission defaults on; `max_spend_usd=None` explicitly disables dollar admission while call/expiry enforcement remains active. Saved contract token/tool limits and semantic correctness are not enforced by this runner.

## Separate dependency build

Only the trusted generated Dockerfile enters the build. Repository Dockerfiles, scripts, editable installs, and source-package builds are unsupported. Source is not copied into the dependency image. Requirements are read from the confirmed `requirements.txt` or `[project].dependencies` in `pyproject.toml`, restricted to exact `package==version` pins. Optional extras, environment markers, dependency groups, URLs, recursive requirements and arbitrary pip options are rejected.

Supply reviewed `.whl` files, including all transitive dependencies, in `wheelhouse`. Missing wheels fail the build. Wheel acquisition/review is a separate operator task; the runner does not download them or execute a repository build backend. Dependency installation runs through pip in a separate Docker build with `--network none`, no credentials, no host secrets, `--no-index`, and binary-only packages. A standard-library-only repository needs no wheelhouse. Builds have a 300-second controller timeout. Build resource limits and total image-storage quotas are not implemented.

Build records bind the resulting immutable Docker image ID to the import SHA, configuration revision and copied source digest. A changed configuration or source requires a new build. Local dependency images remain cached for reuse; import deletion deletes build/run database records, but Docker image pruning is an operator task.

## Execution boundary

The runner checks owner/readiness/configuration under the import deletion lock, then creates a bounded independent snapshot copy. Links, special files, hard links and credential/configuration paths (`.git`, `.aws`, `.ssh`, `.env*`, `*.pem`, `*.key`) are rejected. Only that copy is mounted read-only at `/snapshot`; the original private import, database and evaluators are never mounted.

The execution container uses UID/GID `65532`, a read-only root, all capabilities dropped, `no-new-privileges`, Docker's default seccomp, memory/swap/CPU/PID limits, a file-descriptor cap, and disabled core dumps. `/scratch` is a 64 MiB tmpfs with `noexec,nosuid,nodev`; it is destroyed with the container. The agent receives an explicit clean environment: fixed system/Python paths, scratch HOME/TMPDIR, `OPENAI_BASE_URL` and the throwaway `OPENAI_API_KEY`. No host environment is inherited.

A trusted relay container uses `--network none`, leaving only loopback. The agent shares that network namespace, and calls `http://127.0.0.1:8000/gateway/v1`. The relay forwards only `POST /gateway/v1/chat/completions`, with bounded bodies, to a private gateway Unix socket. The socket is mounted only into the relay. Neither container gets an external interface, route, public port, Docker socket, or host network access. The relay cannot execute imported code and uses the trusted base image, independent of the agent dependency image.

The controller drains stdout/stderr concurrently. At the hard deadline or 1 MiB combined output limit it kills the entire execution container while continuing to drain its pipes. It records Docker's exit code (137 for SIGKILL), the parsed stdout JSON, the last 16 KiB of stderr, wall time, output byte count, and a stop reason: `completed`, `exit_nonzero`, `timeout`, `output_limit`, `oom`, `invalid_json`, or `infrastructure_error`. Wall time includes execution-container start/attach and termination, and excludes dependency build and relay setup. Infrastructure errors may have no exit code or output.

The key is revoked and both containers removed before a result is marked `cleanup_complete`. Scoped keys/server keys echoed in output are redacted. Results and gateway summaries are stored in private SQLite, accessible through owner-scoped service reads; deleting the import deletes the run content. Other private data returned by an agent is still private run content and must not be published automatically.

## Reproduce the live proof

Configure the server-only LiteLLM settings in `.env` first:

```sh
uv run python -m scripts.probe_gateway
uv run python -m scripts.prove_runner
RUNNER_DOCKER_TEST=1 uv run pytest backend/tests/test_runner.py -q
uv run pytest -q
```

The proof script registers `examples/one_call` as a clearly labelled **local fixture**, not a real GitHub import. It uses the normal owner-scoped ready-import, inspection, configuration, build, execution and result persistence paths. It makes one real model call, checks isolation, then runs an injected timeout with a child process. Private evidence is saved in ignored `var/runner-proof.json`.

## Verified live gateway limitation

On October 10, the configured LiteLLM key returned **401** for `/cost/estimate`, but a one-call, 16-token `claude-haiku` diagnostic returned **200**, with 11 prompt tokens, 5 completion tokens, and `x-litellm-response-cost` recorded as **$0.0000396**. Spend-limited requests continue to fail closed; the gateway now explains that the key needs `/cost/estimate` access. This matches the [documented LiteLLM quote endpoint](https://docs.litellm.ai/docs/proxy/pricing_calculator). No guessed price or automatic budget bypass was added.

For the explicitly bounded diagnostic proof only:

```sh
uv run python -m scripts.probe_gateway --call-only
uv run python -m scripts.prove_runner --live-call-only
```

The runner sample returned `OK.`, exit 0, HTTP 200, and one recorded Haiku call costing $0.0000396. Its wall time was 1.955603 seconds. The injected one-second timeout returned exit 137, reason `timeout`, wall time 1.200845 seconds including termination, no model calls, and successful container cleanup. These results establish sample compatibility, not arbitrary imported-framework compatibility, optimization gains, or billing reconciliation.

Final validation: `RUNNER_DOCKER_TEST=1 uv run pytest -q` passed all **196 tests in 81.76 seconds**. Actual Docker checks covered isolation, timeout with a child process, output flooding, invalid JSON, nonzero exit, stale-source rejection, persistence, revocation and offline installation of a labelled synthetic wheel. An output-flood termination stall was fixed by continuing pipe draining while Docker termination runs concurrently. A final `docker ps` check found no remaining runner/relay containers.

## Remaining boundaries

Docker shares the host kernel; this is a local reviewed-workflow runner, not a hardened arbitrary-code hosting platform. Hard termination depends on the controller and Docker daemon remaining available; controller-crash recovery and an independent watchdog are not implemented. A terminated container does not cancel an already-dispatched remote model request: the gateway drains in-flight requests (up to roughly 70 seconds) before completing teardown, and preserves unknown costs/reservations when usage cannot be resolved. Cleanup failure is raised rather than reported as success.

Neatlogs export/readback, a full tool/orchestration trace, optimizer logic, protected evaluation, public run endpoints, and deployment remain unimplemented.
