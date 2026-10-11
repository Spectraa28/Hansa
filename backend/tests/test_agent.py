"""Onboarding agent tests. The model is scripted and the runner is mocked; nothing here calls a provider."""
import dataclasses
import json

from fastapi import HTTPException
import pytest

from app.agent import service as agent_service
from app.agent.tools import SnapshotTools
from tests.test_inspection import imported_client
from tests.test_runner import configured_runner

GOOD = "import json, sys\nprint(json.dumps({'ok': True}))\n"
FIXED = "import json, sys\ntask = json.load(sys.stdin)\nprint(json.dumps({'answer': task['question']}))\n"


def call(name, **arguments):
    return {"role": "assistant", "content": f"Using {name}.",
            "tool_calls": [{"id": "call-" + name, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)}}]}


@pytest.fixture
def agent(configured_runner, monkeypatch):
    state, owner, imported = configured_runner
    service = state.agent
    service.settings = dataclasses.replace(state.settings, litellm_base_url="https://litellm.example/v1",
                                           litellm_api_key="server-key-never-shown")
    monkeypatch.setattr(state.runner, "build", lambda *a, **k: {"build_id": "build", "dependencies": [], "resolved_dependencies": []})
    return state, service, owner, imported


def script(service, monkeypatch, messages):
    queue, seen = list(messages), []
    def complete(key, history, tools=None):
        seen.append(json.loads(json.dumps(history)))
        return queue.pop(0)
    monkeypatch.setattr(service, "complete", complete)
    return seen


def finished(service, owner, imported, job):
    service.threads[job["job_id"]].join(20)
    return service.job(owner, imported, job["job_id"])


def test_agent_recovers_from_a_failed_run_and_stores_the_adapter(agent, imported_client, monkeypatch):
    state, service, owner, imported = agent
    client, _, headers = imported_client
    runs = []
    def run(*args, **kwargs):
        runs.append((args, kwargs))
        failed = len(runs) == 1
        return {"run_id": f"run-{len(runs)}", "stop_reason": "exit_nonzero" if failed else "completed",
                "exit_code": 1 if failed else 0, "output": None if failed else {"answer": "hi"},
                "stderr_tail": "KeyError: 'question'" if failed else "", "wall_time_seconds": 1.5,
                "gateway": {"calls": 2, "estimated_cost_usd": 0.001},
                "egress": {"hosts": {"example.com": {}}, "denied": 0}}
    monkeypatch.setattr(state.runner, "run", run)
    seen = script(service, monkeypatch, [
        call("read_file", path="agent.py"),
        call("write_adapter", code="def broken(:\n"),
        call("write_adapter", code=GOOD),
        call("run_smoke", task={"prompt": "hi"}),
        call("write_adapter", code=FIXED),
        call("finish", outcome="ready", summary="Calls the agent."),
        call("run_smoke", task={"question": "hi"}),
        call("finish", outcome="ready", summary="Calls the agent and returns its answer.", task_description="question: text"),
    ])
    response = client.post(f"/github/imports/{imported}/onboarding", headers=headers)
    assert response.status_code == 202 and response.json()["status"] == "running"
    job = finished(service, owner, imported, response.json())
    assert job["status"] == "ready" and job["result"]["smoke_runs"] == 2
    assert job["result"]["target_usage"] == {"calls": 4, "estimated_cost_usd": 0.002}
    assert job["result"]["agent_usage"]["calls"] == 0
    # Drafts reach the sandbox as adapter_code; nothing is stored until a run of that draft completes.
    assert [kwargs["adapter_code"] for _, kwargs in runs] == [GOOD, FIXED]
    stored = client.get(f"/github/imports/{imported}/adapter").json()
    assert stored["content"] == FIXED and stored["example_task"]["task"] == {"question": "hi"}
    assert stored["sha256"] == job["result"]["adapter_sha256"]
    events = client.get(f"/github/imports/{imported}/agent-jobs/{job['job_id']}/events").json()["events"]
    kinds = [event["kind"] for event in events]
    assert kinds[0] == "started" and kinds[-1] == "finished" and kinds.count("smoke") == 2 and kinds.count("adapter") == 2
    errors = [event["data"]["error"] for event in events if event["kind"] == "tool_error"]
    assert any("Syntax error" in error for error in errors) and any("no completed smoke run" in error for error in errors)
    # The failed run's stderr was returned to the model so it could fix the adapter.
    assert any("KeyError" in message.get("content", "") for message in seen[4] if message["role"] == "tool")
    later = client.get(f"/github/imports/{imported}/agent-jobs/{job['job_id']}/events", params={"after": events[-2]["id"]})
    assert [event["kind"] for event in later.json()["events"]] == ["finished"]
    with state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM gateway_keys WHERE revoked=0").fetchone()[0] == 0
    client.cookies.clear()
    assert client.get(f"/github/imports/{imported}/adapter").status_code == 401
    assert client.post("/auth/register", json={"email": "other@example.com", "password": "another-long-password", "name": "Other"}).status_code == 201
    assert client.get(f"/github/imports/{imported}/adapter").status_code == 404
    assert client.get(f"/github/imports/{imported}/agent-jobs/{job['job_id']}").status_code == 404
    state.github.delete_import(owner, imported)
    with state.database.connect() as db:
        assert [db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("import_adapters", "agent_jobs", "agent_events")] == [0, 0, 0]


def test_agent_reports_a_blocker_without_storing_anything(agent, monkeypatch):
    state, service, owner, imported = agent
    script(service, monkeypatch, [call("finish", outcome="blocked", summary="Needs TAVILY_API_KEY, which the sandbox does not provide.")])
    job = finished(service, owner, imported, service.start_onboarding(owner, imported))
    assert job["status"] == "blocked" and "TAVILY_API_KEY" in job["result"]["reason"]
    with pytest.raises(HTTPException) as exc:
        service.adapter(owner, imported)
    assert exc.value.status_code == 404


def test_unsupported_dependencies_block_before_any_model_call(agent, monkeypatch):
    state, service, owner, imported = agent
    def build(*args, **kwargs):
        raise RuntimeError("Binary-wheel resolution failed; source builds and private indexes are unsupported.")
    monkeypatch.setattr(state.runner, "build", build)
    seen = script(service, monkeypatch, [])
    job = finished(service, owner, imported, service.start_onboarding(owner, imported))
    assert job["status"] == "blocked" and "Binary-wheel resolution failed" in job["result"]["reason"] and not seen


def test_agent_that_never_finishes_fails_with_a_reason(agent, monkeypatch):
    state, service, owner, imported = agent
    monkeypatch.setattr(agent_service, "MAX_TURNS", 3)
    script(service, monkeypatch, [call("list_files")] * 3)
    job = finished(service, owner, imported, service.start_onboarding(owner, imported))
    assert job["status"] == "failed" and "did not finish within 3 turns" in job["result"]["reason"]


def test_only_one_job_runs_and_unconfigured_gateway_is_refused(agent, configured_runner):
    state, service, owner, imported = agent
    assert agent_service.JOB_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as exc:
            service.start_onboarding(owner, imported)
        assert exc.value.status_code == 409
    finally:
        agent_service.JOB_LOCK.release()
    service.settings = dataclasses.replace(service.settings, litellm_api_key="")
    with pytest.raises(HTTPException) as exc:
        service.start_onboarding(owner, imported)
    assert exc.value.status_code == 503


def test_interrupted_jobs_are_marked_failed_on_restart(agent):
    state, service, owner, imported = agent
    with state.database.connect() as db:
        db.execute("INSERT INTO agent_jobs VALUES ('stuck',?,'onboarding','running','{}',1,1)", (imported,))
    service.recover()
    assert service.job(owner, imported, "stuck")["status"] == "failed"


def test_snapshot_tools_stay_inside_the_repository_and_bound_output(tmp_path):
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg/agent.py").write_text("def run(question):\n    return question\n" + "x = 1\n" * 300)
    (root / "data.bin").write_bytes(b"\xff\xfe\x00")
    (tmp_path / "outside.txt").write_text("secret")
    tools = SnapshotTools(root)
    assert tools.list_files(".")["entries"] == ["data.bin (3 bytes)", "pkg/"]
    assert tools.read_file("pkg/agent.py", 1, 2)["lines"] == ["1: def run(question):", "2:     return question"]
    assert tools.search_code("def RUN")["matches"] == ["pkg/agent.py:1: def run(question):"]
    assert len(tools.search_code("x = 1")["matches"]) == 40
    for bad in ("../outside.txt", "/etc/passwd", "pkg/../../outside.txt"):
        with pytest.raises(ValueError):
            tools.read_file(bad)
    with pytest.raises(ValueError):
        tools.read_file("data.bin")
    with pytest.raises(ValueError):
        tools.read_file("pkg/agent.py", 1, 500)
    with pytest.raises(ValueError):
        tools.search_code("x")


def test_runner_adapter_modes_are_validated(configured_runner, tmp_path):
    state, owner, imported = configured_runner
    for kwargs in ({"adapter": "unknown"}, {"adapter": "stored", "adapter_code": "print(1)"},
                   {"adapter_code": ""}, {"adapter_code": "x" * 40000}):
        with pytest.raises(ValueError):
            state.runner.run(owner, imported, "build", {}, **kwargs)
    config, digest = state.runner.stage(owner, imported, tmp_path)
    with state.database.connect() as db:
        db.execute("INSERT INTO runner_builds VALUES ('build',?,?,?,?,?,1)",
                   (imported, config["commit_sha"], config["configuration_revision"], digest, "image"))
    with pytest.raises(HTTPException) as exc:
        state.runner.run(owner, imported, "build", {}, adapter="stored")
    assert exc.value.status_code == 409 and "onboarding" in exc.value.detail


def test_onboarding_budget_includes_smoke_and_retains_failed_accounting(agent, monkeypatch):
    state, service, owner, imported = agent
    script(service, monkeypatch, [call("write_adapter", code=GOOD), call("run_smoke", task={"question": "hi"})])
    monkeypatch.setattr(state.runner, "run", lambda *args, **kwargs: {
        "run_id": "budget-run", "stop_reason": "completed", "exit_code": 0, "output": {"ok": True},
        "stderr_tail": "", "wall_time_seconds": 1,
        "gateway": {"calls": 1, "estimated_cost_usd": 0.02, "unknown_cost_calls": 0}})
    job = finished(service, owner, imported, service.start_onboarding(owner, imported, max_spend_usd=0.01))
    assert job["status"] == "failed" and "budget exhausted" in job["result"]["reason"]
    assert job["result"]["target_usage"]["estimated_cost_usd"] == 0.02
    with state.database.connect() as db:
        assert db.execute("SELECT max_spend_usd FROM gateway_keys").fetchone()[0] == 0
    for invalid in (0, -1, float("nan"), float("inf"), 2, True):
        with pytest.raises(ValueError):
            service.start_onboarding(owner, imported, max_spend_usd=invalid)


def test_failed_draft_is_reviewable_input_for_new_onboarding(agent, monkeypatch):
    state, service, owner, imported = agent
    with state.database.connect() as db:
        db.execute("INSERT INTO agent_jobs VALUES ('prior',?,'onboarding','failed','{}',1,1)", (imported,))
    service.event('prior', 'adapter', {'code': GOOD, 'lines': 3})
    seen = script(service, monkeypatch, [call('finish', outcome='blocked', summary='Review stopped; no imported code executed in this test.')])
    job = finished(service, owner, imported, service.start_onboarding(owner, imported))
    assert job['status'] == 'blocked'
    brief = json.loads(seen[0][1]['content'].split('\n', 1)[1])
    assert brief['previous_failed_draft'] == GOOD
    assert 'restoring every original API parameter' in brief['recovery_guidance']
    with pytest.raises(HTTPException):
        service.adapter(owner, imported)


def test_context_is_compacted_once_large_and_recent_results_stay_whole():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}]
    for index in range(8):
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{index}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{index}", "content": f"result {index} " + "x" * 20000})
    assert agent_service.compact(messages[:6]) == (0, 40021)
    cut, size = agent_service.compact(messages)
    assert cut == 4 and size < 90000
    results = [message["content"] for message in messages if message["role"] == "tool"]
    assert all(text.endswith(agent_service.ELIDED) and text.startswith("result") and len(text) < 500 for text in results[:4])
    assert all(len(text) > 20000 for text in results[4:])
    # Already-cut results are not cut again, so the cached prefix stays stable.
    assert agent_service.compact(messages)[0] == 0


def test_cache_points_mark_only_the_prefix_and_newest_message_without_changing_history():
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "go"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "c"}]}, {"role": "tool", "tool_call_id": "c", "content": "out"}]
    marked = agent_service.with_cache_points(messages)
    assert marked[0]["content"] == [{"type": "text", "text": "rules", "cache_control": {"type": "ephemeral"}}]
    assert marked[3]["content"][0]["cache_control"] == {"type": "ephemeral"} and marked[3]["tool_call_id"] == "c"
    assert marked[1] == messages[1] and marked[2] == messages[2]
    assert all(isinstance(message["content"], str) for message in messages)


def test_managed_context_adds_notes_and_warns_before_the_turn_limit(agent, monkeypatch):
    state, service, owner, imported = agent
    monkeypatch.setattr(agent_service, "MAX_TURNS", 8)
    seen = script(service, monkeypatch, [call("note", text="core.py:140 re-sends history"), call("list_files"), call("list_files"),
                                         call("finish", outcome="blocked", summary="Stopped when told the budget was nearly used.")])
    job = finished(service, owner, imported, service.start_onboarding(owner, imported))
    assert job["status"] == "blocked"
    events = service.events(owner, imported, job["job_id"])["events"]
    assert [e["data"] for e in events if e["kind"] == "ledger"] == [{"text": json.dumps({"text": "core.py:140 re-sends history"})}]
    assert any(e["kind"] == "context" and e["data"].get("warning") for e in events)
    assert "CONTEXT BUDGET" in seen[0][0]["content"]
    # The warning arrives as a user message once, while turns remain.
    assert sum("turns left" in m.get("content", "") for m in seen[-1] if m["role"] == "user") == 1


def test_naive_context_mode_sends_the_transcript_unchanged(agent, monkeypatch):
    state, service, owner, imported = agent
    service.settings = dataclasses.replace(service.settings, agent_context="naive")
    seen = script(service, monkeypatch, [call("finish", outcome="blocked", summary="Nothing to do in this test.")])
    job = finished(service, owner, imported, service.start_onboarding(owner, imported))
    assert job["status"] == "blocked" and "CONTEXT BUDGET" not in seen[0][0]["content"]


def test_task_suggestions_are_validated_drafts_and_save_nothing(agent, monkeypatch):
    state, service, owner, imported = agent
    with pytest.raises(HTTPException) as missing:
        service.suggest_tasks(owner, imported)
    assert missing.value.status_code == 404  # no adapter yet, so no model call
    with state.database.connect() as db:
        db.execute("INSERT INTO import_adapters (import_id,content,sha256,example_task,job_id,created_at) VALUES (?,?,?,?,?,?)",
                   (imported, '"""Reads question. Prints answer and done."""\n', "a" * 64, json.dumps({"task": {"question": "hi"}}), "job", 1))
    seen = script(service, monkeypatch, [call("propose_tasks", tasks=[
        {"name": "Greets", "description": "Answers a greeting.", "input": {"question": "hello"}, "checks": [
            {"pointer": "/done", "field_type": "boolean", "exact_json": "true"},
            {"pointer": "/answer", "field_type": "string", "exact_json": "not json"},  # exact value dropped, type check kept
            {"pointer": "no-slash", "field_type": "string"}]},                       # invalid pointer dropped
        {"name": "Has a command", "description": "x", "input": {"question": "sudo rm -rf /tmp/x"}, "checks": []}])])  # refused by the schema
    monkeypatch.setattr(service.gateway, "summarize_key", lambda key: {"estimated_cost_usd": 0.01})
    result = service.suggest_tasks(owner, imported)
    assert [task["name"] for task in result["tasks"]] == ["Greets"] and result["saved"] is False
    assert result["tasks"][0]["required_fields"] == [
        {"pointer": "/done", "field_type": "boolean", "check_exact": True, "exact_value": True},
        {"pointer": "/answer", "field_type": "string", "check_exact": False, "exact_value": None}]
    assert "Reads question" in seen[0][1]["content"]
    with state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM task_contracts WHERE import_id=?", (imported,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM gateway_keys WHERE run_label LIKE 'hansa-suggest-%' AND revoked=0").fetchone()[0] == 0
    assert agent_service.JOB_LOCK.acquire(blocking=False)
    agent_service.JOB_LOCK.release()
