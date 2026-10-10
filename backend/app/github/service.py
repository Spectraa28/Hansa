import base64
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
from urllib.parse import urlencode
import uuid

from cryptography.fernet import Fernet, InvalidToken

from ..sessions import token_hash
from .archive import extract_archive
from .client import GitHubAPI, GitHubFailure, app_jwt, branch_name, load_app_key, repository_name


class GitHubService:
    def __init__(self, settings, database):
        self.settings, self.database = settings, database
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.cipher = Fernet(settings.github_token_encryption_key.encode()) if settings.github_app_enabled else None
        self.key = load_app_key(settings.github_app_private_key_path) if settings.github_app_enabled else None

    def configured(self):
        if not self.settings.github_app_enabled:
            raise GitHubFailure("not_configured", "GitHub repository import is not configured.", 503)

    def jwt(self):
        self.configured()
        return app_jwt(self.settings.github_app_id, self.key)

    def encrypt(self, value):
        return self.cipher.encrypt(json.dumps(value).encode()).decode()

    def decrypt(self, value):
        try:
            return json.loads(self.cipher.decrypt(value.encode()))
        except (InvalidToken, ValueError, TypeError, AttributeError):
            raise GitHubFailure("credential_unavailable", "Stored GitHub credentials cannot be decrypted. Reconnect GitHub.", 401) from None

    def connection(self, user_id, active=False):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM github_connections WHERE user_id = ?", (user_id,)).fetchone()
        if active and (not row or row["status"] != "connected" or not row["credentials"]):
            raise GitHubFailure("not_connected", "Connect GitHub before selecting a repository.", 409)
        return dict(row) if row else None

    def connection_result(self, user_id):
        row = self.connection(user_id)
        return {"configured": self.settings.github_app_enabled, "status": row["status"] if row else "disconnected",
                "github_user_id": row["github_user_id"] if row else None,
                "github_login": row["github_login"] if row else None,
                "installation_ids": json.loads(row["installation_ids"]) if row else []}

    def app_info(self, api):
        app = api.request("GET", "/app", self.jwt())
        if app["id"] != self.settings.github_app_id or app.get("permissions") != {"contents": "read", "metadata": "read"}:
            raise GitHubFailure("app_permissions", "Configure this GitHub App with only Contents: read and Metadata: read.", 503)
        slug = app["slug"]
        if not isinstance(slug, str) or not slug or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in slug):
            raise GitHubFailure("invalid_response", "GitHub returned an invalid App identity.", 502)
        return {"installation_url": f"https://github.com/apps/{slug}/installations/new",
                "permissions": app["permissions"]}

    def begin_connection(self, user_id, raw_session):
        self.configured()
        with GitHubAPI() as api:
            info = self.app_info(api)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        now = int(time.time())
        with self.database.connect() as db:
            db.execute("DELETE FROM github_oauth_states WHERE expires_at <= ? OR user_id = ?", (now, user_id))
            db.execute("INSERT INTO github_oauth_states VALUES (?, ?, ?, ?, ?)",
                       (token_hash(state), user_id, token_hash(raw_session), self.encrypt(verifier), now + 600))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        url = "https://github.com/login/oauth/authorize?" + urlencode({
            "client_id": self.settings.github_app_client_id, "redirect_uri": self.settings.github_app_callback_url,
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        })
        return {"authorization_url": url, **info}

    def complete_connection(self, user_id, raw_session, state, code):
        with self.lock:
            return self._complete_connection(user_id, raw_session, state, code)

    def _complete_connection(self, user_id, raw_session, state, code):
        self.configured()
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM github_oauth_states WHERE state_hash = ?", (token_hash(state),)).fetchone()
            if (not row or row["user_id"] != user_id or row["expires_at"] <= int(time.time())
                or not secrets.compare_digest(row["session_hash"], token_hash(raw_session))):
                raise GitHubFailure("invalid_state", "GitHub connection expired or belongs to another login session. Start again.")
            db.execute("DELETE FROM github_oauth_states WHERE state_hash = ?", (token_hash(state),))
        verifier = self.decrypt(row["verifier"])
        if not code:
            raise GitHubFailure("authorization_denied", "GitHub authorization was denied or cancelled.")
        with GitHubAPI() as api:
            tokens = api.request("POST", "/login/oauth/access_token", data={
                "client_id": self.settings.github_app_client_id, "client_secret": self.settings.github_app_client_secret,
                "code": code, "redirect_uri": self.settings.github_app_callback_url, "code_verifier": verifier,
            })
            profile = api.request("GET", "/user", tokens["access_token"])
            if type(profile.get("id")) is not int or profile["id"] <= 0 or not isinstance(profile.get("login"), str):
                raise GitHubFailure("invalid_response", "GitHub returned an invalid user identity.", 502)
            installations = self.accessible_installations(api, tokens["access_token"])
        now = int(time.time())
        credentials = self.token_record(tokens, now)
        with self.lock, self.database.connect() as db:
            # A session may have been revoked while the OAuth exchange was in flight.
            if not db.execute("SELECT 1 FROM sessions WHERE token_hash = ? AND user_id = ? AND expires_at > ?",
                              (token_hash(raw_session), user_id, now)).fetchone():
                raise GitHubFailure("invalid_state", "The application login session has expired.", 401)
            identity = db.execute("SELECT user_id FROM identities WHERE provider = 'github' AND subject = ?",
                                  (str(profile["id"]),)).fetchone()
            if identity and identity["user_id"] != user_id:
                raise GitHubFailure("account_conflict", "This GitHub identity signs in to another application account. Use that account.", 409)
            try:
                db.execute("""INSERT INTO github_connections VALUES (?, ?, ?, ?, 'connected', ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET github_user_id=excluded.github_user_id,
                    github_login=excluded.github_login, generation=excluded.generation, status='connected',
                    credentials=excluded.credentials, installation_ids=excluded.installation_ids, updated_at=excluded.updated_at""",
                    (user_id, profile["id"], profile["login"], str(uuid.uuid4()), self.encrypt(credentials),
                     json.dumps([i["id"] for i in installations]), now, now))
            except sqlite3.IntegrityError:
                raise GitHubFailure("account_conflict", "This GitHub identity is connected to another application account.", 409) from None
            db.execute("UPDATE repository_imports SET status='failed', failure_code='connection_changed', "
                       "failure_reason='GitHub connection changed. Start a new import.', updated_at=? "
                       "WHERE user_id=? AND status IN ('queued','downloading')", (now, user_id))
        return {**self.connection_result(user_id), "access_note":
                "Install the App and select repositories. Organization repositories may require owner approval."}

    def token_record(self, tokens, now):
        access = tokens.get("access_token")
        refresh = tokens.get("refresh_token")
        if not isinstance(access, str) or not access:
            raise GitHubFailure("invalid_response", "GitHub did not issue a user access token.", 502)
        return {"access_token": access, "refresh_token": refresh,
                "expires_at": now + int(tokens["expires_in"]) if tokens.get("expires_in") else None,
                "refresh_expires_at": now + int(tokens["refresh_token_expires_in"]) if tokens.get("refresh_token_expires_in") else None}

    def user_token(self, api, user_id):
        self.configured()
        # Serialize refresh-token rotation so simultaneous API requests cannot reuse a refresh token.
        with self.lock:
            connection = self.connection(user_id, active=True)
            record = self.decrypt(connection["credentials"])
            now = int(time.time())
            if record["expires_at"] and record["expires_at"] <= now + 60:
                if not record.get("refresh_token") or (record.get("refresh_expires_at") and record["refresh_expires_at"] <= now):
                    self.invalidate(user_id, "expired")
                    raise GitHubFailure("authorization_expired", "GitHub authorization expired. Reconnect GitHub.", 401)
                try:
                    tokens = api.request("POST", "/login/oauth/access_token", data={
                        "client_id": self.settings.github_app_client_id, "client_secret": self.settings.github_app_client_secret,
                        "grant_type": "refresh_token", "refresh_token": record["refresh_token"],
                    })
                except GitHubFailure as exc:
                    if exc.code == "authorization_expired":
                        self.invalidate(user_id, "expired")
                    raise
                record = self.token_record(tokens, now)
                with self.database.connect() as db:
                    db.execute("UPDATE github_connections SET credentials=?, updated_at=? WHERE user_id=? AND generation=? AND status='connected'",
                               (self.encrypt(record), now, user_id, connection["generation"]))
            return record["access_token"]

    def accessible_installations(self, api, token):
        return [item for item in api.pages("/user/installations", token, "installations")
                if item.get("app_id") == self.settings.github_app_id and not item.get("suspended_at")
                and item.get("permissions", {}).get("contents") == "read"]

    def verify_installation(self, api, user_id, installation_id):
        token = self.user_token(api, user_id)
        try:
            installations = self.accessible_installations(api, token)
        except GitHubFailure as exc:
            if exc.code == "authorization_expired":
                self.invalidate(user_id, "expired")
            raise
        ids = [item["id"] for item in installations]
        with self.database.connect() as db:
            db.execute("UPDATE github_connections SET installation_ids=? WHERE user_id=? AND status='connected'",
                       (json.dumps(ids), user_id))
        if installation_id not in ids:
            raise GitHubFailure("access_denied", "Installation is unavailable to this GitHub user. Check installation and organization approval.", 403)
        return token

    def installations(self, user_id, page, per_page):
        with GitHubAPI() as api:
            token = self.user_token(api, user_id)
            try:
                items = self.accessible_installations(api, token)
            except GitHubFailure as exc:
                if exc.code == "authorization_expired":
                    self.invalidate(user_id, "expired")
                raise
            with self.database.connect() as db:
                db.execute("UPDATE github_connections SET installation_ids=? WHERE user_id=? AND status='connected'",
                           (json.dumps([i["id"] for i in items]), user_id))
            start = (page - 1) * per_page
            return {"installations": [{"id": i["id"], "account": i["account"]["login"],
                                      "repository_selection": i["repository_selection"]} for i in items[start:start + per_page]],
                    "page": page, "has_next": start + per_page < len(items), **self.app_info(api),
                    "access_note": "Missing organization installations may need owner approval; requested installation IDs are never trusted."}

    def repositories(self, user_id, installation_id, page, per_page):
        with GitHubAPI() as api:
            token = self.verify_installation(api, user_id, installation_id)
            result = api.request("GET", f"/user/installations/{installation_id}/repositories", token,
                                 params={"page": page, "per_page": per_page})
            return {"repositories": [self.repo_result(r) for r in result["repositories"]], "page": page,
                    "has_next": page * per_page < result["total_count"]}

    def repo_result(self, repo):
        return {"id": repo["id"], "full_name": repository_name(repo["full_name"]),
                "default_branch": repo.get("default_branch"), "private": bool(repo["private"])}

    def checked_repo(self, api, user_id, installation_id, repository_id):
        token = self.verify_installation(api, user_id, installation_id)
        repo = next((r for r in api.pages(f"/user/installations/{installation_id}/repositories", token, "repositories")
                     if r["id"] == repository_id), None)
        if repo is None:
            raise GitHubFailure("access_denied", "Repository is not accessible to both the GitHub user and App.", 403)
        repository_name(repo["full_name"])
        return token, repo

    def branches(self, user_id, installation_id, repository_id, page, per_page):
        with GitHubAPI() as api:
            token, repo = self.checked_repo(api, user_id, installation_id, repository_id)
            result = api.request("GET", f"/repos/{repo['full_name']}/branches", token,
                                 params={"page": page, "per_page": per_page})
            return {"repository": self.repo_result(repo), "branches": [{"name": b["name"],
                    "commit_sha": b["commit"]["sha"]} for b in result], "page": page, "has_next": api.has_next}

    def queue_import(self, user_id, body):
        with GitHubAPI(self.settings.import_timeout_seconds) as api:
            token, repo = self.checked_repo(api, user_id, body.installation_id, body.repository_id)
            branch = body.branch or repo.get("default_branch")
            if not branch:
                raise GitHubFailure("empty_repository", "The repository has no default branch or commits.", 409)
            branch = branch_name(branch)
            if not api.request("GET", f"/repos/{repo['full_name']}/branches", token, params={"per_page": 1}):
                raise GitHubFailure("empty_repository", "The repository has no branches or commits.", 409)
            sha = api.branch(token, repo["full_name"], branch)
        now, import_id = int(time.time()), str(uuid.uuid4())
        with self.lock, self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            connection = db.execute("SELECT generation FROM github_connections WHERE user_id=? AND status='connected'", (user_id,)).fetchone()
            if not connection:
                raise GitHubFailure("not_connected", "GitHub was disconnected. Reconnect before importing.", 409)
            count = db.execute("SELECT count(*) FROM repository_imports WHERE user_id=? AND status IN ('queued','downloading','ready')", (user_id,)).fetchone()[0]
            queued = db.execute("SELECT count(*) FROM repository_imports WHERE status IN ('queued','downloading')").fetchone()[0]
            if count >= 5 or queued >= 100:
                raise GitHubFailure("queue_limit", "Import limit reached. Delete an existing source or try later.", 429)
            db.execute("""INSERT INTO repository_imports
                (id,user_id,connection_generation,installation_id,repository_id,repository_name,branch,commit_sha,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,'queued',?,?)""", (import_id, user_id, connection["generation"],
                body.installation_id, body.repository_id, repo["full_name"], branch, sha, now, now))
        return self.import_result(user_id, import_id)

    def import_result(self, user_id, import_id):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM repository_imports WHERE id=? AND user_id=?", (import_id, user_id)).fetchone()
        if not row:
            raise GitHubFailure("not_found", "Import not found.", 404)
        # Internal filesystem paths and credentials never leave the backend.
        return {key: row[key] for key in ("id", "repository_id", "repository_name", "installation_id", "branch",
                "commit_sha", "status", "file_count", "extracted_bytes", "failure_code", "failure_reason", "created_at", "updated_at")} | {
                "warnings": json.loads(row["warnings"]), "source_available": row["status"] == "ready"}

    def imports(self, user_id, page, per_page):
        with self.database.connect() as db:
            ids = db.execute("SELECT id FROM repository_imports WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                             (user_id, per_page + 1, (page - 1) * per_page)).fetchall()
        return {"imports": [self.import_result(user_id, row["id"]) for row in ids[:per_page]],
                "page": page, "has_next": len(ids) > per_page}

    def invalidate(self, user_id, status="disconnected"):
        with self.lock, self.database.connect() as db:
            now = int(time.time())
            db.execute("UPDATE github_connections SET status=?,credentials=NULL,installation_ids='[]',updated_at=? WHERE user_id=?", (status, now, user_id))
            db.execute("DELETE FROM github_oauth_states WHERE user_id=?", (user_id,))
            db.execute("UPDATE repository_imports SET status='failed',failure_code='authorization_revoked', "
                       "failure_reason='GitHub authorization disconnected or revoked.',updated_at=? WHERE user_id=? AND status IN ('queued','downloading')", (now, user_id))

    def delete_import(self, user_id, import_id):
        with self.lock:
            self.import_result(user_id, import_id)
            with self.database.connect() as db:
                db.execute("DELETE FROM task_contracts WHERE import_id=?", (import_id,))
                db.execute("DELETE FROM repository_inspections WHERE import_id=?", (import_id,))
                db.execute("UPDATE repository_imports SET status='deleted',snapshot_path=NULL,updated_at=? WHERE id=? AND user_id=?",
                           (int(time.time()), import_id, user_id))
            path = self.source_path(user_id, import_id)
            if path.exists():
                try:
                    shutil.rmtree(path)
                except OSError:
                    raise GitHubFailure("deletion_failed", "Source deletion failed. Retry the deletion request.", 503) from None

    def source_path(self, user_id, import_id):
        # These identifiers originate in our database, never from a requested filesystem path.
        user_id, import_id = str(uuid.UUID(user_id)), str(uuid.UUID(import_id))
        root = self.settings.import_workspace_path.resolve()
        path = root / user_id / import_id
        if not path.resolve().is_relative_to(root):
            raise GitHubFailure("unsafe_workspace", "Import workspace is invalid.", 500)
        return path

    def recover(self):
        with self.database.connect() as db:
            db.execute("UPDATE repository_imports SET status='failed',failure_code='interrupted', "
                       "failure_reason='Import interrupted by backend restart. Start a new import.',updated_at=? WHERE status='downloading'", (int(time.time()),))
        root = self.settings.import_workspace_path
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        for path in root.glob("*/.staging-*"):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
        # Remove a snapshot published just before a crash if SQLite never recorded it as ready.
        with self.database.connect() as db:
            rows = db.execute("SELECT id,user_id FROM repository_imports WHERE status IN ('failed','deleted')").fetchall()
        for row in rows:
            path = self.source_path(row["user_id"], row["id"])
            if path.exists():
                shutil.rmtree(path)

    def claim_import(self):
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM repository_imports WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE repository_imports SET status='downloading',updated_at=? WHERE id=?", (int(time.time()), row["id"]))
            return dict(row)

    def active(self, item):
        if self.stopping.is_set():
            raise GitHubFailure("interrupted", "Import interrupted by backend shutdown. Start a new import.", 409)
        with self.database.connect() as db:
            valid = db.execute("""SELECT 1 FROM repository_imports i JOIN github_connections c ON i.user_id=c.user_id
                WHERE i.id=? AND i.status='downloading' AND c.status='connected' AND c.generation=i.connection_generation""", (item["id"],)).fetchone()
        if not valid:
            raise GitHubFailure("cancelled", "Import was deleted, disconnected, or authorization changed.", 409)

    def perform_import(self, item):
        destination = self.source_path(item["user_id"], item["id"])
        staging = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.parent.chmod(0o700)
            staging = tempfile.mkdtemp(prefix=".staging-", dir=destination.parent)
            staging = Path(staging)
            with GitHubAPI(self.settings.import_timeout_seconds) as api:
                def check_active():
                    api.check_time()
                    self.active(item)
                check_active()
                user_token, repo = self.checked_repo(api, item["user_id"], item["installation_id"], item["repository_id"])
                name = repository_name(repo["full_name"])
                # Validate the fixed commit with the user token before using broader installation authorization.
                commit = api.request("GET", f"/repos/{name}/commits/{item['commit_sha']}", user_token)
                if commit["sha"] != item["commit_sha"]:
                    raise GitHubFailure("invalid_commit", "GitHub did not return the requested fixed commit.", 502)
                tree = api.request("GET", f"/repos/{name}/git/trees/{item['commit_sha']}", user_token, params={"recursive": "1"})
                if tree.get("truncated"):
                    raise GitHubFailure("listing_limit", "Repository tree exceeds the supported inspection limit.", 413)
                has_submodules = any(entry.get("mode") == "160000" for entry in tree["tree"])
                token = api.installation_token(self.jwt(), item["installation_id"], item["repository_id"])
                archive = staging / "source.tar.gz"
                api.download(token, name, item["commit_sha"], archive, self.settings.import_download_bytes, check_active)
                result = extract_archive(archive, staging / "source", self.settings, check_active)
                if has_submodules and "submodules_not_imported" not in result["warnings"]:
                    result["warnings"].append("submodules_not_imported")
                # Recheck the user's intersection of permissions immediately before publishing source.
                self.checked_repo(api, item["user_id"], item["installation_id"], item["repository_id"])
                with self.lock:
                    check_active()
                    (staging / "source").rename(destination)
                    with self.database.connect() as db:
                        db.execute("""UPDATE repository_imports SET status='ready',snapshot_path=?,warnings=?,file_count=?,
                            extracted_bytes=?,updated_at=? WHERE id=? AND status='downloading'""", (str(destination),
                            json.dumps(result["warnings"]), result["file_count"], result["extracted_bytes"], int(time.time()), item["id"]))
        except GitHubFailure as exc:
            if exc.code == "authorization_expired":
                self.invalidate(item["user_id"], "expired")
            self.fail_import(item, exc.code, exc.reason)
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError):
            self.fail_import(item, "import_failed", "Import failed because source storage or GitHub data was invalid. Try again.")
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            with self.lock:
                if self.import_result(item["user_id"], item["id"])["status"] != "ready" and destination.exists():
                    shutil.rmtree(destination, ignore_errors=True)

    def fail_import(self, item, code, reason):
        with self.database.connect() as db:
            db.execute("UPDATE repository_imports SET status='failed',failure_code=?,failure_reason=?,updated_at=? WHERE id=? AND status='downloading'",
                       (code, reason, int(time.time()), item["id"]))

    def webhook(self, event, payload, delivery_id):
        with self.lock, self.database.connect() as db:
            now = int(time.time())
            db.execute("DELETE FROM github_webhook_deliveries WHERE received_at < ?", (now - 7 * 86400,))
            if db.execute("SELECT 1 FROM github_webhook_deliveries WHERE delivery_id=?", (delivery_id,)).fetchone():
                return
            if event == "github_app_authorization" and payload.get("action") == "revoked":
                github_id = payload["sender"]["id"]
                rows = db.execute("SELECT user_id FROM github_connections WHERE github_user_id=?", (github_id,)).fetchall()
                for row in rows:
                    db.execute("UPDATE github_connections SET status='revoked',credentials=NULL,installation_ids='[]',updated_at=? WHERE user_id=?", (now, row["user_id"]))
                    db.execute("DELETE FROM github_oauth_states WHERE user_id=?", (row["user_id"],))
                    db.execute("UPDATE repository_imports SET status='failed',failure_code='authorization_revoked', "
                               "failure_reason='GitHub user authorization was revoked.',updated_at=? WHERE user_id=? AND status IN ('queued','downloading')", (now, row["user_id"]))
            if event in {"installation", "installation_repositories"}:
                installation = payload["installation"]
                if installation["app_id"] != self.settings.github_app_id:
                    raise GitHubFailure("invalid_webhook", "Webhook belongs to another GitHub App.")
                if payload.get("action") in {"deleted", "suspend", "removed"}:
                    installation_id = installation["id"]
                    removed = [r["id"] for r in payload.get("repositories_removed", [])]
                    rows = db.execute("SELECT id,repository_id FROM repository_imports WHERE installation_id=? AND status IN ('queued','downloading')", (installation_id,)).fetchall()
                    for row in rows:
                        if payload["action"] != "removed" or row["repository_id"] in removed:
                            db.execute("UPDATE repository_imports SET status='failed',failure_code='access_revoked', "
                                       "failure_reason='GitHub installation or repository access was removed.',updated_at=? WHERE id=?", (now, row["id"]))
                    if payload["action"] != "removed":
                        connections = db.execute("SELECT user_id,installation_ids FROM github_connections").fetchall()
                        for row in connections:
                            ids = [i for i in json.loads(row["installation_ids"]) if i != installation_id]
                            db.execute("UPDATE github_connections SET installation_ids=?,updated_at=? WHERE user_id=?", (json.dumps(ids), now, row["user_id"]))
            db.execute("INSERT INTO github_webhook_deliveries VALUES (?,?)", (delivery_id, now))
