import json
import time
import uuid

from fastapi import HTTPException

from .scanner import scan
from ..gateway.models import LITELLM_MODELS


def suggestions(findings):
    configuration = {}
    for kind in ("python_version", "entrypoint", "model_provider", "model_id"):
        values = {f["value"] for f in findings["findings"] if f["kind"] == kind}
        configuration[kind] = next(iter(values)) if len(values) == 1 else None
    manifests = sorted({f["value"] for f in findings["findings"] if f["kind"] == "dependency_manifest"})
    configuration["dependency_manifests"] = manifests if len(manifests) == 1 else None
    configuration["approved_tools"] = []
    return configuration


class InspectionService:
    def __init__(self, database, github):
        self.database, self.github = database, github

    def ready(self, db, user_id, import_id):
        row = db.execute("SELECT * FROM repository_imports WHERE id=? AND user_id=?", (import_id, user_id)).fetchone()
        if not row or row["status"] == "deleted":
            raise HTTPException(404, "Import not found.")
        if row["status"] != "ready" or not row["snapshot_path"]:
            raise HTTPException(409, "Import must be ready before inspection.")
        return row

    def inspect(self, user_id, import_id):
        # Share the import deletion lock so source cannot disappear during a scan.
        with self.github.lock:
            with self.database.connect() as db:
                row = self.ready(db, user_id, import_id)
                sha = row["commit_sha"]
                expected = self.github.source_path(user_id, import_id)
                if row["snapshot_path"] != str(expected):
                    raise HTTPException(409, "Import snapshot location is inconsistent.")
            try:
                findings = scan(expected)
                findings["suggested_configuration"] = suggestions(findings)
            except OSError:
                raise HTTPException(409, "Source is unavailable or changed during inspection. Reimport the repository.") from None
            now, revision = int(time.time()), uuid.uuid4().hex
            with self.database.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = self.ready(db, user_id, import_id)
                if current["commit_sha"] != sha:
                    raise HTTPException(409, "Import revision changed. Inspect again.")
                db.execute("""INSERT INTO repository_inspections
                    (import_id,commit_sha,revision,findings,configuration,status,created_at,updated_at)
                    VALUES (?,?,?,?,NULL,'suggested',?,?) ON CONFLICT(import_id) DO UPDATE SET
                    commit_sha=excluded.commit_sha,revision=excluded.revision,findings=excluded.findings,
                    configuration=NULL,configuration_revision=NULL,status='suggested',updated_at=excluded.updated_at""",
                    (import_id, sha, revision, json.dumps(findings), now, now))
        return self.get(user_id, import_id)

    def get(self, user_id, import_id):
        with self.database.connect() as db:
            imported = self.ready(db, user_id, import_id)
            row = db.execute("SELECT * FROM repository_inspections WHERE import_id=? AND commit_sha=?",
                             (import_id, imported["commit_sha"])).fetchone()
        if not row:
            raise HTTPException(404, "No inspection yet. Inspect this import first.")
        findings = json.loads(row["findings"])
        return {"import_id": import_id, "commit_sha": row["commit_sha"], "revision": row["revision"],
                "status": row["status"], "findings": findings, "suggested_configuration": findings["suggested_configuration"],
                "configuration": json.loads(row["configuration"]) if row["configuration"] else None,
                "configuration_revision": row["configuration_revision"],
                "litellm_models": LITELLM_MODELS,
                "created_at": row["created_at"], "updated_at": row["updated_at"], "runnable": False}

    def confirm(self, user_id, import_id, body):
        with self.github.lock, self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            imported = self.ready(db, user_id, import_id)
            row = db.execute("SELECT * FROM repository_inspections WHERE import_id=?", (import_id,)).fetchone()
            if not row or row["revision"] != body.revision or row["commit_sha"] != body.commit_sha or imported["commit_sha"] != body.commit_sha:
                raise HTTPException(409, "Inspection changed. Retrieve the latest findings before confirming.")
            findings = json.loads(row["findings"])
            manifests = {f["value"] for f in findings["findings"] if f["kind"] == "dependency_manifest"}
            tools = {f["value"] for f in findings["findings"] if f["kind"] == "tool"}
            if not set(body.dependency_manifests).issubset(manifests):
                raise HTTPException(422, "Select dependency manifests present in this inspection.")
            if not set(body.approved_tools).issubset(tools):
                raise HTTPException(422, "Only detected tools can be approved at this stage.")
            known_entries = {f["value"] for f in findings["findings"] if f["kind"] == "entrypoint"}
            if body.entrypoint not in known_entries:
                files = set(findings["python_files"])
                if body.entrypoint.startswith("python"):
                    parts = body.entrypoint.split()
                    target = parts[-1]
                    if "-m" in parts:
                        target = target.replace(".", "/")
                        exists = target + ".py" in files or target + "/__main__.py" in files
                    else:
                        exists = target.removeprefix("./") in files
                else:
                    target = body.entrypoint.split(":")[0].replace(".", "/")
                    exists = target + ".py" in files or "src/" + target + ".py" in files or target + "/__init__.py" in files
                if not exists:
                    raise HTTPException(422, "Corrected entrypoint must reference Python source found by inspection.")
            configuration = body.model_dump(exclude={"revision", "commit_sha"}, exclude_none=True)
            configuration["tool_permissions"] = [{"tool": tool, "approved": tool in body.approved_tools} for tool in sorted(tools)]
            configuration["field_sources"] = {key: ("detected" if value in [f["value"] for f in findings["findings"] if f["kind"] == key] else "user_confirmed")
                for key, value in configuration.items() if key in {"python_version", "entrypoint", "model_provider", "model_id"}}
            encoded = json.dumps(configuration, sort_keys=True)
            unchanged = row["configuration"] and json.loads(row["configuration"]) == configuration
            revision = row["configuration_revision"] if unchanged and row["configuration_revision"] else uuid.uuid4().hex
            db.execute("UPDATE repository_inspections SET configuration=?,configuration_revision=?,status='confirmed',updated_at=? WHERE import_id=?",
                       (encoded, revision, int(time.time()), import_id))
        return self.get(user_id, import_id)
