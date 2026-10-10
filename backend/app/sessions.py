import hashlib
import secrets
import time

from fastapi import HTTPException, Request
from fastapi.responses import Response

from .database import Database


SESSION_COOKIE = "ouro_session"
SESSION_SECONDS = 7 * 24 * 60 * 60


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(database: Database, user_id: str, old_token: str | None) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = int(time.time())
    with database.connect() as db:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        if old_token:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(old_token),))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                   (token_hash(token), user_id, csrf_token, now, now + SESSION_SECONDS))
    return token, csrf_token


def session(database: Database, token: str | None) -> dict | None:
    if not token or len(token) > 128:
        return None
    with database.connect() as db:
        row = db.execute(
            "SELECT users.*, sessions.csrf_token, sessions.expires_at FROM sessions "
            "JOIN users ON users.id = sessions.user_id "
            "WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
            (token_hash(token), int(time.time())),
        ).fetchone()
        return dict(row) if row else None


def delete_session(database: Database, token: str):
    with database.connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))


def current_session(request: Request) -> dict:
    user = session(request.app.state.database, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    return user


def establish_session(request: Request, user: dict, response: Response) -> str:
    token, csrf_token = create_session(request.app.state.database, user["id"], request.cookies.get(SESSION_COOKIE))
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS,
                        httponly=True, secure=request.app.state.settings.cookie_secure,
                        samesite="lax", path="/")
    return csrf_token


def logout_session(request: Request, user: dict):
    if not secrets.compare_digest(request.headers.get("x-csrf-token", "").encode(), user["csrf_token"].encode()):
        raise HTTPException(403, "Missing or invalid CSRF token.")
    delete_session(request.app.state.database, request.cookies[SESSION_COOKIE])
    request.session.clear()
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True,
                           secure=request.app.state.settings.cookie_secure, samesite="lax")
    return response
