import io
import json
from types import SimpleNamespace
import sys
import dataclasses
import hashlib
from fastapi import HTTPException

import pytest

from backend.app.runner.baseline import score, combine, score_task, field_reason, equal_json
from backend.app.contracts.schemas import ContractInput, ConfirmInput
from backend.app.agent.service import JOB_LOCK
from backend.tests.test_contracts import content
from backend.app.runner import airline_adapter
from backend.tests.test_runner import configured_runner
from backend.tests.test_inspection import imported_client


@pytest.mark.parametrize("output, expected, passed, actual", [
    ({"messages": [{"role": "assistant", "tool_calls": [1]}, {"role": "tool", "tool_name": "transfer"}]}, "transfer", True, "transfer"),
    ({"messages": [{"role": "assistant", "tool_calls": None, "content": "Hello"}]}, "None", True, "None"),
    ({"messages": [{"role": "tool", "tool_name": "wrong"}]}, "transfer", False, "wrong"),
    ({"messages": []}, "None", False, "None"),
    (None, "None", False, None),
])
def test_upstream_function_scoring(output, expected, passed, actual):
    assert score(output, expected) == (passed, actual)


def test_adapter_calls_existing_swarm_once_without_retries(monkeypatch, capsys):
    calls = []
    agent = SimpleNamespace(name="Triage Agent", functions=[
        SimpleNamespace(__name__="transfer_to_flight_modification"),
        SimpleNamespace(__name__="transfer_to_lost_baggage")])
    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"max_retries": 0, "timeout": 60}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    class Swarm:
        def __init__(self, client):
            assert isinstance(client, Client)
        def run(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(messages=[{"role": "tool", "tool_name": "transfer"}], agent=agent)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=Client))
    monkeypatch.setitem(sys.modules, "swarm", SimpleNamespace(Swarm=Swarm))
    monkeypatch.setitem(sys.modules, "configs", SimpleNamespace(agents=SimpleNamespace(triage_agent=agent)))
    monkeypatch.setattr(sys, "path", sys.path.copy())
    conversation = [{"role": "user", "content": "My bag is missing"}]
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"agent": "triage_agent", "conversation": conversation})))
    airline_adapter.main()
    assert calls == [{"agent": agent, "messages": conversation, "max_turns": 1, "stream": False}]
    assert json.loads(capsys.readouterr().out)["messages"][0]["tool_name"] == "transfer"


def test_baseline_stores_per_case_metrics_and_owner_scoped_endpoint(configured_runner, imported_client, monkeypatch, tmp_path):
    state, owner, imported = configured_runner
    client, _, _ = imported_client
    snapshot = state.github.source_path(owner, imported)
    cases = snapshot / "examples/airline/evals/eval_cases"
    cases.mkdir(parents=True)
    for name in ["triage_cases.json", "flight_modification_cases.json"]:
        (cases / name).write_text(json.dumps([{"conversation": [{"role": "user", "content": "Hello"}], "function": "None"}]))
    config, digest = state.runner.stage(owner, imported, tmp_path)
    monkeypatch.setattr(state.runner, "build", lambda *a: {"build_id": "build", "snapshot_digest": digest})
    invocations = []
    def run(*args, **kwargs):
        invocations.append((args, kwargs))
        return {"run_id": "fixture-run", "stop_reason": "completed", "output": {"messages": [{"role": "assistant", "content": "Hello"}]},
            "gateway": {"calls": 1, "prompt_tokens": 20, "completion_tokens": 4,
                        "estimated_cost_usd": None, "unknown_cost_calls": 1, "unknown_usage_calls": 0, "models": []},
            "wall_time_seconds": 0.5}
    monkeypatch.setattr(state.runner, "run", run)
    report = state.baselines.airline(owner, imported)
    assert report["passed"] == 2 and report["total"] == 2 and report["status"] == "completed"
    assert all(task["cost_usd"] is None and task["tokens_in"] == 20 for task in report["tasks"])
    assert all("function" not in args[3] and kwargs["max_calls"] == 1 for args, kwargs in invocations)
    endpoint = f"/github/imports/{imported}/baseline"
    assert client.get(endpoint).json() == report
    client.cookies.clear()
    assert client.get(endpoint).status_code == 401
    assert client.post("/auth/register", json={"email": "other@example.com", "password": "another-long-password", "name": "Other"}).status_code == 201
    assert client.get(endpoint).status_code == 404
    state.github.delete_import(owner, imported)
    with state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM baselines").fetchone()[0] == 0


def test_repeated_runs_report_mean_spread_and_keep_unknowns_unknown():
    def run(passed, cost, calls, seconds, hosts):
        return {"passed": passed, "actual_function": "f", "run_id": "r", "stop_reason": "completed",
                "model_calls": calls, "tokens_in": 100, "tokens_out": 10, "cost_usd": cost,
                "unknown_cost_calls": int(cost is None), "unknown_usage_calls": 0, "models": [],
                "wall_time_seconds": seconds, "external_calls": len(hosts), "external_denied": 0, "external_hosts": hosts}
    single = run(True, 0.01, 2, 1.0, ["a.example"])
    assert combine([single]) == single
    task = combine([run(True, 0.01, 2, 1.0, ["a.example"]), run(False, 0.03, 4, 3.0, ["b.example"])])
    assert task["passed"] is False and task["pass_rate"] == 0.5 and len(task["runs"]) == 2
    assert task["cost_usd"] == pytest.approx(0.02) and task["spread"]["cost_usd"] == [0.01, 0.03]
    assert task["model_calls"] == 3 and task["spread"]["wall_time_seconds"] == [1.0, 3.0]
    assert task["external_hosts"] == ["a.example", "b.example"]
    unknown = combine([run(True, 0.01, 1, 1.0, []), run(True, None, 1, 1.0, [])])
    assert unknown["cost_usd"] is None and unknown["spread"]["cost_usd"] is None and unknown["unknown_cost_calls"] == 1


def test_baseline_repetitions_are_bounded(configured_runner):
    state, owner, imported = configured_runner
    for value in (0, 6, True, "2"):
        with pytest.raises(ValueError):
            state.baselines.airline(owner, imported, repetitions=value)


@pytest.mark.parametrize("output,rule,reason", [
    ({"a/b": {"~": [3]}}, {"pointer": "/a~1b/~0/0", "field_type": "integer"}, None),
    ({"value": True}, {"pointer": "/value", "field_type": "integer"}, "must be integer"),
    ({"value": 1}, {"pointer": "/value", "field_type": "boolean"}, "must be boolean"),
    ({"value": None}, {"pointer": "/value", "field_type": "null"}, None),
    ({}, {"pointer": "/value", "field_type": "null"}, "Missing required field"),
    ([1], {"pointer": "/01", "field_type": "number"}, "Missing required field"),
    ([1], {"pointer": "/-", "field_type": "number"}, "Missing required field"),
    ({"value": "bad"}, {"pointer": "/value", "field_type": "string", "check_exact": True, "exact_value": "ok"}, "Exact value mismatch"),
])
def test_field_rules(output, rule, reason):
    actual = field_reason(output, {"check_exact": False, **rule})
    assert actual is None if reason is None else reason in actual


def test_expected_output_and_human_review_are_separate():
    contract = ContractInput.model_validate(content("a" * 32)).model_dump(mode="json")
    task = contract["tasks"][0]
    result = score_task({"status": "needs_information"}, task, contract)
    assert result["status"] == "needs_review" and result["passed"] is None and result["automatic_passed"]
    assert all(r["status"] == "needs_review" for r in result["requirements"])
    task["required_evidence"] = [{"description": "Status required", "verification": "automatic", "rule": task["required_fields"][0]}]
    failed = score_task({"status": "wrong"}, task, contract)
    assert failed["status"] == "failed" and failed["passed"] is False
    assert "expected_output" in failed["reason"] and "Exact value" in failed["reason"]
    assert failed["requirements"][-1]["status"] == "needs_review"
    assert any(r["status"] == "failed" for r in failed["requirements"])
    assert score_task({"status": "needs_information"}, task, contract, "timeout")["status"] == "failed"
    assert not equal_json({"a": [True]}, {"a": [1]})
    assert equal_json({"a": [1]}, {"a": [1.0]})


@pytest.fixture
def contract_baseline(configured_runner, monkeypatch):
    state, owner, imported = configured_runner
    state.runner.settings = dataclasses.replace(state.settings, litellm_base_url="https://fixture.invalid", litellm_api_key="fixture")
    config = state.runner.configuration(owner, imported)
    body = content(config["configuration_revision"])
    saved = state.contracts.save(owner, imported, ContractInput.model_validate(body))
    state.contracts.confirm(owner, imported, ConfirmInput(version=saved["version"], configuration_revision=config["configuration_revision"]))
    code = "import json\nprint(json.dumps({'status': 'needs_information'}))\n"
    with state.database.connect() as db:
        db.execute("INSERT INTO import_adapters VALUES (?,?,?,'{}','fixture',1)", (imported, code, hashlib.sha256(code.encode()).hexdigest()))
    monkeypatch.setattr(state.runner, "build", lambda *a: {"build_id": "fixture"})
    calls = []
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return {"run_id": str(len(calls)), "stop_reason": "completed", "output": {"status": "needs_information"},
                "gateway": {"calls": 1, "prompt_tokens": 20, "completion_tokens": 4, "estimated_cost_usd": 0.001,
                            "unknown_cost_calls": 0, "unknown_usage_calls": 0, "models": []},
                "wall_time_seconds": 0.5, "trace": {"status": "queued", "trace_id": "trace-" + str(len(calls))},
                "egress": {"allowed": 1, "denied": 0, "hosts": {"example.com": {}}}}
    monkeypatch.setattr(state.runner, "run", run)
    return state, owner, imported, calls, code


def wait_baseline(service, owner, imported, job):
    thread = service.threads.get(job["baseline_id"])
    if thread:
        thread.join(10)
        assert not thread.is_alive()
    return service.get(owner, imported, job["baseline_id"])


def test_generic_background_baseline_events_metrics_and_security(contract_baseline, imported_client):
    state, owner, imported, calls, code = contract_baseline
    client, _, headers = imported_client
    endpoint = f"/github/imports/{imported}/baseline"
    assert client.post(endpoint, json={"repetitions": 2}).status_code == 403
    assert client.post(endpoint, headers=headers, json={"repetitions": True}).status_code == 422
    response = client.post(endpoint, headers=headers, json={"repetitions": 2})
    assert response.status_code == 202
    report = wait_baseline(state.baselines, owner, imported, response.json())
    assert report["status"] == "completed" and report["needs_review"] == 1 and report["passed"] == report["failed"] == 0
    task = report["tasks"][0]
    assert task["passed"] is None and task["pass_rate"] is None and task["trace_ids"] == ["trace-1", "trace-2"]
    assert task["model_calls"] == 1 and task["tokens_in"] == 20 and task["cost_usd"] == 0.001 and task["external_calls"] == 1
    assert [run["repetition"] for run in task["runs"]] == [1, 2]
    assert all(kwargs["adapter_code"] == code and args[3] == report["contract"]["tasks"][0]["input"] for args, kwargs in calls)
    assert all("expected_output" not in args[3] for args, _ in calls)
    assert client.get(endpoint).json() == report
    job_url = f"/github/imports/{imported}/baseline-jobs/{report['baseline_id']}"
    assert client.get(job_url).json() == report
    events = client.get(job_url + "/events").json()["events"]
    assert [event["kind"] for event in events] == ["started", "build", "run", "run", "task", "finished"]
    assert len(client.get(job_url + "/events", params={"after": events[-2]["id"]}).json()["events"]) == 1
    client.cookies.clear()
    assert client.get(job_url).status_code == 401
    client.post("/auth/register", json={"email": "other@example.com", "password": "another-long-password", "name": "Other"})
    assert client.get(job_url).status_code == client.get(job_url + "/events").status_code == 404
    state.github.delete_import(owner, imported)
    with state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM baseline_events").fetchone()[0] == 0


def test_baseline_preconditions_and_shared_job_lock(contract_baseline):
    state, owner, imported, _, _ = contract_baseline
    JOB_LOCK.acquire()
    try:
        with pytest.raises(HTTPException) as exc:
            state.baselines.start(owner, imported)
        assert exc.value.status_code == 409
    finally:
        JOB_LOCK.release()
    with state.database.connect() as db:
        db.execute("DELETE FROM import_adapters WHERE import_id=?", (imported,))
    with pytest.raises(HTTPException) as exc:
        state.baselines.start(owner, imported)
    assert exc.value.status_code == 409
    with state.database.connect() as db:
        db.execute("UPDATE task_contracts SET status='draft' WHERE import_id=?", (imported,))
    with pytest.raises(HTTPException) as exc:
        state.baselines.start(owner, imported)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("failure", ["build", "stale", "unknown", "budget"])
def test_baseline_failure_keeps_partial_results_and_releases_lock(contract_baseline, monkeypatch, failure):
    state, owner, imported, calls, _ = contract_baseline
    original = state.runner.run
    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        if failure == "stale":
            with state.database.connect() as db:
                db.execute("UPDATE repository_inspections SET configuration_revision=? WHERE import_id=?", ("b" * 32, imported))
        if failure == "unknown":
            result["gateway"].update(estimated_cost_usd=None, unknown_cost_calls=1)
        if failure == "budget":
            result["gateway"]["prompt_tokens"] = 10001
        return result
    monkeypatch.setattr(state.runner, "run", run)
    if failure == "build":
        def build(*args):
            raise RuntimeError("Fixture build failure")
        monkeypatch.setattr(state.runner, "build", build)
    job = state.baselines.start(owner, imported, 2)
    report = wait_baseline(state.baselines, owner, imported, job)
    assert report["status"] == "failed" and report["reason"]
    assert len(calls) == (0 if failure == "build" else 1)
    if calls:
        assert len(report["tasks"][0]["runs"]) == 1
    assert JOB_LOCK.acquire(blocking=False)
    JOB_LOCK.release()
    report["status"] = "running"
    state.baselines.save(owner, report)
    state.baselines.recover()
    assert state.baselines.latest(owner, imported)["status"] == "failed"


def test_live_fixture_contract_is_complete_and_bounded():
    from scripts.prove_baseline import fixture_contract
    from backend.app.contracts.schemas import missing_requirements
    contract = ContractInput.model_validate(fixture_contract("a" * 32)).model_dump(mode="json")
    assert not missing_requirements(contract)
    assert len(contract["tasks"]) == 3 and contract["limits"]["max_spend_usd"] == 0.12


@pytest.mark.parametrize("unavailable", [False, True])
def test_proof_keeps_result_and_retries_trace_readback_without_execution(tmp_path, monkeypatch, unavailable):
    from scripts import prove_baseline
    (tmp_path / "var").mkdir()
    monkeypatch.setattr(prove_baseline, "ROOT", tmp_path)
    monkeypatch.setattr(prove_baseline.time, "sleep", lambda _: None)
    calls = []
    def context(*args):
        calls.append(args)
        if unavailable or len(calls) == 1:
            raise HTTPException(502, "Neatlogs get_trace_context refused the request: not_found.")
        return {"status": "finalized"}
    state = SimpleNamespace(traces=SimpleNamespace(context=context))
    report = {"status": "completed", "tasks": [{"runs": [{"trace_id": "trace-123"}]}]}
    if unavailable:
        with pytest.raises(SystemExit):
            prove_baseline.export_report(state, "owner", "import", report)
    else:
        prove_baseline.export_report(state, "owner", "import", report)
    evidence = json.loads((tmp_path / "var/baseline-proof.json").read_text())
    assert evidence["result"] == report
    assert len(calls) == (4 if unavailable else 2)
    assert ("error" in evidence["trace_readback"][0]) == unavailable
