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


@router.get("/{provider}/login")
async def oauth_login(provider: Literal["google", "github"], request: Request):
    client = provider_client(request, provider)
    await run_in_threadpool(rate_limit, request)
    request.session.clear()
    redirect_uri = f"{request.app.state.settings.app_url}/auth/{provider}/callback"
    try:
        return await client.authorize_redirect(request, redirect_uri)
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
    except (OAuthError, JoseError):
        raise HTTPException(400, "Sign-in was cancelled, expired, or invalid. Start sign-in again.") from None
    except httpx.HTTPError:
        raise HTTPException(502, "Could not verify your identity with the provider. Try again.") from None
    except (ValidationError, ValueError, KeyError, TypeError):
        raise HTTPException(502, "The provider returned an invalid identity.") from None
    except EmailInUse:
        raise HTTPException(409, "This email already has an account. Use its existing sign-in method; account linking is not enabled yet.") from None
    finally:
        request.session.clear()
