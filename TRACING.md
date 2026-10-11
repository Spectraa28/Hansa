# Neatlogs tracing

Status: every sandboxed run and every agent job can be submitted to Neatlogs, with owner-scoped readback. Acceptance is recorded as `queued`, not proof of readable spans. Some earlier fixture traces were finalized and readable; newer baseline traces returned not_found or processing after acceptance. Investigation therefore uses database evidence and records the unavailable second view explicitly. Patching and comparison are not built.

## What is logged

| Trace | Workflow name | Contents |
| --- | --- | --- |
| A target run | `hansa-run`, `hansa-smoke`, `hansa-baseline` | One LLM span per gateway model call, one tool span per outside HTTP(S) connection, and an inferred gap span between model calls |
| An agent job | `hansa-onboarding`, `hansa-investigation` | One LLM span per model call the agent made and one tool span per tool it used, in order |

Nothing runs inside the imported agent to produce these. Model calls come from the gateway ledger, and connections from the egress sidecar, so the target's code is not instrumented or changed.

Each LLM span carries the served model, the model the agent asked for, prompt and completion tokens, latency, HTTP status, and:

- `hansa.prompt_chars`, `hansa.messages`, `hansa.tool_schema_chars`: the size of what was sent.
- `hansa.repeated_messages`, `hansa.repeated_chars`: how much of the request's opening messages were already sent in the previous call. This is the measurement behind "the whole history is re-sent every turn".
- `hansa.cost_usd`, `hansa.cost_source`: the LiteLLM-reported cost, or `unknown`.

Coverage is stated in each trace's metadata. Time between model calls is the agent's own code and tools; it is recorded as `agent code and tools (inferred gap)` with `hansa.inferred: true`, never as a measured tool call. A proxied connection is measured, but only its host, port, duration and byte count are known.

## Cost

Neatlogs reports `total_cost: 0` for these traces because it does not price the LiteLLM aliases (`claude-haiku` and the others). The cost in our database, taken from LiteLLM's response header, is the figure to use. It is copied into each trace as `hansa.cost_usd` and `hansa_cost_usd`. A run with any call of unknown cost reports its cost as unknown, not a partial sum.

## What leaves the server

The gateway records the shape of every model call: message count, characters per role, a 12-character hash per message, tool-schema size and timing. It does not store conversations.

When `TRACE_CONTENT=true` (the default) it also stores, and exports to Neatlogs, a 500-character preview of the last message of each request and of each response, plus the task input and final output (2,000 characters each). Credential-shaped strings are masked first. This is pattern matching and will miss secrets in unusual formats. Set `TRACE_CONTENT=false` to export sizes, tokens, timings and costs only.

The Neatlogs ingest endpoint refuses some payloads with `403` based on their text; a file path such as `../../etc/passwd` in a tool argument is enough. When that happens the trace is resent with tool inputs and outputs removed, and if refused again with all free text removed. The trace's `content` is then `partial` or `withheld`. Measurements are never dropped. In the live runs, target-run traces exported in full and the agent-job trace was always `withheld`; which text triggers the refusal there was not isolated.

A tracing failure never fails or changes a run. The run result records `trace: {"status": "failed", "reason": ...}`.

Successful submission records `trace.status: queued` and a trace ID. The `traces` database table stores current `status`, `checked_at`, `confirmed_at`, and `last_error` separately. A matching readback with `verification_ready: true` or `finalization_status: finalized` changes it to `confirmed`. Processing/pending, not_found, unreadable responses and mismatched IDs never establish confirmation. An already-confirmed trace retains its historical confirmation if a later read fails; the latest error and check time are also recorded. Existing accepted trace rows migrate to queued until rechecked.

Run/baseline/job JSON retains its submission-time trace status; `GET /traces` and recheck return the current state. Confirmation means finalized readback succeeded, not that Neatlogs' counts/costs match our ledger or every field is exported.

## Reading traces back

All of an account's imports share one Neatlogs project, and the project key can read and change all of it. The key stays in the server, the client only permits `log_trace`, `search_traces`, `get_trace_context`, `list_detections`, `ping` and `whoami`, and readback goes through our own record of which trace IDs were logged for which import.

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | `/github/imports/{id}/traces` | Traces logged for this import, newest first, with our summary: kind, stop reason, calls, tokens, cost, outside calls, repeated characters |
| GET | `/github/imports/{id}/traces/{trace_id}` | The span tree from Neatlogs. `404` unless we logged that trace for this import |
| GET | `/github/imports/{id}/traces/search?q=` | Neatlogs keyword search, filtered to this import's trace IDs. A match outside the first 100 project-wide results is not returned |
| POST | `/github/imports/{id}/traces/{trace_id}/recheck` | Retry readback once, update queued/confirmed state and last error, return the context or explicit unavailability; never re-export or execute a model call |

All require the owner's session. Import deletion removes our trace records; it does not delete the traces in Neatlogs, because the MCP tools offer no delete.

Recheck also requires the existing CSRF token and rate limiter. Ordinary GET readback and investigation's `read_trace` update the same state. A remote read error still returns `502` at the ordinary GET endpoint; recheck returns the queued/error record so callers can retry later without treating it as a missing owner/import. No periodic background rechecks are scheduled.

## Configuration

`NEATLOGS_API_KEY` is the project key from Settings → API keys (not the `nlw_` ingest key). Without it tracing is off and everything else works. `NEATLOGS_MCP_URL` defaults to `https://ingest.neatlogs.com/mcp`.

## Known limits of the Neatlogs endpoint, observed October 11

- `search_traces` with `fields`, and `get_trace_context` with `max_chars_per_field`, return `not_enabled`. Both are called without those arguments.
- A top-level `token_usage` on `log_trace` creates an extra LLM span that double-counts tokens. It is not sent; per-call spans carry the tokens.
- `log_trace` returns a trace ID and no dashboard URL, so none is stored.
- An earlier logged trace was readable and finalized within about six seconds. That timing is not guaranteed: all six later baseline IDs were accepted, but readback was not finalized during the baseline proof.

## Verification

`RUNNER_DOCKER_TEST=1 uv run pytest -q` passed **239 tests**. The ten tracing tests use a fake client or a mock HTTP transport and never contact Neatlogs: call shapes, redaction, trace construction, cost provenance, the stepped content fallback, owner-scoped readback, deletion, and client session handling.

Live, with `AGENT_MODEL=claude-haiku uv run python -m scripts.prove_onboarding`: smoke, run and onboarding traces were logged, read back as `finalized`, and Neatlogs' token and call counts matched our ledger. A run that fetched two live pages showed three model calls with repeated context growing from 0 to 197 to 2,108 characters, two egress spans under the calls that requested them, and two inferred gaps. Search returned only this import's traces, and a trace ID logged outside the application returned `404`.

The Neatlogs project also contains about ten small probe and spike traces from this verification (`hansa-probe`, and an early `hansa-run` with doubled token counts). They are labelled as fixtures or probes and cannot be deleted through the MCP tools.

The later full Docker-enabled suite passed **264 tests**. Added trace tests verify acceptance as queued, not_found/processing remaining queued, finalized readback becoming confirmed, owner/CSRF protection on recheck, mismatched IDs never confirming, and historical confirmation retaining a later read error. A live investigation rechecked two accepted baseline traces: one returned `conflict`, the other `not_found`; both stayed queued with their last error saved. Its own export returned HTTP 403 after the content fallbacks and is reported as failed. The investigation still completed using database numbers and saved source evidence. No successful confirmation is claimed for these later traces.
