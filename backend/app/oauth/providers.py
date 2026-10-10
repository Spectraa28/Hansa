from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from ..config import Settings


class ProviderIdentity(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    name: str = Field(min_length=1, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=2048)


def oauth_clients(settings: Settings) -> OAuth:
    oauth = OAuth()
    if settings.google_client_id and settings.google_client_secret:
        oauth.register(
            name="google", client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256", "timeout": 15},
        )
    if settings.github_client_id and settings.github_client_secret:
        oauth.register(
            name="github", client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
            authorize_url="https://github.com/login/oauth/authorize",
            access_token_url="https://github.com/login/oauth/access_token",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "read:user user:email", "code_challenge_method": "S256",
                           "token_endpoint_auth_method": "client_secret_post", "timeout": 15},
        )
    return oauth


def provider_client(request: Request, provider: str):
    client = request.app.state.oauth.create_client(provider)
    if client is None:
        raise HTTPException(503, f"{provider.title()} sign-in is not configured.")
    return client


async def provider_identity(client, provider: str, token: dict) -> ProviderIdentity:
    if provider == "google":
        # Authlib verifies the OIDC signature, issuer, audience, expiry, and nonce.
        profile = token.get("userinfo")
        if not isinstance(profile, dict) or profile.get("email_verified") is not True or not profile.get("email"):
            raise HTTPException(403, "Google must provide a verified email address.")
        return ProviderIdentity(subject=profile.get("sub"), email=profile.get("email"),
                                name=(profile.get("name") or profile.get("email") or "Google user")[:100],
                                avatar_url=profile.get("picture"))
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    profile_response = await client.get("user", token=token, headers=headers)
    profile_response.raise_for_status()
    profile = profile_response.json()
    if not isinstance(profile, dict) or type(profile.get("id")) is not int or profile["id"] <= 0:
        raise HTTPException(502, "GitHub returned an invalid user identity.")
    email_response = await client.get("user/emails", token=token, headers=headers)
    email_response.raise_for_status()
    emails = email_response.json()
    if not isinstance(emails, list) or not all(isinstance(item, dict) for item in emails):
        raise HTTPException(502, "GitHub returned invalid email information.")
    verified = [item for item in emails if item.get("verified") is True]
    selected = next((item for item in verified if item.get("primary")), verified[0] if verified else None)
    return ProviderIdentity(subject=str(profile["id"]), email=selected["email"] if selected else None,
                            name=(profile.get("name") or profile.get("login") or "GitHub user")[:100],
                            avatar_url=profile.get("avatar_url"))
