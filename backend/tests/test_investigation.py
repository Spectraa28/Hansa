"""Scripted investigation and trace clients: no paid calls or source execution."""
import dataclasses
import json

from fastapi import HTTPException
import pytest

from backend.app.agent.investigation import CATEGORIES, InvestigationTools, SYSTEM, toolset
from backend.app.agent.service import TOOLS, JOB_LOCK
from backend.app.runner.baseline import measured
from backend.app.sessions import token_hash
from backend.app.tracing.neatlogs import NeatlogsError
from backend.tests.test_agent import call, finished
from backend.tests.test_inspection import imported_client
from backend.tests.test_runner import configured_runner
from backend.tests.test_tracing import traced, run_result


@pytest.fixture
def investigation(traced, tmp_path):
    state, tracer, owner, imported, _ = traced
    (tmp_path / "staged").mkdir()
    config, digest = state.runner.stage(owner, imported, tmp_path / "staged")
    state.agent.settings = dataclasses.replace(state.settings, litellm_base_url="https://fixture.invalid/v1", litellm_api_key="fixture")
    state.agent.tracer = tracer
    result = run_result(cost=0.003, unknown=0)
    result["gateway"].update(unknown_usage_calls=0, models=[])
    result["commit_sha"] = config["commit_sha"]
    with state.database.connect() as db:
        db.execute("UPDATE gateway_keys SET run_label='run-1'")
        db.execute("UPDATE model_calls SET estimated_cost_usd=0.002,cost_source='litellm_response_header' WHERE id=2")
        db.execute("INSERT INTO runner_builds VALUES ('fixture',?,?,?,?,?,1)",
                   (imported, config["commit_sha"], config["configuration_revision"], digest, "image"))
    result["trace"] = tracer.log_run(imported, token_hash("gw_key"), result, {})
    baseline = {"baseline_id": "a" * 32, "import_id": imported, "status": "completed", "commit_sha": config["commit_sha"],
                "configuration_revision": config["configuration_revision"], "snapshot_digest": digest,
                "build": {"build_id": "fixture", "snapshot_digest": digest}, "repetitions": 1,
                "tasks": [{"task_id": "1", "runs": [measured(result, True, None)]}], "created_at": 1}
    with state.database.connect() as db:
        db.execute("INSERT INTO runner_runs VALUES ('run-1',?,'fixture',?,1)", (imported, json.dumps(result)))
    state.baselines.save(owner, baseline)
    return state, tracer, owner, imported, baseline, tmp_path / "staged/snapshot"


def finding(**changes):
    return {"waste": "Repeated system context consumes input tokens.", "run_ids": ["run-1"],
            "source": [{"path": "agent.py", "start_line": 1, "end_line": 3}],
            "estimated_saving": {"tokens": 10, "cost_usd": 0.0001, "method": "Estimate removing ten input tokens at the observed input cost share."},
            "behaviour_risk": "Removing instructions may change correct behaviour.",
            "proposed_change": "Shorten redundant instruction text after reviewing the task contract.", **changes}


def scripted(service, monkeypatch, messages):
    seen = []
    def complete(key, history, tools=None):
        seen.append((key, list(history), tools))
        return messages.pop(0)
    monkeypatch.setattr(service, "complete", complete)
    return seen


def reads():
    return [call("read_baseline"), call("read_run", run_id="run-1"), call("read_trace", run_id="run-1"),
            call("read_file", path="agent.py", start_line=1, max_lines=10)]



def coverage(finding_ids=None):
    return [{"category": category, "status": "finding" if category == "Context" and finding_ids else "checked, nothing found",
             "observation": "Scripted test inspected the measured calls and three source lines.",
             "run_ids": ["run-1"], "source": [{"path": "agent.py", "start_line": 1, "end_line": 3}],
             "finding_ids": finding_ids if category == "Context" and finding_ids else []} for category in CATEGORIES]

def test_investigation_uses_shared_loop_saves_ledger_and_code_evidence_with_missing_trace(investigation, imported_client, monkeypatch):
    state, tracer, owner, imported, baseline, root = investigation
    original = tracer.client.call
    def client(tool, args):
        if tool == "get_trace_context":
            raise NeatlogsError("Neatlogs get_trace_context refused the request: not_found.")
        return original(tool, args)
    tracer.client.call = client
    seen = scripted(state.agent, monkeypatch, [call("read_file", path="agent.py"), call("save_finding", **finding()),
        *reads(), call("save_finding", **finding()), call("finish", coverage=coverage(["1"]), summary="One small, untested instruction compression hypothesis, with behaviour risk.")])
    client, _, headers = imported_client
    url = f"/github/imports/{imported}/investigation"
    assert client.post(url, json={}).status_code == 403
    response = client.post(url, headers=headers, json={"baseline_id": baseline["baseline_id"]})
    assert response.status_code == 202 and response.json()["kind"] == "investigation"
    job = finished(state.agent, owner, imported, response.json())
    assert job["status"] == "ready" and not job["result"]["nothing_worth_changing"]
    saved = job["result"]["findings"][0]
    assert job["result"]["baseline_evidence"]["totals"]["cost_usd"] == 0.003
    assert job["result"]["source_evidence"][0]["lines_read"]
    assert len(job["result"]["coverage"]) == 8
    assert job["result"]["coverage"][0]["finding_ids"] == ["1"]
    run = saved["evidence"]["runs"][0]
    assert run["summary"]["cost_usd"] == 0.003 and run["summary"]["latency_ms"] == 1400
    assert run["calls"][1]["repeated_chars"] == 408 and run["gaps"][0]["gap_ms"] == 700
    assert run["calls"][1]["prompt_chars_by_role"] == {"system": 400, "user": 8, "tool": 4}
    assert "not newly added tool output" in run["coverage"]
    assert run["calls"][0]["tool_calls_requested"] == ["fetch"] and len(run["outside_connections"]) == 3
    assert run["trace"]["status"] == "queued" and "not_found" in run["trace"]["error"]
    assert saved["evidence"]["source"][0]["path"] == "agent.py" and len(saved["evidence"]["source"][0]["sha256"]) == 64
    assert job["result"]["baseline_id"] == baseline["baseline_id"] and job["result"]["trace"]["status"] == "queued"
    events = state.agent.events(owner, imported, job["job_id"])["events"]
    assert events[0]["kind"] == "started" and events[-1]["kind"] == "finished"
    assert [e["kind"] for e in events].count("finding") == 1 and [e["kind"] for e in events].count("tool_error") == 2
    names = {t["function"]["name"] for t in seen[0][2]}
    assert {"read_run", "read_trace", "save_finding"} <= names and not {"write_adapter", "run_smoke"}.intersection(names)
    with state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM gateway_keys WHERE revoked=0").fetchone()[0] == 0
    client.cookies.clear()
    assert client.get(f"/github/imports/{imported}/agent-jobs/{job['job_id']}").status_code == 401
    client.post("/auth/register", json={"email": "other@example.com", "password": "another-long-password", "name": "Other"})
    other_headers = {"X-CSRF-Token": client.get("/auth/me").json()["csrf_token"]}
    assert client.post(url, headers=other_headers, json={}).status_code == 404
    state.github.delete_import(owner, imported)
    with state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_jobs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM agent_events").fetchone()[0] == 0


def test_investigation_can_conclude_nothing_is_worth_changing(investigation, monkeypatch):
    state, _, owner, imported, _, _ = investigation
    scripted(state.agent, monkeypatch, [call("finish", summary="No changes needed."), *reads(),
        call("finish", coverage=coverage(), summary="The live fetch is required and the measured cost is too small to justify changing behaviour.")])
    job = finished(state.agent, owner, imported, state.agent.start_investigation(owner, imported))
    assert job["status"] == "ready" and job["result"]["findings"] == [] and job["result"]["nothing_worth_changing"]


def test_investigation_needs_completed_current_baseline_and_shares_job_lock(investigation, monkeypatch):
    state, _, owner, imported, baseline, _ = investigation
    with pytest.raises(HTTPException):
        state.agent.start_investigation(owner, imported, "b" * 32)
    baseline["status"] = "running"
    state.baselines.save(owner, baseline)
    with pytest.raises(HTTPException):
        state.agent.start_investigation(owner, imported)
    baseline["status"] = "completed"
    state.baselines.save(owner, baseline)
    JOB_LOCK.acquire()
    try:
        with pytest.raises(HTTPException) as exc:
            state.agent.start_investigation(owner, imported)
        assert exc.value.status_code == 409
    finally:
        JOB_LOCK.release()
    baseline["snapshot_digest"] = "f" * 64
    state.baselines.save(owner, baseline)
    scripted(state.agent, monkeypatch, [])
    job = finished(state.agent, owner, imported, state.agent.start_investigation(owner, imported))
    assert job["status"] == "failed" and "stale" in job["result"]["reason"]


def test_finding_bounds_scope_pagination_and_observed_source_lines(investigation):
    state, _, owner, imported, baseline, root = investigation
    with state.database.connect() as db:
        db.execute("INSERT INTO agent_jobs VALUES ('job',?,'investigation','running','{}',1,1)", (imported,))
    tools = InvestigationTools(state.agent, "job", owner, imported, baseline, root)
    with pytest.raises(ValueError, match="EMPTY arguments"):
        tools.read_baseline(baseline["baseline_id"])
    assert not tools.baseline_seen
    denied = tools.dispatch(call("read_file", path="agent.py")["tool_calls"][0])
    assert "Read baseline numbers" in denied["error"]
    schema = next(t for t in toolset(TOOLS[:3], ["1"]) if t["function"]["name"] == "read_baseline")
    assert schema["function"]["parameters"]["properties"]["task_id"]["enum"] == ["1"]
    with pytest.raises(ValueError):
        tools.read_run("other-run")
    page = tools.read_run("run-1", limit=1)
    assert len(page["calls"]) == 1 and page["next_offset"] == 1
    assert tools.read_run("run-1", offset=1, limit=1)["calls"][0]["call_id"] == 2
    for args in ({"offset": -1}, {"limit": 21}, {"offset": True}):
        with pytest.raises(ValueError):
            tools.read_run("run-1", **args)
    with pytest.raises(ValueError):
        tools.save_finding(**finding())
    tools.read_trace("run-1")
    tools.read_baseline()
    tools.dispatch(call("read_file", path="agent.py", start_line=1, max_lines=3)["tool_calls"][0])
    with pytest.raises(ValueError, match="already read"):
        tools.save_finding(**finding(source=[{"path": "agent.py", "start_line": 1, "end_line": 10}]))
    with pytest.raises(ValueError):
        tools.save_finding(**finding(source=[{"path": "../outside", "start_line": 1, "end_line": 1}]))
    with pytest.raises(ValueError, match="Saving"):
        tools.save_finding(**finding(estimated_saving={"cost_usd": 1, "method": "An unsupported cost estimate."}))
    with state.database.connect() as db:
        db.execute("UPDATE model_calls SET estimated_cost_usd=NULL WHERE id=2")
    assert tools.read_run("run-1")["summary"]["cost_usd"] is None
    with pytest.raises(ValueError, match="unknown"):
        tools.save_finding(**finding())
    assert "$ref" not in json.dumps(toolset(TOOLS[:3]))


def test_legacy_job_migration_preserves_jobs_events_and_cascade(investigation):
    state, _, owner, imported, _, _ = investigation
    with state.database.connect() as db:
        job_sql = db.execute("SELECT sql FROM sqlite_master WHERE name='agent_jobs'").fetchone()[0]
        event_sql = db.execute("SELECT sql FROM sqlite_master WHERE name='agent_events'").fetchone()[0]
        db.executescript("DROP TABLE agent_events; DROP TABLE agent_jobs;")
        db.execute(job_sql.replace("'onboarding','investigation'", "'onboarding'"))
        db.execute(event_sql)
        db.execute("INSERT INTO agent_jobs VALUES ('legacy',?,'onboarding','ready','{}',1,1)", (imported,))
        db.execute("INSERT INTO agent_events VALUES (41,'legacy','finished','{}',1)")
    state.database.initialize()
    state.database.initialize()
    with state.database.connect() as db:
        assert db.execute("SELECT kind FROM agent_jobs WHERE id='legacy'").fetchone()[0] == "onboarding"
        assert db.execute("SELECT id FROM agent_events").fetchone()[0] == 41
        db.execute("INSERT INTO agent_jobs VALUES ('new',?,'investigation','ready','{}',1,1)", (imported,))
        db.execute("INSERT INTO agent_events (job_id,kind,data,created_at) VALUES ('new','finished','{}',1)")
        assert db.execute("SELECT max(id) FROM agent_events").fetchone()[0] == 42
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    state.github.delete_import(owner, imported)
    with state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_jobs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM agent_events").fetchone()[0] == 0


def test_finish_requires_complete_observed_coverage(investigation):
    state, _, owner, imported, baseline, root = investigation
    with state.database.connect() as db:
        db.execute("INSERT INTO agent_jobs VALUES ('coverage',?,'investigation','running','{}',1,1)", (imported,))
    tools = InvestigationTools(state.agent, "coverage", owner, imported, baseline, root)
    for message in reads():
        assert not tools.dispatch(message["tool_calls"][0]).get("error")
    def finish(items):
        return tools.dispatch(call("finish", summary="No change justified in these scripted calls.", coverage=items)["tool_calls"][0])
    assert "error" in finish([])
    items = coverage()
    items[-1]["category"] = "Context"
    assert "exactly once" in finish(items)["error"]
    items = coverage()
    items[0]["run_ids"] = ["unread"]
    assert "already-read" in finish(items)["error"]
    items = coverage()
    items[0]["source"][0]["end_line"] = 100
    assert "already read" in finish(items)["error"]
    items = coverage(["missing"])
    assert "valid saved" in finish(items)["error"]
    assert tools.coverage == [] and tools.state["finish"] is None
    assert finish(coverage())["accepted"]
    assert len(state.agent.job(owner, imported, "coverage")["result"]["coverage"]) == 8
    assert "WHAT TO LOOK FOR" in SYSTEM and "JUDGEMENT" in SYSTEM
