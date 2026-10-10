from contextlib import asynccontextmanager
import asyncio
import logging
import secrets
import sqlite3

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp

from .auth.routes import router as auth_router
from .auth.service import password_hasher
from .config import Settings
from .database import Database
from .github.client import GitHubFailure
from .github.routes import router as github_router
from .github.service import GitHubService
from .github.worker import import_worker
from .inspection.routes import router as inspection_router
from .inspection.service import InspectionService
from .contracts.routes import router as contracts_router
from .contracts.service import ContractService
from .gateway.routes import router as gateway_router
from .gateway.service import GatewayService
from .runner.service import RunnerService
from .ui.routes import router as ui_router
from .oauth.providers import oauth_clients
from .oauth.routes import router as oauth_router


def create_app(settings: Settings | None = None) -> ASGIApp:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)
    github = GitHubService(settings, database)
    # Signed archive URLs and OAuth requests must not enter HTTP client's diagnostic logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(database.initialize)
        await run_in_threadpool(app.state.gateway.recover, restart=True)
        app.state.dummy_password_hash = await run_in_threadpool(password_hasher.hash, secrets.token_urlsafe(32))
        worker = None
        if settings.github_app_enabled:
            await run_in_threadpool(github.recover)
            worker = asyncio.create_task(import_worker(github))
        try:
            yield
        finally:
            github.stopping.set()
            if worker:
                await worker

    app = FastAPI(title="Ouro backend", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.oauth = oauth_clients(settings)
    app.state.github = github
    app.state.inspection = InspectionService(database, github)
    app.state.contracts = ContractService(database, app.state.inspection)
    app.state.gateway = GatewayService(settings, database, app.state.inspection)
    app.state.runner = RunnerService(settings, database, app.state.inspection, app.state.gateway)
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key,
                       session_cookie="ouro_oauth", max_age=600,
                       same_site="lax", https_only=settings.cookie_secure)
    app.include_router(auth_router)
    app.include_router(oauth_router)
    app.include_router(github_router)
    app.include_router(inspection_router)
    app.include_router(contracts_router)
    app.include_router(gateway_router)
    app.include_router(ui_router)

    @app.middleware("http")
    async def auth_boundary(request: Request, call_next):
        if request.url.path.startswith(("/auth/", "/github/")):
            if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path != "/github/webhook":
                origin = request.headers.get("origin")
                if (origin and origin not in settings.allowed_origins) or (
                    not origin and request.headers.get("sec-fetch-site") == "cross-site"
                ):
                    return JSONResponse({"detail": "Request origin is not allowed."}, status_code=403,
                                        headers={"Cache-Control": "no-store"})
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        # FastAPI's default error includes submitted passwords in its input field.
        errors = [{key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_unavailable(request: Request, exc: sqlite3.OperationalError):
        return JSONResponse({"detail": "Application storage is temporarily unavailable."}, status_code=503)

    @app.exception_handler(GitHubFailure)
    async def github_failure(request: Request, exc: GitHubFailure):
        headers = {"Cache-Control": "no-store"}
        if exc.retry_after:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse({"code": exc.code, "detail": exc.reason}, status_code=exc.status, headers=headers)

    # Wrap the whole app so CORS headers are also present on error responses.
    return CORSMiddleware(app, allow_origins=sorted(settings.allowed_origins),
                          allow_credentials=True, allow_methods=["GET", "POST", "DELETE"],
                          allow_headers=["Content-Type", "X-CSRF-Token"])
