"""Investigate an existing web_lookup fixture baseline with real metered model calls.

No target execution or patching. Maximum 36 model calls, 30 turns, $1.50 soft admission threshold.
Use AGENT_MODEL=claude-haiku for the small local proof.
"""
import argparse
import json
import time

from app.config import ROOT, Settings
from app.main import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("import_id")
    parser.add_argument("--baseline-id")
    args = parser.parse_args()
    state = create_app(Settings.from_env()).app.state
    state.database.initialize()
    with state.database.connect() as db:
        row = db.execute("SELECT * FROM repository_imports WHERE id=?", (args.import_id,)).fetchone()
    if not row or row["connection_generation"] != "local-fixture" or row["repository_name"] != "examples/web_lookup":
        raise SystemExit("Supply the existing labelled web_lookup fixture, not an unrelated import.")
    owner = row["user_id"]
    job = state.agent.start_investigation(owner, args.import_id, args.baseline_id)
    evidence = {"fixture": True, "job": job, "events": []}
    path = ROOT / "var/investigation-proof.json"
    print(json.dumps({"job_id": job["job_id"], "baseline_id": job["result"].get("baseline_id"),
                      "model": state.settings.agent_model, "max_calls": 36, "max_spend_usd": 1.5}), flush=True)
    after = 0
    while True:
        for event in state.agent.events(owner, args.import_id, job["job_id"], after)["events"]:
            after = event["id"]
            evidence["events"].append(event)
            # Full event data stays in private evidence; avoid dumping large ledger snapshots.
            data = dict(event["data"])
            if event["kind"] == "finding":
                data = {key: data[key] for key in ("finding_id", "waste", "estimated_saving", "behaviour_risk", "proposed_change")}
            if event["kind"] == "finished":
                data = {key: data.get(key) for key in ("status", "summary", "reason", "agent_usage", "trace")}
            print(f"[{event['kind']}] {json.dumps(data, ensure_ascii=False)[:2000]}", flush=True)
        evidence["job"] = state.agent.job(owner, args.import_id, job["job_id"])
        path.write_text(json.dumps(evidence, indent=2, allow_nan=False))
        path.chmod(0o600)
        if (evidence["job"]["status"] != "running" and not state.agent.threads[job["job_id"]].is_alive() and
                not state.agent.events(owner, args.import_id, job["job_id"], after)["events"]):
            break
        time.sleep(1)
    # One explicit recheck of the investigation's own accepted trace; no model call or re-export.
    trace = evidence["job"]["result"].get("trace") or {}
    if trace.get("trace_id"):
        evidence["job_trace_readback"] = state.traces.recheck(owner, args.import_id, trace["trace_id"])
        path.write_text(json.dumps(evidence, indent=2, allow_nan=False))
    print("Saved private findings and events: var/investigation-proof.json", flush=True)
    assert evidence["job"]["kind"] == "investigation" and evidence["events"][-1]["kind"] == "finished"
    if evidence["job"]["status"] != "ready":
        raise SystemExit("Investigation did not finish; inspect its saved job and events. No paid retry was started.")


if __name__ == "__main__":
    main()
