import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ..auth.service import rate_limit
from ..sessions import current_session, require_csrf
from .schemas import ConfirmInput, ContractInput, MAX_BODY_BYTES

router = APIRouter(prefix="/github/imports", tags=["Task and correctness contracts"])


async def parse_body(request, schema):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(413, "Contract request exceeds 128 KiB.")
        raw.extend(chunk)
    try:
        data = json.loads(raw)
        return schema.model_validate(data)
    except (ValueError, TypeError, RecursionError, ValidationError):
        # Never echo inputs, arbitrary keys, or validation context containing credentials.
        raise HTTPException(422, "Invalid contract: check required fields, types, size/depth limits, and remove credentials or executable content.") from None


@router.post("/{import_id}/contract", status_code=201)
async def save(import_id: uuid.UUID, request: Request, user: dict = Depends(require_csrf)):
    rate_limit(request)
    body = await parse_body(request, ContractInput)
    return await run_in_threadpool(request.app.state.contracts.save, user["id"], str(import_id), body)


@router.get("/{import_id}/contract")
def retrieve(import_id: uuid.UUID, request: Request, version: int | None = Query(default=None, ge=1, le=200),
             user: dict = Depends(current_session)):
    return request.app.state.contracts.get(user["id"], str(import_id), version)


@router.get("/{import_id}/contract/versions")
def history(import_id: uuid.UUID, request: Request, page: int = Query(default=1, ge=1, le=200),
            per_page: int = Query(default=20, ge=1, le=50), user: dict = Depends(current_session)):
    return request.app.state.contracts.history(user["id"], str(import_id), page, per_page)


@router.post("/{import_id}/contract/confirm")
async def confirm(import_id: uuid.UUID, request: Request, user: dict = Depends(require_csrf)):
    body = await parse_body(request, ConfirmInput)
    return await run_in_threadpool(request.app.state.contracts.confirm, user["id"], str(import_id), body)
