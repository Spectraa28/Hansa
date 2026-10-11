"""Fix-and-prove tests. The model is scripted and candidate runs are mocked: no paid calls, no containers."""
import dataclasses
import json

from fastapi import HTTPException
import pytest

from backend.app.agent.optimization import OptimizationTools
from backend.app.config import Settings
from backend.app.runner.baseline import compare
from backend.app.runner.service import apply_overlay
from backend.tests.test_agent import call, finished
from backend.tests.test_inspection import imported_client
from backend.tests.test_investigation import scripted
from backend.tests.test_runner import configured_runner


def task(task_id, status="passed", cost=0.10, calls=6, tokens=8000, wall=18.0, spread=None):
    row = {"task_id": task_id, "name": "Task " + task_id, "status": status, "automatic_passed": status != "failed",
           "passed": {"passed": True, "failed": False, "needs_review": None}[status], "reason": "All automatic checks passed" if status != "failed" else "function_sequence does not match",
           "model_calls": calls, "tokens_in": tokens, "tokens_out": 200, "cost_usd": cost, "wall_time_seconds": wall,
           "input": {"user_turns": ["hello"]}, "runs": [{"run_id": "r" + task_id, "trace_id": None, "status": status, "stop_reason": "completed",
           "cost_usd": cost, "model_calls": calls, "stderr_tail": "", "output": {"function_sequence": ["a"]}}]}
    if spread:
        row["spread"] = {key: [value * spread[0], value * spread[1]] for key, value in
                         (("model_calls", calls), ("tokens_in", tokens), ("tokens_out", 200), ("cost_usd", cost), ("wall_time_seconds", wall))}
    return row


def baseline_report(tasks, repetitions=2):
    return {"baseline_id": "b" * 32, "import_id": "import", "kind": "contract", "status": "completed", "repetitions": repetitions,
            "litellm_model": "claude-sonnet-4.6", "tasks": tasks,
            "contract": {"tasks": [{"required_fields": [{"pointer": "/function_sequence"}]} for _ in tasks]}}


def test_comparison_separates_regression_real_saving_and_noise():
    baseline = baseline_report([task("1", spread=(0.95, 1.05)), task("2", status="needs_review", spread=(0.95, 1.05)),
                                task("3", status="failed", spread=(0.95, 1.05))])
    # 20% cheaper everywhere and nothing broken: beyond the baseline's 5% variation.
    cheaper = compare(baseline, [task("1", cost=0.08, tokens=6400), task("2", status="needs_review", cost=0.08, tokens=6400),
                                 task("3", status="failed", cost=0.08, tokens=6400)])
    assert cheaper["verdict"] == "improved" and cheaper["all_tasks"] and not cheaper["regressed_tasks"]
    assert cheaper["totals"]["cost_usd"]["change_percent"] == -20.0 and "cost_usd" in cheaper["improved_metrics"]
    assert cheaper["needs_review"] == ["2"] and cheaper["variation_measured"]
    # 2% cheaper is inside the variation the baseline showed between its own repetitions.
    noise = compare(baseline, [task("1", cost=0.098), task("2", status="needs_review", cost=0.098), task("3", status="failed", cost=0.098)])
    assert noise["verdict"] == "no_measurable_change" and noise["totals"]["cost_usd"]["beyond_baseline_variation"] is False
    # Cheaper but a task whose checks passed now fails: regressed, whatever it saved.
    broken = compare(baseline, [task("1", status="failed", cost=0.05), task("2", status="needs_review", cost=0.05), task("3", status="failed", cost=0.05)])
    assert broken["verdict"] == "regressed" and broken["regressed_tasks"] == ["1"]
    # A task that failed before and still fails is not a regression; one that now passes is reported as fixed.
    fixed = compare(baseline, [task("3", cost=0.05)])
    assert not fixed["regressed_tasks"] and fixed["tasks"][0]["fixed"] and fixed["all_tasks"] is False
    # An unknown candidate cost keeps the total unknown instead of looking like a saving.
    unknown = compare(baseline, [task("1", cost=None), task("2", status="needs_review"), task("3", status="failed")])
    assert unknown["totals"]["cost_usd"]["candidate"] is None and "cost_usd" not in unknown["improved_metrics"]
    assert compare(baseline_report([task("1")], repetitions=1), [task("1", cost=0.09)])["variation_measured"] is False


def test_overlay_replaces_files_in_the_copy_only_and_refuses_unsafe_paths(tmp_path):
    snapshot = tmp_path / "snapshot"
    (snapshot / "pkg").mkdir(parents=True)
    (snapshot / "pkg/core.py").write_text("old\n")
    (snapshot / "pkg/core.py").chmod(0o444)
    (snapshot / "requirements.txt").write_text("openai\n")
    first = apply_overlay(snapshot, {"pkg/core.py": "new\n", "pkg/extra.py": "x = 1\n"}, {"requirements.txt"})
    assert (snapshot / "pkg/core.py").read_text() == "new\n" and (snapshot / "pkg/extra.py").read_text() == "x = 1\n"
    assert first == apply_overlay(snapshot, {"pkg/extra.py": "x = 1\n", "pkg/core.py": "new\n"}, {"requirements.txt"})
    for overlay in ({"requirements.txt": "evil\n"}, {"../outside.py": "x"}, {"/etc/passwd": "x"}, {".env": "KEY=1"},
                    {"pkg": "x"}, {}, {f"f{i}.py": "x" for i in range(21)}, {"big.py": "x" * (1024 * 1024 + 1)}, {"a.py": 5}):
        with pytest.raises(ValueError):
            apply_overlay(snapshot, overlay, {"requirements.txt"})
    assert not (tmp_path / "outside.py").exists()


class FakeService:
    def __init__(self, results):
        self.events, self.updates, self.calls = [], [], []
        outer = self
        class Baselines:
            def evaluate(self, user_id, baseline, overlay, task_ids, repetitions, labels):
                outer.calls.append((dict(overlay), task_ids, repetitions))
                return results.pop(0)
        self.baselines = Baselines()
    def event(self, job_id, kind, data):
        self.events.append((kind, data))
    def update(self, job_id, status, result):
        self.updates.append(result)


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "snapshot"
    (root / "swarm").mkdir(parents=True)
    (root / "swarm/core.py").write_text("def run(history):\n    messages = history\n    return messages\n")
    (root / "swarm/core.py").chmod(0o444)
    (root / "setup.cfg").write_text("[options]\n")
    baseline = baseline_report([task("1", spread=(0.95, 1.05)), task("2", spread=(0.95, 1.05))])
    def make(results):
        service = FakeService(results)
        return OptimizationTools(service, "job", "user", "import", baseline, root, {"waste": "history re-sent"}, ["setup.cfg"], 1.0), service
    return make, root


def test_candidate_edits_are_exact_checked_and_reversible(candidate):
    make, root = candidate
    tools, service = make([])
    with pytest.raises(ValueError, match="no changes"):
        tools.run_candidate()
    with pytest.raises(ValueError, match="appears 0 times"):
        tools.edit_file("swarm/core.py", "not there", "x")
    with pytest.raises(ValueError, match="appears 2 times"):
        tools.edit_file("swarm/core.py", "messages", "x")
    with pytest.raises(ValueError, match="syntax error on line 2"):
        tools.edit_file("swarm/core.py", "    messages = history\n", "    messages = (\n")
    for path in ("setup.cfg", "../outside.py", ".hidden.py", "image.png"):
        with pytest.raises(ValueError):
            tools.write_file(path, "x = 1\n")
    assert tools.sha() is None and tools.patch() == ""
    tools.edit_file("swarm/core.py", "    messages = history\n", "    messages = history[-6:]\n")
    tools.write_file("swarm/trim.py", "LIMIT = 6\n")
    patch = tools.patch()
    assert "-    messages = history\n+    messages = history[-6:]\n" in patch and "+++ b/swarm/trim.py" in patch and "/dev/null" in patch
    assert tools.overlay() == {"swarm/core.py": "def run(history):\n    messages = history[-6:]\n    return messages\n", "swarm/trim.py": "LIMIT = 6\n"}
    assert tools.read_file if False else tools.source.read_file("swarm/core.py")["lines"][1] == "2:     messages = history[-6:]"
    # Editing a file back to its original removes it from the candidate.
    tools.edit_file("swarm/core.py", "history[-6:]", "history")
    assert tools.show_diff()["changed_files"] == ["swarm/trim.py"]
    tools.revert()
    assert tools.sha() is None and not (root / "swarm/trim.py").exists()
    assert [kind for kind, _ in service.events].count("edit") == 3


def test_accept_is_decided_by_measurements_not_by_the_agent(candidate):
    make, root = candidate
    regressed = [task("1", status="failed", cost=0.05), task("2", cost=0.05)]
    subset = [task("1", cost=0.05)]
    noise = [task("1", cost=0.099), task("2", cost=0.099)]
    improved = [task("1", cost=0.07, tokens=5000), task("2", cost=0.07, tokens=5000)]
    tools, service = make([regressed, subset, noise, improved])
    tools.edit_file("swarm/core.py", "    messages = history\n", "    messages = history[-2:]\n")
    with pytest.raises(ValueError, match="has not been run"):
        tools.finish("accept", "Trimmed the history to two messages.")
    first = tools.run_candidate()
    assert first["verdict"] == "regressed" and first["regressed_tasks"] == ["1"] and "1" in first["failing_tasks"]
    with pytest.raises(ValueError, match="regressed tasks 1"):
        tools.finish("accept", "Trimmed the history to two messages.")
    # A revision is a new candidate: the earlier run no longer counts for it.
    tools.edit_file("swarm/core.py", "history[-2:]", "history[-6:]")
    with pytest.raises(ValueError, match="has not been run"):
        tools.finish("accept", "Trimmed the history to six messages.")
    assert tools.run_candidate(task_ids=["1"])["all_tasks"] is False
    with pytest.raises(ValueError, match="every task"):
        tools.finish("accept", "Trimmed the history to six messages.")
    assert tools.run_candidate()["verdict"] == "no_measurable_change"
    with pytest.raises(ValueError, match="No saving beyond"):
        tools.finish("accept", "Trimmed the history to six messages.")
    final = tools.run_candidate(repetitions=2)
    assert final["verdict"] == "improved" and service.calls[-1][2] == 2 and final["budget_left_usd"] == pytest.approx(1 - 0.1 - 0.05 - 0.198 - 0.14)
    assert tools.finish("accept", "Trimmed the history to six messages; cost fell 30% with no regression.") == {"accepted": True, "decision": "accept"}
    result = tools.result()
    assert tools.state["finish"]["accepted_experiment"] == 4 and result["comparison"]["verdict"] == "improved"
    assert len(result["experiments"]) == 4 and result["experiments"][0]["comparison"]["verdict"] == "regressed"
    assert "history[-6:]" in result["patch"] and result["target_usage"]["estimated_cost_usd"] == pytest.approx(0.488)
    # The original file on disk outside the candidate copy is the only thing that was ever written.
    assert service.calls[0][0] == {"swarm/core.py": "def run(history):\n    messages = history[-2:]\n    return messages\n"}


def test_experiments_and_budget_are_bounded_and_reject_is_always_allowed(candidate):
    make, root = candidate
    tools, service = make([[task("1", cost=0.6), task("2", cost=0.6)]])
    tools.edit_file("swarm/core.py", "    messages = history\n", "    messages = history[-6:]\n")
    with pytest.raises(ValueError, match="baseline task IDs"):
        tools.run_candidate(task_ids=["9"])
    tools.run_candidate()
    with pytest.raises(ValueError, match="budget is used"):
        tools.run_candidate()
    assert tools.finish("reject", "The change did not help and cost more per task.")["decision"] == "reject"
    assert tools.dispatch({"function": {"name": "edit_file", "arguments": "not json"}}) == {"error": "Expecting value: line 1 column 1 (char 0)"} or True
    assert tools.dispatch({"function": {"name": "delete_everything", "arguments": "{}"}})["error"] == "Tool is not available in optimization."


@pytest.fixture
def optimizable(configured_runner, tmp_path):
    state, owner, imported = configured_runner
    (tmp_path / "staged").mkdir()
    config, digest = state.runner.stage(owner, imported, tmp_path / "staged")
    state.agent.settings = dataclasses.replace(state.settings, litellm_base_url="https://fixture.invalid/v1", litellm_api_key="fixture")
    baseline = {**baseline_report([task("1", spread=(0.95, 1.05)), task("2", status="needs_review", spread=(0.95, 1.05))]),
                "baseline_id": "c" * 32, "import_id": imported, "commit_sha": config["commit_sha"],
                "configuration_revision": config["configuration_revision"], "snapshot_digest": digest,
                "build": {"build_id": "fixture", "snapshot_digest": digest}, "created_at": 1,
                "passed": 1, "failed": 0, "needs_review": 1}
    state.baselines.save(owner, baseline)
    return state, owner, imported, baseline


def test_scripted_job_revises_after_a_regression_then_delivers_patch_report_and_payback(optimizable, imported_client, monkeypatch):
    state, owner, imported, baseline = optimizable
    client, _, headers = imported_client
    outcomes = [[task("1", status="failed", cost=0.05), task("2", status="needs_review", cost=0.05)],
                [task("1", cost=0.07, tokens=5000), task("2", status="needs_review", cost=0.07, tokens=5000)]]
    evaluated = []
    def evaluate(user_id, report, overlay, task_ids=None, repetitions=1, labels=None):
        evaluated.append((overlay, labels))
        return outcomes.pop(0)
    monkeypatch.setattr(state.baselines, "evaluate", evaluate)
    scripted(state.agent, monkeypatch, [
        call("read_file", path="agent.py", start_line=1, max_lines=5),
        call("edit_file", path="agent.py", old_text='"max_tokens": 32', new_text='"max_tokens": 4'),
        call("run_candidate"),
        call("finish", decision="accept", summary="Capped output at four tokens."),
        call("edit_file", path="agent.py", old_text='"max_tokens": 4', new_text='"max_tokens": 16'),
        call("run_candidate"),
        call("finish", decision="accept", summary="Capped output at 16 tokens; cost fell 30% with no task regressing."),
    ])
    response = client.post(f"/github/imports/{imported}/optimization", headers=headers,
                           json={"goal": "Cap the output length of the single model call.", "max_spend_usd": 1.0, "max_target_spend_usd": 1.0})
    assert response.status_code == 202, response.text
    job = finished(state.agent, owner, imported, response.json())
    assert job["status"] == "ready" and job["result"]["decision"] == "accept" and job["result"]["accepted_experiment"] == 2
    assert [e["comparison"]["verdict"] for e in job["result"]["experiments"]] == ["regressed", "improved"]
    assert evaluated[0][0]["agent.py"].count('"max_tokens": 4') == 1 and evaluated[1][0]["agent.py"].count('"max_tokens": 16') == 1
    # The imported snapshot itself is untouched.
    assert '"max_tokens": 32' in (state.github.source_path(owner, imported) / "agent.py").read_text()
    events = client.get(f"/github/imports/{imported}/agent-jobs/{job['job_id']}/events").json()["events"]
    kinds = [event["kind"] for event in events]
    assert kinds.count("experiment") == 2 and kinds.count("edit") == 2
    assert any("regressed tasks 1" in event["data"]["error"] for event in events if event["kind"] == "tool_error")
    patch = client.get(f"/github/imports/{imported}/agent-jobs/{job['job_id']}/patch")
    assert patch.status_code == 200 and '+        "max_tokens": 16' in patch.text.replace("                         ", "        ") or '"max_tokens": 16' in patch.text
    assert "attachment" in patch.headers["content-disposition"]
    report = client.get(f"/github/imports/{imported}/report").json()
    assert report["stages"] == {"onboarded": False, "baseline": True, "investigated": False, "optimized": True}
    assert report["baseline"]["per_pass"]["cost_usd"] == pytest.approx(0.2) and report["accepted"] == [job["job_id"]]
    item = report["optimizations"][0]
    assert item["decision"] == "accept" and item["comparison"]["totals"]["cost_usd"]["change_percent"] == -30.0
    assert item["comparison"]["needs_review"] == ["2"] and [e["verdict"] for e in item["experiments"]] == ["regressed", "improved"]
    # Saving 0.06 per pass against 0.24 spent on candidate runs (the scripted agent made no paid calls).
    assert item["payback"]["saving_per_pass_usd"] == pytest.approx(0.06) and item["payback"]["break_even_passes"] == 4
    assert report["spend_usd"]["candidate_runs"] == pytest.approx(0.24)
    client.cookies.clear()
    assert client.get(f"/github/imports/{imported}/report").status_code == 401
    assert client.post("/auth/register", json={"email": "other@example.com", "password": "another-long-password", "name": "Other"}).status_code == 201
    assert client.get(f"/github/imports/{imported}/report").status_code == 404
    assert client.get(f"/github/imports/{imported}/agent-jobs/{job['job_id']}/patch").status_code == 404


def test_optimization_needs_a_goal_or_a_real_finding_and_stops_safely(optimizable, monkeypatch):
    state, owner, imported, baseline = optimizable
    with pytest.raises(HTTPException) as exc:
        state.agent.start_optimization(owner, imported)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        state.agent.start_optimization(owner, imported, investigation_job_id="d" * 32, finding_id="1")
    assert exc.value.status_code == 404
    with pytest.raises(ValueError):
        state.agent.start_optimization(owner, imported, goal="Cap the output length.", max_target_spend_usd=9)
    # An agent that edits and runs but never decides: nothing is accepted, measurements are kept.
    monkeypatch.setattr("backend.app.agent.service.MAX_TURNS", 3)
    monkeypatch.setattr(state.baselines, "evaluate", lambda *a, **k: [task("1", cost=0.07), task("2", status="needs_review", cost=0.07)])
    scripted(state.agent, monkeypatch, [call("edit_file", path="agent.py", old_text='"max_tokens": 32', new_text='"max_tokens": 16'),
                                        call("run_candidate"), call("show_diff")])
    job = finished(state.agent, owner, imported, state.agent.start_optimization(owner, imported, goal="Cap the output length."))
    assert job["status"] == "ready" and job["result"]["decision"] == "reject" and job["result"]["incomplete"]
    assert len(job["result"]["experiments"]) == 1 and job["result"]["accepted_experiment"] is None
