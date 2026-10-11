# Docker runner

The service executes one JSON task against a ready, owner-scoped Python snapshot. It never imports or executes repository Python in the API/worker process. Authenticated onboarding and [baseline jobs](BASELINE.md) dispatch work in the background. Configuration/contract confirmation still does not start a run or establish correctness.

## Prerequisites and interface

Use a trusted local Linux Docker Engine, the local `python:3.12-slim` image, and confirmed Python constraint accepting `3.12` with a LiteLLM model selection. Docker must support the default seccomp policy, cgroup memory/CPU/PID limits, and network namespace sharing. Docker access grants host-level privileges to the controller; execution containers receive no Docker socket. Run only one runner/controller process. The service serializes local builds/runs; multi-process scheduling is not implemented.

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

The entrypoint must already consume JSON from stdin and emit exactly one JSON value on stdout. Supported invocations are `python relative_file.py`, `python -m module`, and `module:function`; module functions are invoked without arguments and must implement that stdin/stdout protocol themselves. Logs belong on stderr. For interactive agents, [onboarding](AGENT.md) writes and stores an adapter; `adapter="stored"` uses it. Contract baselines freeze that stored code and pass it as `adapter_code` so replacing the adapter cannot change a running baseline.

Task JSON uses the existing data-only bounds (16 KiB, finite numbers, depth/node limits, no credential/executable fields). Runtime accepts 0.1–300 seconds, 64–4096 MiB, 0.1–4 CPUs, and 8–256 PIDs. A fresh key binds all requests to the confirmed model and enforces the supplied call/spend/expiry limits. Dollar-budget admission defaults on; `max_spend_usd=None` explicitly disables dollar admission while call/expiry enforcement remains active. Saved contract token/tool limits and semantic correctness are not enforced by this runner.

## Separate dependency build

Only validated requirement text and the trusted generated Dockerfile enter dependency preparation. Repository Dockerfiles, editable installs, URLs, pip options, private indexes and source builds are unsupported. Requirements may contain package names, ranges, extras and environment markers, read as data from `requirements.txt`, `[project].dependencies` in `pyproject.toml`, or `[options].install_requires` in `setup.cfg`. No setup code or repository build backend runs.

Without a supplied wheelhouse, a separate bounded container downloads binary wheels from public PyPI, including transitive dependencies. It has bridge networking, a clean environment with no secrets, a read-only root, CPU/memory/PID limits, and mounts only validated requirements and the wheel output directory. It receives no snapshot or gateway key. Resolution has a 300-second deadline and cleanup on failure. The controller validates at most 200 regular wheels and 500 MiB after download; this is not a hard disk quota during downloading.

Resolved distribution versions and SHA-256 hashes are saved in `runner_dependencies` against the build ID. Pip installs those exact hashed requirements offline in a separate generated Docker build with `--network none`, `--no-index`, and `--only-binary=:all:`. Supplying a reviewed wheelhouse remains supported. The snapshot source is never installed as a package; execution imports it from the read-only mount.

Build records bind the resulting immutable Docker image ID to the import SHA, configuration revision and copied source digest. A changed configuration or source requires a new build. Local dependency images remain cached for reuse; import deletion deletes build/run database records, but Docker image pruning is an operator task.

## Execution boundary

The runner checks owner/readiness/configuration under the import deletion lock, then creates a bounded independent snapshot copy. Links, special files, hard links and credential/configuration paths (`.git`, `.aws`, `.ssh`, `.env*`, `*.pem`, `*.key`) are rejected. Only that copy is mounted read-only at `/snapshot`; the original private import, database and evaluators are never mounted.

The execution container uses UID/GID `65532`, a read-only root, all capabilities dropped, `no-new-privileges`, Docker's default seccomp, memory/swap/CPU/PID limits, a file-descriptor cap, and disabled core dumps. `/scratch` is a 64 MiB tmpfs with `noexec,nosuid,nodev`; it is destroyed with the container. The agent receives an explicit clean environment: fixed system/Python paths, scratch HOME/TMPDIR, `OPENAI_BASE_URL` and the throwaway `OPENAI_API_KEY`. No host environment is inherited.

A trusted relay container uses `--network none`, leaving only loopback. The agent shares that network namespace, and calls `http://127.0.0.1:8000/gateway/v1`. The relay forwards only `POST /gateway/v1/chat/completions`, with bounded bodies, to a private gateway Unix socket. The socket is mounted only into the relay. Neither container gets an external interface, route, public port, Docker socket, or host network access. The relay cannot execute imported code and uses the trusted base image, independent of the agent dependency image.

The controller drains stdout/stderr concurrently. At the hard deadline or 1 MiB combined output limit it kills the entire execution container while continuing to drain its pipes. It records Docker's exit code (137 for SIGKILL), the parsed stdout JSON, the last 16 KiB of stderr, wall time, output byte count, and a stop reason: `completed`, `exit_nonzero`, `timeout`, `output_limit`, `oom`, `invalid_json`, or `infrastructure_error`. Wall time includes execution-container start/attach and termination, and excludes dependency build and relay setup. Infrastructure errors may have no exit code or output.

The key is revoked and both containers removed before a result is marked `cleanup_complete`. Scoped keys/server keys echoed in output are redacted. Results and gateway summaries are stored in private SQLite, accessible through owner-scoped service reads; deleting the import deletes the run content. Other private data returned by an agent is still private run content and must not be published automatically.

## Filtered internet access

`runner.run(..., internet=True)` lets an agent's tools reach the public web. It is off by default for direct runner calls; baselines follow `RUNNER_INTERNET` (default `true`).

The execution container still has no external route. Each run gets its own internal Docker network created with `gateway_mode_ipv4=isolated`, so there is no host gateway address on it. A trusted sidecar running [`backend/app/runner/egress.py`](backend/app/runner/egress.py) is the only container also attached to the public bridge. The agent receives `HTTP_PROXY`/`HTTPS_PROXY` pointing at the sidecar and `NO_PROXY` for the loopback gateway.

The sidecar accepts `CONNECT host:443`, `CONNECT host:80` and absolute `http://` requests on port 80. It resolves every destination itself (IPv4), refuses the request unless all resolved addresses are public, and connects to the address it checked. Private, loopback, link-local (including the cloud metadata address), carrier-grade NAT, multicast and reserved ranges are refused with `403`. Plain HTTP is one request per connection so each destination is re-checked.

Each run result gains `egress`: one record per connection (host, port, method, allowed or refused with the reason, duration, bytes each way) and a per-host summary. Paths, query strings, headers and bodies are never logged. `isolation.internet` is `filtered_proxy` or `none`.

Limits of this design, stated plainly:

- Only clients that honour proxy environment variables reach the web: `requests`, `httpx`, `urllib` and the OpenAI SDK do; `aiohttp` (unless `trust_env=True`) and raw sockets do not.
- Only ports 80 and 443. No UDP, no IPv6, no direct DNS from the agent.
- HTTPS content is tunnelled, not inspected; the log shows where an agent connected, not what it sent.
- An agent with internet access can send its own source, task input and the short-lived scoped gateway key anywhere public. The key is revoked when the run ends and is bounded by its call and spend limits. Host credentials, the server LiteLLM key and other imports are not in the container.
- Results now vary between runs when tools read live data. Compare repeated runs, not single ones.

Verified on October 11 with real containers: `https://example.com` and `http://example.com` returned `200` through the sidecar; the metadata address, `10.0.0.1`, the Docker host bridge and port 8081 returned `403`; a direct connection to `1.1.1.1:443` failed; no sidecar, relay, run container or network remained afterwards. A live `claude-haiku` call through the gateway succeeded with internet enabled.

## Reproduce the live proof

Configure the server-only LiteLLM settings in `.env` first:

```sh
uv run python -m scripts.probe_gateway
uv run python -m scripts.prove_runner
uv run python -m scripts.prove_runner --internet
RUNNER_DOCKER_TEST=1 uv run pytest backend/tests/test_runner.py -q
uv run pytest -q
```

The proof script registers `examples/one_call` as a clearly labelled **local fixture**, not a real GitHub import. It uses the normal owner-scoped ready-import, inspection, configuration, build, execution and result persistence paths. It makes one real model call, checks isolation, then runs an injected timeout with a child process. Private evidence is saved in ignored `var/runner-proof.json`.

## Prior local proof

On October 10, the labelled `examples/one_call` fixture verified real Docker → gateway → LiteLLM Haiku execution and timeout/child cleanup. At that time `/cost/estimate` returned 401, so the diagnostic explicitly disabled dollar admission. The current gateway no longer depends on that endpoint. Prior fixture evidence does not establish imported-agent compatibility or optimization gains. See [BASELINE.md](BASELINE.md) for the airline baseline workflow.

## Remaining boundaries

Docker shares the host kernel; this is a local reviewed-workflow runner, not a hardened arbitrary-code hosting platform. Hard termination depends on the controller and Docker daemon remaining available; controller-crash recovery and an independent watchdog are not implemented. A terminated container does not cancel an already-dispatched remote model request: the gateway drains in-flight requests (up to roughly 70 seconds) before completing teardown, and preserves unknown costs/reservations when usage cannot be resolved. Cleanup failure is raised rather than reported as success.

Neatlogs export and owner-scoped readback are implemented; see [TRACING.md](TRACING.md) for measured model calls, outside connections and inferred gaps. Full local-tool instrumentation, optimizer logic, protected evaluation, public execution and deployment remain unimplemented.
