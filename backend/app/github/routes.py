import hashlib
import hmac
import json
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from ..auth.service import rate_limit
from ..sessions import SESSION_COOKIE, current_session, require_csrf
from .client import GitHubFailure


router = APIRouter(prefix="/github", tags=["GitHub repositories"])
Page = Annotated[int, Query(ge=1, le=10000)]
PerPage = Annotated[int, Query(ge=1, le=100)]
PositiveID = Annotated[int, Query(gt=0)]


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installation_id: int = Field(gt=0)
    repository_id: int = Field(gt=0)
    branch: str | None = Field(default=None, min_length=1, max_length=255)


@router.get("/connection")
def connection(request: Request, user: dict = Depends(current_session)):
    return request.app.state.github.connection_result(user["id"])


@router.post("/connect")
def connect(request: Request, user: dict = Depends(require_csrf)):
    rate_limit(request)
    return request.app.state.github.begin_connection(user["id"], request.cookies[SESSION_COOKIE])


@router.get("/callback")
def callback(request: Request, state: Annotated[str, Query(min_length=1, max_length=128)],
             code: Annotated[str | None, Query(max_length=512)] = None, user: dict = Depends(current_session)):
    request.app.state.github.complete_connection(user["id"], request.cookies[SESSION_COOKIE], state, code)
    return RedirectResponse(f"{request.app.state.settings.frontend_origin.rstrip('/')}/app/new", status_code=303)


@router.get("/installations")
def installations(request: Request, page: Page = 1, per_page: PerPage = 30, user: dict = Depends(current_session)):
    return request.app.state.github.installations(user["id"], page, per_page)


@router.get("/repositories")
def repositories(request: Request, installation_id: PositiveID, page: Page = 1, per_page: PerPage = 30,
                 user: dict = Depends(current_session)):
    return request.app.state.github.repositories(user["id"], installation_id, page, per_page)


@router.get("/branches")
def branches(request: Request, installation_id: PositiveID, repository_id: PositiveID,
             page: Page = 1, per_page: PerPage = 30, user: dict = Depends(current_session)):
    return request.app.state.github.branches(user["id"], installation_id, repository_id, page, per_page)


@router.post("/imports", status_code=202)
def import_repository(body: ImportInput, request: Request, user: dict = Depends(require_csrf)):
    rate_limit(request)
    return request.app.state.github.queue_import(user["id"], body)


@router.get("/imports")
def imports(request: Request, page: Page = 1, per_page: PerPage = 30, user: dict = Depends(current_session)):
    return request.app.state.github.imports(user["id"], page, per_page)


@router.get("/imports/{import_id}")
def import_status(import_id: uuid.UUID, request: Request, user: dict = Depends(current_session)):
    return request.app.state.github.import_result(user["id"], str(import_id))


@router.delete("/imports/{import_id}", status_code=204)
def delete_import(import_id: uuid.UUID, request: Request, user: dict = Depends(require_csrf)):
    request.app.state.github.delete_import(user["id"], str(import_id))
    return Response(status_code=204)


@router.delete("/connection", status_code=204)
def disconnect(request: Request, user: dict = Depends(require_csrf)):
    request.app.state.github.invalidate(user["id"])
    return Response(status_code=204)


def verify_webhook(secret: str, body: bytes, signature: str):
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected.encode(), signature.encode()):
        raise GitHubFailure("invalid_signature", "Webhook signature is invalid.", 401)


@router.post("/webhook", status_code=204)
async def webhook(request: Request):
    secret = request.app.state.settings.github_webhook_secret
    if not secret:
        raise GitHubFailure("not_configured", "GitHub webhook is not configured.", 503)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            raise GitHubFailure("webhook_limit", "Webhook body exceeds the size limit.", 413)
    verify_webhook(secret, bytes(body), request.headers.get("x-hub-signature-256", ""))
    try:
        delivery_id = str(uuid.UUID(request.headers.get("x-github-delivery", "")))
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError
        await run_in_threadpool(request.app.state.github.webhook, request.headers.get("x-github-event", ""), payload, delivery_id)
    except (ValueError, TypeError, KeyError):
        raise GitHubFailure("invalid_webhook", "Webhook payload or delivery ID is invalid.") from None
    return Response(status_code=204)
