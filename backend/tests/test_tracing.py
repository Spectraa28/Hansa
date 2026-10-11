"""Tracing tests. Neatlogs is always a fake transport or fake client; nothing here leaves the machine."""
import dataclasses
import json

from fastapi import HTTPException
import httpx
import pytest

from backend.app.gateway.shape import redact, repeated_prefix, request_shape, response_shape
from backend.app.sessions import token_hash
from backend.app.tracing.neatlogs import NeatlogsClient, NeatlogsError
from backend.app.tracing.service import TraceService, marker
from backend.tests.test_inspection import imported_client
from backend.tests.test_runner import configured_runner


def test_shapes_measure_repeated_context_without_keeping_the_conversation():
    system = {"role": "system", "content": "You are helpful. " * 20}
    first = {"messages": [system, {"role": "user", "content": "Find the title."}], "tools": [{"type": "function"}], "max_tokens": 64}
    second = {"messages": [system, {"role": "user", "content": "Find the title."},
                           {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "fetch", "arguments": "{}"}}]},
                           {"role": "tool", "content": [{"type": "text", "text": "page text"}]}]}
    a, b = request_shape(first, True), request_shape(second, True)
    assert a["messages"] == 2 and a["tools"] == 1 and a["max_tokens"] == 64 and a["chars_by_role"]["system"] == 340
    assert repeated_prefix(a, b) == (2, a["prompt_chars"]) and repeated_prefix({}, a) == (0, 0)
    assert b["last_message"] == {"role": "tool", "preview": "page text"}
    assert "last_message" not in request_shape(second, False)
    # Nothing but sizes, hashes and one short preview is retained.
    assert "You are helpful" not in json.dumps(b)
    reply = {"choices": [{"finish_reason": "tool_calls", "message": {"content": None,
             "tool_calls": [{"function": {"name": "fetch", "arguments": '{"url": "https://example.com"}'}}]}}]}
    shape = response_shape(reply, True)
    assert shape["tool_calls"] == ["fetch"] and shape["finish_reason"] == "tool_calls" and "example.com" in shape["preview"]
    assert "preview" not in response_shape(reply, False) and response_shape({}, True) == {}


def test_redaction_masks_credential_shaped_text_and_bounds_length():
    text = "key sk-proj-abcdefghijklmnop and gw_abcdefghijklmnopqrst plus Bearer abcdefghijklmnopqrstuv end"
    masked = redact(text)
    assert "sk-proj" not in masked and "gw_abc" not in masked and "abcdefghijklmnopqrstuv" not in masked
    assert masked.count("[redacted]") == 3 and len(redact("x" * 900)) == 501


@pytest.fixture
def traced(configured_runner):
    state, owner, imported = configured_runner
    calls = []
    class Client:
        enabled = True
        def call(self, tool, arguments):
            calls.append((tool, arguments))
            if tool == "log_trace":
                return {"trace_id": f"trace{len(calls):04d}", "span_count": len(arguments["spans"]), "status": "queued"}
            if tool == "search_traces":
                return {"results": [{"trace_id": "trace0001"}, {"trace_id": "someone-elses-trace"}]}
            return {"trace_id": arguments["trace_id"], "spans": [], "finalization_status": "finalized"}
    service = TraceService(state.settings, state.database, state.inspection, Client())
    with state.database.connect() as db:
        db.execute("""INSERT INTO gateway_keys (key_hash, run_label, max_calls, max_spend_usd, expires_at, revoked, created_at, model_map)
                      VALUES (?, 'run', 5, 1, 9999999999, 1, 1, '{}')""", (token_hash("gw_key"),))
        system = {"role": "system", "content": "s" * 400}
        bodies = [{"messages": [system, {"role": "user", "content": "question"}]},
                  {"messages": [system, {"role": "user", "content": "question"}, {"role": "tool", "content": "page"}]}]
        for index, (start, latency, cost) in enumerate([(1_700_000_000_000, 800, 0.001), (1_700_000_001_500, 600, None)]):
            db.execute("""INSERT INTO model_calls (key_hash, model, upstream_model, prompt_tokens, completion_tokens, latency_ms,
                http_status, estimated_cost_usd, cost_source, created_at, started_at_ms, request_shape, response_shape)
                VALUES (?, 'gpt-4o', 'claude-haiku', 100, 10, ?, 200, ?, ?, 1, ?, ?, ?)""",
                (token_hash("gw_key"), latency, cost, "litellm_response_header" if cost else None, start,
                 json.dumps(request_shape(bodies[index], True)), json.dumps({"preview": "answer", "tool_calls": ["fetch"]})))
    return state, service, owner, imported, calls


def run_result(cost=0.001, unknown=1):
    return {"run_id": "run-1", "stop_reason": "completed", "exit_code": 0, "wall_time_seconds": 2.5, "commit_sha": "c" * 40,
            "adapter_sha256": "a" * 64, "output": {"answer": "Example Domain"}, "isolation": {"internet": "filtered_proxy"},
            "gateway": {"calls": 2, "prompt_tokens": 200, "completion_tokens": 20, "estimated_cost_usd": cost, "unknown_cost_calls": unknown},
            "egress": {"connections": [
                {"host": "example.com", "port": 443, "method": "CONNECT", "allowed": True, "reason": None,
                 "started_at": 1_700_000_000.9, "duration_ms": 300, "bytes_down": 6000},
                {"host": "169.254.169.254", "port": 80, "method": "GET", "allowed": False, "reason": "Destination is not a public address.",
                 "started_at": 1_700_000_001.25, "duration_ms": 0, "bytes_down": 0},
                {"host": "broken", "started_at": "soon", "duration_ms": 1}]}}


def test_run_trace_carries_calls_gaps_egress_cost_provenance_and_scope(traced):
    state, service, owner, imported, calls = traced
    logged = service.log_run(imported, token_hash("gw_key"), run_result(), {"question": "title? sk-proj-abcdefghijklmnop"},
                             {"kind": "baseline", "task_id": "case/1"})
    assert logged == {"status": "queued", "trace_id": "trace0001", "spans": 5, "content": "exported"}
    tool, arguments = calls[0]
    assert tool == "log_trace" and arguments["workflow_name"] == "hansa-baseline" and arguments["latency_ms"] == 2500
    assert "sk-proj" not in arguments["input"] and "Example Domain" in arguments["output"]
    # One call's cost is unknown, so the run's cost is unknown rather than a partial sum.
    assert "cost_usd" not in arguments and arguments["metadata"]["hansa_cost_usd"] == "unknown"
    assert arguments["metadata"]["hansa_import"] == marker(imported) and "-" not in marker(imported)
    assert "token_usage" not in arguments
    spans = {span["span_id"]: span for span in arguments["spans"]}
    assert [span["kind"] for span in arguments["spans"]] == ["LLM", "CHAIN", "TOOL", "TOOL", "LLM"]
    first, second = spans["llm-1"], spans["llm-2"]
    assert first["attributes"]["neatlogs.llm.model_name"] == "claude-haiku" and first["attributes"]["hansa.requested_model"] == "gpt-4o"
    assert first["attributes"]["neatlogs.llm.token_count.prompt"] == 100 and first["attributes"]["hansa.cost_usd"] == 0.001
    assert second["attributes"]["hansa.cost_usd"] == "unknown" and second["attributes"]["hansa.repeated_messages"] == 2
    assert second["attributes"]["hansa.repeated_size"] == 408 and "(size 408) repeat" in second["attributes"]["neatlogs.input.value"]
    gap = spans["gap-llm-1"]
    assert gap["attributes"] == {"hansa.inferred": True, "hansa.gap_ms": 700} and gap["parent_span_id"] == "llm-1"
    assert spans["egress-0"]["parent_span_id"] == "llm-1" and spans["egress-0"]["status_code"] == "OK"
    assert spans["egress-1"]["status_code"] == "ERROR" and "refused" in spans["egress-1"]["attributes"]["neatlogs.tool.output"]
    assert all(not key.startswith("_") for span in arguments["spans"] for key in span)
    listed = service.list(owner, imported)["traces"]
    assert listed[0]["trace_id"] == "trace0001" and listed[0]["kind"] == "baseline" and listed[0]["cost_usd"] is None
    assert listed[0]["repeated_chars"] == 408 and listed[0]["task_id"] == "case/1"


def test_known_cost_and_content_setting_are_respected(traced):
    state, service, owner, imported, calls = traced
    service.log_run(imported, token_hash("gw_key"), run_result(cost=0.002, unknown=0), {"q": "x"})
    assert calls[-1][1]["cost_usd"] == 0.002 and calls[-1][1]["workflow_name"] == "hansa-run"
    service.settings = dataclasses.replace(state.settings, trace_content=False)
    service.log_run(imported, token_hash("gw_key"), run_result(), {"q": "private"})
    assert calls[-1][1]["input"] == calls[-1][1]["output"] == "content not exported"


def test_readback_is_limited_to_traces_logged_for_an_import_its_owner_can_read(traced, imported_client):
    state, service, owner, imported, calls = traced
    client, _, _ = imported_client
    state.traces.client = service.client
    service.log_run(imported, token_hash("gw_key"), run_result(), {"q": "x"})
    assert client.get(f"/github/imports/{imported}/traces").json()["traces"][0]["trace_id"] == "trace0001"
    assert client.get(f"/github/imports/{imported}/traces/trace0001").json()["trace_id"] == "trace0001"
    # A trace ID from the same Neatlogs project that we did not log for this import is not readable.
    assert client.get(f"/github/imports/{imported}/traces/someone-elses-trace").status_code == 404
    found = client.get(f"/github/imports/{imported}/traces/search", params={"q": "title"}).json()
    assert [item["trace_id"] for item in found["results"]] == ["trace0001"]
    assert calls[-1][1] == {"query": "title", "limit": 100}
    client.cookies.clear()
    assert client.get(f"/github/imports/{imported}/traces").status_code == 401
    assert client.post("/auth/register", json={"email": "other@example.com", "password": "another-long-password", "name": "Other"}).status_code == 201
    assert client.get(f"/github/imports/{imported}/traces").status_code == 404
    assert client.get(f"/github/imports/{imported}/traces/trace0001").status_code == 404
    state.github.delete_import(owner, imported)
    with state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM traces").fetchone()[0] == 0


def test_tracing_failure_or_absence_never_fails_the_run(traced):
    state, service, owner, imported, calls = traced
    class Broken:
        enabled = True
        def call(self, tool, arguments):
            raise NeatlogsError("Neatlogs could not be reached.")
    service.client = Broken()
    assert service.log_run(imported, token_hash("gw_key"), run_result(), {}) == {"status": "failed", "reason": "Neatlogs could not be reached.", "trace_ids": []}
    with pytest.raises(HTTPException) as exc:
        service.search(owner, imported, "anything")
    assert exc.value.status_code == 502
    disabled = TraceService(state.settings, state.database, state.inspection)
    assert not disabled.enabled and disabled.log_run(imported, token_hash("gw_key"), run_result(), {}) is None
    assert disabled.list(owner, imported) == {"enabled": False, "traces": []}


def test_job_trace_orders_model_calls_and_tools(traced):
    state, service, owner, imported, calls = traced
    steps = [{"name": "read_file", "input": '{"path": "agent.py"}', "output": "{}", "ok": True,
              "start_ms": 1_700_000_000_900, "end_ms": 1_700_000_000_950, "trace_id": None},
             {"name": "run_smoke", "input": "{}", "output": '{"error": "x"}', "ok": False,
              "start_ms": 1_700_000_002_200, "end_ms": 1_700_000_004_000, "trace_id": "trace-of-run"}]
    logged = service.log_job(imported, "job-1", "onboarding", token_hash("gw_key"), steps, "ready", "Adapter stored.", 1_700_000_000_000)
    arguments = calls[-1][1]
    assert logged["status"] == "queued" and arguments["workflow_name"] == "hansa-onboarding" and arguments["agent_name"] == "hansa-agent"
    assert [span["span_id"] for span in arguments["spans"]] == ["agent-1", "tool-0", "agent-2", "tool-1"]
    assert arguments["spans"][1]["parent_span_id"] == "agent-1" and arguments["spans"][3]["parent_span_id"] == "agent-2"
    assert arguments["spans"][3]["status_code"] == "ERROR" and arguments["spans"][3]["attributes"]["hansa.run_trace_id"] == "trace-of-run"
    assert service.list(owner, imported)["traces"][0]["job_id"] == "job-1"


def settings_with_key(tmp_path):
    from backend.app.config import Settings
    return Settings(database_path=tmp_path / "db", secret_key="test-only-" * 4, neatlogs_api_key="project-key")


def test_client_opens_one_session_parses_event_streams_and_reopens_once(tmp_path):
    seen = []
    def handler(request):
        body = json.loads(request.content)
        seen.append((body["method"], request.headers.get("mcp-session-id"), request.headers["authorization"]))
        if body["method"] == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": f"session-{sum(m == 'initialize' for m, _, _ in seen)}"}, json={"result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if request.headers.get("mcp-session-id") == "session-1" and len(seen) > 4:
            return httpx.Response(404)
        payload = {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": json.dumps({"ok": body["params"]["name"]})}]}}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="event: message\ndata: " + json.dumps(payload) + "\n\n")
    client = NeatlogsClient(settings_with_key(tmp_path), transport=httpx.MockTransport(handler))
    assert client.call("ping", {}) == {"ok": "ping"} and client.call("whoami", {}) == {"ok": "whoami"}
    assert [method for method, _, _ in seen] == ["initialize", "notifications/initialized", "tools/call", "tools/call"]
    assert all(auth == "Bearer project-key" for _, _, auth in seen)
    assert client.call("search_traces", {"query": "x"}) == {"ok": "search_traces"}
    assert [method for method, _, _ in seen][4:] == ["tools/call", "initialize", "notifications/initialized", "tools/call"]
    assert seen[-1][1] == "session-2"


def test_client_refuses_unused_tools_bad_keys_and_tool_errors(tmp_path):
    def handler(request):
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "s"}, json={"result": {}})
        if body["method"] != "tools/call":
            return httpx.Response(202)
        text = json.dumps({"error": "Summary projection is not enabled", "errorCode": "not_enabled"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": text}]}})
    client = NeatlogsClient(settings_with_key(tmp_path), transport=httpx.MockTransport(handler))
    with pytest.raises(NeatlogsError, match="not used"):
        client.call("triage_dismiss", {"fix_id": "1"})
    with pytest.raises(NeatlogsError, match="not_enabled"):
        client.call("search_traces", {"query": "x"})
    rejected = NeatlogsClient(settings_with_key(tmp_path), transport=httpx.MockTransport(lambda request: httpx.Response(401, text="project-key")))
    with pytest.raises(NeatlogsError) as exc:
        rejected.call("ping", {})
    assert "project-key" not in str(exc.value) and "rejected" in str(exc.value)
    from backend.app.config import Settings
    with pytest.raises(NeatlogsError, match="not configured"):
        NeatlogsClient(Settings(database_path=tmp_path / "db", secret_key="test-only-" * 4)).call("ping", {})
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(database_path=tmp_path / "db", secret_key="test-only-" * 4, neatlogs_mcp_url="http://ingest.example/mcp")


def test_refused_payload_is_resent_with_less_text_each_time(traced):
    state, service, owner, imported, calls = traced
    attempts = []
    class Filtered:
        enabled = True
        def __init__(self, refusals):
            self.refusals = refusals
        def call(self, tool, arguments):
            attempts.append(arguments)
            if len(attempts) <= self.refusals:
                raise NeatlogsError("Neatlogs log_trace failed with status 403.", 403)
            return {"trace_id": f"trace-after-{self.refusals}"}
    # First refusal: only tool inputs and outputs are dropped; model-call descriptions stay.
    service.client = Filtered(1)
    logged = service.log_run(imported, token_hash("gw_key"), run_result(), {"path": "../../etc/passwd"})
    assert logged == {"status": "queued", "trace_id": "trace-after-1", "spans": 5, "content": "partial"}
    partial = attempts[1]
    assert partial["metadata"]["hansa_content"] == "partial" and "passwd" in partial["input"]
    assert all(("neatlogs.tool.input" not in span["attributes"]) == (span["kind"] == "TOOL") or span["kind"] != "TOOL" for span in partial["spans"])
    assert all("neatlogs.input.value" in span["attributes"] for span in partial["spans"] if span["kind"] == "LLM")
    assert all("neatlogs.tool.input" not in span["attributes"] for span in partial["spans"] if span["kind"] == "TOOL")
    # Second refusal: all free text goes; measurements survive.
    attempts.clear()
    service.client = Filtered(2)
    logged = service.log_run(imported, token_hash("gw_key"), run_result(), {"path": "../../etc/passwd"})
    assert logged["content"] == "withheld" and len(attempts) == 3
    sent = attempts[2]
    assert "passwd" not in json.dumps(sent) and sent["metadata"]["hansa_content"] == "withheld"
    llm = [span for span in sent["spans"] if span["kind"] == "LLM"]
    assert all("neatlogs.input.value" not in span["attributes"] and span["attributes"]["hansa.content_withheld"] for span in llm)
    assert llm[0]["attributes"]["neatlogs.llm.token_count.prompt"] == 100 and llm[1]["attributes"]["hansa.repeated_size"] == 408
    assert service.list(owner, imported)["traces"][0]["content"] == "withheld"
    # Refused at every size, or any other failure: reported and never raised.
    attempts.clear()
    service.client = Filtered(99)
    assert service.log_run(imported, token_hash("gw_key"), run_result(), {})["status"] == "failed"


def test_queued_trace_needs_finalized_readback_and_can_be_rechecked(traced, imported_client):
    state, service, owner, imported, calls = traced
    client, _, headers = imported_client
    state.traces.client = service.client
    trace = service.log_run(imported, token_hash("gw_key"), run_result(), {})
    trace_id = trace["trace_id"]
    assert trace["status"] == service.list(owner, imported)["traces"][0]["status"] == "queued"
    original = service.client.call
    def missing(tool, arguments):
        raise NeatlogsError("Neatlogs get_trace_context refused the request: not_found.")
    service.client.call = missing
    checked = service.recheck(owner, imported, trace_id)
    assert checked["status"] == "queued" and "not_found" in checked["error"] and checked["confirmed_at"] is None
    assert service.list(owner, imported)["traces"][0]["checked_at"] is not None
    service.client.call = lambda *a: {"trace_id": trace_id, "status": "processing", "finalization_status": "pending"}
    assert service.recheck(owner, imported, trace_id)["status"] == "queued"
    service.client.call = original
    url = f"/github/imports/{imported}/traces/{trace_id}/recheck"
    assert client.post(url).status_code == 403
    response = client.post(url, headers=headers)
    assert response.status_code == 200 and response.json()["status"] == "confirmed" and response.json()["confirmed_at"]
    assert service.list(owner, imported)["traces"][0]["status"] == "confirmed"
    service.client.call = missing
    # Earlier successful readback remains recorded; a later failure is also explicit.
    assert service.recheck(owner, imported, trace_id)["status"] == "confirmed"
    assert "not_found" in service.list(owner, imported)["traces"][0]["last_error"]
    client.post("/auth/register", json={"email": "other@example.com", "password": "another-long-password", "name": "Other"})
    other_headers = {"X-CSRF-Token": client.get("/auth/me").json()["csrf_token"]}
    assert client.post(url, headers=other_headers).status_code == 404


def test_readback_cannot_confirm_a_different_trace(traced):
    state, service, owner, imported, _ = traced
    logged = service.log_run(imported, token_hash("gw_key"), run_result(), {})
    service.client.call = lambda *a: {"trace_id": "different", "finalization_status": "finalized"}
    checked = service.recheck(owner, imported, logged["trace_id"])
    assert checked["status"] == "queued" and checked["context"] is None and checked["error"]
    class Down:
        enabled = True
        def call(self, tool, arguments):
            raise NeatlogsError("Neatlogs log_trace failed with status 500.", 500)
    service.client = Down()
    assert service.log_run(imported, token_hash("gw_key"), run_result(), {})["status"] == "failed"


def test_long_traces_are_sent_in_parts_under_the_endpoint_limit(traced):
    from backend.app.tracing.service import MODEL_SPANS_PER_TRACE, parts
    state, service, owner, imported, calls = traced
    def span(index, kind, parent=None):
        return {"span_id": f"{kind}-{index}", "name": kind, "kind": kind, "attributes": {}, **({"parent_span_id": parent} if parent else {})}
    spans = []
    for index in range(40):
        spans.append(span(index, "LLM"))
        spans.append(span(index, "TOOL", f"LLM-{index}"))
    spans.insert(2 * MODEL_SPANS_PER_TRACE, span(999, "TOOL", f"LLM-{MODEL_SPANS_PER_TRACE - 1}"))
    arguments = {"workflow_name": "hansa-investigation", "cost_usd": 0.7, "metadata": {"hansa_job": "j"}, "spans": spans}
    split = parts(arguments)
    assert [sum(s["kind"] == "LLM" for s in part["spans"]) for part in split] == [10, 10, 10, 10]
    assert sum(len(part["spans"]) for part in split) == len(spans)
    assert [part["metadata"]["hansa_part"] for part in split] == ["1/4", "2/4", "3/4", "4/4"]
    # Cost is stated once; a tool whose caller is in the previous part loses only its parent link.
    assert [("cost_usd" in part) for part in split] == [True, False, False, False]
    assert split[0]["spans"][-1]["span_id"] == "TOOL-999" and split[0]["spans"][-1]["parent_span_id"] == "LLM-9"
    assert all(s.get("parent_span_id") in {x["span_id"] for x in part["spans"]} for part in split for s in part["spans"] if "parent_span_id" in s)
    assert parts({**arguments, "spans": spans[:10]}) == [{**arguments, "spans": spans[:10]}]
    service.client.call = lambda tool, args: {"trace_id": "part-trace-" + args["metadata"]["hansa_part"][0] * 4}
    logged = service.send(imported, "investigation", arguments, {"kind": "investigation"}, job_id="j")
    assert logged["trace_ids"] == ["part-trace-1111", "part-trace-2222", "part-trace-3333", "part-trace-4444"] and logged["trace_id"] == "part-trace-1111"
    assert [t["part"] for t in service.list(owner, imported)["traces"]][::-1] == ["1/4", "2/4", "3/4", "4/4"]
    # A part the endpoint refuses even without text is halved until it is accepted.
    sent = []
    def picky(tool, args):
        sent.append(len(args["spans"]))
        if len(args["spans"]) > 6:
            raise NeatlogsError("Neatlogs log_trace failed with status 403.", 403)
        return {"trace_id": f"half-trace-{len(sent):04d}"}
    service.client.call = picky
    halves = service.send(imported, "investigation", {**arguments, "spans": spans[:20]}, {"kind": "investigation"}, job_id="k")
    assert halves["status"] == "queued" and len(halves["trace_ids"]) == 4 and sent.count(5) == 4 and sent.count(20) == 3
