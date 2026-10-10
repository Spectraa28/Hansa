from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from ..sessions import current_session, establish_session, logout_session
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
