import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth.service import rate_limit
from ..sessions import current_session, require_csrf

router = APIRouter(prefix="/github/imports", tags=["Agent"])


class StageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_spend_usd: float = Field(default=1.5, strict=True, gt=0, le=1.5, allow_inf_nan=False)


class InvestigationInput(StageInput):
    baseline_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


@router.post("/{import_id}/investigation", status_code=202)
def start_investigation(import_id: uuid.UUID, body: InvestigationInput, request: Request, user: dict = Depends(require_csrf)):
    rate_limit(request)
    return request.app.state.agent.start_investigation(user["id"], str(import_id), body.baseline_id, body.max_spend_usd)


@router.post("/{import_id}/onboarding", status_code=202)
def start_onboarding(import_id: uuid.UUID, request: Request, body: StageInput | None = None, user: dict = Depends(require_csrf)):
    rate_limit(request)
    return request.app.state.agent.start_onboarding(user["id"], str(import_id), (body or StageInput()).max_spend_usd)


@router.get("/{import_id}/agent-jobs/{job_id}")
def job(import_id: uuid.UUID, job_id: str, request: Request, user: dict = Depends(current_session)):
    return request.app.state.agent.job(user["id"], str(import_id), job_id)


@router.get("/{import_id}/agent-jobs/{job_id}/events")
def events(import_id: uuid.UUID, job_id: str, request: Request, after: int = Query(default=0, ge=0),
           user: dict = Depends(current_session)):
    return request.app.state.agent.events(user["id"], str(import_id), job_id, after)


@router.get("/{import_id}/adapter")
def adapter(import_id: uuid.UUID, request: Request, user: dict = Depends(current_session)):
    return request.app.state.agent.adapter(user["id"], str(import_id))
