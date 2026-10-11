import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth.service import rate_limit
from ..sessions import current_session, require_csrf

router = APIRouter(prefix="/github/imports", tags=["Baseline"])


class BaselineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repetitions: int = Field(default=1, strict=True, ge=1, le=5)


@router.post("/{import_id}/baseline", status_code=202)
def start_baseline(import_id: uuid.UUID, body: BaselineInput, request: Request, user: dict = Depends(require_csrf)):
    rate_limit(request)
    return request.app.state.baselines.start(user["id"], str(import_id), body.repetitions)


@router.get("/{import_id}/baseline-jobs/{baseline_id}")
def job(import_id: uuid.UUID, baseline_id: str, request: Request, user: dict = Depends(current_session)):
    return request.app.state.baselines.get(user["id"], str(import_id), baseline_id)


@router.get("/{import_id}/baseline-jobs/{baseline_id}/events")
def events(import_id: uuid.UUID, baseline_id: str, request: Request, after: int = Query(default=0, ge=0),
           user: dict = Depends(current_session)):
    return request.app.state.baselines.events(user["id"], str(import_id), baseline_id, after)


@router.get("/{import_id}/baseline")
def baseline(import_id: uuid.UUID, request: Request, user: dict = Depends(current_session)):
    return request.app.state.baselines.latest(user["id"], str(import_id))
