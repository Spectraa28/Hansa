from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE COLLATE NOCASE,
                    email_verified INTEGER NOT NULL DEFAULT 0,
                    name TEXT NOT NULL,
                    avatar_url TEXT,
                    password_hash TEXT,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identities (
                    provider TEXT NOT NULL CHECK (provider IN ('google', 'github')),
                    subject TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    PRIMARY KEY (provider, subject),
                    UNIQUE (provider, user_id)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
                CREATE TABLE IF NOT EXISTS auth_attempts (
                    bucket_hash TEXT PRIMARY KEY,
                    window_start INTEGER NOT NULL,
                    attempts INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS github_connections (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    github_user_id INTEGER NOT NULL UNIQUE,
                    github_login TEXT NOT NULL,
                    generation TEXT NOT NULL,
                    status TEXT NOT NULL,
                    credentials TEXT,
                    installation_ids TEXT NOT NULL DEFAULT '[]',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS github_oauth_states (
                    state_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    session_hash TEXT NOT NULL,
                    verifier TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repository_imports (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    connection_generation TEXT NOT NULL,
                    installation_id INTEGER NOT NULL,
                    repository_id INTEGER NOT NULL,
                    repository_name TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    commit_sha TEXT NOT NULL,
                    snapshot_path TEXT,
                    status TEXT NOT NULL,
                    warnings TEXT NOT NULL DEFAULT '[]',
                    file_count INTEGER,
                    extracted_bytes INTEGER,
                    failure_code TEXT,
                    failure_reason TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS imports_owner ON repository_imports(user_id, created_at);
                CREATE INDEX IF NOT EXISTS imports_queue ON repository_imports(status, created_at);
                CREATE TABLE IF NOT EXISTS repository_inspections (
                    import_id TEXT PRIMARY KEY REFERENCES repository_imports(id) ON DELETE CASCADE,
                    commit_sha TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    findings TEXT NOT NULL,
                    configuration TEXT,
                    configuration_revision TEXT,
                    status TEXT NOT NULL CHECK(status IN ('suggested','confirmed')),
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_contracts (
                    import_id TEXT NOT NULL REFERENCES repository_imports(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    commit_sha TEXT NOT NULL,
                    configuration_revision TEXT NOT NULL,
                    configuration_snapshot TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('draft','confirmed')),
                    created_at INTEGER NOT NULL,
                    confirmed_at INTEGER,
                    PRIMARY KEY (import_id, version)
                );
                CREATE TABLE IF NOT EXISTS github_webhook_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    received_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runner_builds (
                    id TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL REFERENCES repository_imports(id) ON DELETE CASCADE,
                    commit_sha TEXT NOT NULL,
                    configuration_revision TEXT NOT NULL,
                    snapshot_digest TEXT NOT NULL,
                    image_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runner_runs (
                    id TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL REFERENCES repository_imports(id) ON DELETE CASCADE,
                    build_id TEXT NOT NULL REFERENCES runner_builds(id),
                    result TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runner_dependencies (
                    build_id TEXT PRIMARY KEY REFERENCES runner_builds(id) ON DELETE CASCADE,
                    resolved TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS baselines (
                    id TEXT PRIMARY KEY,
                    import_id TEXT NOT NULL REFERENCES repository_imports(id) ON DELETE CASCADE,
                    result TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gateway_keys (
                    key_hash TEXT PRIMARY KEY,
                    run_label TEXT NOT NULL,
                    max_calls INTEGER NOT NULL CHECK(max_calls >= 0),
                    max_spend_usd REAL CHECK(max_spend_usd >= 0),
                    expires_at INTEGER NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    model_map TEXT NOT NULL DEFAULT '{}',
                    litellm_model TEXT
                );
                CREATE TABLE IF NOT EXISTS model_calls (
                    id INTEGER PRIMARY KEY,
                    key_hash TEXT NOT NULL REFERENCES gateway_keys(key_hash),
                    model TEXT NOT NULL,
                    upstream_model TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    latency_ms INTEGER,
                    http_status INTEGER,
                    estimated_cost_usd REAL,
                    cost_source TEXT,
                    reserved_cost_usd REAL NOT NULL DEFAULT 0,
                    lease_expires_at INTEGER,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS model_calls_key ON model_calls(key_hash);
            """)
            key_columns = {row["name"] for row in db.execute("PRAGMA table_info(gateway_keys)")}
            if "model_map" not in key_columns:
                db.execute("ALTER TABLE gateway_keys ADD COLUMN model_map TEXT NOT NULL DEFAULT '{}'")
            if "litellm_model" not in key_columns:
                db.execute("ALTER TABLE gateway_keys ADD COLUMN litellm_model TEXT")
            call_columns = {row["name"] for row in db.execute("PRAGMA table_info(model_calls)")}
            if "upstream_model" not in call_columns:
                db.execute("ALTER TABLE model_calls ADD COLUMN upstream_model TEXT")
                # Earlier gateway versions always forwarded the requested model unchanged.
                db.execute("UPDATE model_calls SET upstream_model=model")
            if "cost_source" not in call_columns:
                db.execute("ALTER TABLE model_calls ADD COLUMN cost_source TEXT")
                db.execute("UPDATE model_calls SET cost_source='legacy_price_table' WHERE estimated_cost_usd IS NOT NULL")
            if "lease_expires_at" not in call_columns:
                db.execute("ALTER TABLE model_calls ADD COLUMN lease_expires_at INTEGER")
                db.execute("UPDATE model_calls SET lease_expires_at=created_at+120 WHERE http_status IS NULL")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(repository_inspections)")}
            if "configuration_revision" not in columns:
                db.execute("ALTER TABLE repository_inspections ADD COLUMN configuration_revision TEXT")
            db.execute("UPDATE repository_inspections SET configuration_revision=lower(hex(randomblob(16))) "
                       "WHERE status='confirmed' AND configuration_revision IS NULL")
