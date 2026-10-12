"""Write the recorded demo's data files from one import's saved results.

    uv run python -m scripts.export_demo IMPORT_ID

Reads only what the API would return to the import's owner (report, patches, briefs, suggestions) and
writes it under frontend/src/data/. No model call, no sandbox run, no change to the database. The
output is published with the site, so point it only at an import of a public repository.
"""
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

from app.agent import playbook
from app.agent.report import build, handoff
from app.agent.routes import suggestion_set
from app.config import ROOT, Settings
from app.main import create_app

DATA = ROOT / "frontend" / "src" / "data"


def main(import_id):
    settings = Settings.from_env()
    # Services only: the app is built but never started, so no second import worker runs.
    state = create_app(settings).app.state
    with sqlite3.connect(settings.database_path) as db:
        owner = db.execute("SELECT user_id FROM repository_imports WHERE id=? AND status='ready'", (import_id,)).fetchone()
    if owner is None:
        raise SystemExit("No ready import with that ID.")
    user = owner[0]
    report = build(state.agent, state.baselines, user, import_id)
    report["active"] = None  # a recording is never mid-run
    patches, briefs = {}, {}
    for attempt in report["optimizations"]:
        job = state.agent.job(user, import_id, attempt["job_id"])
        result = job["result"]
        tried = [experiment["patch"] for experiment in result.get("experiments", []) if experiment.get("patch")]
        text = result.get("patch") if result.get("decision") == "accept" else (tried[-1] if tried else None)
        if text:
            patches[attempt["job_id"]] = text
        with state.agent.database.connect() as rows:
            imported = state.agent.owned(rows, user, import_id)
            saved = rows.execute("SELECT result FROM baselines WHERE id=? AND import_id=?", (result.get("baseline_id"), import_id)).fetchone()
        brief = handoff(job, imported["repository_name"], json.loads(saved["result"]) if saved else None, imported["commit_sha"])
        if brief:
            briefs[attempt["job_id"]] = brief
    imported, xray, found = suggestion_set(SimpleNamespace(app=SimpleNamespace(state=state)), user, import_id)
    suggestions = {"measured": xray is not None, "suggestions": found,
                   "note": "Chosen from measurements and a text-only read of the source. Savings are estimates until the tasks are rerun.",
                   "brief_all": playbook.brief(imported["repository_name"], imported["commit_sha"], imported["folder"], xray, found) if found else ""}
    for name, value in (("swarm-report", report), ("swarm-patches", patches), ("swarm-handoffs", briefs), ("swarm-suggestions", suggestions)):
        (DATA / f"{name}.json").write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n")
    print(f"Wrote {len(report['baseline']['tasks'])} tasks, {len(report['optimizations'])} tested fixes, "
          f"{len(patches)} patches, {len(briefs)} briefs and {len(found)} suggestions to {DATA}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
