import time
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import httpx
import pytest

from app.config import Settings
from app.sessions import session, token_hash
from app.users import EmailInUse, oauth_user
from app.main import create_app
from app.oauth.providers import ProviderIdentity
from app.oauth import routes as oauth_routes


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_path=tmp_path / "auth.sqlite3", secret_key="test-only-secret-" * 4)
    with TestClient(create_app(settings)) as client:
        yield client


def register(client):
    return client.post("/auth/register", json={
        "email": "Person@example.com", "password": "a-long-test-password", "name": "Person",
    })


def test_password_and_session_credentials_are_not_stored_in_plaintext(client):
    response = register(client)
    assert response.status_code == 201
    assert response.json()["user"]["email"] == "person@example.com"
    assert response.json()["user"]["email_verified"] is False
    assert "password" not in response.text
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    raw_session = client.cookies["ouro_session"]
    store = client.app.app.state.database
    with store.connect() as db:
        user = db.execute("SELECT password_hash FROM users").fetchone()
        session = db.execute("SELECT token_hash FROM sessions").fetchone()
    assert user["password_hash"].startswith("$argon2id$")
    assert session["token_hash"] == token_hash(raw_session)
    assert session["token_hash"] != raw_session
    assert client.get("/auth/me").status_code == 200


def test_logout_requires_csrf_and_revokes_the_session(client):
    response = register(client)
    raw_session = client.cookies["ouro_session"]
    assert client.post("/auth/logout").status_code == 403
    assert client.post("/auth/logout", headers={"X-CSRF-Token": response.json()["csrf_token"]}).status_code == 204
    assert client.get("/auth/me").status_code == 401
    client.cookies.set("ouro_session", raw_session)
    assert client.get("/auth/me").status_code == 401


def test_login_rotates_the_session_and_rejects_bad_passwords(client):
    register(client)
    old_session = client.cookies["ouro_session"]
    bad = {"email": "person@example.com", "password": "incorrect"}
    assert client.post("/auth/login", json=bad).status_code == 401
    missing = {"email": "missing@example.com", "password": "incorrect"}
    assert client.post("/auth/login", json=missing).json() == client.post("/auth/login", json=bad).json()
    response = client.post("/auth/login", json={"email": "person@example.com", "password": "a-long-test-password"})
    assert response.status_code == 200
    assert client.cookies["ouro_session"] != old_session
    assert session(client.app.app.state.database, old_session) is None


def test_expired_session_cannot_authenticate(client):
    register(client)
    with client.app.app.state.database.connect() as db:
        db.execute("UPDATE sessions SET expires_at = ?", (int(time.time()) - 1,))
    assert client.get("/auth/me").status_code == 401


def test_validation_does_not_echo_passwords_and_cross_origin_signup_is_rejected(client):
    body = {"email": "invalid", "password": "private", "name": "Person"}
    response = client.post("/auth/register", json=body)
    assert response.status_code == 422
    assert "private" not in response.text
    assert "input" not in response.json()["detail"][0]
    body["email"] = "person@example.com"
    body["password"] = "a-long-test-password"
    assert client.post("/auth/register", json=body, headers={"Origin": "https://attacker.example"}).status_code == 403


def test_oauth_does_not_link_accounts_by_email(client):
    register(client)
    store = client.app.app.state.database
    with pytest.raises(EmailInUse):
        oauth_user(store, "google", "different-identity", "person@example.com", "Other Person", None)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM identities").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 1
    original = oauth_user(store, "github", "123", "new@example.com", "New Person", None)
    repeated = oauth_user(store, "github", "123", "changed@example.com", "Changed", None)
    assert original["id"] == repeated["id"]


def test_login_attempts_are_limited(client):
    body = {"email": "missing@example.com", "password": "incorrect"}
    for _ in range(10):
        assert client.post("/auth/login", json=body).status_code == 401
    response = client.post("/auth/login", json=body)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "600"


def test_optional_email_and_unconfigured_providers(tmp_path):
    settings = Settings(database_path=tmp_path / "auth.sqlite3", secret_key="test-only-secret-" * 4,
                        email_login_enabled=False)
    with TestClient(create_app(settings)) as client:
        assert client.get("/auth/providers").json() == {"google": False, "github": False, "email": False}
        assert register(client).status_code == 404
        assert client.post("/auth/login", json={"email": "person@example.com", "password": "anything"}).status_code == 404
        assert client.get("/auth/google/login").status_code == 503


def test_github_requests_identity_scopes_and_rejects_invalid_oauth_state(tmp_path, monkeypatch):
    async def no_network(*args, **kwargs):
        raise AssertionError("State rejection must happen before any provider request.")

    monkeypatch.setattr(httpx.AsyncClient, "request", no_network)
    settings = Settings(database_path=tmp_path / "auth.sqlite3", secret_key="test-only-secret-" * 4,
                        github_client_id="test-client", github_client_secret="test-secret")
    with TestClient(create_app(settings)) as client:
        response = client.get("/auth/github/login", follow_redirects=False)
        assert response.status_code == 302
        query = parse_qs(urlsplit(response.headers["location"]).query)
        assert set(query["scope"][0].split()) == {"read:user", "user:email"}
        assert query["code_challenge_method"] == ["S256"]
        assert "state" in query
        response = client.get("/auth/github/callback?state=incorrect&code=test-code")
        assert response.status_code == 400
        assert client.get("/auth/me").status_code == 401


def test_hosted_settings_require_https_and_secure_cookies(tmp_path):
    with pytest.raises(ValueError):
        Settings(database_path=tmp_path / "auth.sqlite3", secret_key="test-only-secret-" * 4,
                 app_url="http://ouro.example")
    with pytest.raises(ValueError):
        Settings(database_path=tmp_path / "auth.sqlite3", secret_key="test-only-secret-" * 4,
                 app_url="https://ouro.example")


@pytest.mark.parametrize("provider", ["google", "github"])
def test_oauth_success_redirects_to_frontend_app_and_sets_session(tmp_path, monkeypatch, provider):
    class FakeProvider:
        async def authorize_access_token(self, request):
            return {"access_token": "test-only"}

    async def identity(*args):
        return ProviderIdentity(subject="test-subject", name="Test Person", email="test@example.com")

    monkeypatch.setattr(oauth_routes, "provider_client", lambda *args: FakeProvider())
    monkeypatch.setattr(oauth_routes, "provider_identity", identity)
    settings = Settings(database_path=tmp_path / "auth.sqlite3", secret_key="test-only-secret-" * 4,
                        frontend_origin="http://localhost:5174/")
    with TestClient(create_app(settings)) as client:
        response = client.get(f"/auth/{provider}/callback?next=https://attacker.example", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "http://localhost:5174/app"
        assert "httponly" in response.headers["set-cookie"].lower()
        assert client.get("/auth/me").json()["user"]["name"] == "Test Person"
