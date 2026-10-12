"""One document for an import: what was measured, what was found, what was changed, and what it cost to find out.

Everything here is read from stored results. Nothing is recomputed from the model and nothing starts work.
"""
import json
import math
from pathlib import Path

from ..runner.service import left_out
from ..runner.xray import anatomy

METRICS = ("model_calls", "tokens_in", "tokens_out", "cost_usd", "wall_time_seconds")


def total(tasks, key):
    values = [task.get(key) for task in tasks]
    return None if any(value is None for value in values) else sum(values)


def baseline_section(baseline, database=None):
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
            # What the agent is made of, from the call ledger alone. Free to compute; None until a baseline completes.
            "xray": anatomy(database, baseline) if database is not None and baseline["status"] == "completed" else None,
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


def proof(comparison, baseline):
    """How much a verdict rests on. A pass on loose checks over two tasks is not the same as one on exact checks over twenty."""
    if not comparison:
        return None
    tasks = comparison.get("tasks") or []
    contract = ((baseline or {}).get("contract") or {}).get("tasks") or []
    by_id = {str(index): task for index, task in enumerate(contract, 1)}
    exact = {task["task_id"]: sum(1 for rule in (by_id.get(task["task_id"]) or {}).get("required_fields", []) if rule.get("check_exact"))
             + (1 if (by_id.get(task["task_id"]) or {}).get("expected_output") is not None else 0) for task in tasks}
    shape_only = [task_id for task_id, count in exact.items() if not count] if contract else []
    repetitions = (baseline or {}).get("repetitions")
    notes = []
    if len(tasks) < 3:
        notes.append(f"It rests on {len(tasks)} task{'s' if len(tasks) != 1 else ''}.")
    if not comparison.get("all_tasks"):
        notes.append("Not every task in the set was run.")
    if contract and len(shape_only) == len(tasks):
        notes.append("The checks only test the shape of the answer, so they would not catch the agent doing the wrong thing.")
    elif shape_only:
        notes.append(f"Task{'s' if len(shape_only) != 1 else ''} {', '.join(shape_only)} {'have' if len(shape_only) != 1 else 'has'} no exact check, "
                     "so only the shape of the answer is tested there.")
    if not comparison.get("variation_measured"):
        notes.append("The baseline ran each task once, so normal run-to-run variation was not measured.")
    if comparison.get("needs_review"):
        notes.append("A person still has to confirm the answers on the tasks marked for review.")
    weak = len(tasks) < 3 or not comparison.get("all_tasks") or (contract and len(shape_only) == len(tasks))
    strong = len(tasks) >= 5 and comparison.get("variation_measured") and not shape_only and comparison.get("all_tasks")
    return {"tasks": len(tasks), "repetitions": repetitions, "tasks_with_exact_checks": len(tasks) - len(shape_only) if contract else None,
            "variation_measured": bool(comparison.get("variation_measured")),
            "strength": "thin" if weak else "solid" if strong else "fair", "notes": notes}


def patch_files(patch):
    """Paths a unified diff touches, with lines added and removed."""
    files, current = {}, None
    for line in (patch or "").splitlines():
        if line.startswith("+++ "):
            current = line[4:].removeprefix("b/")
            files[current] = [0, 0]
        elif current and line.startswith("+") and not line.startswith("+++"):
            files[current][0] += 1
        elif current and line.startswith("-") and not line.startswith("---"):
            files[current][1] += 1
    return files


def handoff(job, repository, baseline=None, commit=None):
    """A work order the owner can paste into their own coding agent. Built only from stored results; no model call.

    Written for a reader that has the repository open and nothing else: what the job is, what to do in order,
    the exact change, what must stay true, how to know it is done, and what to report back.
    """
    result = job["result"]
    accepted = result.get("decision") == "accept" and bool(result.get("patch"))
    tried = [e for e in result.get("experiments", []) if e.get("patch")]
    patch = result["patch"] if accepted else tried[-1]["patch"] if tried else None
    if patch is None:
        return None
    comparison = result.get("comparison") or (tried[-1]["comparison"] if tried else {})
    finding = result.get("finding") or {}
    strength = proof(comparison, baseline)
    files = patch_files(patch)
    at = f" at commit `{commit[:12]}`" if commit else ""
    lines = [f"# Task: {'apply' if accepted else 'review'} a measured change to {repository}", "",
             f"You are working in a checkout of `{repository}`{at}. A tool called Hansa ran this repository's AI agent on a fixed set of tasks, "
             "found a way to make it cheaper or faster, changed a private copy, and measured the result. Your job is below.", ""]
    if accepted:
        lines += ["**Status: accepted.** The change passed every automatic check that passed before, and the saving is measured.", ""]
    else:
        lines += [f"**Status: NOT accepted (decision: {result.get('decision') or 'none'}).** The change is here for review only. "
                  "Do not apply it as it stands.", ""]
    lines += ["## What to do", ""]
    if accepted:
        lines += ["1. Confirm the files below still match the diff's context lines. If the code has moved since that commit, find the same code by function or symbol name and apply the same edit there.",
                  "2. Apply the diff exactly. Change nothing else: no refactoring, renaming or reformatting.",
                  "3. Work through the checklist under \"Before you call it done\".",
                  "4. Run the project's tests. If there are none for the code you touched, say so.",
                  "5. Report back in the format at the end."]
    else:
        lines += ["1. Read the reason the change was not accepted, below.",
                  "2. Reproduce the failing task with and without the change, several times each, to see whether the change causes the failure or the agent already fails that way.",
                  "3. Only if the unchanged code fails the same way should the change be reconsidered, and then it must be measured again.",
                  "4. Report back in the format at the end. Do not commit the diff."]
    lines += ["", "## Why this change", "", str(finding.get("waste") or "No finding text was recorded."), ""]
    if result.get("summary"):
        # The agent writes its own headings; keep them under this one.
        lines += ["## What Hansa did and saw", "", "\n".join("#" + line if line.startswith("#") else line for line in result["summary"].splitlines()), ""]
    totals = comparison.get("totals") or {}
    rows = [(label, totals.get(key) or {}) for label, key in (("Model calls", "model_calls"), ("Input tokens", "tokens_in"),
                                                               ("Cost (USD)", "cost_usd"), ("Wall time (s)", "wall_time_seconds"))]
    if any(row.get("baseline") is not None for _, row in rows):
        lines += ["## Measured, same tasks before and after", "", "| Per pass of the task set | Before | After | Change |", "| --- | --- | --- | --- |"]
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
    if strength:
        lines += [f"## How strong the proof is: {strength['strength']}", ""] + [f"- {note}" for note in strength["notes"]]
        lines += ["- Nothing here limits the result." if not strength["notes"] else "", ""]
    lines += ["## The change", "", "Files: " + ", ".join(f"`{path}` (+{added} −{removed})" for path, (added, removed) in files.items()) + ".", "",
              "```diff", patch.rstrip("\n"), "```", ""]
    if accepted:
        lines += ["## Before you call it done", "",
                  "Hansa measured this on a small task set. Check what it could not:", "",
                  "- [ ] Read the diff as a reviewer. If it decides something by matching words in free text, make it match whole words only and confirm an input containing two intents, or none, still takes the original path.",
                  "- [ ] If it touches a shared library or framework file rather than the agent's own code, confirm nothing else that uses that file changes behaviour, or move the edit into the agent's code.",
                  "- [ ] If it adds anything to what the agent returns or stores, confirm downstream code and saved data tolerate it, or remove it.",
                  "- [ ] Add a test for the changed path and one for the fallback path.",
                  "- [ ] Try two realistic inputs the task set did not cover and compare the agent's behaviour with and without the change.", ""]
    lines += ["## Must stay true", "",
              "- Tool names, tool behaviour, prompt wording and the shape of the agent's output are unchanged unless the diff changes them.",
              "- Any task that passed before still passes. If one fails, stop and report it; do not adjust the task or its checks.", "",
              "## Report back", "",
              "- Applied: yes or no, and the commit.",
              "- Each file changed, with the lines.",
              "- Checklist items you did, and any you could not do and why.",
              "- Tests run and their result.",
              "- Anything that behaved differently from what is described here.", "",
              "Figures are provider-reported costs for the listed tasks at one commit and model. They are not a guarantee for other inputs."]
    return "\n".join(line for index, line in enumerate(lines) if not (line == "" and index and lines[index - 1] == "")) + "\n"


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
    # A fix is judged against the baseline it ran on, which may not be the latest one.
    with service.database.connect() as db:
        baselines_by_id = {row["id"]: json.loads(row["result"]) for row in db.execute("SELECT id, result FROM baselines WHERE import_id=?", (import_id,))}
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
            "proof": proof(result.get("comparison") or (tried[-1]["comparison"] if tried else None), baselines_by_id.get(result.get("baseline_id")) or baseline),
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
        "import": {"import_id": import_id, "repository": imported["repository_name"], "branch": imported["branch"], "commit_sha": imported["commit_sha"],
                   # Source references are relative to this folder when one was imported.
                   "folder": imported["folder"] if "folder" in imported.keys() else None,
                   "left_out": left_out(Path(imported["snapshot_path"])) if imported["snapshot_path"] else []},
        "adapter": dict(adapter) if adapter else None,
        "baseline": baseline_section(baseline, service.database),
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
