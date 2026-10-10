# Ouro backend

Status: authentication code written; application startup, tests, and real OAuth sign-in have **not been run**. The optimizer and agent sandbox are not implemented yet.

## Backend layout

Files are grouped by responsibility within one FastAPI application:

```text
backend/app/
├── auth/
│   ├── routes.py       # Email login, registration, current user, logout
│   ├── schemas.py      # Login and registration input validation
│   └── service.py      # Password authentication and sign-in rate limits
├── oauth/
│   ├── providers.py    # Google/GitHub clients and identity parsing
│   └── routes.py       # Provider redirects and callbacks
├── users.py            # User and provider identity storage
├── sessions.py         # Session storage, cookies, and logout CSRF checks
├── database.py         # SQLite connections and schema initialization
├── config.py           # Environment settings and validation
└── main.py             # Application setup, routers, and shared middleware
```

The service modules share the local SQLite database. API paths and the database schema are unchanged by this reorganization.

## Local setup

Run from this repository root. These are setup instructions, not verified execution results.

```sh
uv sync --locked
```

Add the authentication settings from [.env.example](.env.example) to your existing ignored `.env`. Preserve any existing keys. Generate the session-signing secret locally:

```sh
openssl rand -hex 32
```

Set `AUTH_SECRET_KEY` to that output. Do not paste it into chat or commit it. Defaults use `http://localhost:8000`, enable email/password login, and create `var/auth.sqlite3` when the application starts. SQLite uses the standard library; no database server is required.

Start the API when ready:

```sh
uv run uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

The application reads the root `.env`; environment variables take precedence. Access logs are disabled to avoid logging OAuth callback codes. API documentation is at `http://localhost:8000/docs`.

## Google and GitHub setup

Register your own OAuth applications with each provider. Their client IDs and secrets belong in `.env`, not SQLite or frontend code. An unconfigured provider returns `503`; email login works independently.

| Provider | Environment variables | Local callback URL | Requested permissions |
| --- | --- | --- | --- |
| Google | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | `http://localhost:8000/auth/google/callback` | `openid email profile` |
| GitHub | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | `http://localhost:8000/auth/github/callback` | `read:user user:email` |

For Google, create a Web application OAuth client and configure its consent screen/test users as required. For GitHub, create an OAuth App with homepage `http://localhost:8000` and the callback above. Start a browser login using `/auth/google/login` or `/auth/github/login`. Open these URLs as a top-level navigation rather than fetching them with JavaScript. A successful callback sets the application session cookie and redirects to `/auth/me`.

OAuth uses state, PKCE, and (for Google) OpenID Connect nonce and ID-token validation through Authlib. GitHub identity uses its stable numeric user ID; Google uses its `sub` claim. Only verified provider emails are stored. GitHub users without a verified email can still sign in through their provider identity.

GitHub sign-in does not request `repo` or `public_repo`. Repository authorization and linking GitHub to an existing account are deferred. Use a dedicated identity-only GitHub OAuth App; a future repository connector can have separate permissions and credentials.

## Authentication endpoints

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/auth/providers` | Which login methods are configured/enabled |
| POST | `/auth/register` | Create an email/password account and sign in |
| POST | `/auth/login` | Sign in with email/password |
| GET | `/auth/me` | Current user and session CSRF token; `401` without a valid session |
| POST | `/auth/logout` | Revoke the current session; requires `X-CSRF-Token` |
| GET | `/auth/google/login` | Redirect to Google |
| GET | `/auth/google/callback` | Complete Google sign-in |
| GET | `/auth/github/login` | Redirect to GitHub |
| GET | `/auth/github/callback` | Complete GitHub sign-in |

Email registration accepts JSON:

```json
{
  "email": "person@example.com",
  "name": "Person",
  "password": "choose-a-private-password"
}
```

Login accepts `email` and `password`. Registration requires a password of 12–128 characters. Email addresses are normalized case-insensitively. Login and registration return:

```json
{
  "user": {
    "id": "user-id",
    "email": "person@example.com",
    "email_verified": false,
    "name": "Person",
    "avatar_url": null,
    "created_at": 0
  },
  "csrf_token": "session-csrf-token"
}
```

The example above describes the response shape; it is not a recorded run. The login token is only in an HttpOnly, SameSite=Lax cookie. Send cookies with frontend requests (`credentials: "include"`). Fetch `/auth/me` to obtain the CSRF token, then send it in the `X-CSRF-Token` header when logging out. Current sessions expire after seven days; signing in rotates the browser's previous session, and logout revokes it in SQLite.

Set `AUTH_EMAIL_LOGIN_ENABLED=false` to disable both email registration and password login. `FRONTEND_ORIGIN` allows one frontend origin (default `http://localhost:5173`); other browser origins cannot submit authentication mutations.

## Stored credentials and boundaries

- SQLite stores users, Argon2id password hashes, Google/GitHub identity mappings, hashed application session tokens, CSRF tokens, and rate-limit counters. Passwords and raw login tokens are not stored.
- Provider access/refresh tokens are used transiently for login and are not persisted. Provider passwords are never received. OAuth app secrets stay in server configuration.
- OAuth flow cookies hold temporary signed state/nonce/PKCE data, expire after ten minutes, and are cleared after the callback. They contain no provider access tokens or account passwords.
- Existing accounts are not linked automatically by matching email. A collision returns `409` and asks the user to use the existing sign-in method.
- Email/password accounts are marked `email_verified=false`. Email verification, recovery emails, password reset, and account linking are outside this slice. Unverified email must not be used to grant future repository or organization permissions.
- Authentication responses disable caching. Validation errors omit submitted input to avoid echoing passwords. Authentication handlers are not exported to Neatlogs.
- Attempts are limited in SQLite to 30 starts per client IP and 10 email attempts per client IP/address per ten-minute window. `429` includes `Retry-After`; behind a reverse proxy, trust forwarded IP headers only from that proxy.

For hosting, set HTTPS `APP_URL` and `FRONTEND_ORIGIN`, set `AUTH_COOKIE_SECURE=true`, and register the exact hosted callback URLs. Serve frontend and API on the same site so SameSite cookies work. Keep the SQLite file and server secrets outside any future candidate sandbox. This single-host authentication slice has not been security-tested or deployed.

## Deferred tests

Security regression tests are written in [backend/tests/test_auth.py](backend/tests/test_auth.py). At the user's request, none have been executed, and no application process has been started. After authorization to test:

```sh
uv run pytest
```

The tests cover password/session storage, login rotation, expiry, logout/CSRF, origin checks, validation redaction, account collision, rate limits, optional providers, and OAuth state rejection. Real Google/GitHub callback success still needs configured OAuth applications and a separate browser check.

## Planning references

Read [prd.md](prd.md), [ARCHITECTURE.md](ARCHITECTURE.md), [SPONSORS.md](SPONSORS.md), and [hackathon.md](hackathon.md) for the optimization product and event constraints. Authentication is the first implemented slice; it does not establish a working optimizer, sandbox, or measured improvement.

Implementation references: [Authlib example](https://github.com/authlib/demo-oauth-client/blob/master/starlette-google-login/app.py), [Google web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [GitHub authorization](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps), [GitHub scopes](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps), and [pwdlib password hashing](https://frankie567.github.io/pwdlib/guide/).
