from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SECRET = "test-only-secret-" * 4
ACCOUNT = {"email": "guest@example.com", "password": "a-long-test-password", "name": "Guest"}


def test_api_reference_is_hidden_when_hosted(tmp_path):
    hosted = Settings(database_path=tmp_path / "a.sqlite3", secret_key=SECRET, app_url="https://hansa.example.com",
                      frontend_origin="https://hansa.example.com", cookie_secure=True)
    with TestClient(create_app(hosted), base_url="https://hansa.example.com") as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
        response = client.get("/auth/providers")
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "max-age" in response.headers["strict-transport-security"]


def test_api_reference_stays_available_locally(tmp_path):
    with TestClient(create_app(Settings(database_path=tmp_path / "a.sqlite3", secret_key=SECRET))) as client:
        assert client.get("/openapi.json").status_code == 200


def test_invite_list_refuses_other_addresses_without_creating_an_account(tmp_path):
    settings = Settings(database_path=tmp_path / "a.sqlite3", secret_key=SECRET, allowed_emails=frozenset({"owner@example.com"}))
    with TestClient(create_app(settings)) as client:
        refused = client.post("/auth/register", json=ACCOUNT)
        assert refused.status_code == 403 and "invitation-only" in refused.json()["detail"]
        with client.app.app.state.database.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert client.post("/auth/register", json={**ACCOUNT, "email": "Owner@Example.com"}).status_code == 201


def test_no_invite_list_means_anyone_may_register(tmp_path):
    with TestClient(create_app(Settings(database_path=tmp_path / "a.sqlite3", secret_key=SECRET))) as client:
        assert client.post("/auth/register", json=ACCOUNT).status_code == 201
