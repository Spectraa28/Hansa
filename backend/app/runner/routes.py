import uuid

from fastapi import APIRouter, Depends, Request

from ..sessions import current_session

router = APIRouter(prefix="/github/imports", tags=["Baseline"])


@router.get("/{import_id}/baseline")
def baseline(import_id: uuid.UUID, request: Request, user: dict = Depends(current_session)):
    return request.app.state.baselines.latest(user["id"], str(import_id))
