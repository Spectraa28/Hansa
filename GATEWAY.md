# Model gateway

Status: implemented non-streaming Chat Completions proxy with mocked-upstream regression coverage. On October 10, a real `claude-haiku` diagnostic and the [Docker sample runner](RUNNER.md) returned HTTP 200; each recorded 11 input tokens, 5 output tokens, and $0.0000396 from the LiteLLM cost header. The configured key returned 401 for `/cost/estimate`; spend-limited calls still fail closed, now with an actionable permission error. The diagnostic explicitly used a one-call key with dollar admission disabled. Other model aliases, imported frameworks and live billing reconciliation remain unverified. No source is executed or dependencies installed by this module.

## Configuration and API

Set `LITELLM_BASE_URL` to the server's OpenAI-compatible API root (include `/v1` if required), and `LITELLM_API_KEY` to the real server-only key. The gateway appends `/chat/completions`. HTTPS is required except on localhost. Do not put credentials in the URL. If either setting is empty, the app starts and the gateway returns `503`.

`POST /gateway/v1/chat/completions` requires `Authorization: Bearer <throwaway-key>`. It does not use application cookies or CSRF. Future approved containers should receive `OPENAI_BASE_URL=http://<reachable-backend>:8000/gateway/v1` and `OPENAI_API_KEY=<throwaway-key>`. Container networking and enforcement remain unimplemented; this proxy alone cannot prevent direct provider calls.

Non-streaming successful JSON response bytes pass through unchanged, except a response containing the real key is blocked. Client cookies and credentials are never forwarded. Provider error responses retain their HTTP status (including `429` and `503`) with a clean gateway error body. A validated numeric `Retry-After` header is preserved; arbitrary upstream headers, HTTP-date retry values, and redirect locations are dropped. Transport/invalid-response failures return `502`; timeouts return `504`. Provider error bodies and exception text are discarded. The ledger records the upstream HTTP status (or synthetic `502` for connection failures and `504` for timeouts). It never stores prompts or response content. The real key is excluded from settings repr, HTTP diagnostic logs, errors and responses. Do not enable HTTP wire logging or export request headers to tracing.

Requests are capped at 1 MiB, decoded model responses at 8 MiB, and model dispatch at 65 seconds total with a 60-second HTTP timeout. Spend-limited calls also have a nonbillable, 10-second cost-quote phase capped at 64 KiB. Recorded call latency measures dispatch/finalization; it excludes the quote phase. Redirects and environment HTTP proxies are disabled. `stream=true` returns a clear `400` before dispatch. Streaming/final-chunk usage metering is deferred; use `stream=false`. Responses, embeddings, files and other OpenAI endpoints are unsupported.

## Saved LiteLLM model selection

In `/setup`, retrieve or inspect an import, then choose **LiteLLM model** under **Model for this agent** and save the configuration. The seven choices are `nova-micro`, `nova-lite`, `nova-pro`, `nova-2-lite`, `claude-haiku`, `claude-sonnet-4.6`, and `claude-opus-4.6`, supplied by the user for this hackathon. This is a fixed catalog, not a live provider availability check. No model is selected implicitly.

The saved `litellm_model` is separate from the source's `model_provider` and `model_id`. Changing it creates a configuration revision and makes earlier task contracts stale. Old configurations can still be read/saved without a selection, but cannot mint a selected-model run key. Saving never starts execution.

The application service `app.state.gateway.mint_for_import(user_id, import_id, run_label, max_calls=..., max_spend_usd=..., expires_at=...)` reads the owner-scoped, ready import's confirmed selection and mints a key bound to it. There is no browser mint or run endpoint. Reinspection clears confirmation and prevents minting until the user saves again. Existing keys retain their original model when configuration changes; the future runner must mint a fresh key for each approved run and handle revocation.

For standalone service use, `mint_key(..., litellm_model="nova-lite")` chooses the same fixed routing policy. Every requested model name is replaced by the chosen alias for both quotes and dispatch, with requested and upstream names recorded separately. A fixed model and a nonempty `model_map` cannot be supplied together. Existing keys without a fixed model keep their map/pass-through behavior. Startup adds the nullable key column without changing earlier keys. This gateway supports OpenAI-compatible Chat Completions clients; selecting a model does not adapt native Anthropic/Google SDK calls.

**Own API key mode is deferred to the next step.** Its credentials must be encrypted server-side using the existing GitHub-token pattern, remain outside containers, and select a provider ID from a fixed server-owned list of OpenAI-compatible providers/URLs. No credential input, arbitrary URL, storage, or dispatch path for this mode exists yet.

## Keys and accounting

`GatewayService(settings, database).mint_key(run_label, max_calls=..., max_spend_usd=..., expires_at=..., model_map=None, litellm_model=None)` returns a random raw key once. SQLite stores only its SHA-256 hash. Expiry is a UTC Unix timestamp; `max_calls` is a nonnegative integer. `max_spend_usd=None` explicitly disables spend admission, while call/expiry limits still apply. There are no public mint, summary or administration endpoints. Revocation is an administrator update of `gateway_keys.revoked=1` against the key hash; already dispatched work is not cancelled.

`summarize_key(raw_key)` returns call count, reported prompt/completion token sums, total/mean latency in milliseconds, known reported cost, outstanding reservations, pending calls, unknown-usage calls, unknown-cost calls, unresolved-cost calls whose estimates still consume budget, legacy-price-table call count, and a `models` breakdown grouped by `requested_model` / `upstream_model` with calls, token sums, known cost and unknown-cost counts. Sums include available values only and remain `NULL` when no values are known; check unknown counts before treating them as totals. Token usage is accepted only as nonnegative integers. Missing/invalid token fields stay `NULL` and do not prevent a separately reported cost from being recorded.

## Per-key model mapping

Pass an optional `model_map` when minting a key. It is saved with that key and applies only to its calls. For example:

```python
key = service.mint_key(
    "imported-agent", max_calls=20, max_spend_usd=0.50,
    expires_at=int(time.time()) + 3600,
    model_map={"gpt-4o": "nova-pro", "gpt-4o-mini": "nova-micro"},
)
```

Maps support at most 100 exact, case-sensitive name pairs; each name must be a printable, nonempty string of at most 200 characters with no surrounding whitespace. Empty/omitted maps preserve pass-through behavior. Unmapped names pass through unchanged and are subject to LiteLLM availability. Resolution is one hop: mappings do not chain. Set the map when minting; there is no public map-management endpoint or request-body override.

Only the outgoing request's `model` changes. Messages, tools, supplied generation settings and successful response bytes remain unchanged (spend-limited requests without an output allowance receive the documented default below); the response's provider model is not rewritten to pretend the original model ran. In `model_calls`, the existing `model` column retains the requested name and `upstream_model` records the LiteLLM alias selected for dispatch. Both names are saved before dispatch, including failed or pending attempts. The summary's `models` list exposes both names so a report can disclose the substitution and its measured expense. The LiteLLM alias is not proof of the physical provider model selected by any upstream fallback. Model compatibility and behavior preservation require separate evaluation.

Startup migration gives existing keys an empty map and fills older calls' `upstream_model` from `model`, since the earlier gateway always passed names through. Existing limits, cost provenance and call history are preserved. Restart the API to apply the migration.

## LiteLLM cost headers

Cost comes only from `x-litellm-response-cost` on the configured upstream response. [LiteLLM documents this header](https://docs.litellm.ai/docs/proxy/response_headers) as the call's USD cost, including input/output and other applicable components. It is LiteLLM's reported estimate, not an independently reconciled invoice. There is no local price table and no token-times-price fallback. Do not use `x-litellm-key-spend`: it is the upstream key's cumulative spend and can include unrelated calls. Client-supplied cost headers are neither forwarded nor trusted.

The user's available route aliases are `nova-micro`, `nova-lite`, `nova-pro`, `nova-2-lite`, `claude-haiku`, `claude-sonnet-4.6`, and `claude-opus-4.6`. The gateway applies the key's explicit model map and forwards the resulting alias; LiteLLM owns routing and pricing. A different provider model in the response does not invalidate the cost header. Live availability and cost-header emission were verified for `claude-haiku`; the other aliases remain user-reported and unverified live.

Exactly one finite, nonnegative numeric cost header is required. Missing, malformed, duplicate, negative or nonfinite values store `NULL`, never a guessed zero. A reported zero is accepted, even if token usage is missing. A valid header is recorded on provider errors and invalid/blocked response bodies too, since the attempted call can incur cost. Token usage remains independent. Arbitrary upstream headers, including key-wide spend, are not exposed to agents.

The existing `estimated_cost_usd` column stores this amount to preserve the ledger/summary interface; `cost_source='litellm_response_header'` identifies new known costs. Existing databases gain the source column on startup; historical known estimates are preserved as `legacy_price_table`, not relabelled as upstream reports. `legacy_cost_calls` flags mixed summaries. Restart the API to apply this migration.

## Admission and spend limits

Admission uses a short SQLite `BEGIN IMMEDIATE` transaction to recheck expiry, revocation, count and spend and insert a per-call reservation before model dispatch. Parallel calls on the same key are allowed whenever call slots and unreserved budget remain. Pending attempts count toward both limits; two simultaneous requests cannot claim the same remaining balance. Rejected admissions do not consume a call. Every admitted attempt, including failures and retries, consumes one call; the gateway never automatically replays a model request.

### Request-sized reservations

For spend-limited keys, the gateway requests a quote from [LiteLLM's `/cost/estimate` API](https://docs.litellm.ai/docs/proxy/pricing_calculator), sending only the mapped model alias and estimated input/output token counts, never prompts or source. The endpoint is the configured API root with a final `/v1` removed, followed by `/cost/estimate`; any earlier path prefix is preserved. There is no local price table. **Your LiteLLM key must have access to this endpoint.** Missing access, timeouts or invalid quotes return a clean `503` without dispatching a model call or consuming a call slot. The current hackathon key returns 401 for this endpoint; request permission from the LiteLLM administrator. No automatic budget bypass was added.

Input sizing uses UTF-8 bytes of compact JSON for messages, function tools and response-format schemas, plus 32 tokens per message and 128 for framing. This deliberately errs above ordinary text tokenization without reserving an entire 128k context. Output sizing uses `max_completion_tokens` or `max_tokens`, multiplied by `n`. If neither is supplied, spend-limited requests receive and forward a **1,024-token `max_tokens` default** so the quoted allowance is actually bounded. Explicit allowances are preserved; `n` is limited to 1–16. A valid quoted zero is accepted. Missing or invalid estimates are never replaced by a guessed free call.

The quote becomes `reserved_cost_usd` for that attempt. Admission checks the sum of known costs plus all outstanding/retained estimates plus the new quote against `max_spend_usd`. A valid response cost header replaces its reservation with reported cost. Missing/invalid cost headers, timeouts, disconnects and ambiguous failures retain the per-request estimate and `NULL` actual cost, but do not block every later call. Further calls can use the remaining budget; enough unresolved estimates can still exhaust it. Provider request/auth/quota rejections (`400`, `401`, `402`, `403`, `404`, `405`, `406`, `413`, `415`, `422`, `429`) release their holds; valid costs on those responses still count. Unknown costs and token usage remain explicitly unknown, never fabricated zero.

**These are estimated reservations, not an independently validated invoice ceiling.** Provider tokenization, cache billing, price changes, routing/fallbacks and retries can make actual expense exceed a quote. Concurrent dispatched calls can collectively exceed the budget if their quotes underestimate expense. Validate sponsor quoting/routing and enforce an upstream budget before treating this as a hard cash cap.

### Cancellation and recovery

Finalization runs in a cancellation-shielded `finally` block. A cancelled request is recorded as internal `499`, with any known cost or the retained estimate; dropped upstream connections return `502`. Calls have a 120-second persisted lease, longer than the 65-second dispatch deadline. Admission and usage summaries recover expired pending rows to internal `504`, retain their estimates and keep actual cost unknown. On startup, the single API process settles all prior pending rows the same way. No abandoned call is blindly retried or refunded. Late known completion can reconcile the existing row without counting a new call.

Restart the API to migrate the lease column. Recovery supports the repository's single-API-process deployment; starting another API process against a live instance's database can classify its calls as interrupted. Historical unknown calls with older full-balance holds still require billing review if those holds consume the whole budget; their request inputs were never persisted, so a request-sized quote cannot be reconstructed honestly. Historical holds on definitive rejection statuses remain ignored by admission and effective-reservation summaries.

### Supported content

Spend-limited calls accept string content, `None` for assistant tool-call messages, and arrays of strings or `{"type": "text", "text": "..."}` parts, including LangChain text-part messages. Accepted parts and local function tools are forwarded unchanged; no tools are executed by the gateway. Malformed text parts, images, audio and provider-hosted tools remain unsupported for spend-limited calls. The upstream validates model-specific output/context limits.

Job-wide sharing across optimizer/target keys, model permission scopes, tool accounting, strict pre-dispatch reservations and automated billing reconciliation belong to the later execution controller.

## One real call

After configuring the server-only LiteLLM settings and starting the API per [README.md](README.md), run this from the repository root in your own terminal. The command reads server configuration locally, captures the one-time throwaway key without printing it, and mints a one-call key expiring in ten minutes. It uses the same configured database as the API. Never put the real LiteLLM key in curl. This example maps the agent's `gpt-4o` request to the user-reported `nova-micro` route; this is an instruction, not a verified live call.

```sh
GATEWAY_KEY="$(uv run python - <<'PY'
import time
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.gateway.service import GatewayService
settings = Settings.from_env()
database = Database(settings.database_path)
database.initialize()
print(GatewayService(settings, database).mint_key(
    "manual-smoke", max_calls=1, max_spend_usd=0.05,
    expires_at=int(time.time()) + 600,
    model_map={"gpt-4o": "nova-micro"}))
PY
)"
curl --fail-with-body http://127.0.0.1:8000/gateway/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":16,"stream":false}'
unset GATEWAY_KEY
```

## Verification boundaries

`uv run pytest`: 187 passed, 2 HTTP-client deprecation warnings, in 38.29 seconds on October 10, 2026 (outside the sandbox). `git diff --check` passed.

Synthetic browser checks at 1280px and 390px verified the seven-choice picker, explicit selection, routing preview, save/reload and retained source model metadata. Backend tests cover invalid alias rejection, owner/CSRF boundaries, immutable key selection, reinspection invalidation, and contract staleness.

`backend/tests/test_gateway.py` uses `httpx.MockTransport`; it covers response preservation, hashed storage, credential isolation, invalid/expired/revoked keys, atomic concurrency, call/spend admission, missing/invalid/zero cost headers, independent missing usage, all seven supplied model aliases, ledger/lease migration, per-key model substitution/isolation and dual-name summaries, provider status/Retry-After propagation, retryable rejection accounting, parallel dispatch and atomic reservations, request-sized Sonnet-like quotes, content parts, disconnect/cancellation/restart recovery, timeout, body cap, unsupported streaming, and disabled configuration. It does not establish live billing accuracy, imported-agent compatibility, container isolation or deployment readiness.
