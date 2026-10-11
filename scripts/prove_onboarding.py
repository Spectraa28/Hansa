"""Register examples/web_lookup as a labelled local fixture and let the agent onboard it for real.

Makes paid model calls: the agent's own (AGENT_MODEL) and the target's (claude-haiku), both metered.
"""
import argparse
import hashlib
import json
import shutil
import time
import uuid

from backend.app.agent.service import AgentService
from backend.app.config import Settings, ROOT
from backend.app.database import Database
from backend.app.gateway.service import GatewayService
from backend.app.github.service import GitHubService
from backend.app.inspection.schemas import ConfirmInput
from backend.app.inspection.service import InspectionService
from backend.app.runner.service import RunnerService
from backend.app.tracing.service import TraceService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--example", default="web_lookup")
    parser.add_argument("--entrypoint", default="python cli.py")
    parser.add_argument("--question", default="What is the title of the page at https://example.com ?")
    args = parser.parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_path)
    database.initialize()
    github = GitHubService(settings, database)
    inspection = InspectionService(database, github)
    gateway = GatewayService(settings, database, inspection)
    runner = RunnerService(settings, database, inspection, gateway)
    runner.tracer = TraceService(settings, database, inspection)
    agent = AgentService(settings, database, runner, gateway)
    agent.tracer = runner.tracer
    owner, import_id = str(uuid.uuid4()), str(uuid.uuid4())
    source = ROOT / "examples" / args.example
    files = sorted(p for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    sha = hashlib.sha1(b"".join(p.read_bytes() for p in files)).hexdigest()
    snapshot = github.source_path(owner, import_id)
    snapshot.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copytree(source, snapshot, ignore=shutil.ignore_patterns("__pycache__"))
    now = int(time.time())
    with database.connect() as db:
        db.execute("INSERT INTO users(id,email,name,created_at) VALUES (?,?,?,?)",
                   (owner, "onboarding-" + owner + "@example.invalid", "Local onboarding fixture", now))
        db.execute("""INSERT INTO repository_imports
            (id,user_id,connection_generation,installation_id,repository_id,repository_name,branch,
             commit_sha,snapshot_path,status,created_at,updated_at)
            VALUES (?,?,'local-fixture',0,0,?,'local',?,?,'ready',?,?)""",
                   (import_id, owner, "examples/" + args.example, sha, str(snapshot), now, now))
    findings = inspection.inspect(owner, import_id)
    inspection.confirm(owner, import_id, ConfirmInput(revision=findings["revision"], commit_sha=sha,
        python_version="3.12", entrypoint=args.entrypoint, dependency_manifests=["requirements.txt"],
        model_provider="openai", model_id="gpt-4o", litellm_model="claude-haiku", approved_tools=[]))
    job = agent.start_onboarding(owner, import_id)
    print(json.dumps({"fixture_import": import_id, "job_id": job["job_id"], "agent_model": settings.agent_model}), flush=True)
    last = 0
    while True:
        for event in agent.events(owner, import_id, job["job_id"], last)["events"]:
            last = event["id"]
            data = dict(event["data"])
            if "code" in data:
                data["code"] = f"<{data['lines']} lines>"
            print(f"[{event['kind']}] {json.dumps(data, ensure_ascii=False)[:700]}", flush=True)
        current = agent.job(owner, import_id, job["job_id"])
        if current["status"] != "running" and not agent.events(owner, import_id, job["job_id"], last)["events"]:
            break
        time.sleep(1)
    evidence = {"fixture": True, "job": current, "events": []}
    after = 0
    while batch := agent.events(owner, import_id, job["job_id"], after)["events"]:
        evidence["events"] += batch
        after = batch[-1]["id"]
    if current["status"] == "ready":
        stored = agent.adapter(owner, import_id)
        print("\n--- stored adapter ---\n" + stored["content"], flush=True)
        build = runner.build(owner, import_id)
        rerun = runner.run(owner, import_id, build["build_id"], {**stored["example_task"]["task"]}, timeout_seconds=150,
                           max_calls=30, max_spend_usd=0.25, memory_mb=1024, pids=128, adapter="stored",
                           internet=settings.runner_internet)
        print(json.dumps({"stored_adapter_rerun": {k: rerun[k] for k in ("stop_reason", "exit_code", "wall_time_seconds", "output")},
                          "gateway": {k: rerun["gateway"][k] for k in ("calls", "prompt_tokens", "completion_tokens", "estimated_cost_usd")},
                          "egress_hosts": (rerun.get("egress") or {}).get("hosts")}, indent=2)[:3000], flush=True)
        evidence["stored_adapter_rerun"] = rerun
    path = ROOT / "var/onboarding-proof.json"
    path.write_text(json.dumps(evidence, indent=2, default=str))
    path.chmod(0o600)
    print("Saved private evidence: var/onboarding-proof.json", flush=True)


if __name__ == "__main__":
    main()
