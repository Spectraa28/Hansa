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


def handoff(job, repository):
    """A brief the owner can paste into their own coding agent. Built only from stored results; no model call."""
    result = job["result"]
    accepted = result.get("decision") == "accept" and bool(result.get("patch"))
    tried = [e for e in result.get("experiments", []) if e.get("patch")]
    patch = result["patch"] if accepted else tried[-1]["patch"] if tried else None
    if patch is None:
        return None
    comparison = result.get("comparison") or (tried[-1]["comparison"] if tried else {})
    finding = result.get("finding") or {}
    lines = [f"# Change for {repository}", ""]
    if accepted:
        lines += ["Hansa tested this change against the project's task baseline and accepted it. Apply it exactly as written.", ""]
    else:
        lines += [f"**This change was NOT accepted (decision: {result.get('decision') or 'none'}).** It is included for review only. "
                  "Do not apply it as it stands. Read the reason below and resolve it first.", ""]
    lines += ["## Why", "", str(finding.get("waste") or "No finding text was recorded."), ""]
    if result.get("summary"):
        lines += ["## What was measured", "", result["summary"], ""]
    totals = comparison.get("totals") or {}
    rows = [(label, totals.get(key) or {}) for label, key in (("Model calls", "model_calls"), ("Input tokens", "tokens_in"),
                                                               ("Cost (USD)", "cost_usd"), ("Wall time (s)", "wall_time_seconds"))]
    if any(row.get("baseline") is not None for _, row in rows):
        lines += ["| Per pass of the task set | Baseline | Candidate | Change |", "| --- | --- | --- | --- |"]
        for label, row in rows:
            if row.get("baseline") is not None:
                lines.append(f"| {label} | {row['baseline']:.4g} | {row['candidate']:.4g} | {row['change_percent']}% |")
        lines.append("")
    regressed = comparison.get("regressed_tasks") or []
    if regressed:
        names = {row["task_id"]: row.get("name") for row in comparison.get("tasks", [])}
        lines += ["Tasks whose automatic checks passed before and failed with this change: "
                  + ", ".join(f"{task_id} ({names.get(task_id)})" for task_id in regressed) + ".", ""]
    review = comparison.get("needs_review") or []
    if review:
        lines += [f"Tasks {', '.join(review)} were compared on automatic checks only. A person still has to confirm their answers.", ""]
    lines += ["## The change", "", "```diff", patch.rstrip("\n"), "```", "", "## Instructions", ""]
    if accepted:
        lines += ["1. Apply the diff above to the repository at the commit it was made against. Change nothing else.",
                  "2. Do not refactor, rename or reformat surrounding code.",
                  "3. Run the project's own tests and the task set the baseline used.",
                  "4. If any task that passed before now fails, stop and report it instead of adjusting the task or its checks."]
    else:
        lines += ["1. Do not apply the diff unchanged.",
                  "2. Reproduce the failing task above with and without the change, several times each, to see whether the change causes it.",
                  "3. Only if the unchanged code fails the same way should the change be reconsidered, and then it must be measured again."]
    lines += ["", "Figures are provider-reported costs for the listed tasks at one commit and model. They are not a guarantee for other inputs."]
    return "\n".join(lines) + "\n"


def next_step(adapter, baseline, investigation, optimizations, jobs):
    """What the owner can usefully do now. Advice for the interface; it starts nothing."""
    if any(job["status"] == "running" for job in jobs) or (baseline and baseline["status"] == "running"):
        return {"action": "wait", "reason": "A job is running."}
    if adapter is None:
        blocked = [job for job in jobs if job["kind"] == "onboarding" and job["status"] == "blocked"]
        return {"action": "onboard", "endpoint": "onboarding",
                "reason": blocked[-1]["result"].get("reason") if blocked else "No adapter is stored for this import."}
    if not baseline or baseline["status"] != "completed":
        return {"action": "baseline", "endpoint": "baseline", "reason": "Confirm a task contract, then measure the agent."}
    if investigation is None or investigation["result"].get("baseline_id") != baseline["baseline_id"]:
        return {"action": "investigate", "endpoint": "investigation", "reason": "The latest baseline has not been investigated."}
    tried = {(item["finding"] or {}).get("finding_id") for item in optimizations
             if (item["finding"] or {}).get("investigation_job_id") == investigation["job_id"]}
    untried = [f["finding_id"] for f in investigation["result"].get("findings", []) if f["finding_id"] not in tried]
    if untried:
        return {"action": "optimize", "endpoint": "optimization", "finding_ids": untried,
                "reason": "Findings that have not been tested yet."}
    return {"action": "review", "reason": "Every saved finding has been tested. Review the results."}


def active(baseline, jobs):
    running = [job for job in jobs if job["status"] == "running"]
    if running:
        return {"kind": running[-1]["kind"], "job_id": running[-1]["job_id"], "events": f"agent-jobs/{running[-1]['job_id']}/events"}
    if baseline and baseline["status"] == "running":
        return {"kind": "baseline", "job_id": baseline["baseline_id"], "events": f"baseline-jobs/{baseline['baseline_id']}/events"}
    return None


def build(service, baselines, user_id, import_id):
    with service.database.connect() as db:
        imported = service.owned(db, user_id, import_id)
        baseline_row = db.execute("SELECT result FROM baselines WHERE import_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                                  (import_id,)).fetchone()
        jobs = db.execute("SELECT id FROM agent_jobs WHERE import_id=? ORDER BY created_at, rowid", (import_id,)).fetchall()
        adapter = db.execute("SELECT sha256, job_id, created_at FROM import_adapters WHERE import_id=?", (import_id,)).fetchone()
    baseline = json.loads(baseline_row["result"]) if baseline_row else None
    jobs = [service.job(user_id, import_id, row["id"]) for row in jobs]
    # Findings are verified and saved one at a time, so a job that later ran out of turns still has real ones.
    investigations = [job for job in jobs if job["kind"] == "investigation"
                      and (job["status"] == "ready" or job["result"].get("findings"))]
    concluded = [job for job in investigations if job["status"] == "ready" and not job["result"].get("incomplete")]
    investigation = (concluded or investigations or [None])[-1]
    optimizations = []
    for job in jobs:
        if job["kind"] != "optimization":
            continue
        result = job["result"]
        tried = result.get("experiments", [])
        optimizations.append({
            "job_id": job["job_id"], "status": job["status"], "decision": result.get("decision"), "summary": result.get("summary") or result.get("reason"),
            "incomplete": bool(result.get("incomplete")), "finding": result.get("finding"), "changed_files": result.get("changed_files", []),
            "patch_available": bool(result.get("patch")), "candidate_sha256": result.get("candidate_sha256"),
            # A rejected change is reverted, so its measurements and patch live on the last experiment.
            "tried_patch_available": bool(tried and tried[-1].get("patch")),
            "comparison": result.get("comparison") or (tried[-1]["comparison"] if tried else None),
            "comparison_is_of": "accepted candidate" if result.get("decision") == "accept" else "last candidate tried" if tried else None,
            "stability_checks": result.get("stability_checks", []),
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
            "incomplete": bool(investigation["result"].get("incomplete")) or investigation["status"] != "ready",
            "status": investigation["status"],
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
        "next": next_step(adapter, baseline, investigation, optimizations, jobs),
        # Lets the interface reattach to a live event feed after a reload.
        "jobs": [{"job_id": job["job_id"], "kind": job["kind"], "status": job["status"], "created_at": job["created_at"]} for job in jobs],
        "active": active(baseline, jobs),
        "limits": ["Results hold for the listed tasks at this commit, model and repetition count only.",
                   "Tasks marked needs_review have not had their answers confirmed by a person.",
                   "A candidate is compared on automatic checks; it is not a protected, held-out evaluation.",
                   "Costs are the provider's reported figures per call and exclude compute."],
    }
