import uuid

from fastapi import APIRouter, Depends, Request

from ..auth.service import rate_limit
from ..sessions import current_session, require_csrf
from .schemas import ConfirmInput

router = APIRouter(prefix="/github/imports", tags=["Repository inspection"])


@router.post("/{import_id}/inspection")
def inspect(import_id: uuid.UUID, request: Request, user: dict = Depends(require_csrf)):
    rate_limit(request)
    return request.app.state.inspection.inspect(user["id"], str(import_id))


@router.get("/{import_id}/inspection")
def findings(import_id: uuid.UUID, request: Request, user: dict = Depends(current_session)):
    return request.app.state.inspection.get(user["id"], str(import_id))


@router.post("/{import_id}/configuration")
def confirm(import_id: uuid.UUID, body: ConfirmInput, request: Request, user: dict = Depends(require_csrf)):
    return request.app.state.inspection.confirm(user["id"], str(import_id), body)
