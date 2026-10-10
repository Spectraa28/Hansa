from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["Testing UI"])
ROOT = Path(__file__).parent


@router.get("/setup", include_in_schema=False)
def setup():
    return FileResponse(ROOT / "setup.html", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})


@router.get("/setup/{asset}", include_in_schema=False)
def asset(asset: str):
    if asset not in {"setup.js", "setup.css"}:
        raise HTTPException(404, "Asset not found.")
    return FileResponse(ROOT / asset, headers={"X-Content-Type-Options": "nosniff"})
