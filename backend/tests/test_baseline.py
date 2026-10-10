import io
import json
from types import SimpleNamespace
import sys

import pytest

from backend.app.runner.baseline import score, combine
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
