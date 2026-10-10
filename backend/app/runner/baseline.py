"""Airline development evals; controller scores outputs without sending labels in stdin."""
import hashlib
import json
import time
import uuid

from fastapi import HTTPException

from ..contracts.schemas import bounded_data
from .service import HERE


def score(output, expected):
    messages = output.get("messages") if isinstance(output, dict) else None
    if not isinstance(messages, list):
        return False, None
    actual, has_message = "None", False
    for message in messages:
        if not isinstance(message, dict):
            return False, None
        if message.get("role") == "tool":
            actual = message.get("tool_name")
            return actual == expected, actual
        if message.get("role") == "assistant" and not message.get("tool_calls"):
            has_message = True
    return has_message and expected == "None", actual


def measured(result, passed, actual):
    usage, egress = result["gateway"], result.get("egress") or {}
    return {"passed": passed and result["stop_reason"] == "completed", "actual_function": actual,
            "run_id": result["run_id"], "stop_reason": result["stop_reason"],
            "model_calls": usage["calls"], "tokens_in": usage["prompt_tokens"],
            "tokens_out": usage["completion_tokens"], "cost_usd": usage["estimated_cost_usd"],
            "unknown_cost_calls": usage["unknown_cost_calls"], "unknown_usage_calls": usage["unknown_usage_calls"],
            "models": usage["models"], "wall_time_seconds": result["wall_time_seconds"],
            "external_calls": egress.get("allowed", 0), "external_denied": egress.get("denied", 0),
            "external_hosts": sorted(egress.get("hosts", {}))}


def combine(runs):
    """One run is reported as measured. Several are averaged, with the spread kept beside the mean."""
    if len(runs) == 1:
        return dict(runs[0])
    task = dict(runs[0])
    task["passed"] = all(run["passed"] for run in runs)
    task["pass_rate"] = sum(run["passed"] for run in runs) / len(runs)
    task["spread"] = {}
    for key in ("model_calls", "tokens_in", "tokens_out", "cost_usd", "wall_time_seconds", "external_calls"):
        values = [run[key] for run in runs]
        # An unknown measurement in any repetition keeps the aggregate unknown, never a partial mean.
        known = all(type(value) in {int, float} for value in values)
        task[key] = sum(values) / len(values) if known else None
        task["spread"][key] = [min(values), max(values)] if known else None
    for key in ("unknown_cost_calls", "unknown_usage_calls", "external_denied"):
        task[key] = sum(run[key] for run in runs)
    task["external_hosts"] = sorted({host for run in runs for host in run["external_hosts"]})
    task["runs"] = runs
    return task


class BaselineService:
    def __init__(self, runner):
        self.runner = runner
        self.database = runner.database

    def airline(self, user_id, import_id, repetitions=1):
        if type(repetitions) is not int or not 1 <= repetitions <= 5:
            raise ValueError("Repetitions must be between 1 and 5.")
        # Stage via the same owner/readiness/snapshot-copy boundary as normal builds.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(prefix="ouro-evals-") as temporary:
            config, digest = self.runner.stage(user_id, import_id, Path(temporary))
            source = Path(temporary) / "snapshot/examples/airline/evals/eval_cases"
            cases, hashes = [], {}
            for filename, agent in [("triage_cases.json", "triage_agent"),
                                    ("flight_modification_cases.json", "flight_modification")]:
                path = source / filename
                if path.stat().st_size > 65536:
                    raise ValueError("Airline eval file exceeds 64 KiB.")
                content = path.read_bytes()
                hashes[filename] = hashlib.sha256(content).hexdigest()
                values = json.loads(content)
                if not isinstance(values, list) or not 1 <= len(values) <= 50:
                    raise ValueError("Airline eval cases must be a bounded list.")
                for index, case in enumerate(values):
                    if (not isinstance(case, dict) or set(case) != {"conversation", "function"}
                            or not isinstance(case["function"], str) or len(case["function"]) > 100
                            or not isinstance(case["conversation"], list) or not case["conversation"]):
                        raise ValueError("Invalid airline eval case.")
                    task = {"agent": agent, "conversation": case["conversation"]}
                    bounded_data(task, 16384)
                    cases.append((f"{agent}/{index + 1}", task, case["function"]))
        if len(cases) > 20:
            raise ValueError("Baseline is limited to 20 cases and one call per case.")
        build = self.runner.build(user_id, import_id)
        if build["snapshot_digest"] != digest:
            raise HTTPException(409, "Source changed before baseline build.")
        report = {"baseline_id": uuid.uuid4().hex, "import_id": import_id,
                  "commit_sha": config["commit_sha"], "configuration_revision": config["configuration_revision"],
                  "snapshot_digest": digest, "build": build, "eval_file_hashes": hashes,
                  "adapter_sha256": hashlib.sha256((HERE / "airline_adapter.py").read_bytes()).hexdigest(),
                  "litellm_model": config["configuration"]["litellm_model"],
                  "evaluation": f"upstream function selection, max_turns=1, n={repetitions}; development cases",
                  "repetitions": repetitions,
                  "limits_per_task": {"max_calls": 1, "max_tokens": 1024, "max_spend_usd": 0.02,
                                      "timeout_seconds": 90, "sdk_retries": 0,
                                      "internet": "filtered_proxy" if self.runner.settings.runner_internet else "none"},
                  "status": "running", "tasks": [], "created_at": int(time.time())}
        self.save(user_id, report)
        for case_id, task, expected in cases:
            runs = []
            for _ in range(repetitions):
                current = self.runner.configuration(user_id, import_id)
                if current["configuration_revision"] != report["configuration_revision"]:
                    raise HTTPException(409, "Configuration changed during baseline; partial results are saved.")
                result = self.runner.run(user_id, import_id, build["build_id"], task,
                    timeout_seconds=90, max_calls=1, max_spend_usd=0.02, adapter="swarm_airline",
                    internet=self.runner.settings.runner_internet)
                runs.append(measured(result, *score(result["output"], expected)))
            report["tasks"].append({"task_id": case_id, "input": task, "expected_function": expected, **combine(runs)})
            self.save(user_id, report)
        report["status"] = "completed"
        report["passed"] = sum(task["passed"] for task in report["tasks"])
        report["total"] = len(cases)
        self.save(user_id, report)
        return report

    def save(self, user_id, report):
        with self.runner.inspection.github.lock, self.database.connect() as db:
            self.runner.inspection.ready(db, user_id, report["import_id"])
            db.execute("INSERT INTO baselines VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET result=excluded.result",
                       (report["baseline_id"], report["import_id"], json.dumps(report, allow_nan=False), report["created_at"]))

    def latest(self, user_id, import_id):
        with self.database.connect() as db:
            self.runner.inspection.ready(db, user_id, import_id)
            row = db.execute("SELECT result FROM baselines WHERE import_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                             (import_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "No baseline recorded for this import.")
        return json.loads(row["result"])
