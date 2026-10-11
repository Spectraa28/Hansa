"""Read-only investigation tools. Ledger numbers and observed source lines back every finding."""
import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..gateway.shape import repeated_prefix
from .tools import SnapshotTools

SYSTEM = Path(__file__).with_name("investigation_prompt.md").read_text()

CATEGORIES = ("Context", "Memory", "Orchestration", "Model choice", "Output", "Tools", "Latency", "Wasted work")


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=400)
    start_line: int = Field(strict=True, ge=1)
    end_line: int = Field(strict=True, ge=1)

    @model_validator(mode="after")
    def range(self):
        if not self.start_line <= self.end_line < self.start_line + 200:
            raise ValueError("Source evidence must be a range of at most 200 lines.")
        return self


class Saving(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cost_usd: float | None = Field(default=None, strict=True, ge=0, le=100, allow_inf_nan=False)
    wall_time_seconds: float | None = Field(default=None, strict=True, ge=0, le=3600, allow_inf_nan=False)
    tokens: int | None = Field(default=None, strict=True, ge=0, le=1000000)
    model_calls: int | None = Field(default=None, strict=True, ge=0, le=1000)
    method: str = Field(min_length=10, max_length=2000)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    waste: str = Field(min_length=10, max_length=2000)
    run_ids: list[str] = Field(min_length=1, max_length=10)
    source: list[Source] = Field(min_length=1, max_length=5)
    estimated_saving: Saving
    behaviour_risk: str = Field(min_length=10, max_length=2000)
    proposed_change: str = Field(min_length=10, max_length=2000)


class Coverage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["Context", "Memory", "Orchestration", "Model choice", "Output", "Tools", "Latency", "Wasted work"]
    status: Literal["finding", "checked, nothing found"]
    observation: str = Field(min_length=10, max_length=2000)
    run_ids: list[str] = Field(min_length=1, max_length=12)
    source: list[Source] = Field(min_length=1, max_length=5)
    finding_ids: list[str] = Field(default_factory=list, max_length=10)


class Conclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=10, max_length=2000)
    coverage: list[Coverage] = Field(min_length=8, max_length=8)


def toolset(source_tools, task_ids=None):
    schema = Finding.model_json_schema()
    definitions = schema.pop("$defs")
    schema["properties"]["source"]["items"] = definitions["Source"]
    schema["properties"]["estimated_saving"] = definitions["Saving"]
    conclusion = Conclusion.model_json_schema()
    definitions = conclusion.pop("$defs")
    coverage = definitions["Coverage"]
    coverage["properties"]["source"]["items"] = definitions["Source"]
    conclusion["properties"]["coverage"]["items"] = coverage
    return [*source_tools,
        {"type": "function", "function": {"name": "read_baseline", "description": "Already bound to the baseline. First call with EMPTY arguments {} for all task totals. Only later pass a task_id from the overview to read that task's rules. NEVER pass a baseline ID.",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string", "description": "Optional task ID from the overview, not a baseline ID.",
                                                                            **({"enum": task_ids} if task_ids else {})}}}}},
        {"type": "function", "function": {"name": "read_run", "description": "Read a baseline run's actual output, ledger calls in order, outside connections and inferred gaps. Calls are paginated.",
            "parameters": {"type": "object", "properties": {"run_id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["run_id"]}}},
        {"type": "function", "function": {"name": "read_trace", "description": "Read/recheck a baseline run's Neatlogs second view. Unavailable traces do not block investigation.",
            "parameters": {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"]}}},
        {"type": "function", "function": {"name": "save_finding", "description": "Save an evidence-backed, untested proposal. The controller attaches ledger numbers and verifies source citations.", "parameters": schema}},
        {"type": "function", "function": {"name": "finish", "description": "Finish with a summary and all eight categories, each with what you saw, already-read run/source evidence, and saved finding IDs or 'checked, nothing found'. Never claim an unchecked category was checked.",
            "parameters": conclusion}},
    ]


def completed_baseline(service, user_id, import_id, baseline_id=None):
    with service.database.connect() as db:
        service.owned(db, user_id, import_id)
        row = db.execute("SELECT result FROM baselines WHERE import_id=? " +
                         ("AND id=?" if baseline_id else "ORDER BY created_at DESC,rowid DESC LIMIT 1"),
                         (import_id, baseline_id) if baseline_id else (import_id,)).fetchone()
    if not row:
        raise HTTPException(409, "A completed baseline is required for investigation.")
    report = json.loads(row["result"])
    if report["status"] != "completed":
        raise HTTPException(409, "Wait for a completed baseline before investigating.")
    return report


class InvestigationTools:
    def __init__(self, service, job_id, user_id, import_id, baseline, root):
        self.service, self.job_id, self.user_id, self.import_id = service, job_id, user_id, import_id
        self.baseline, self.source = baseline, SnapshotTools(root)
        self.allowed_runs = {run["run_id"] for task in baseline["tasks"] for run in task.get("runs", [task])}
        self.runs, self.traces, self.lines, self.findings, self.coverage = {}, {}, {}, [], []
        self.baseline_seen = False
        self.state = {"finish": None, "result_limit": 16000}

    def read_baseline(self, task_id=None):
        metrics = ("model_calls", "tokens_in", "tokens_out", "cost_usd", "wall_time_seconds", "external_calls")
        tasks = []
        for index, task in enumerate(self.baseline["tasks"]):
            runs = task.get("runs", [task])
            totals = {}
            for metric in metrics:
                values = [None if (metric == "cost_usd" and run.get("unknown_cost_calls")) or
                          (metric in {"tokens_in", "tokens_out"} and run.get("unknown_usage_calls"))
                          else run.get(metric) for run in runs]
                totals[metric] = sum(values) if all(type(v) in {int, float} for v in values) else None
            item = {"task_id": task["task_id"], "name": task.get("name", task["task_id"]),
                    "status": task.get("status"), "reason": task.get("reason"), "totals": totals,
                    "run_ids": [run["run_id"] for run in runs]}
            if task_id is not None and task["task_id"] == task_id:
                self.baseline_seen = True
                item["runs"] = [{k: run.get(k) for k in (*metrics, "run_id", "trace_id", "stop_reason", "status", "reason", "automatic_passed", "unknown_cost_calls")} for run in runs]
                item["rules"] = self.baseline.get("contract", {}).get("tasks", [])[index] if self.baseline.get("contract") else {"expected_function": task.get("expected_function")}
                return item
            tasks.append(item)
        if task_id is not None:
            raise ValueError("Invalid task_id. Call read_baseline with EMPTY arguments {} for the overview; valid task IDs: " +
                             ", ".join(task["task_id"] for task in self.baseline["tasks"]))
        self.baseline_seen = True
        totals = {}
        for metric in metrics:
            values = [task["totals"][metric] for task in tasks]
            totals[metric] = sum(values) if all(v is not None for v in values) else None
        for task in tasks:
            task["share_of_total"] = {metric: task["totals"][metric] / totals[metric]
                                      if totals[metric] and task["totals"][metric] is not None else None
                                      for metric in ("cost_usd", "model_calls", "tokens_in", "wall_time_seconds")}
        return {"baseline_id": self.baseline["baseline_id"], "numbers_source": "private database",
                "repetitions": self.baseline.get("repetitions", 1), "tasks": tasks, "totals": totals,
                "totals_scope": "Totals over all repetitions, not per-run means; fractions are not percentages.",
                "limits": (self.baseline.get("contract") or {}).get("limits"),
                "coverage": "Development cases; pending human reviews are not correctness passes."}

    def run(self, run_id):
        if run_id not in self.allowed_runs:
            raise ValueError("Run is not in this baseline.")
        return self.service.runner.get(self.user_id, self.import_id, run_id)

    def read_run(self, run_id, offset=0, limit=10):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Use a nonnegative offset and limit 1-20.")
        result = self.run(run_id)
        with self.service.database.connect() as db:
            rows = db.execute("""SELECT m.id,m.model,m.upstream_model,m.prompt_tokens,m.completion_tokens,
                m.latency_ms,m.http_status,m.estimated_cost_usd,m.cost_source,m.started_at_ms,m.request_shape,m.response_shape
                FROM model_calls m JOIN gateway_keys k ON k.key_hash=m.key_hash
                WHERE k.run_label=? ORDER BY m.started_at_ms,m.id LIMIT 1001""", (run_id,)).fetchall()
        if len(rows) > 1000:
            raise ValueError("This run exceeds the investigation's 1000-call evidence bound.")
        if len(rows) != result["gateway"]["calls"]:
            raise ValueError("Run ledger is incomplete; do not infer missing calls or zero cost.")
        calls, gaps, previous, previous_call = [], [], {}, None
        for row in rows:
            shape, response = json.loads(row["request_shape"] or "{}"), json.loads(row["response_shape"] or "{}")
            repeated, chars = repeated_prefix(previous, shape)
            call = {"call_id": row["id"], "requested_model": row["model"], "upstream_model": row["upstream_model"],
                    "tokens_in": row["prompt_tokens"], "tokens_out": row["completion_tokens"], "latency_ms": row["latency_ms"],
                    "http_status": row["http_status"], "cost_usd": row["estimated_cost_usd"], "cost_source": row["cost_source"],
                    "started_at_ms": row["started_at_ms"], "prompt_chars": shape.get("prompt_chars"),
                    "prompt_chars_by_role": shape.get("chars_by_role"),
                    "tool_schema_chars": shape.get("tool_schema_chars"), "messages": shape.get("messages"),
                    "repeated_messages": repeated if shape and (previous or not previous_call) else None,
                    "repeated_chars": chars if shape and (previous or not previous_call) else None,
                    "tool_calls_requested": response.get("tool_calls", []), "output_chars": response.get("output_chars")}
            if previous_call:
                timing = (previous_call["started_at_ms"], previous_call["latency_ms"], call["started_at_ms"])
                gaps.append({"from_call": previous_call["call_id"], "to_call": call["call_id"], "inferred": True,
                             "gap_ms": max(0, timing[2] - timing[0] - timing[1]) if all(v is not None for v in timing) else None})
            calls.append(call)
            previous, previous_call = shape, call
        summary = {"model_calls": len(calls), "wall_time_seconds": result["wall_time_seconds"],
                   "stop_reason": result["stop_reason"]}
        for metric in ("tokens_in", "tokens_out", "cost_usd", "latency_ms"):
            values = [c[metric] for c in calls]
            summary[metric] = sum(values) if all(v is not None for v in values) else None
        record = {"run_id": run_id, "trace_id": (result.get("trace") or {}).get("trace_id"), "summary": summary,
                  "calls": calls, "gaps": gaps, "outside_connections": (result.get("egress") or {}).get("connections", []),
                  "coverage": "Ledger numbers. Repeated characters are unchanged OPENING messages already in the PREVIOUS request, not newly added tool output. Hashes cover up to 200 messages; characters are not tokens. Gaps are inferred and overlap outside connections; wall time also includes container start/stop."}
        self.runs[run_id] = record
        return {"output": result.get("output"), **record, "calls": calls[offset:offset + limit], "gaps": gaps[max(0, offset - 1):offset + limit],
                "offset": offset, "next_offset": offset + limit if offset + limit < len(calls) else None}

    def read_trace(self, run_id):
        result = self.run(run_id)
        trace_id = (result.get("trace") or {}).get("trace_id")
        if not trace_id or self.service.tracer is None:
            checked = {"trace_id": trace_id, "status": "unavailable", "error": "No recorded trace or tracing service."}
        else:
            try:
                checked = self.service.tracer.recheck(self.user_id, self.import_id, trace_id)
            except HTTPException as exc:
                checked = {"trace_id": trace_id, "status": "unavailable", "error": str(exc.detail)}
        self.traces[run_id] = {k: checked.get(k) for k in ("trace_id", "status", "checked_at", "error", "note")}
        return {"run_id": run_id, **checked, "numbers_source": "Use read_run database numbers, never Neatlogs costs."}

    def save_finding(self, **arguments):
        finding = Finding.model_validate(arguments)
        ids = list(dict.fromkeys(finding.run_ids))
        if any(run_id not in self.runs for run_id in ids):
            raise ValueError("Read each cited baseline run with read_run before saving a finding.")
        for run_id in ids:
            # The controller fetches the second view itself, so a finding never costs the agent a turn per trace.
            if run_id not in self.traces:
                self.read_trace(run_id)
        sources = self.references(finding.source)
        measurements = [{**self.runs[run_id], "trace": self.traces[run_id]} for run_id in ids]
        for metric, actual in (("cost_usd", "cost_usd"), ("wall_time_seconds", "wall_time_seconds"), ("model_calls", "model_calls")):
            estimate = getattr(finding.estimated_saving, metric)
            values = [r["summary"][actual] for r in measurements]
            if estimate is not None and (any(v is None for v in values) or estimate > sum(values)):
                raise ValueError("Saving must not exceed the cited measured total or invent an unknown measurement.")
        if finding.estimated_saving.tokens is not None:
            tokens = [r["summary"][k] for r in measurements for k in ("tokens_in", "tokens_out")]
            if any(v is None for v in tokens) or finding.estimated_saving.tokens > sum(tokens):
                raise ValueError("Token saving exceeds the cited known token total.")
        saved = {"finding_id": str(len(self.findings) + 1), "waste": finding.waste,
                 "evidence": {"runs": measurements, "source": sources}, "estimated_saving": finding.estimated_saving.model_dump(),
                 "saving_scope": "Total over the cited runs; hypothesis, not a measured improvement.",
                 "behaviour_risk": finding.behaviour_risk, "proposed_change": finding.proposed_change}
        if len(self.findings) >= 10 or len(json.dumps(saved).encode()) > 131072:
            raise ValueError("Findings are bounded to ten, each at most 128 KiB.")
        self.findings.append(saved)
        self.service.update(self.job_id, "running", self.result())
        self.service.event(self.job_id, "finding", saved)
        return {"saved": True, "finding_id": saved["finding_id"], "run_ids": ids, "source": sources}

    def references(self, references):
        sources = []
        for reference in references:
            path = str(self.source.path(reference.path).relative_to(self.source.root))
            if not set(range(reference.start_line, reference.end_line + 1)).issubset(self.lines.get(path, set())):
                raise ValueError("Source citations must be file/lines already read with the source tools.")
            sources.append({"path": path, "start_line": reference.start_line, "end_line": reference.end_line,
                            "sha256": hashlib.sha256(self.source.path(path).read_bytes()).hexdigest()})
        return sources

    def result(self):
        return {"baseline_id": self.baseline["baseline_id"], "findings": self.findings, "coverage": self.coverage,
                "inspected_runs": list(self.runs), "trace_readback": self.traces,
                "baseline_evidence": self.read_baseline(), "run_evidence": list(self.runs.values()),
                "source_evidence": [{"path": path, "lines_read": sorted(lines),
                    "sha256": hashlib.sha256(self.source.path(path).read_bytes()).hexdigest()} for path, lines in sorted(self.lines.items())],
                "source_files_read": sorted(self.lines)}

    def dispatch(self, call):
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"]["arguments"] or "{}")
            if not isinstance(args, dict):
                raise ValueError("Tool arguments must be an object.")
            self.service.event(self.job_id, "tool", {"name": name, "arguments": args})
            if name in {"list_files", "search_code", "read_file"}:
                if not self.baseline_seen:
                    raise ValueError("Read baseline numbers before reading source.")
                result = getattr(self.source, name)(**args)
                if name == "read_file":
                    path = str(self.source.path(args["path"]).relative_to(self.source.root))
                    self.lines.setdefault(path, set()).update(int(line.split(":", 1)[0]) for line in result["lines"])
                elif name == "search_code":
                    for match in result["matches"]:
                        path, number = match.split(": ", 1)[0].rsplit(":", 1)
                        self.lines.setdefault(path, set()).add(int(number))
                return result
            if name in {"read_baseline", "read_run", "read_trace", "save_finding"}:
                return getattr(self, name)(**args)
            if name == "finish":
                conclusion = Conclusion.model_validate(args)
                if {item.category for item in conclusion.coverage} != set(CATEGORIES):
                    raise ValueError("Coverage must contain each of the eight categories exactly once.")
                known = {finding["finding_id"] for finding in self.findings}
                covered, saved = set(), []
                for item in conclusion.coverage:
                    if any(run_id not in self.runs for run_id in item.run_ids):
                        raise ValueError("Coverage must cite already-read baseline runs.")
                    if (item.status == "finding") != bool(item.finding_ids) or not set(item.finding_ids) <= known:
                        raise ValueError("Finding coverage needs valid saved finding IDs; no-finding coverage cannot cite findings.")
                    covered.update(item.finding_ids)
                    saved.append({**item.model_dump(), "source": self.references(item.source)})
                if covered != known:
                    raise ValueError("Coverage must reference every saved finding.")
                summary = args.get("summary")
                if not self.baseline_seen or not self.runs or not self.lines or not isinstance(summary, str) or not 10 <= len(summary.strip()) <= 2000:
                    raise ValueError("Finish needs inspected baseline/run numbers, source evidence, and a bounded explanation.")
                self.coverage = saved
                self.state["finish"] = {"summary": summary.strip(), "nothing_worth_changing": not self.findings}
                self.service.update(self.job_id, "running", {**self.result(), **self.state["finish"]})
                self.service.event(self.job_id, "coverage", {"coverage": saved})
                return {"accepted": True, "findings": len(self.findings)}
            raise ValueError("Tool is not available in investigation.")
        except (ValueError, TypeError, OSError, HTTPException) as exc:
            error = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            self.service.event(self.job_id, "tool_error", {"name": name, "error": error[:300]})
            return {"error": error[:300]}
