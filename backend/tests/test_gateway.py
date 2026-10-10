import json
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from backend.app.config import Settings
from backend.app.gateway.service import MAX_BODY_BYTES, DEFAULT_OUTPUT_TOKENS
from backend.app.main import create_app
from backend.app.sessions import token_hash


REAL_KEY = "server-secret-never-expose"
BODY = {"model": "nova-micro", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10}


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / "auth.sqlite3", secret_key="test-secret-" * 4,
                        litellm_base_url="https://provider.test/v1", litellm_api_key=REAL_KEY)
    state = {"requests": [], "quotes": [], "status": 200, "cost": "0.000123", "body": {"model": "provider-specific-model", "choices": [],
             "usage": {"prompt_tokens": 100, "completion_tokens": 10}}}

    async def respond(request):
        assert request.headers["authorization"] == "Bearer " + REAL_KEY
        assert "cookie" not in request.headers
        assert request.url == "https://provider.test/v1/chat/completions"
        state["requests"].append(request)
        if state.get("started") is not None:
            state["started"].set()
            await state["release"].wait()
        if state.get("parallel"):
            state["active"] = state.get("active", 0) + 1
            state["max_active"] = max(state.get("max_active", 0), state["active"])
            await asyncio.sleep(0.05)
            state["active"] -= 1
        if state.get("disconnect"):
            raise httpx.RemoteProtocolError(REAL_KEY)
        if state.get("timeout"):
            raise httpx.ReadTimeout(REAL_KEY, request=request)
        if "raw" in state:
            return httpx.Response(200, content=state["raw"])
        headers = [("x-secret", REAL_KEY)]
        if "retry_after" in state:
            headers.append(("retry-after", state["retry_after"]))
        if state["cost"] is not None:
            values = state["cost"] if isinstance(state["cost"], list) else [state["cost"]]
            headers.extend(("x-litellm-response-cost", value) for value in values)
        return httpx.Response(state["status"], json=state["body"], headers=headers)

    original = httpx.AsyncClient

    def mocked_client(**kwargs):
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr("backend.app.gateway.service.httpx.AsyncClient", mocked_client)
    with TestClient(create_app(settings)) as client:
        service = client.app.app.state.gateway
        key = service.mint_key("test-run", max_calls=5, max_spend_usd=1, expires_at=int(time.time()) + 3600)
        yield client, service, key, state


def call(client, key, body=None):
    return client.post("/gateway/v1/chat/completions", json=BODY if body is None else body,
                       headers={"Authorization": "Bearer " + key})


def test_spend_limited_call_never_requests_quote(gateway):
    client, service, key, state = gateway
    assert call(client, key).status_code == 200
    assert len(state["requests"]) == 1 and not state["quotes"]


def rows(service):
    with service.database.connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM model_calls")]


def test_valid_call_recorded(gateway):
    client, service, key, state = gateway
    response = call(client, key)
    assert response.status_code == 200
    assert response.content == httpx.Response(200, json=state["body"]).content
    assert json.loads(state["requests"][0].content) == BODY
    row = rows(service)[0]
    assert row["prompt_tokens"] == 100 and row["completion_tokens"] == 10
    assert row["model"] == BODY["model"] and row["upstream_model"] == BODY["model"]
    assert row["estimated_cost_usd"] == pytest.approx(0.000123)
    assert row["cost_source"] == "litellm_response_header"
    assert row["http_status"] == 200 and row["latency_ms"] >= 0
    assert row["reserved_cost_usd"] == 0
    summary = service.summarize_key(key)
    assert summary["calls"] == 1 and summary["unknown_usage_calls"] == 0
    assert summary["estimated_cost_usd"] == row["estimated_cost_usd"]
    with service.database.connect() as db:
        saved = dict(db.execute("SELECT * FROM gateway_keys").fetchone())
    assert saved["key_hash"] == token_hash(key) and key not in str(saved)
    assert REAL_KEY not in response.text and REAL_KEY not in str(response.headers)


@pytest.mark.parametrize("kind", ["unknown", "expired", "revoked", "missing"])
def test_invalid_keys(gateway, kind):
    client, service, key, state = gateway
    if kind in {"expired", "revoked"}:
        with service.database.connect() as db:
            column, value = ("expires_at", 0) if kind == "expired" else ("revoked", 1)
            db.execute(f"UPDATE gateway_keys SET {column}=?", (value,))
    response = client.post("/gateway/v1/chat/completions", json=BODY) if kind == "missing" else call(
        client, "unknown-key" if kind == "unknown" else key)
    assert response.status_code == 401
    assert not state["requests"] and not rows(service)


def test_call_limit(gateway):
    client, service, key, state = gateway
    with service.database.connect() as db:
        db.execute("UPDATE gateway_keys SET max_calls=1")
    assert call(client, key).status_code == 200
    assert call(client, key).status_code == 429
    assert len(state["requests"]) == 1


def test_spend_limit(gateway):
    client, service, key, state = gateway
    with service.database.connect() as db:
        db.execute("UPDATE gateway_keys SET max_spend_usd=0.000123")
    assert call(client, key).status_code == 200
    assert call(client, key).status_code == 429
    assert len(state["requests"]) == 1


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 405, 406, 413, 415, 422, 429, 408, 500, 503, 302])
def test_upstream_error_recorded(gateway, status):
    client, service, key, state = gateway
    state.update(status=status, cost=None, body={"error": REAL_KEY})
    response = call(client, key)
    assert response.status_code == status and REAL_KEY not in response.text
    assert rows(service)[0]["http_status"] == status
    assert rows(service)[0]["estimated_cost_usd"] is None
    if status in {400, 401, 402, 403, 404, 405, 406, 413, 415, 422, 429}:
        assert rows(service)[0]["reserved_cost_usd"] == 0
        assert service.summarize_key(key)["unknown_cost_calls"] == 1
        assert service.summarize_key(key)["unresolved_cost_calls"] == 0
        state.update(status=200, cost="0.000123", body={"choices": []})
        assert call(client, key).status_code == 200
        assert len(state["requests"]) == 2
    else:
        assert service.summarize_key(key)["unresolved_cost_calls"] == 1
        state.update(status=200, cost="0.000123", body={"choices": []})
        assert call(client, key).status_code == 200
        assert len(state["requests"]) == 2


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": 100}, {"prompt_tokens": True, "completion_tokens": -1}])
def test_missing_usage_null(gateway, usage):
    client, service, key, state = gateway
    state["body"]["usage"] = usage
    assert call(client, key).status_code == 200
    row = rows(service)[0]
    assert row["estimated_cost_usd"] == pytest.approx(0.000123) and row["reserved_cost_usd"] == 0
    assert service.summarize_key(key)["unknown_usage_calls"] == 1
    assert service.summarize_key(key)["unknown_cost_calls"] == 0
    assert call(client, key).status_code == 200


@pytest.mark.parametrize("model", ["nova-micro", "nova-lite", "nova-pro", "nova-2-lite", "claude-haiku",
                                   "claude-sonnet-4.6", "claude-opus-4.6"])
def test_model_alias_cost_from_header(gateway, model):
    client, service, key, state = gateway
    assert call(client, key, {**BODY, "model": model}).status_code == 200
    assert rows(service)[0]["model"] == model
    assert rows(service)[0]["estimated_cost_usd"] == pytest.approx(0.000123)


def test_timeout_recorded(gateway, caplog):
    client, service, key, state = gateway
    state["timeout"] = True
    response = call(client, key)
    assert response.status_code == 504 and REAL_KEY not in response.text
    assert rows(service)[0]["http_status"] == 504
    assert rows(service)[0]["reserved_cost_usd"] == 0
    assert service.summarize_key(key)["unresolved_cost_calls"] == 1
    state["timeout"] = False
    assert call(client, key).status_code == 200
    assert REAL_KEY not in caplog.text


def test_provider_secret_in_success_is_blocked(gateway):
    client, service, key, state = gateway
    state["body"]["choices"] = [{"message": {"content": REAL_KEY}}]
    response = call(client, key)
    assert response.status_code == 502 and REAL_KEY not in response.text
    assert rows(service)[0]["estimated_cost_usd"] == pytest.approx(0.000123)


def test_streaming_and_oversize_rejected(gateway):
    client, service, key, state = gateway
    response = call(client, key, {**BODY, "stream": True})
    assert response.status_code == 400 and "Streaming" in response.text
    response = client.post("/gateway/v1/chat/completions", content=b"x" * (MAX_BODY_BYTES + 1),
                           headers={"Authorization": "Bearer " + key})
    assert response.status_code == 413
    assert not state["requests"] and not rows(service)


def test_disabled_gateway_starts(tmp_path):
    settings = Settings(database_path=tmp_path / "auth.sqlite3", secret_key="test-secret-" * 4)
    with TestClient(create_app(settings)) as client:
        assert call(client, "anything").status_code == 503


def test_atomic_admission(gateway):
    client, service, key, state = gateway

    def admit():
        try:
            return service.admit(key, BODY)
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: admit(), range(2)))
    assert all(isinstance(result, tuple) for result in results) and len(rows(service)) == 2
    assert service.summarize_key(key)["pending_calls"] == 2
    assert service.summarize_key(key)["reserved_cost_usd"] == 0


@pytest.mark.parametrize("changes", [{"max_tokens": -1}, {"max_tokens": None}, {"n": 0}, {"tools": [{"type": "web_search"}]},
                                    {"max_completion_tokens": 20},
                                    {"messages": [{"role": "user", "content": [{"type": "image_url"}]}]}])
def test_unbounded_spend_request_rejected(gateway, changes):
    client, service, key, state = gateway
    assert call(client, key, {**BODY, **changes}).status_code == 400
    assert not state["requests"]


def test_local_function_tools_pass_through(gateway):
    client, service, key, state = gateway
    body = {**BODY, "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
            "messages": [{"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "call_1", "content": "found"}]}
    assert call(client, key, body).status_code == 200
    assert json.loads(state["requests"][0].content) == body


def test_duplicate_escaped_provider_secret_blocked(gateway):
    client, service, key, state = gateway
    escaped = "".join("\\u%04x" % ord(char) for char in REAL_KEY)
    state["raw"] = '{"discarded":["' + escaped + '"],"discarded":"safe","choices":[]}'
    response = call(client, key)
    assert response.status_code == 502 and REAL_KEY not in response.text
    assert rows(service)[0]["estimated_cost_usd"] is None


@pytest.mark.parametrize("cost", [None, "", "None", "invalid", "NaN", "inf", "-inf", "-1", "1e9999", "1e-9999",
                                  "0.1, 0.2", ["0.1", "0.2"], REAL_KEY])
def test_missing_invalid_header_cost_null(gateway, cost, caplog):
    client, service, key, state = gateway
    state["cost"] = cost
    response = call(client, key)
    assert response.status_code == 200 and REAL_KEY not in response.text
    row = rows(service)[0]
    assert row["estimated_cost_usd"] is None and row["cost_source"] is None
    assert row["reserved_cost_usd"] == 0
    summary = service.summarize_key(key)
    assert summary["unknown_cost_calls"] == 1 and summary["unknown_usage_calls"] == 0
    assert summary["estimated_cost_usd"] is None
    assert call(client, key).status_code == 200
    assert len(state["requests"]) == 2 and REAL_KEY not in caplog.text


def test_zero_cost_header_with_missing_usage(gateway):
    client, service, key, state = gateway
    state["cost"] = "0"
    state["body"].pop("usage")
    assert call(client, key).status_code == 200
    row = rows(service)[0]
    assert row["estimated_cost_usd"] == 0 and row["cost_source"] == "litellm_response_header"
    assert row["prompt_tokens"] is None and row["completion_tokens"] is None
    assert call(client, key).status_code == 200


def test_upstream_error_cost_header_recorded(gateway):
    client, service, key, state = gateway
    state.update(status=500, cost="0.02", body={"error": REAL_KEY})
    assert call(client, key).status_code == 500
    row = rows(service)[0]
    assert row["http_status"] == 500 and row["estimated_cost_usd"] == 0.02
    assert row["prompt_tokens"] is None and row["completion_tokens"] is None


def test_spend_threshold_can_overshoot_one_call(gateway):
    client, service, key, state = gateway
    with service.database.connect() as db:
        db.execute("UPDATE gateway_keys SET max_spend_usd=0.0001")
    state["cost"] = "0.02"
    assert call(client, key).status_code == 200
    assert call(client, key).status_code == 429
    assert service.summarize_key(key)["estimated_cost_usd"] == 0.02
    assert len(state["requests"]) == 1


def test_zero_budget_rejects_before_dispatch(gateway):
    client, service, key, state = gateway
    with service.database.connect() as db:
        db.execute("UPDATE gateway_keys SET max_spend_usd=0")
    assert call(client, key).status_code == 429
    assert not state["requests"] and not rows(service)


def test_client_cost_header_cannot_forge_accounting(gateway):
    client, service, key, state = gateway
    response = client.post("/gateway/v1/chat/completions", json=BODY,
                           headers={"Authorization": "Bearer " + key, "x-litellm-response-cost": "0"})
    assert response.status_code == 200
    assert rows(service)[0]["estimated_cost_usd"] == pytest.approx(0.000123)
    assert "x-litellm-response-cost" not in state["requests"][0].headers


def test_missing_cost_without_spend_threshold(gateway):
    client, service, key, state = gateway
    with service.database.connect() as db:
        db.execute("UPDATE gateway_keys SET max_spend_usd=NULL")
    state["cost"] = None
    assert call(client, key).status_code == 200
    assert call(client, key).status_code == 200
    assert service.summarize_key(key)["estimated_cost_usd"] is None
    assert service.summarize_key(key)["unknown_cost_calls"] == 2


def test_legacy_cost_migration_preserves_history(gateway):
    client, service, key, state = gateway
    assert call(client, key).status_code == 200
    with service.database.connect() as db:
        db.execute("ALTER TABLE model_calls DROP COLUMN cost_source")
    service.database.initialize()
    service.database.initialize()
    assert rows(service)[0]["estimated_cost_usd"] == pytest.approx(0.000123)
    assert rows(service)[0]["cost_source"] == "legacy_price_table"
    assert service.summarize_key(key)["legacy_cost_calls"] == 1
    assert call(client, key).status_code == 200
    assert rows(service)[1]["cost_source"] == "litellm_response_header"


def test_per_key_model_map_records_swap_and_preserves_response(gateway):
    client, service, key, state = gateway
    mapping = {"gpt-4o": "nova-pro", "nova-pro": "nova-lite"}
    mapped_key = service.mint_key("mapped-run", max_calls=5, max_spend_usd=1,
                                 expires_at=int(time.time()) + 3600, model_map=mapping)
    mapping["gpt-4o"] = "nova-micro"
    body = {**BODY, "model": "gpt-4o"}
    response = call(client, mapped_key, body)
    assert response.status_code == 200
    assert response.content == httpx.Response(200, json=state["body"]).content
    assert json.loads(state["requests"][0].content) == {**body, "model": "nova-pro"}
    row = rows(service)[0]
    assert row["model"] == "gpt-4o" and row["upstream_model"] == "nova-pro"
    assert row["estimated_cost_usd"] == pytest.approx(0.000123)
    models = service.summarize_key(mapped_key)["models"]
    assert models == [{"requested_model": "gpt-4o", "upstream_model": "nova-pro", "calls": 1,
                       "prompt_tokens": 100, "completion_tokens": 10,
                       "estimated_cost_usd": 0.000123, "unknown_cost_calls": 0}]
    assert call(client, key, body).status_code == 200
    assert json.loads(state["requests"][1].content)["model"] == "gpt-4o"
    assert service.summarize_key(mapped_key)["calls"] == 1


def test_unmapped_model_on_mapped_key_passes_through(gateway):
    client, service, key, state = gateway
    mapped_key = service.mint_key("mapped-run", max_calls=5, max_spend_usd=1,
                                 expires_at=int(time.time()) + 3600, model_map={"gpt-4o": "nova-lite"})
    body = {**BODY, "model": "gpt-4.1"}
    assert call(client, mapped_key, body).status_code == 200
    assert json.loads(state["requests"][0].content) == body
    row = rows(service)[0]
    assert row["model"] == "gpt-4.1" and row["upstream_model"] == "gpt-4.1"


def test_mapped_failed_call_records_both_names(gateway):
    client, service, key, state = gateway
    mapped_key = service.mint_key("mapped-run", max_calls=5, max_spend_usd=1,
                                 expires_at=int(time.time()) + 3600, model_map={"gpt-4o": "claude-sonnet-4.6"})
    state.update(status=500, cost=None, body={"error": REAL_KEY})
    assert call(client, mapped_key, {**BODY, "model": "gpt-4o"}).status_code == 500
    row = rows(service)[0]
    assert row["model"] == "gpt-4o" and row["upstream_model"] == "claude-sonnet-4.6"
    models = service.summarize_key(mapped_key)["models"]
    assert models[0]["estimated_cost_usd"] is None and models[0]["unknown_cost_calls"] == 1


@pytest.mark.parametrize("mapping", [[], "nova-lite", {1: "nova-lite"}, {"gpt-4o": None},
                                     {"": "nova-lite"}, {"gpt-4o": ""}, {"gpt-4o": " nova-lite"},
                                     {"gpt-4o": "nova-lite\n"}, {"gpt-4o": "x" * 201},
                                     {str(index): "nova-lite" for index in range(101)}])
def test_invalid_model_maps_rejected(gateway, mapping):
    client, service, key, state = gateway
    with pytest.raises(ValueError, match="Model map"):
        service.mint_key("bad-map", max_calls=1, max_spend_usd=1,
                         expires_at=int(time.time()) + 3600, model_map=mapping)
    with service.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM gateway_keys").fetchone()[0] == 1


def test_model_map_migration_preserves_existing_keys_and_calls(gateway):
    client, service, key, state = gateway
    assert call(client, key).status_code == 200
    with service.database.connect() as db:
        db.execute("ALTER TABLE gateway_keys DROP COLUMN model_map")
        db.execute("ALTER TABLE model_calls DROP COLUMN upstream_model")
    service.database.initialize()
    service.database.initialize()
    row = rows(service)[0]
    assert row["model"] == BODY["model"] and row["upstream_model"] == BODY["model"]
    assert row["cost_source"] == "litellm_response_header"
    assert call(client, key).status_code == 200
    assert json.loads(state["requests"][1].content) == BODY
    assert service.summarize_key(key)["models"][0]["calls"] == 2


@pytest.mark.parametrize("retry_after, expected", [("30", "30"), ("0", "0"), (REAL_KEY, None),
                                                   ("-1", None), ("1.5", None), ("9" * 11, None)])
def test_provider_429_preserves_safe_retry_after(gateway, retry_after, expected):
    client, service, key, state = gateway
    state.update(status=429, cost=None, retry_after=retry_after, body={"error": REAL_KEY})
    response = call(client, key)
    assert response.status_code == 429
    assert response.headers.get("retry-after") == expected
    assert "x-secret" not in response.headers
    assert REAL_KEY not in response.text and REAL_KEY not in str(response.headers)
    state.update(status=200, cost="0.000123", body={"choices": []})
    assert call(client, key).status_code == 200


def test_rejected_attempts_still_consume_call_limit(gateway):
    client, service, key, state = gateway
    with service.database.connect() as db:
        db.execute("UPDATE gateway_keys SET max_calls=2")
    state.update(status=429, cost=None)
    assert call(client, key).status_code == 429
    assert call(client, key).status_code == 429
    response = call(client, key)
    assert response.status_code == 429 and "call limit" in response.text
    assert len(state["requests"]) == 2 and service.summarize_key(key)["calls"] == 2


def test_provider_rejection_with_reported_cost_counts_toward_spend(gateway):
    client, service, key, state = gateway
    state.update(status=429, cost="1")
    assert call(client, key).status_code == 429
    summary = service.summarize_key(key)
    assert summary["estimated_cost_usd"] == 1 and summary["unknown_cost_calls"] == 0
    assert call(client, key).status_code == 429
    assert len(state["requests"]) == 1


def test_legacy_rejection_hold_no_longer_blocks_key(gateway):
    client, service, key, state = gateway
    state.update(status=429, cost=None)
    assert call(client, key).status_code == 429
    with service.database.connect() as db:
        db.execute("UPDATE model_calls SET reserved_cost_usd=1")
    summary = service.summarize_key(key)
    assert summary["reserved_cost_usd"] == 0 and summary["unknown_cost_calls"] == 1
    assert summary["unresolved_cost_calls"] == 0
    state.update(status=200, cost="0.000123", body={"choices": []})
    assert call(client, key).status_code == 200


def test_parallel_model_calls_share_key(gateway):
    client, service, key, state = gateway
    state["parallel"] = True
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: call(client, key), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert state["max_active"] == 2
    summary = service.summarize_key(key)
    assert summary["calls"] == 2 and summary["pending_calls"] == 0
    assert summary["estimated_cost_usd"] == pytest.approx(0.000246)
    assert summary["reserved_cost_usd"] == 0


@pytest.mark.parametrize("limit, admitted", [(1, 1), (5, 2)])
def test_parallel_admission_obeys_calls_while_spend_is_unrecorded(gateway, limit, admitted):
    client, service, key, state = gateway
    with service.database.connect() as db:
        db.execute("UPDATE gateway_keys SET max_calls=?, max_spend_usd=0.001", (limit,))
    def admit():
        try:
            return service.admit(key, BODY)
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: admit(), range(2)))
    assert sum(isinstance(result, tuple) for result in results) == admitted
    assert len(rows(service)) == admitted
    assert service.summarize_key(key)["reserved_cost_usd"] == 0


@pytest.mark.parametrize("parts", [[{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}],
                                  ["a", {"type": "text", "text": "héllo 🌍"}]])
def test_langchain_text_parts_pass_through(gateway, parts):
    client, service, key, state = gateway
    body = {**BODY, "messages": [{"role": "user", "content": parts}]}
    assert call(client, key, body).status_code == 200
    assert json.loads(state["requests"][0].content) == body
    assert not state["quotes"]


@pytest.mark.parametrize("parts", [[42], [{"type": "text", "text": 42}], [{"type": "text"}]])
def test_invalid_text_parts_rejected_before_quote(gateway, parts):
    client, service, key, state = gateway
    assert call(client, key, {**BODY, "messages": [{"role": "user", "content": parts}]}).status_code == 400
    assert not state["quotes"] and not state["requests"]


def test_disconnect_records_unknown_charge_without_locking_key(gateway):
    client, service, key, state = gateway
    state["disconnect"] = True
    response = call(client, key)
    assert response.status_code == 502 and REAL_KEY not in response.text
    row = rows(service)[0]
    assert row["http_status"] == 502 and row["lease_expires_at"] is None
    assert row["estimated_cost_usd"] is None and row["reserved_cost_usd"] == 0
    state["disconnect"] = False
    assert call(client, key).status_code == 200
    assert service.summarize_key(key)["pending_calls"] == 0


def test_cancelled_request_finishes_ledger_and_key_can_continue(gateway):
    client, service, key, state = gateway

    async def scenario():
        state["started"], state["release"] = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(service.forward(key, BODY))
        await asyncio.wait_for(state["started"].wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        row = rows(service)[0]
        assert row["http_status"] == 499 and row["lease_expires_at"] is None
        assert row["estimated_cost_usd"] is None and row["reserved_cost_usd"] == 0
        state.pop("started")
        state.pop("release")
        response = await service.forward(key, BODY)
        assert response.status_code == 200

    asyncio.run(scenario())
    assert service.summarize_key(key)["pending_calls"] == 0


def test_stale_lease_recovery_retains_estimate_and_accepts_late_cost(gateway):
    client, service, key, state = gateway
    call_id, model = service.admit(key, BODY)
    with service.database.connect() as db:
        db.execute("UPDATE model_calls SET lease_expires_at=0")
    summary = service.summarize_key(key)
    assert summary["pending_calls"] == 0 and summary["reserved_cost_usd"] == 0
    assert summary["estimated_cost_usd"] is None
    assert rows(service)[0]["http_status"] == 504
    assert call(client, key).status_code == 200
    service.finish(call_id, 200, 10, state["body"], 0.005)
    summary = service.summarize_key(key)
    assert summary["estimated_cost_usd"] == pytest.approx(0.005123)
    assert summary["reserved_cost_usd"] == 0
    assert len(state["requests"]) == 1


def test_startup_recovers_prior_pending_call(gateway):
    client, service, key, state = gateway
    service.admit(key, BODY)
    with TestClient(create_app(service.settings)) as restarted:
        assert rows(service)[0]["http_status"] == 504
        assert rows(service)[0]["reserved_cost_usd"] == 0
        assert call(restarted, key).status_code == 200


def test_missing_output_limit_gets_bounded_default(gateway):
    client, service, key, state = gateway
    body = {name: value for name, value in BODY.items() if name != "max_tokens"}
    assert call(client, key, body).status_code == 200
    assert not state["quotes"]
    assert json.loads(state["requests"][0].content) == {**body, "max_tokens": DEFAULT_OUTPUT_TOKENS}


def test_unknown_cost_does_not_invent_spend(gateway):
    client, service, key, state = gateway
    with service.database.connect() as db:
        db.execute("UPDATE gateway_keys SET max_spend_usd=0.01")
    call_id, model = service.admit(key, BODY)
    service.finish(call_id, 502, 1, {}, None)
    assert call(client, key).status_code == 200
    assert len(state["requests"]) == 1 and rows(service)[0]["estimated_cost_usd"] is None


def test_lease_migration_recovers_old_pending_rows_without_refund(gateway):
    client, service, key, state = gateway
    service.admit(key, BODY)
    with service.database.connect() as db:
        db.execute("ALTER TABLE model_calls DROP COLUMN lease_expires_at")
        db.execute("UPDATE model_calls SET created_at=0")
    service.database.initialize()
    service.database.initialize()
    summary = service.summarize_key(key)
    assert summary["pending_calls"] == 0 and summary["reserved_cost_usd"] == 0
    assert rows(service)[0]["http_status"] == 504 and rows(service)[0]["estimated_cost_usd"] is None
    assert call(client, key).status_code == 200
import asyncio


@pytest.mark.parametrize('selected', ['nova-micro', 'nova-lite', 'nova-pro', 'nova-2-lite',
                                     'claude-haiku', 'claude-sonnet-4.6', 'claude-opus-4.6'])
def test_fixed_model_routes_all_names_and_quotes_selected_model(gateway, selected):
    client, service, _, state = gateway
    key = service.mint_key('picked', max_calls=3, max_spend_usd=1,
                          expires_at=int(time.time()) + 60, litellm_model=selected)
    for requested in ['gpt-4o', 'another-runtime-model']:
        assert call(client, key, {**BODY, 'model': requested}).status_code == 200
    assert {json.loads(r.content)['model'] for r in state['requests']} == {selected}
    assert not state["quotes"]
    assert {(r['model'], r['upstream_model']) for r in rows(service)} == {
        ('gpt-4o', selected), ('another-runtime-model', selected)}
    assert {r['upstream_model'] for r in service.summarize_key(key)['models']} == {selected}


@pytest.mark.parametrize('selected', ['gpt-4o', 'https://provider.test', '', 'sk-private', ['nova-lite']])
def test_fixed_model_rejects_unlisted_values(gateway, selected):
    _, service, _, _ = gateway
    with pytest.raises(ValueError):
        service.mint_key('invalid', max_calls=1, max_spend_usd=1,
                         expires_at=int(time.time()) + 60, litellm_model=selected)


def test_fixed_model_and_map_are_mutually_exclusive(gateway):
    _, service, _, _ = gateway
    with pytest.raises(ValueError):
        service.mint_key('invalid', max_calls=1, max_spend_usd=1,
                         expires_at=int(time.time()) + 60, litellm_model='nova-lite',
                         model_map={'gpt-4o': 'nova-pro'})
