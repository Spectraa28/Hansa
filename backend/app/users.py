import sqlite3
import time
import uuid

from .database import Database


class EmailInUse(Exception):
    pass


def public_user(user: dict) -> dict:
    return {key: user[key] for key in ("id", "email", "name", "avatar_url", "created_at")} | {
        "email_verified": bool(user["email_verified"]),
    }


def create_password_user(database: Database, email: str, name: str, password_hash: str) -> dict:
    user_id = str(uuid.uuid4())
    try:
        with database.connect() as db:
            db.execute(
                "INSERT INTO users (id, email, name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email, name, password_hash, int(time.time())),
            )
            return dict(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise EmailInUse from exc


def password_user(database: Database, email: str) -> dict | None:
    with database.connect() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def oauth_user(database: Database, provider: str, subject: str, email: str | None, name: str,
               avatar_url: str | None) -> dict:
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT users.* FROM identities JOIN users ON users.id = identities.user_id "
            "WHERE provider = ? AND subject = ?", (provider, subject),
        ).fetchone()
        if row:
            return dict(row)
        # Email equality does not prove permission to link an existing account.
        if email and db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise EmailInUse
        user_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO users (id, email, email_verified, name, avatar_url, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, email, bool(email), name, avatar_url, int(time.time())),
        )
        db.execute("INSERT INTO identities VALUES (?, ?, ?)", (provider, subject, user_id))
        return dict(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
