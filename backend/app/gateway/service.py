import asyncio
from decimal import Decimal, InvalidOperation
import re
import json
import math
import secrets
import time

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response
import httpx
from starlette.concurrency import run_in_threadpool

from ..sessions import token_hash
from .shape import request_shape, response_shape
from .models import LITELLM_MODELS


MAX_BODY_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_OUTPUT_TOKENS = 1024
CALL_LEASE_SECONDS = 120
# Request/auth/quota rejection; timeouts and server failures can have incurred a charge.
REJECTED_STATUSES = {400, 401, 402, 403, 404, 405, 406, 413, 415, 422, 429}
REJECTED_SQL = ",".join(str(status) for status in sorted(REJECTED_STATUSES))


# The model provider says the shared allowance is spent. Matched on the refusal's wording, which is never echoed.
SPENT = re.compile(rb"budget[^\"]{0,60}exceeded|exceeded[^\"]{0,60}budget|ExceededBudget|budget_exceeded|"
                   rb"insufficient[_ ](credit|quota|funds|balance)|quota[_ ]exceeded|exceeded your current quota|"
                   rb"credit balance is too low", re.IGNORECASE)
ALLOWANCE_MESSAGE = ("Hansa's shared model allowance is used up, so no model calls can run right now. Nothing is wrong with "
                     "your agent or your setup. Saved results and the recorded demo still work, and runs resume once the "
                     "allowance is topped up.")
# When the provider last refused for that reason, so jobs can say so instead of failing with a bare status.
ALLOWANCE = {"at": 0}


def allowance_spent(since=None, within=600):
    """Whether the provider reported a spent allowance since a moment, or in the last few minutes."""
    return ALLOWANCE["at"] >= since if since is not None else time.time() - ALLOWANCE["at"] < within


def error(status, message, kind="gateway_error"):
    return JSONResponse({"error": {"message": message, "type": kind}},
                        status_code=status, headers={"Cache-Control": "no-store"})


def usage_tokens(payload):
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None, None
    values = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
    return tuple(value if type(value) is int and 0 <= value <= 10**12 else None for value in values)


def usd_cost(value):
    if type(value) not in {str, int, float} or len(str(value)) > 128:
        return None
    try:
        reported = Decimal(str(value))
        if not reported.is_finite() or reported < 0:
            return None
        cost = float(reported)
    except (InvalidOperation, ValueError, OverflowError):
        return None
    return cost if math.isfinite(cost) and (cost > 0 or reported == 0) else None


def response_cost(headers):
    values = headers.get_list("x-litellm-response-cost")
    return usd_cost(values[0]) if len(values) == 1 else None


def text_content(value):
    return value is None or isinstance(value, str) or (
        isinstance(value, list) and all(isinstance(part, str) or (
            isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
        ) for part in value))


def contains_secret(value, secret):
    if isinstance(value, str):
        return secret in value
    if isinstance(value, dict):
        value = list(value.items())
    return isinstance(value, (list, tuple)) and any(contains_secret(item, secret) for item in value)


MESSAGE_FIELDS = {"role", "content", "name", "tool_calls", "tool_call_id"}
BODY_FIELDS = {"model", "messages", "stream", "max_tokens", "max_completion_tokens", "temperature", "top_p", "n", "stop", "seed",
               "presence_penalty", "frequency_penalty", "tools", "tool_choice", "parallel_tool_calls", "response_format", "user",
               "logprobs", "top_logprobs", "logit_bias", "store", "metadata"}


class GatewayService:
    def __init__(self, settings, database, inspection=None):
        self.settings = settings
        self.database = database
        self.inspection = inspection

    def mint_key(self, run_label, *, max_calls, max_spend_usd, expires_at, model_map=None, litellm_model=None):
        if litellm_model is not None and litellm_model not in LITELLM_MODELS:
            raise ValueError("Choose a supported LiteLLM model.")
        if litellm_model is not None and model_map:
            raise ValueError("Choose a fixed LiteLLM model or a model map, not both.")
        model_map = {} if model_map is None else model_map
        if (not isinstance(model_map, dict) or len(model_map) > 100
                or any(not isinstance(name, str) or not 1 <= len(name) <= 200
                       or name != name.strip() or not name.isprintable()
                       for pair in model_map.items() for name in pair)):
            raise ValueError("Model map must contain at most 100 bounded model-name pairs.")
        if (not isinstance(run_label, str) or not 1 <= len(run_label) <= 200
                or type(max_calls) is not int or not 0 <= max_calls <= 1_000_000
                or type(expires_at) is not int or expires_at <= int(time.time())
                or (max_spend_usd is not None and (type(max_spend_usd) not in {int, float}
                    or not math.isfinite(max_spend_usd) or max_spend_usd < 0))):
            raise ValueError("Invalid gateway key limits, label, or expiry.")
        raw_key = "gw_" + secrets.token_urlsafe(32)
        with self.database.connect() as db:
            db.execute("""INSERT INTO gateway_keys
                (key_hash, run_label, max_calls, max_spend_usd, expires_at, revoked, created_at, model_map, litellm_model)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)""",
                       (token_hash(raw_key), run_label, max_calls, max_spend_usd, expires_at,
                        int(time.time()), json.dumps(model_map), litellm_model))
        return raw_key

    def mint_for_import(self, user_id, import_id, run_label, *, max_calls, max_spend_usd, expires_at):
        if self.inspection is None:
            raise ValueError("Inspection service is required.")
        result = self.inspection.get(user_id, import_id)
        selected = (result["configuration"] or {}).get("litellm_model")
        if result["status"] != "confirmed" or not selected:
            raise HTTPException(409, "Save a LiteLLM model selection before minting a run key.")
        return self.mint_key(run_label, max_calls=max_calls, max_spend_usd=max_spend_usd,
                             expires_at=expires_at, litellm_model=selected)

    def summarize_key(self, raw_key):
        self.recover()
        with self.database.connect() as db:
            key = db.execute("SELECT run_label FROM gateway_keys WHERE key_hash=?", (token_hash(raw_key),)).fetchone()
            if key is None:
                raise ValueError("Unknown gateway key.")
            row = db.execute(f"""
                SELECT COUNT(*) AS calls, SUM(prompt_tokens) AS prompt_tokens,
                       SUM(completion_tokens) AS completion_tokens, SUM(latency_ms) AS latency_ms,
                       AVG(latency_ms) AS mean_latency_ms, SUM(estimated_cost_usd) AS estimated_cost_usd,
                       SUM(CASE WHEN http_status IN ({REJECTED_SQL}) THEN 0 ELSE reserved_cost_usd END) AS reserved_cost_usd,
                       COALESCE(SUM(prompt_tokens IS NULL OR completion_tokens IS NULL), 0) AS unknown_usage_calls,
                       COALESCE(SUM(estimated_cost_usd IS NULL), 0) AS unknown_cost_calls,
                       COALESCE(SUM(estimated_cost_usd IS NULL AND
                           (http_status IS NULL OR http_status NOT IN ({REJECTED_SQL}))), 0) AS unresolved_cost_calls,
                       -- An answer we received and could not price. A failed upstream attempt is not one.
                       COALESCE(SUM(estimated_cost_usd IS NULL AND http_status = 200), 0) AS unpriced_answer_calls,
                       COALESCE(SUM(http_status IS NULL), 0) AS pending_calls,
                       COALESCE(SUM(cost_source = 'legacy_price_table'), 0) AS legacy_cost_calls
                FROM model_calls WHERE key_hash=?
            """, (token_hash(raw_key),)).fetchone()
            models = db.execute("""SELECT model AS requested_model, upstream_model, COUNT(*) AS calls,
                SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens,
                SUM(estimated_cost_usd) AS estimated_cost_usd,
                SUM(estimated_cost_usd IS NULL) AS unknown_cost_calls
                FROM model_calls WHERE key_hash=? GROUP BY model, upstream_model ORDER BY model, upstream_model
            """, (token_hash(raw_key),)).fetchall()
        return {"run_label": key["run_label"], **dict(row), "models": [dict(model) for model in models]}

    def prepare(self, raw_key, body):
        with self.database.connect() as db:
            key = db.execute("SELECT * FROM gateway_keys WHERE key_hash=?", (token_hash(raw_key),)).fetchone()
        if key is None or key["revoked"] or key["expires_at"] <= int(time.time()):
            raise HTTPException(401, "Invalid or expired gateway key.")
        limited = key["max_spend_usd"] is not None
        if limited:
            # SDKs dump their own bookkeeping into requests: null `refusal`/`audio`/`function_call` on messages,
            # a framework's `sender`, tuning fields a given provider does not know. Refusing those made every
            # new agent framework fail on its first call. They are dropped here instead, before metering and
            # forwarding, so what is priced is what is sent. Anything that would change what is billed for
            # (non-text content, a legacy function call, a provider-hosted tool) is still refused, by name.
            for message in body["messages"]:
                if not isinstance(message, dict):
                    raise HTTPException(400, "Each message must be an object.")
                if message.get("function_call"):
                    raise HTTPException(400, "Legacy function_call messages are not supported; use tool_calls.")
                for field in set(message) - MESSAGE_FIELDS:
                    del message[field]
                if not text_content(message.get("content")):
                    raise HTTPException(400, "Spend-limited calls support text content only; this request has non-text message content.")
            tools = body.get("tools", [])
            if tools is None:
                body.pop("tools")
                tools = []
            hosted = sorted({str(tool.get("type") if isinstance(tool, dict) else type(tool).__name__)[:40]
                             for tool in (tools if isinstance(tools, list) else [tools])
                             if not isinstance(tool, dict) or tool.get("type") != "function"})
            if not isinstance(tools, list) or hosted:
                raise HTTPException(400, "Spend-limited calls support local function tools only; this request includes: "
                                    + (", ".join(hosted) or "a tools value that is not a list") + ".")
            for field in set(body) - BODY_FIELDS:
                del body[field]
            output = body.get("max_completion_tokens", body.get("max_tokens"))
            count = body.get("n", 1)
            if ("max_tokens" in body and "max_completion_tokens" in body
                    or (("max_tokens" in body or "max_completion_tokens" in body)
                        and (type(output) is not int or output <= 0))
                    or type(count) is not int or not 1 <= count <= 16):
                raise HTTPException(400, "Invalid output token limit or n.")
        return key["litellm_model"] or json.loads(key["model_map"]).get(body["model"], body["model"]), limited

    def recover(self, restart=False):
        with self.database.connect() as db:
            db.execute("""UPDATE model_calls SET http_status=504, lease_expires_at=NULL
                WHERE http_status IS NULL AND (? OR lease_expires_at <= ?)""",
                       (restart, int(time.time())))

    def admit(self, raw_key, body):
        self.recover()
        now = int(time.time())
        hashed = token_hash(raw_key)
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            key = db.execute("SELECT * FROM gateway_keys WHERE key_hash=?", (hashed,)).fetchone()
            if key is None or key["revoked"] or key["expires_at"] <= now:
                raise HTTPException(401, "Invalid or expired gateway key.")
            ledger = db.execute("""SELECT COUNT(*) AS calls,
                COALESCE(SUM(estimated_cost_usd), 0) AS spend
                FROM model_calls WHERE key_hash=?""", (hashed,)).fetchone()
            if ledger["calls"] >= key["max_calls"]:
                raise HTTPException(429, "Gateway call limit reached.")
            # shortcut: recorded spend is a soft threshold; admitted/unknown calls can overshoot until the call cap.
            if key["max_spend_usd"] is not None and ledger["spend"] >= key["max_spend_usd"]:
                raise HTTPException(429, "Gateway recorded spend limit reached.")
            upstream_model = key["litellm_model"] or json.loads(key["model_map"]).get(body["model"], body["model"])
            cursor = db.execute("""INSERT INTO model_calls
                (key_hash, model, upstream_model, reserved_cost_usd, lease_expires_at, created_at, started_at_ms, request_shape)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                (hashed, body["model"], upstream_model, 0, now + CALL_LEASE_SECONDS, now,
                                 int(time.time() * 1000), json.dumps(request_shape(body, self.settings.trace_content))))
            return cursor.lastrowid, upstream_model

    def finish(self, call_id, status, latency, payload, cost):
        prompt, completion = usage_tokens(payload)
        with self.database.connect() as db:
            db.execute("""UPDATE model_calls SET prompt_tokens=?, completion_tokens=?, latency_ms=?,
                http_status=?, estimated_cost_usd=?, cost_source=?, lease_expires_at=NULL, response_shape=?,
                reserved_cost_usd=CASE WHEN ? THEN 0 ELSE reserved_cost_usd END
                WHERE id=?""", (prompt, completion, latency, status, cost,
                                "litellm_response_header" if cost is not None else None,
                                json.dumps(response_shape(payload, self.settings.trace_content)),
                                cost is not None or status in REJECTED_STATUSES, call_id))

    async def forward(self, raw_key, body):
        upstream_model, limited = await run_in_threadpool(self.prepare, raw_key, body)
        if limited and "max_tokens" not in body and "max_completion_tokens" not in body:
            body = {**body, "max_tokens": DEFAULT_OUTPUT_TOKENS}
        call_id, upstream_model = await run_in_threadpool(self.admit, raw_key, body)
        body = {**body, "model": upstream_model}
        started = time.monotonic()
        status, payload, cost = 502, {}, None
        result = error(502, "Model provider request failed.")

        def provider_object(pairs):
            # Check before collapsing duplicate JSON keys, including escaped strings.
            if contains_secret(pairs, self.settings.litellm_api_key):
                raise ValueError("Unsafe provider response")
            return dict(pairs)

        try:
            async with asyncio.timeout(65):
                async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
                    async with client.stream("POST", self.settings.litellm_base_url.rstrip("/") + "/chat/completions",
                                             headers={"Authorization": "Bearer " + self.settings.litellm_api_key},
                                             json=body) as upstream:
                        status = upstream.status_code
                        cost = response_cost(upstream.headers)
                        if not 200 <= status < 300:
                            result = error(status, "Model provider rejected or failed the request.")
                            if status in {400, 401, 402, 403, 429}:
                                refusal = bytearray()
                                async for chunk in upstream.aiter_bytes():
                                    refusal.extend(chunk[:4096 - len(refusal)])
                                    if len(refusal) >= 4096:
                                        break
                                if SPENT.search(bytes(refusal)):
                                    ALLOWANCE["at"] = int(time.time())
                                    result = error(402, ALLOWANCE_MESSAGE, "allowance_exhausted")
                            retry_after = upstream.headers.get("retry-after", "")
                            if (0 < len(retry_after) <= 10 and retry_after.isascii() and retry_after.isdecimal()
                                    and not contains_secret(retry_after, self.settings.litellm_api_key)):
                                result.headers["Retry-After"] = str(int(retry_after))
                        if 200 <= status < 300:
                            content = bytearray()
                            async for chunk in upstream.aiter_bytes():
                                content.extend(chunk)
                                if len(content) > MAX_RESPONSE_BYTES:
                                    raise ValueError("Response too large")
                            decoded = json.loads(content, object_pairs_hook=provider_object)
                            if not isinstance(decoded, dict):
                                raise ValueError("Invalid provider response")
                            payload = decoded
                            result = Response(bytes(content), status_code=status, media_type="application/json",
                                              headers={"Cache-Control": "no-store"})
        except (httpx.TimeoutException, TimeoutError):
            status = 504
            result = error(504, "Model provider timed out; usage is unresolved.")
        except (httpx.HTTPError, ValueError, RecursionError):
            result = error(502, "Model provider returned an unavailable or invalid response.")
        except asyncio.CancelledError:
            status = 499
            raise
        finally:
            await asyncio.shield(run_in_threadpool(
                self.finish, call_id, status, int((time.monotonic() - started) * 1000), payload, cost))
        return result
