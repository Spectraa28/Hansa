import json

from fastapi import APIRouter, HTTPException, Request

from .service import MAX_BODY_BYTES, error


router = APIRouter(prefix="/gateway/v1", tags=["Model gateway"])


@router.post("/chat/completions")
async def chat_completions(request: Request):
    service = request.app.state.gateway
    if not service.settings.litellm_base_url or not service.settings.litellm_api_key:
        return error(503, "Model gateway is not configured.")
    authorization = request.headers.get("authorization", "").split()
    if len(authorization) != 2 or authorization[0].lower() != "bearer" or len(authorization[1]) > 128:
        return error(401, "A gateway Bearer key is required.")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_BODY_BYTES:
            return error(413, "Gateway request exceeds 1 MiB.")
    try:
        body = json.loads(content)
    except (ValueError, RecursionError):
        return error(400, "Expected a JSON chat completion request.")
    if (not isinstance(body, dict) or not isinstance(body.get("model"), str)
            or not 1 <= len(body["model"]) <= 200 or not isinstance(body.get("messages"), list)
            or not body["messages"] or any(not isinstance(message, dict) for message in body["messages"])
            or type(body.get("stream", False)) is not bool):
        return error(400, "A model, nonempty messages array and boolean stream are required.")
    if body.get("stream"):
        return error(400, "Streaming is not supported yet; use stream=false so usage can be metered.")
    try:
        return await service.forward(authorization[1], body)
    except HTTPException as exc:
        return error(exc.status_code, exc.detail)
