import pytest
from fastapi import HTTPException

from app.agent import service as agent_service
from app.runner.baseline import METRICS, MIN_EFFECT_PERCENT, compare


def task(value, spread=None):
    row = {"task_id": "1", "name": "one", "status": "passed", "automatic_passed": True, **{key: value for key in METRICS}}
    if spread:
        row["spread"] = {key: spread for key in METRICS}
    return row


def test_small_saving_is_not_an_improvement_when_variation_was_not_measured():
    result = compare({"repetitions": 1, "tasks": [task(100)]}, [task(98)])
    assert result["verdict"] == "no_measurable_change"
    assert result["minimum_effect_percent"] == MIN_EFFECT_PERCENT
    assert result["totals"]["cost_usd"]["change_percent"] == -2


def test_saving_past_the_floor_counts_when_variation_was_not_measured():
    assert compare({"repetitions": 1, "tasks": [task(100)]}, [task(90)])["verdict"] == "improved"


def test_measured_variation_still_decides_when_the_baseline_was_repeated():
    baseline = {"repetitions": 2, "tasks": [task(100, spread=[97, 103])]}
    assert compare(baseline, [task(98)])["verdict"] == "no_measurable_change"
    improved = compare(baseline, [task(96)])
    assert improved["verdict"] == "improved" and improved["minimum_effect_percent"] is None


def test_a_refused_job_says_what_is_running():
    agent_service.claim("baseline")
    try:
        with pytest.raises(HTTPException) as refused:
            agent_service.claim("fix test")
        assert refused.value.status_code == 409
        assert "baseline" in refused.value.detail and "not queued" in refused.value.detail
    finally:
        agent_service.JOB_LOCK.release()


def test_tool_steps_keep_no_repository_text():
    from app.tracing.service import step_input, step_output
    source = "API_TOKEN = load()\n" * 40
    read = {"name": "read_file", "input": '{"path": "agent/main.py"}', "output": source}
    assert "API_TOKEN" not in step_output(read) and "not stored" in step_output(read)
    assert step_input(read) == '{"path": "agent/main.py"}'
    edit = {"name": "edit_file", "input": '{"path": "agent/main.py", "new": "secret source text"}', "output": {"ok": True}}
    assert step_input(edit) == '{"path": "agent/main.py"}' and "secret source" not in step_input(edit)
    assert step_output({"name": "read_baseline", "input": "{}", "output": {"calls": 40}}) == '{"calls": 40}'
