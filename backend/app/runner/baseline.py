"""Development baselines; the controller scores labels never sent in task stdin."""
import hashlib
import json
import time
import uuid
import threading

from fastapi import HTTPException

from ..contracts.schemas import bounded_data
from ..contracts.service import ContractService
from ..agent.service import JOB_LOCK
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
            "trace_id": (result.get("trace") or {}).get("trace_id"),
            "external_calls": egress.get("allowed", 0), "external_denied": egress.get("denied", 0),
            "external_hosts": sorted(egress.get("hosts", {}))}


def equal_json(actual, expected):
    # JSON numbers may compare across int/float, but booleans must never equal 0/1.
    if type(actual) in {int, float} and type(expected) in {int, float}:
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(equal_json(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(equal_json(a, b) for a, b in zip(actual, expected))
    return actual == expected


def field_reason(output, rule):
    value = output
    for part in rule["pointer"][1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isascii() and part.isdecimal() and (part == "0" or not part.startswith("0")) and int(part) < len(value):
            value = value[int(part)]
        else:
            return "Missing required field " + rule["pointer"]
    matches = {"string": type(value) is str, "integer": type(value) is int,
               "number": type(value) in {int, float}, "boolean": type(value) is bool,
               "object": type(value) is dict, "array": type(value) is list, "null": value is None}
    if not matches[rule["field_type"]]:
        return f"Field {rule['pointer']} must be {rule['field_type']}"
    if rule["check_exact"] and not equal_json(value, rule["exact_value"]):
        return "Exact value mismatch at " + rule["pointer"]
    return None


def score_task(output, task, contract, stop_reason="completed"):
    failures, checks = [], []
    if stop_reason != "completed":
        failures.append("Run stopped: " + stop_reason)
    if task["expected_output"] is not None and not equal_json(output, task["expected_output"]):
        failures.append("Output does not match expected_output")
    for rule in task["required_fields"]:
        reason = field_reason(output, rule)
        if reason:
            failures.append(reason)
    requirements = [(category, requirement) for category in ("required_facts", "required_evidence")
                    for requirement in task[category]]
    requirements += [(f"{category}.{name}", requirement)
                     for category in ("acceptable_failures", "protected_behavior")
                     for name, requirement in contract[category].items() if requirement]
    for category, requirement in requirements:
        if requirement["verification"] == "human_review":
            checks.append({"category": category, **requirement, "status": "needs_review"})
        else:
            reason = field_reason(output, requirement["rule"])
            checks.append({"category": category, **requirement, "status": "failed" if reason else "passed", "reason": reason})
            if reason:
                failures.append(requirement["description"] + ": " + reason)
    review = any(check["status"] == "needs_review" for check in checks)
    status = "failed" if failures else "needs_review" if review else "passed"
    return {"status": status, "passed": False if failures else None if review else True,
            "automatic_passed": not failures, "reason": "; ".join(failures) if failures else
            "Automatic checks passed; human review required" if review else "All automatic checks passed",
            "requirements": checks}


def combine(runs):
    """One run is reported as measured. Several are averaged, with the spread kept beside the mean."""
    if len(runs) == 1:
        return dict(runs[0])
    task = dict(runs[0])
    task["passed"] = False if any(run["passed"] is False for run in runs) else None if any(run["passed"] is None for run in runs) else True
    task["pass_rate"] = None if any(run["passed"] is None for run in runs) else sum(run["passed"] for run in runs) / len(runs)
    if "status" in task:
        task["status"] = "failed" if task["passed"] is False else "needs_review" if task["passed"] is None else "passed"
        task["automatic_passed"] = all(run["automatic_passed"] for run in runs)
        task["reason"] = "; ".join(dict.fromkeys(run["reason"] for run in runs))
        task["trace_ids"] = [run["trace_id"] for run in runs]
        task["requirements"] = []
        for index, check in enumerate(runs[0]["requirements"]):
            checks = [run["requirements"][index] for run in runs]
            status = "failed" if any(c["status"] == "failed" for c in checks) else check["status"]
            task["requirements"].append({**check, "status": status,
                "reason": "; ".join(dict.fromkeys(c["reason"] for c in checks if c.get("reason"))) or None})
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
        self.contracts = ContractService(self.database, runner.inspection)
        self.threads = {}

    def event(self, baseline_id, kind, data):
        with self.database.connect() as db:
            db.execute("INSERT INTO baseline_events (baseline_id,kind,data,created_at) VALUES (?,?,?,?)",
                       (baseline_id, kind, json.dumps(data, allow_nan=False), int(time.time())))

    def get(self, user_id, import_id, baseline_id):
        with self.database.connect() as db:
            self.runner.inspection.ready(db, user_id, import_id)
            row = db.execute("SELECT result FROM baselines WHERE id=? AND import_id=?", (baseline_id, import_id)).fetchone()
        if not row:
            raise HTTPException(404, "Baseline job not found.")
        return json.loads(row["result"])

    def events(self, user_id, import_id, baseline_id, after=0):
        self.get(user_id, import_id, baseline_id)
        with self.database.connect() as db:
            rows = db.execute("SELECT * FROM baseline_events WHERE baseline_id=? AND id>? ORDER BY id LIMIT 200",
                              (baseline_id, after)).fetchall()
        return {"events": [{"id": row["id"], "kind": row["kind"], "data": json.loads(row["data"]),
                            "created_at": row["created_at"]} for row in rows]}

    def recover(self):
        with self.database.connect() as db:
            rows = db.execute("SELECT id,result FROM baselines").fetchall()
            for row in rows:
                report = json.loads(row["result"])
                if report["status"] == "running":
                    report.update(status="failed", reason="Interrupted by a backend restart. Start a new baseline.")
                    db.execute("UPDATE baselines SET result=? WHERE id=?", (json.dumps(report), row["id"]))
                    db.execute("INSERT INTO baseline_events (baseline_id,kind,data,created_at) VALUES (?,'finished',?,?)",
                               (row["id"], json.dumps({"status": "failed", "reason": report["reason"]}), int(time.time())))

    def confirmed(self, user_id, import_id):
        contract = self.contracts.get(user_id, import_id)
        if contract.get("status") != "confirmed" or contract["stale"] or contract["missing_requirements"]:
            raise HTTPException(409, "Confirm a current task contract before starting a baseline.")
        return contract

    def start(self, user_id, import_id, repetitions=1):
        if type(repetitions) is not int or not 1 <= repetitions <= 5:
            raise ValueError("Repetitions must be between 1 and 5.")
        self.runner.configuration(user_id, import_id)
        contract = self.confirmed(user_id, import_id)
        with self.database.connect() as db:
            self.runner.inspection.ready(db, user_id, import_id)
            adapter = db.execute("SELECT * FROM import_adapters WHERE import_id=?", (import_id,)).fetchone()
        if adapter is None:
            raise HTTPException(409, "Run onboarding to store an adapter before starting a baseline.")
        if not self.runner.settings.litellm_base_url or not self.runner.settings.litellm_api_key:
            raise HTTPException(503, "Model gateway is not configured.")
        if not JOB_LOCK.acquire(blocking=False):
            raise HTTPException(409, "Another agent or baseline job is running.")
        try:
            report = {"baseline_id": uuid.uuid4().hex, "import_id": import_id, "kind": "contract",
                      "commit_sha": contract["commit_sha"], "configuration_revision": contract["configuration_revision"],
                      "contract_version": contract["version"], "contract": contract["contract"],
                      "adapter_sha256": adapter["sha256"], "adapter_job_id": adapter["job_id"],
                      "repetitions": repetitions, "status": "running", "tasks": [], "created_at": int(time.time())}
            self.save(user_id, report)
            self.event(report["baseline_id"], "started", {"contract_version": contract["version"], "repetitions": repetitions})
            thread = threading.Thread(target=self.guarded, args=(user_id, report, adapter["content"]), daemon=True)
            self.threads[report["baseline_id"]] = thread
            thread.start()
        except BaseException:
            JOB_LOCK.release()
            raise
        return self.get(user_id, import_id, report["baseline_id"])

    def guarded(self, user_id, report, adapter_code):
        try:
            self.execute(user_id, report, adapter_code)
        except HTTPException as exc:
            report.update(status="failed", reason=str(exc.detail))
        except (ValueError, RuntimeError) as exc:
            report.update(status="failed", reason=str(exc))
        except Exception as exc:
            report.update(status="failed", reason="Unexpected controller error: " + type(exc).__name__)
        try:
            self.save(user_id, report)
            self.event(report["baseline_id"], "finished", {"status": report["status"], "reason": report.get("reason"),
                       "passed": report.get("passed"), "failed": report.get("failed"), "needs_review": report.get("needs_review")})
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        finally:
            self.threads.pop(report["baseline_id"], None)
            JOB_LOCK.release()

    def execute(self, user_id, report, adapter_code):
        imported, contract = report["import_id"], report["contract"]
        build = self.runner.build(user_id, imported)
        report["build"] = build
        self.save(user_id, report)
        self.event(report["baseline_id"], "build", {"build_id": build["build_id"]})
        limits = contract["limits"]
        calls, cost, tokens, outside = 0, 0.0, 0, 0
        started = time.monotonic()
        for index, task in enumerate(contract["tasks"], 1):
            task_report = {"task_id": str(index), "name": task["name"], "input": task["input"], "runs": []}
            report["tasks"].append(task_report)
            for repetition in range(1, report["repetitions"] + 1):
                current = self.confirmed(user_id, imported)
                if current["version"] != report["contract_version"] or current["configuration_revision"] != report["configuration_revision"]:
                    raise HTTPException(409, "Contract or configuration changed during baseline; partial results are saved.")
                remaining = limits["max_runtime_seconds"] - (time.monotonic() - started)
                if remaining < 0.1 or calls > limits["max_model_calls"] or cost > limits["max_spend_usd"] or tokens > limits["max_tokens"] or outside > limits["max_tool_calls"]:
                    raise ValueError("Contract execution budget exhausted; partial results are saved.")
                result = self.runner.run(user_id, imported, build["build_id"], task["input"],
                    adapter_code=adapter_code, timeout_seconds=min(300, remaining),
                    max_calls=limits["max_model_calls"] - calls, max_spend_usd=limits["max_spend_usd"] - cost,
                    memory_mb=1024, pids=128, internet=self.runner.settings.runner_internet,
                    labels={"kind": "baseline", "baseline_id": report["baseline_id"], "task_id": str(index), "repetition": repetition})
                run = {**measured(result, True, None), **score_task(result["output"], task, contract, result["stop_reason"]),
                       "repetition": repetition, "output": result["output"], "trace": result.get("trace")}
                task_report["runs"].append(run)
                runs = task_report["runs"]
                task_report.update(combine(runs))
                task_report["runs"] = runs
                self.save(user_id, report)
                self.event(report["baseline_id"], "run", {"task_id": str(index), **run})
                calls += run["model_calls"]
                cost += run["cost_usd"] or 0
                tokens += (run["tokens_in"] or 0) + (run["tokens_out"] or 0)
                outside += run["external_calls"] + run["external_denied"]
                if run["unknown_cost_calls"] or run["unknown_usage_calls"]:
                    raise ValueError("Unknown model cost or usage; no further runs admitted. Partial results are saved.")
                if tokens > limits["max_tokens"] or outside > limits["max_tool_calls"] or cost > limits["max_spend_usd"]:
                    raise ValueError("Recorded contract budget exceeded; partial results are saved.")
            self.event(report["baseline_id"], "task", {"task_id": str(index), "status": task_report["status"], "reason": task_report["reason"]})
        report.update(status="completed", total=len(report["tasks"]),
                      passed=sum(task["status"] == "passed" for task in report["tasks"]),
                      failed=sum(task["status"] == "failed" for task in report["tasks"]),
                      needs_review=sum(task["status"] == "needs_review" for task in report["tasks"]))

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
                    internet=self.runner.settings.runner_internet,
                    labels={"kind": "baseline", "task_id": case_id})
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
