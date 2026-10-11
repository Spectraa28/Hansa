import uuid

from fastapi import APIRouter, Depends, Query, Request

from ..sessions import current_session, require_csrf
from ..auth.service import rate_limit

router = APIRouter(prefix="/github/imports", tags=["Traces"])
TraceID = r"^[A-Za-z0-9_-]{8,64}$"


@router.get("/{import_id}/traces")
def traces(import_id: uuid.UUID, request: Request, user: dict = Depends(current_session)):
    return request.app.state.traces.list(user["id"], str(import_id))


@router.get("/{import_id}/traces/search")
def search(import_id: uuid.UUID, request: Request, q: str = Query(min_length=2, max_length=200),
           user: dict = Depends(current_session)):
    return request.app.state.traces.search(user["id"], str(import_id), q)


@router.get("/{import_id}/traces/{trace_id}")
def context(import_id: uuid.UUID, request: Request, trace_id: str, user: dict = Depends(current_session)):
    return request.app.state.traces.context(user["id"], str(import_id), trace_id)


@router.post("/{import_id}/traces/{trace_id}/recheck")
def recheck(import_id: uuid.UUID, request: Request, trace_id: str, user: dict = Depends(require_csrf)):
    rate_limit(request)
    return request.app.state.traces.recheck(user["id"], str(import_id), trace_id)
