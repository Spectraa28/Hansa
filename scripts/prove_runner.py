"""Register the local example as a labelled fixture, then prove real container execution."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import uuid

from backend.app.config import Settings, ROOT
from backend.app.database import Database
from backend.app.github.service import GitHubService
from backend.app.inspection.service import InspectionService
from backend.app.inspection.schemas import ConfirmInput
from backend.app.gateway.service import GatewayService
from backend.app.runner.service import RunnerService
from backend.app.tracing.service import TraceService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-call-only", action="store_true", help="One live call without dollar-budget admission.")
    parser.add_argument("--internet", action="store_true", help="Also prove filtered internet access through the egress sidecar.")
    args = parser.parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_path)
    database.initialize()
    github = GitHubService(settings, database)
    inspection = InspectionService(database, github)
    gateway = GatewayService(settings, database, inspection)
    runner = RunnerService(settings, database, inspection, gateway)
    runner.tracer = TraceService(settings, database, inspection)
    owner, import_id = str(uuid.uuid4()), str(uuid.uuid4())
    source = ROOT / "examples/one_call"
    sha = hashlib.sha1(b"".join(p.read_bytes() for p in sorted(source.iterdir()) if p.is_file())).hexdigest()
    snapshot = github.source_path(owner, import_id)
    snapshot.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copytree(source, snapshot, ignore=shutil.ignore_patterns("__pycache__"))
    now = int(time.time())
    with database.connect() as db:
        db.execute("INSERT INTO users(id,email,name,created_at) VALUES (?,?,?,?)",
                   (owner, "runner-" + owner + "@example.invalid", "Local runner fixture", now))
        db.execute("""INSERT INTO repository_imports
            (id,user_id,connection_generation,installation_id,repository_id,repository_name,branch,
             commit_sha,snapshot_path,status,created_at,updated_at)
            VALUES (?,?,'local-fixture',0,0,'examples/one_call','local',?,?,'ready',?,?)""",
                   (import_id, owner, sha, str(snapshot), now, now))
    findings = inspection.inspect(owner, import_id)
    inspection.confirm(owner, import_id, ConfirmInput(revision=findings["revision"], commit_sha=sha,
        python_version="3.12", entrypoint="python agent.py", dependency_manifests=["requirements.txt"],
        model_provider="openai", model_id="claude-haiku", litellm_model="claude-haiku", approved_tools=[]))
    build = runner.build(owner, import_id)
    print(json.dumps({"fixture_import": import_id, "fixture_owner": owner, "build": build}), flush=True)
    live = runner.run(owner, import_id, build["build_id"], {"prompt": "Reply with OK."}, timeout_seconds=30,
                      max_calls=1, max_spend_usd=None if args.live_call_only else 0.01, internet=args.internet)
    print(json.dumps({"live": live}, indent=2), flush=True)
    assert live["stop_reason"] == "completed" and live["output"]["http_status"] == 200
    assert all(live["output"]["isolation"].values()) and live["gateway"]["calls"] == 1
    assert live["gateway"]["unknown_cost_calls"] == 0
    assert runner.get(owner, import_id, live["run_id"]) == live
    timeout = runner.run(owner, import_id, build["build_id"], {"mode": "timeout"}, timeout_seconds=1, max_calls=0)
    print(json.dumps({"timeout": timeout}, indent=2), flush=True)
    assert timeout["stop_reason"] == "timeout" and timeout["exit_code"] == 137
    assert timeout["cleanup_complete"] and not timeout["container_running"] and timeout["gateway"]["calls"] == 0
    internet = None
    if args.internet:
        internet = runner.run(owner, import_id, build["build_id"], {"mode": "internet"}, timeout_seconds=60,
                              max_calls=0, internet=True)
        print(json.dumps({"internet": internet}, indent=2), flush=True)
        assert internet["stop_reason"] == "completed" and all(internet["output"]["isolation"].values())
        assert internet["output"]["internet"] == {"https_public": 200, "http_public": 200, "metadata": 403,
                                                  "private": 403, "docker_host": 403, "other_port": 403}
        assert internet["egress"]["allowed"] == 2 and internet["egress"]["denied"] == 4
    evidence = ROOT / "var/runner-proof.json"
    evidence.write_text(json.dumps({"fixture": True, "build": build, "live": live, "timeout": timeout,
                                    "internet": internet}, indent=2))
    evidence.chmod(0o600)
    print("Saved private evidence: var/runner-proof.json", flush=True)


if __name__ == "__main__":
    main()
