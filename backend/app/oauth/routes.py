from typing import Literal

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
from joserfc.errors import JoseError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ..auth.service import rate_limit
from ..sessions import establish_session
from ..users import EmailInUse, oauth_user
from .providers import provider_client, provider_identity


router = APIRouter(prefix="/auth", tags=["OAuth"])


def failed(request: Request, code: str):
    return RedirectResponse(f"{request.app.state.settings.frontend_origin.rstrip('/')}/sign-in?error={code}", status_code=303)


@router.get("/{provider}/login")
async def oauth_login(provider: Literal["google", "github"], request: Request):
    client = provider_client(request, provider)
    await run_in_threadpool(rate_limit, request)
    request.session.clear()
    redirect_uri = f"{request.app.state.settings.app_url}/auth/{provider}/callback"
    try:
        # Ask which account every time; otherwise signing out and back in silently reuses the last one.
        return await client.authorize_redirect(request, redirect_uri, prompt="select_account")
    except (OAuthError, httpx.HTTPError):
        request.session.clear()
        raise HTTPException(502, "Could not contact the sign-in provider. Try again.") from None


@router.get("/{provider}/callback")
async def oauth_callback(provider: Literal["google", "github"], request: Request):
    client = provider_client(request, provider)
    try:
        token = await client.authorize_access_token(request)
        identity = await provider_identity(client, provider, token)
        user = await run_in_threadpool(
            oauth_user, request.app.state.database, provider, identity.subject,
            str(identity.email).casefold() if identity.email else None, identity.name, identity.avatar_url,
        )
        response = RedirectResponse(f"{request.app.state.settings.frontend_origin.rstrip('/')}/app", status_code=303)
        await run_in_threadpool(establish_session, request, user, response)
        return response
    # A browser lands here, so failures go back to the sign-in page as a fixed code it can explain.
    except (OAuthError, JoseError):
        return failed(request, "cancelled")
    except httpx.HTTPError:
        return failed(request, "provider")
    except (ValidationError, ValueError, KeyError, TypeError):
        return failed(request, "identity")
    except EmailInUse:
        return failed(request, "email_in_use")
    finally:
        request.session.clear()
