from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from ..sessions import current_session, establish_session, logout_session, require_csrf
from ..users import public_user
from .schemas import LoginInput, RegisterInput
from .service import login_user, register_user, require_email_login


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/providers")
def providers(request: Request):
    settings = request.app.state.settings
    return {
        "google": bool(settings.google_client_id and settings.google_client_secret),
        "github": bool(settings.github_client_id and settings.github_client_secret),
        "email": settings.email_login_enabled,
    }


@router.post("/register", status_code=201, dependencies=[Depends(require_email_login)])
def register(body: RegisterInput, request: Request, response: Response):
    user = register_user(request, body)
    csrf_token = establish_session(request, user, response)
    return {"user": public_user(user), "csrf_token": csrf_token}


@router.post("/login", dependencies=[Depends(require_email_login)])
def login(body: LoginInput, request: Request, response: Response):
    user = login_user(request, body)
    csrf_token = establish_session(request, user, response)
    return {"user": public_user(user), "csrf_token": csrf_token}


@router.get("/me")
def me(user: dict = Depends(current_session)):
    return {"user": public_user(user), "csrf_token": user["csrf_token"]}


@router.post("/logout", status_code=204)
def logout(request: Request, user: dict = Depends(current_session)):
    return logout_session(request, user)


@router.delete("/me", status_code=204)
def delete_account(request: Request, user: dict = Depends(require_csrf)):
    """Remove the account and everything it owns: sessions, sign-in identities, the GitHub connection, imports and their results."""
    database, github = request.app.state.database, request.app.state.github
    with database.connect() as db:
        imports = [row["id"] for row in db.execute("SELECT id FROM repository_imports WHERE user_id=?", (user["id"],))]
        marks = ",".join("?" * len(imports))
        running = imports and (
            db.execute(f"SELECT 1 FROM agent_jobs WHERE status='running' AND import_id IN ({marks})", imports).fetchone()
            or db.execute(f"SELECT 1 FROM baselines WHERE import_id IN ({marks}) AND json_extract(result,'$.status')='running'", imports).fetchone())
    if running:
        raise HTTPException(409, "A job is still running. Wait for it to finish, then delete the account.")
    github.invalidate(user["id"])
    for import_id in imports:
        github.delete_import(user["id"], import_id)  # removes results and the source snapshot on disk
    response = logout_session(request, user)
    with database.connect() as db:
        db.execute("DELETE FROM users WHERE id=?", (user["id"],))  # sessions, identities, connection and import rows cascade
    return response
