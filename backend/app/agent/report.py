"""One document for an import: what was measured, what was found, what was changed, and what it cost to find out.

Everything here is read from stored results. Nothing is recomputed from the model and nothing starts work.
"""
import json
import math

METRICS = ("model_calls", "tokens_in", "tokens_out", "cost_usd", "wall_time_seconds")


def total(tasks, key):
    values = [task.get(key) for task in tasks]
    return None if any(value is None for value in values) else sum(values)


def baseline_section(baseline):
    if baseline is None:
        return None
    tasks = baseline.get("tasks", [])
    return {"baseline_id": baseline["baseline_id"], "status": baseline["status"], "model": baseline.get("litellm_model"),
            "repetitions": baseline.get("repetitions"), "commit_sha": baseline.get("commit_sha"), "created_at": baseline.get("created_at"),
            "passed": baseline.get("passed"), "failed": baseline.get("failed"), "needs_review": baseline.get("needs_review"),
            "per_pass": {key: total(tasks, key) for key in METRICS},
            "tasks": [{"task_id": task.get("task_id"), "name": task.get("name"), "status": task.get("status"), "reason": task.get("reason"),
                       **{key: task.get(key) for key in METRICS}, "spread": task.get("spread"),
                       "trace_ids": task.get("trace_ids") or [task.get("trace_id")]} for task in tasks],
            "note": "per_pass is the mean cost of running every task once. Cost is LiteLLM-reported, not invoice-reconciled."}


def payback(job, baseline):
    """How many full passes of the task set repay what was spent finding and proving this change."""
    result = job["result"]
    comparison = result.get("comparison") or {}
    cost = (comparison.get("totals") or {}).get("cost_usd") or {}
    usages = [result.get("agent_usage") or {}, result.get("target_usage") or {}]
    # No calls means nothing was spent; a call of unknown cost means the total is unknown.
    spent = [0 if not usage.get("calls") else None if usage.get("unknown_cost_calls") else usage.get("estimated_cost_usd")
             for usage in usages]
    if result.get("decision") != "accept" or cost.get("baseline") is None or cost.get("candidate") is None or None in spent:
        return None
    saving = cost["baseline"] - cost["candidate"]
    return {"saving_per_pass_usd": saving, "optimization_cost_usd": sum(spent),
            # Rounded first so float error cannot turn exactly four passes into five.
            "break_even_passes": math.ceil(round(sum(spent) / saving, 6)) if saving > 0 else None,
            "note": "Optimization cost is the agent's model calls plus every candidate run. It excludes the baseline, "
                    "the investigation and compute. A pass is every contract task run once."}


def build(service, baselines, user_id, import_id):
    with service.database.connect() as db:
        imported = service.owned(db, user_id, import_id)
        baseline_row = db.execute("SELECT result FROM baselines WHERE import_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                                  (import_id,)).fetchone()
        jobs = db.execute("SELECT id FROM agent_jobs WHERE import_id=? ORDER BY created_at, rowid", (import_id,)).fetchall()
        adapter = db.execute("SELECT sha256, job_id, created_at FROM import_adapters WHERE import_id=?", (import_id,)).fetchone()
    baseline = json.loads(baseline_row["result"]) if baseline_row else None
    jobs = [service.job(user_id, import_id, row["id"]) for row in jobs]
    investigations = [job for job in jobs if job["kind"] == "investigation" and job["status"] == "ready"]
    investigation = investigations[-1] if investigations else None
    optimizations = []
    for job in jobs:
        if job["kind"] != "optimization":
            continue
        result = job["result"]
        optimizations.append({
            "job_id": job["job_id"], "status": job["status"], "decision": result.get("decision"), "summary": result.get("summary") or result.get("reason"),
            "incomplete": bool(result.get("incomplete")), "finding": result.get("finding"), "changed_files": result.get("changed_files", []),
            "patch_available": bool(result.get("patch")), "candidate_sha256": result.get("candidate_sha256"),
            "comparison": result.get("comparison"),
            "experiments": [{"experiment": e["experiment"], "verdict": e["comparison"]["verdict"], "all_tasks": e["comparison"]["all_tasks"],
                             "regressed_tasks": e["comparison"]["regressed_tasks"], "cost_usd": e["cost_usd"],
                             "changed_files": e["changed_files"]} for e in result.get("experiments", [])],
            "agent_usage": result.get("agent_usage"), "target_usage": result.get("target_usage"),
            "payback": payback(job, baseline), "trace": result.get("trace"), "created_at": job["created_at"]})
    spend = {kind: sum((job["result"].get("agent_usage") or {}).get("estimated_cost_usd") or 0 for job in jobs if job["kind"] == kind)
             for kind in ("onboarding", "investigation", "optimization")}
    spend["candidate_runs"] = sum((job["result"].get("target_usage") or {}).get("estimated_cost_usd") or 0
                                  for job in jobs if job["kind"] == "optimization")
    return {
        "import": {"import_id": import_id, "repository": imported["repository_name"], "branch": imported["branch"], "commit_sha": imported["commit_sha"]},
        "adapter": dict(adapter) if adapter else None,
        "baseline": baseline_section(baseline),
        "investigation": None if investigation is None else {
            "job_id": investigation["job_id"], "summary": investigation["result"].get("summary"),
            "incomplete": bool(investigation["result"].get("incomplete")),
            "nothing_worth_changing": investigation["result"].get("nothing_worth_changing"),
            "findings": [{key: finding.get(key) for key in ("finding_id", "waste", "proposed_change", "behaviour_risk", "estimated_saving", "saving_scope")}
                         | {"source": finding["evidence"]["source"], "run_ids": [run["run_id"] for run in finding["evidence"]["runs"]]}
                         for finding in investigation["result"].get("findings", [])],
            "coverage": investigation["result"].get("coverage", []), "agent_usage": investigation["result"].get("agent_usage"),
            "trace": investigation["result"].get("trace"),
            "note": "Estimated savings are hypotheses until an optimization measures them."},
        "optimizations": optimizations,
        "accepted": [item["job_id"] for item in optimizations if item["decision"] == "accept"],
        "spend_usd": spend,
        "stages": {"onboarded": adapter is not None, "baseline": bool(baseline and baseline["status"] == "completed"),
                   "investigated": investigation is not None, "optimized": bool(optimizations)},
        "limits": ["Results hold for the listed tasks at this commit, model and repetition count only.",
                   "Tasks marked needs_review have not had their answers confirmed by a person.",
                   "A candidate is compared on automatic checks; it is not a protected, held-out evaluation.",
                   "Costs are the provider's reported figures per call and exclude compute."],
    }
