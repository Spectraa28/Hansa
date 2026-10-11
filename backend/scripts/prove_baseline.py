"""Run a three-task development contract against an already-onboarded web_lookup fixture.

Paid Haiku calls, two repetitions, $0.12 soft recorded-spend admission threshold.
Uses the stored adapter; imported Python executes only inside the Docker runner.
"""
import argparse
import json
import time
from fastapi import HTTPException

from app.config import ROOT, Settings
from app.contracts.schemas import ContractInput, ConfirmInput
from app.main import create_app


def fixture_contract(revision, base_version=None):
    def field(pointer, field_type, exact=None):
        return {"pointer": pointer, "field_type": field_type, "check_exact": exact is not None,
                "exact_value": exact}

    def review(description):
        return {"description": description, "verification": "human_review", "review_guidance":
                "Read the stored answer and steps. Check the stated behavior; do not infer correctness from valid JSON."}

    tasks = []
    for name, question, answer in [
        ("Capital", "What is the capital of France? Reply with exactly the single word Paris, without punctuation. Do not fetch a page for this stable fact.", "Paris"),
        ("Arithmetic", "What is 2 + 2? Reply with exactly the digit 4, without punctuation. No web lookup is needed.", "4"),
    ]:
        tasks.append({"name": name, "description": "Return the requested exact answer.", "case_kind": "ordinary",
                      "input": {"question": question}, "expected_output": {"answer": answer, "steps": []},
                      "required_fields": [field("/answer", "string", answer), field("/steps", "array")]})
    tasks.append({"name": "Live page", "description": "Fetch example.com and identify its title.", "case_kind": "ordinary",
                  "input": {"question": "Fetch https://example.com with your tool. What is the page title? Quote the page you used."},
                  "required_fields": [field("/answer", "string"), field("/steps", "array"),
                                      field("/steps/0/tool", "string", "fetch_page"),
                                      field("/steps/0/url", "string", "https://example.com"),
                                      field("/steps/0/characters", "integer")],
                  "required_facts": [review("The answer names Example Domain as the title and quotes the fetched page.")]})
    return {"base_version": base_version, "configuration_revision": revision, "tasks": tasks,
            "acceptable_failures": {name: review("Report " + name.replace("_", " ") + " honestly when encountered.")
                                    for name in ("missing_information", "denied_access", "tool_failure")},
            "protected_behavior": {name: review("Preserve " + name.replace("_", " ") + ".")
                                   for name in ("instructions", "permissions", "freshness", "essential_information")},
            "limits": {"max_runtime_seconds": 900, "max_model_calls": 18, "max_tool_calls": 12,
                       "max_tokens": 30000, "max_spend_usd": 0.12}}


def export_report(state, owner, import_id, report):
    evidence = {"fixture": True, "result": report, "trace_readback": []}
    path = ROOT / "var/baseline-proof.json"
    # Preserve the completed result even if the remote trace read fails.
    path.write_text(json.dumps(evidence, indent=2, allow_nan=False))
    path.chmod(0o600)
    for task in report["tasks"]:
        for run in task["runs"]:
            if not run["trace_id"]:
                continue
            for attempt in range(4):
                try:
                    context = state.traces.context(owner, import_id, run["trace_id"])
                    record = {"trace_id": run["trace_id"], "context": context}
                    break
                except HTTPException as exc:
                    if "not_found" not in str(exc.detail) or attempt == 3:
                        record = {"trace_id": run["trace_id"], "error": str(exc.detail)}
                        break
                    time.sleep(3)
            evidence["trace_readback"].append(record)
            path.write_text(json.dumps(evidence, indent=2, allow_nan=False))
    print(json.dumps(report, indent=2), flush=True)
    print("Saved private evidence: var/baseline-proof.json", flush=True)
    if report["status"] != "completed" or any("error" in r for r in evidence["trace_readback"]):
        raise SystemExit("Baseline or trace readback incomplete; inspect the saved evidence. Do not rerun paid calls to retry readback.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("import_id", help="Existing labelled examples/web_lookup fixture with a stored adapter")
    parser.add_argument("--baseline-id", help="Export an existing result and retry trace readback without paid calls")
    args = parser.parse_args()
    state = create_app(Settings.from_env()).app.state
    state.database.initialize()
    with state.database.connect() as db:
        row = db.execute("SELECT * FROM repository_imports WHERE id=?", (args.import_id,)).fetchone()
    if not row or row["repository_name"] != "examples/web_lookup" or row["connection_generation"] != "local-fixture":
        raise SystemExit("Supply an already-onboarded local web_lookup fixture ID, never an unrelated import.")
    if not state.traces.enabled:
        raise SystemExit("Configure Neatlogs before running this traced proof.")
    owner = row["user_id"]
    if args.baseline_id:
        export_report(state, owner, args.import_id, state.baselines.get(owner, args.import_id, args.baseline_id))
        return
    config = state.runner.configuration(owner, args.import_id)
    if config["configuration"]["litellm_model"] != "claude-haiku":
        raise SystemExit("This bounded proof requires the fixture's confirmed claude-haiku selection.")
    state.agent.adapter(owner, args.import_id)
    previous = state.contracts.get(owner, args.import_id)
    body = fixture_contract(config["configuration_revision"], previous["version"])
    saved = state.contracts.save(owner, args.import_id, ContractInput.model_validate(body))
    state.contracts.confirm(owner, args.import_id, ConfirmInput(version=saved["version"], configuration_revision=config["configuration_revision"]))
    job = state.baselines.start(owner, args.import_id, repetitions=2)
    print(json.dumps({"fixture": True, "import_id": args.import_id, "baseline_id": job["baseline_id"],
                      "tasks": 3, "repetitions": 2, "max_spend_usd": 0.12}), flush=True)
    after = 0
    while True:
        for event in state.baselines.events(owner, args.import_id, job["baseline_id"], after)["events"]:
            after = event["id"]
            data = event["data"]
            print(json.dumps({"event": event["kind"], **{k: data[k] for k in
                ("task_id", "repetition", "status", "reason", "trace_id", "cost_usd") if k in data}}), flush=True)
        report = state.baselines.get(owner, args.import_id, job["baseline_id"])
        if report["status"] != "running" and job["baseline_id"] not in state.baselines.threads:
            break
        time.sleep(1)
    # Read the persisted latest report, not the worker's in-memory dictionary.
    report = state.baselines.latest(owner, args.import_id)
    export_report(state, owner, args.import_id, report)


if __name__ == "__main__":
    main()
