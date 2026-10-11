"""Fix and prove: edit a private copy, run the baseline's tasks on it, and let controller code judge the result.

The model chooses the change and how to respond to a regression. This module decides what a candidate may
touch, counts experiments and spend, compares against the baseline, and refuses an accept the numbers do not
support. The imported source on disk is never written to.
"""
import ast
import difflib
import hashlib
import json
from pathlib import Path

from fastapi import HTTPException

from ..runner.baseline import compare
from ..runner.service import MAX_OVERLAY_FILES
from .tools import MAX_FILE_BYTES, SnapshotTools

SYSTEM = Path(__file__).with_name("optimization_prompt.md").read_text()
MAX_EXPERIMENTS = 5
MAX_DIFF = 60_000

TOOLS = [
    {"type": "function", "function": {"name": "edit_file", "description": "Replace one exact occurrence of old_text with new_text in a file of the candidate copy. old_text must appear exactly once.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
                       "required": ["path", "old_text", "new_text"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create a new source file in the candidate copy, or replace a small one entirely.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "revert", "description": "Restore one changed file, or every changed file when path is omitted.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "show_diff", "description": "Show the candidate's current patch against the original source.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_baseline", "description": "Baseline status, calls, tokens, cost and time per task, with the checks each task must pass.",
        "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "run_candidate", "description": "Run the current candidate on baseline tasks and compare with the baseline. Omit task_ids to run every task, which is required before accept.",
        "parameters": {"type": "object", "properties": {"task_ids": {"type": "array", "items": {"type": "string"}},
                                                        "repetitions": {"type": "integer", "minimum": 1, "maximum": 3}}}}},
    {"type": "function", "function": {"name": "finish", "description": "End with a decision the measurements support.",
        "parameters": {"type": "object", "properties": {
            "decision": {"type": "string", "enum": ["accept", "reject", "no_improvement"]},
            "summary": {"type": "string", "description": "What changed, what was measured, and what a reviewer should check."}},
            "required": ["decision", "summary"]}}},
]


class OptimizationTools:
    def __init__(self, service, job_id, user_id, import_id, baseline, root, finding, manifests, target_budget):
        self.service, self.job_id, self.user_id, self.import_id = service, job_id, user_id, import_id
        self.baseline, self.finding, self.manifests = baseline, finding, set(manifests)
        self.source, self.root = SnapshotTools(root), Path(root).resolve()
        self.original, self.experiments = {}, []
        self.target_budget, self.target_cost, self.target_calls = target_budget, 0.0, 0
        self.state = {"finish": None, "result_limit": 12000}

    # -- the candidate ---------------------------------------------------------------------------

    def target(self, path, new=False):
        target = self.source.path(path)
        relative = str(target.relative_to(self.root))
        parts = Path(relative).parts
        if relative in self.manifests or any(part.startswith(".") for part in parts):
            raise ValueError("Dependency manifests and hidden files cannot change.")
        if Path(relative).suffix not in {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}:
            raise ValueError("Only text source and configuration files can change.")
        if not new and not target.is_file():
            raise ValueError("File does not exist. Use write_file to create one.")
        if relative not in self.original and len(self.original) >= MAX_OVERLAY_FILES // 2:
            raise ValueError("A candidate may change at most ten files.")
        return target, relative

    def store(self, target, relative, content):
        if len(content.encode()) > MAX_FILE_BYTES:
            raise ValueError("A changed file may be at most 256 KiB.")
        if relative.endswith(".py"):
            try:
                ast.parse(content)  # syntax only; candidate code never runs in this process
            except SyntaxError as exc:
                raise ValueError(f"The change leaves a syntax error on line {exc.lineno}: {exc.msg}") from None
        if relative not in self.original:
            self.original[relative] = target.read_text(encoding="utf-8") if target.exists() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(0o644)
        target.write_text(content)
        if content == self.original[relative]:
            del self.original[relative]
        self.service.event(self.job_id, "edit", {"path": relative, "candidate_sha256": self.sha(), "changed_files": sorted(self.original)})
        return {"saved": True, "path": relative, "changed_files": sorted(self.original)}

    def edit_file(self, path, old_text, new_text):
        target, relative = self.target(path)
        if not isinstance(old_text, str) or not isinstance(new_text, str) or not old_text:
            raise ValueError("old_text and new_text must be text, and old_text cannot be empty.")
        content = target.read_text(encoding="utf-8")
        found = content.count(old_text)
        if found != 1:
            raise ValueError(f"old_text appears {found} times; it must appear exactly once. Include more surrounding lines.")
        return self.store(target, relative, content.replace(old_text, new_text))

    def write_file(self, path, content):
        target, relative = self.target(path, new=True)
        if not isinstance(content, str):
            raise ValueError("content must be text.")
        return self.store(target, relative, content)

    def revert(self, path=None):
        chosen = [str(self.source.path(path).relative_to(self.root))] if path else list(self.original)
        for relative in chosen:
            if relative not in self.original:
                raise ValueError("That file has no changes.")
            target, before = self.root / relative, self.original.pop(relative)
            if before is None:
                target.unlink()
            else:
                target.write_text(before)
        self.service.event(self.job_id, "revert", {"paths": chosen, "changed_files": sorted(self.original)})
        return {"reverted": chosen, "changed_files": sorted(self.original)}

    def overlay(self):
        return {relative: (self.root / relative).read_text(encoding="utf-8") for relative in sorted(self.original)
                if (self.root / relative).exists()}

    def sha(self):
        digest = hashlib.sha256()
        for relative, content in self.overlay().items():
            digest.update(relative.encode() + b"\0" + hashlib.sha256(content.encode()).digest())
        return digest.hexdigest() if self.original else None

    def patch(self):
        lines = []
        for relative in sorted(self.original):
            before, target = self.original[relative], self.root / relative
            after = target.read_text(encoding="utf-8") if target.exists() else ""
            lines += difflib.unified_diff((before or "").splitlines(keepends=True), after.splitlines(keepends=True),
                                          "a/" + relative if before is not None else "/dev/null", "b/" + relative)
        return "".join(line if line.endswith("\n") else line + "\n" for line in lines)

    def show_diff(self):
        patch = self.patch()
        return {"changed_files": sorted(self.original), "patch": patch[:MAX_DIFF], "truncated": len(patch) > MAX_DIFF}

    # -- evidence --------------------------------------------------------------------------------

    def read_baseline(self, task_id=None):
        tasks = [task for task in self.baseline["tasks"] if task_id in (None, task["task_id"])]
        if not tasks:
            raise ValueError("Unknown task ID.")
        contract = self.baseline["contract"]["tasks"]
        return {"repetitions": self.baseline["repetitions"], "model": self.baseline.get("litellm_model"), "tasks": [
            {"task_id": task["task_id"], "name": task["name"], "status": task["status"], "reason": task["reason"],
             **{key: task[key] for key in ("model_calls", "tokens_in", "tokens_out", "cost_usd", "wall_time_seconds")},
             **({"input": task["input"], "required_fields": contract[int(task["task_id"]) - 1]["required_fields"]} if task_id else {})}
            for task in tasks]}

    def run_candidate(self, task_ids=None, repetitions=1):
        if not self.original:
            raise ValueError("The candidate has no changes. Edit a file first.")
        if len(self.experiments) >= MAX_EXPERIMENTS:
            raise ValueError("No experiments remain. Call finish.")
        if self.target_cost >= self.target_budget:
            raise ValueError("The experiment budget is used. Call finish.")
        known = {task["task_id"] for task in self.baseline["tasks"]}
        if task_ids is not None and (not isinstance(task_ids, list) or not task_ids or not set(task_ids) <= known):
            raise ValueError("task_ids must be baseline task IDs: " + ", ".join(sorted(known)))
        if type(repetitions) is not int or not 1 <= repetitions <= 3:
            raise ValueError("repetitions must be 1 to 3.")
        number, sha = len(self.experiments) + 1, self.sha()
        self.service.event(self.job_id, "experiment_started", {"experiment": number, "candidate_sha256": sha,
                                                               "task_ids": task_ids or sorted(known), "repetitions": repetitions})
        try:
            tasks = self.service.baselines.evaluate(self.user_id, self.baseline, self.overlay(), task_ids, repetitions,
                                                    {"job_id": self.job_id, "experiment": number})
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from None
        runs = [run for task in tasks for run in task["runs"]]
        cost = sum(run["cost_usd"] or 0 for run in runs)
        self.target_cost += cost
        self.target_calls += sum(run["model_calls"] for run in runs)
        comparison = compare(self.baseline, tasks)
        experiment = {"experiment": number, "candidate_sha256": sha, "changed_files": sorted(self.original), "patch": self.patch(),
                      "repetitions": repetitions, "cost_usd": cost, "comparison": comparison,
                      "runs": [{"task_id": task["task_id"], "run_id": run["run_id"], "trace_id": run.get("trace_id"),
                                "status": run["status"], "stop_reason": run["stop_reason"]} for task in tasks for run in task["runs"]]}
        self.experiments.append(experiment)
        self.service.update(self.job_id, "running", self.result())
        self.service.event(self.job_id, "experiment", {key: experiment[key] for key in ("experiment", "candidate_sha256", "repetitions", "cost_usd", "comparison")})
        failures = {task["task_id"]: {"reason": task["reason"], "stderr_tail": task["runs"][-1]["stderr_tail"][-800:],
                                      "output": json.dumps(task["runs"][-1]["output"], default=str)[:1500]}
                    for task in tasks if not task["automatic_passed"]}
        return {"experiment": number, "of": MAX_EXPERIMENTS, "verdict": comparison["verdict"], "all_tasks": comparison["all_tasks"],
                "regressed_tasks": comparison["regressed_tasks"], "improved_metrics": comparison["improved_metrics"],
                "totals": comparison["totals"], "tasks": [{k: row[k] for k in ("task_id", "name", "baseline_status", "candidate_status", "regressed", "fixed")}
                                                          | {"cost_change_percent": row["metrics"]["cost_usd"]["change_percent"],
                                                             "calls": [row["metrics"]["model_calls"]["baseline"], row["metrics"]["model_calls"]["candidate"]]}
                                                          for row in comparison["tasks"]],
                "failing_tasks": failures, "experiment_cost_usd": cost, "budget_left_usd": round(self.target_budget - self.target_cost, 4)}

    def finish(self, decision, summary):
        if decision not in {"accept", "reject", "no_improvement"} or not isinstance(summary, str) or not 10 <= len(summary.strip()) <= 3000:
            raise ValueError("finish needs a decision and a summary of 10 to 3000 characters.")
        latest = next((e for e in reversed(self.experiments) if e["candidate_sha256"] == self.sha()), None)
        if decision == "accept":
            # The model proposes; these measurements decide.
            if latest is None:
                raise ValueError("The current candidate has not been run. Run every task before accepting.")
            if not latest["comparison"]["all_tasks"]:
                raise ValueError("Accept needs a run of every task on the current candidate, not a subset.")
            if latest["comparison"]["verdict"] == "regressed":
                raise ValueError("The current candidate regressed tasks " + ", ".join(latest["comparison"]["regressed_tasks"]) + ". Revise, revert, or reject.")
            if latest["comparison"]["verdict"] != "improved":
                raise ValueError("No saving beyond the baseline's own variation was measured. Finish as no_improvement, or revise.")
        self.state["finish"] = {"decision": decision, "summary": summary.strip(), "accepted_experiment": latest["experiment"] if decision == "accept" else None}
        return {"accepted": True, "decision": decision}

    def result(self):
        latest = next((e for e in reversed(self.experiments) if e["candidate_sha256"] == self.sha()), None)
        return {"baseline_id": self.baseline["baseline_id"], "finding": self.finding, "experiments": self.experiments,
                "changed_files": sorted(self.original), "candidate_sha256": self.sha(), "patch": self.patch(),
                "comparison": latest["comparison"] if latest else None,
                "target_usage": {"calls": self.target_calls, "estimated_cost_usd": self.target_cost}}

    def dispatch(self, call):
        name = call["function"]["name"]
        try:
            arguments = json.loads(call["function"]["arguments"] or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object.")
            logged = {key: (value if len(str(value)) <= 300 else str(value)[:300] + "…") for key, value in arguments.items()}
            self.service.event(self.job_id, "tool", {"name": name, "arguments": logged})
            if name in {"list_files", "search_code", "read_file"}:
                return getattr(self.source, name)(**arguments)
            if name in {"edit_file", "write_file", "revert", "show_diff", "read_baseline", "run_candidate", "finish"}:
                return getattr(self, name)(**arguments)
            raise ValueError("Tool is not available in optimization.")
        except (ValueError, TypeError, OSError, HTTPException) as exc:
            error = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            self.service.event(self.job_id, "tool_error", {"name": name, "error": error[:400]})
            return {"error": error[:400]}
