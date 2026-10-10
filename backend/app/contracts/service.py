import json
import time

from fastapi import HTTPException

from .schemas import missing_requirements


class ContractService:
    def __init__(self, database, inspection):
        self.database, self.inspection = database, inspection

    def configuration(self, db, user_id, import_id):
        imported = self.inspection.ready(db, user_id, import_id)
        config = db.execute("SELECT * FROM repository_inspections WHERE import_id=? AND commit_sha=?",
                            (import_id, imported["commit_sha"])).fetchone()
        return imported, config

    def confirmed_configuration(self, db, user_id, import_id):
        imported, config = self.configuration(db, user_id, import_id)
        if not config or config["status"] != "confirmed" or not config["configuration_revision"]:
            raise HTTPException(409, "Confirm execution configuration before saving a contract.")
        return imported, config

    def result(self, row, imported, config):
        content = json.loads(row["content"])
        stale = not config or config["status"] != "confirmed" or config["configuration_revision"] != row["configuration_revision"] or imported["commit_sha"] != row["commit_sha"]
        missing = missing_requirements(content)
        return {"version": row["version"], "commit_sha": row["commit_sha"], "configuration_revision": row["configuration_revision"],
                "configuration_snapshot": json.loads(row["configuration_snapshot"]), "contract": content,
                "status": row["status"], "stale": stale, "missing_requirements": missing,
                "can_confirm": not stale and not missing and row["status"] == "draft", "dataset_scope": "development", "runnable": False, "limits_enforced": False,
                "created_at": row["created_at"], "confirmed_at": row["confirmed_at"]}

    def get(self, user_id, import_id, version=None):
        with self.database.connect() as db:
            imported, config = self.configuration(db, user_id, import_id)
            row = db.execute("SELECT * FROM task_contracts WHERE import_id=? " +
                ("AND version=?" if version else "ORDER BY version DESC LIMIT 1"),
                (import_id, version) if version else (import_id,)).fetchone()
            latest_version = db.execute("SELECT max(version) FROM task_contracts WHERE import_id=?", (import_id,)).fetchone()[0]
        if not row:
            return {"version": None, "contract": None, "stale": False, "can_confirm": False,
                    "missing_requirements": ["Create a task contract."], "runnable": False, "limits_enforced": False}
        result = self.result(row, imported, config)
        result["can_confirm"] = result["can_confirm"] and row["version"] == latest_version
        return result

    def history(self, user_id, import_id, page, per_page):
        with self.database.connect() as db:
            imported, config = self.configuration(db, user_id, import_id)
            rows = db.execute("SELECT * FROM task_contracts WHERE import_id=? ORDER BY version DESC LIMIT ? OFFSET ?",
                (import_id, per_page + 1, (page - 1) * per_page)).fetchall()
        # History summaries do not expose task labels. Detail is an explicit owner-only read.
        return {"versions": [{k: self.result(row, imported, config)[k] for k in
                ("version", "commit_sha", "configuration_revision", "status", "stale", "created_at", "confirmed_at")} for row in rows[:per_page]],
                "page": page, "has_next": len(rows) > per_page}

    def save(self, user_id, import_id, body):
        content = body.model_dump(exclude={"base_version", "configuration_revision"}, mode="json")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            imported, config = self.confirmed_configuration(db, user_id, import_id)
            if config["configuration_revision"] != body.configuration_revision:
                raise HTTPException(409, "Configuration changed. Review current configuration before saving.")
            latest = db.execute("SELECT max(version) FROM task_contracts WHERE import_id=?", (import_id,)).fetchone()[0]
            if body.base_version != latest:
                raise HTTPException(409, "Contract changed. Retrieve its latest version before editing.")
            version = (latest or 0) + 1
            if version > 200:
                raise HTTPException(409, "Contract version limit reached for this import.")
            db.execute("""INSERT INTO task_contracts
                (import_id,version,commit_sha,configuration_revision,configuration_snapshot,content,status,created_at)
                VALUES (?,?,?,?,?,?,'draft',?)""", (import_id, version, imported["commit_sha"],
                config["configuration_revision"], config["configuration"], json.dumps(content, ensure_ascii=False, allow_nan=False), int(time.time())))
        return self.get(user_id, import_id, version)

    def confirm(self, user_id, import_id, body):
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            imported, config = self.confirmed_configuration(db, user_id, import_id)
            latest = db.execute("SELECT * FROM task_contracts WHERE import_id=? ORDER BY version DESC LIMIT 1", (import_id,)).fetchone()
            if not latest or latest["version"] != body.version:
                raise HTTPException(409, "Only the latest contract version can be confirmed.")
            result = self.result(latest, imported, config)
            if result["stale"] or body.configuration_revision != config["configuration_revision"]:
                raise HTTPException(409, "Contract is stale. Save a reviewed version against current configuration.")
            if result["missing_requirements"]:
                raise HTTPException(422, {"message": "Complete the contract before confirmation.", "missing_requirements": result["missing_requirements"]})
            if latest["status"] != "confirmed":
                db.execute("UPDATE task_contracts SET status='confirmed',confirmed_at=? WHERE import_id=? AND version=?",
                           (int(time.time()), import_id, body.version))
        return self.get(user_id, import_id, body.version)
