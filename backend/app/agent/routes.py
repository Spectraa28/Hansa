import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
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


class OptimizationInput(StageInput):
    investigation_job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    finding_id: str | None = Field(default=None, min_length=1, max_length=8)
    goal: str | None = Field(default=None, min_length=10, max_length=2000)
    max_target_spend_usd: float = Field(default=1.5, strict=True, gt=0, le=3, allow_inf_nan=False)


@router.post("/{import_id}/optimization", status_code=202)
def start_optimization(import_id: uuid.UUID, body: OptimizationInput, request: Request, user: dict = Depends(require_csrf)):
    rate_limit(request)
    return request.app.state.agent.start_optimization(user["id"], str(import_id), body.investigation_job_id, body.finding_id,
                                                       body.goal, body.max_spend_usd, body.max_target_spend_usd)


@router.post("/{import_id}/contract/suggest")
def suggest_tasks(import_id: uuid.UUID, request: Request, user: dict = Depends(require_csrf)):
    rate_limit(request)
    return request.app.state.agent.suggest_tasks(user["id"], str(import_id))


class BriefInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=20)


def suggestion_set(request: Request, user_id: str, import_id: str):
    """Plays for an import, from its latest completed baseline and a text-only read of its source. No model call."""
    import json
    from ..runner.xray import anatomy
    from . import playbook
    agent = request.app.state.agent
    with agent.database.connect() as db:
        imported = agent.owned(db, user_id, import_id)
        row = db.execute("SELECT result FROM baselines WHERE import_id=? AND json_extract(result,'$.status')='completed' "
                         "ORDER BY created_at DESC, rowid DESC LIMIT 1", (import_id,)).fetchone()
    xray = anatomy(agent.database, json.loads(row["result"])) if row else None
    try:
        entrypoint = (request.app.state.inspection.get(user_id, import_id)["configuration"] or {}).get("entrypoint")
    except HTTPException:
        entrypoint = None
    found = playbook.plays(xray, playbook.scan(imported["snapshot_path"], entrypoint))
    return imported, xray, found


@router.get("/{import_id}/suggestions")
def suggestions(import_id: uuid.UUID, request: Request, user: dict = Depends(current_session)):
    _, xray, found = suggestion_set(request, user["id"], str(import_id))
    return {"measured": xray is not None, "suggestions": found,
            "note": "Chosen from measurements and a text-only read of the source. Savings are estimates until the tasks are rerun."}


@router.post("/{import_id}/suggestions/brief")
def suggestion_brief(import_id: uuid.UUID, body: BriefInput, request: Request, user: dict = Depends(require_csrf)):
    from . import playbook
    imported, xray, found = suggestion_set(request, user["id"], str(import_id))
    chosen = [play for play in found if play["id"] in set(body.ids)]
    if not chosen:
        raise HTTPException(422, "Choose at least one current suggestion.")
    text = playbook.brief(imported["repository_name"], imported["commit_sha"], imported["folder"] if "folder" in imported.keys() else None, xray, chosen)
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


@router.get("/{import_id}/report")
def report(import_id: uuid.UUID, request: Request, user: dict = Depends(current_session)):
    from .report import build
    return build(request.app.state.agent, request.app.state.baselines, user["id"], str(import_id))


@router.get("/{import_id}/agent-jobs/{job_id}/patch")
def patch(import_id: uuid.UUID, job_id: str, request: Request, user: dict = Depends(current_session)):
    result = request.app.state.agent.job(user["id"], str(import_id), job_id)["result"]
    tried = [experiment["patch"] for experiment in result.get("experiments", []) if experiment.get("patch")]
    accepted = result.get("decision") == "accept" and result.get("patch")
    if not accepted and not tried:
        raise HTTPException(404, "This job has no patch.")
    # A change that was not accepted is still downloadable for review, and is named and marked as such.
    name = f"hansa-{job_id[:8]}.patch" if accepted else f"hansa-{job_id[:8]}-not-accepted.patch"
    return PlainTextResponse(result["patch"] if accepted else tried[-1],
                             headers={"Content-Disposition": f'attachment; filename="{name}"',
                                      "X-Hansa-Decision": str(result.get("decision") or "none")})


@router.get("/{import_id}/agent-jobs/{job_id}/handoff")
def handoff(import_id: uuid.UUID, job_id: str, request: Request, user: dict = Depends(current_session)):
    """A Markdown brief for the owner's own coding agent: the reason, the measurements and the exact diff."""
    from .report import handoff as build_handoff
    agent = request.app.state.agent
    job = agent.job(user["id"], str(import_id), job_id)
    import json
    with agent.database.connect() as db:
        imported = agent.owned(db, user["id"], str(import_id))
        row = db.execute("SELECT result FROM baselines WHERE id=? AND import_id=?", (job["result"].get("baseline_id"), str(import_id))).fetchone()
    text = (build_handoff(job, imported["repository_name"], json.loads(row["result"]) if row else None, imported["commit_sha"])
            if job["kind"] == "optimization" else None)
    if text is None:
        raise HTTPException(404, "This job has no change to hand off.")
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8",
                             headers={"X-Hansa-Decision": str(job["result"].get("decision") or "none")})


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
