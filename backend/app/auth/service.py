import hashlib
import time

from fastapi import HTTPException, Request
from pwdlib import PasswordHash

from ..database import Database
from ..users import EmailInUse, create_password_user, password_user
from .schemas import LoginInput, RegisterInput


password_hasher = PasswordHash.recommended()


def admit_attempt(database: Database, key: str, limit: int, seconds: int = 600) -> bool:
    now = int(time.time())
    bucket = hashlib.sha256(key.encode()).hexdigest()
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM auth_attempts WHERE window_start <= ?", (now - seconds,))
        db.execute(
            "INSERT INTO auth_attempts VALUES (?, ?, 1) "
            "ON CONFLICT(bucket_hash) DO UPDATE SET attempts = attempts + 1", (bucket, now),
        )
        count = db.execute("SELECT attempts FROM auth_attempts WHERE bucket_hash = ?", (bucket,)).fetchone()[0]
        return count <= limit


def rate_limit(request: Request, email: str | None = None):
    ip = request.client.host if request.client else "unknown"
    database = request.app.state.database
    if not admit_attempt(database, f"auth:ip:{ip}", 30):
        raise HTTPException(429, "Too many sign-in attempts. Try again in 10 minutes.", headers={"Retry-After": "600"})
    if email and not admit_attempt(database, f"auth:email:{ip}:{email}", 10):
        raise HTTPException(429, "Too many sign-in attempts. Try again in 10 minutes.", headers={"Retry-After": "600"})


def require_email_login(request: Request):
    if not request.app.state.settings.email_login_enabled:
        raise HTTPException(404, "Email/password login is disabled.")


def register_user(request: Request, body: RegisterInput) -> dict:
    rate_limit(request, str(body.email))
    try:
        user = create_password_user(
            request.app.state.database, str(body.email), body.name,
            password_hasher.hash(body.password.get_secret_value()),
        )
    except EmailInUse:
        raise HTTPException(409, "An account already exists for this email. Use its existing sign-in method.") from None
    return user


def login_user(request: Request, body: LoginInput) -> dict:
    rate_limit(request, str(body.email))
    database = request.app.state.database
    user = password_user(database, str(body.email))
    stored_hash = user["password_hash"] if user and user["password_hash"] else request.app.state.dummy_password_hash
    valid = password_hasher.verify(body.password.get_secret_value(), stored_hash)
    if not user or not user["password_hash"] or not valid:
        raise HTTPException(401, "Invalid email or password.")
    return user
