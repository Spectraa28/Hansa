import asyncio
from dataclasses import replace
import hashlib
import hmac
import io
import json
import tarfile
import time
from urllib.parse import parse_qs, urlsplit
import uuid

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import httpx
import pytest

from app.config import Settings
from app.github.archive import extract_archive
from app.github.client import GitHubAPI, GitHubFailure, archive_redirect, branch_name
from app.main import create_app


SHA = "a" * 40
REPO = {"id": 300, "full_name": "owner/agent", "default_branch": "main", "private": True}


def source_archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        root = tarfile.TarInfo("owner-agent/")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for name, body, kind in entries:
            info = tarfile.TarInfo("owner-agent/" + name)
            info.type = kind
            if kind == tarfile.SYMTYPE:
                info.linkname = "../../outside"
                archive.addfile(info)
            else:
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
    return output.getvalue()


@pytest.fixture
def github_client(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path = tmp_path / "app.pem"
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    settings = Settings(database_path=tmp_path / "auth.sqlite3", secret_key="test-only-secret-" * 4,
                        github_app_id=100, github_app_client_id="app-client", github_app_client_secret="app-secret",
                        github_app_private_key_path=key_path, github_app_callback_url="http://localhost:8000/github/callback",
                        github_token_encryption_key=Fernet.generate_key().decode(), github_webhook_secret="webhook-test-secret",
                        import_workspace_path=tmp_path / "imports")
    state = {"requests": [], "sha": SHA, "accessible": True, "rate_limited": False,
             "archive": source_archive([("main.py", b"print('source only')", tarfile.REGTYPE)])}

    def respond(request):
        state["requests"].append(request)
        path = request.url.path
        if path == "/app":
            return httpx.Response(200, json={"id": 100, "slug": "ouro-test", "permissions": {"contents": "read", "metadata": "read"}})
        if path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "private-user-token", "expires_in": 3600,
                                            "refresh_token": "private-refresh-token", "refresh_token_expires_in": 86400})
        if path == "/user":
            return httpx.Response(200, json={"id": 12345, "login": "github-person"})
        if path == "/user/installations":
            if state["rate_limited"]:
                return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "retry-after": "60"})
            return httpx.Response(200, json={"installations": [{"id": 200, "app_id": 100,
                "account": {"login": "owner"}, "repository_selection": "selected", "permissions": {"contents": "read"}}]})
        if path == "/user/installations/200/repositories":
            repos = [REPO] if state["accessible"] else []
            return httpx.Response(200, json={"total_count": len(repos), "repositories": repos})
        if path == "/repos/owner/agent/branches":
            return httpx.Response(200, json=[{"name": "main", "commit": {"sha": state["sha"]}}])
        if path == "/repos/owner/agent/branches/main":
            return httpx.Response(200, json={"name": "main", "commit": {"sha": state["sha"]}})
        if path == f"/repos/owner/agent/commits/{SHA}":
            return httpx.Response(200, json={"sha": SHA})
        if path == f"/repos/owner/agent/git/trees/{SHA}":
            return httpx.Response(200, json={"truncated": False, "tree": [{"mode": "100644", "path": "main.py"}]})
        if path == "/app/installations/200/access_tokens":
            assert json.loads(request.content) == {"repository_ids": [300], "permissions": {"contents": "read", "metadata": "read"}}
            return httpx.Response(201, json={"token": "private-installation-token"})
        if path == f"/repos/owner/agent/tarball/{SHA}":
            return httpx.Response(302, headers={"location": f"https://codeload.github.com/owner/agent/legacy.tar.gz/{SHA}?token=signed"})
        if request.url.host == "codeload.github.com":
            assert "authorization" not in request.headers
            return httpx.Response(200, content=state["archive"])
        raise AssertionError(f"Unexpected endpoint: {request.method} {request.url.host}{path}")

    def mocked_api(self, seconds=120):
        def streaming_response(request):
            response = respond(request)
            return httpx.Response(response.status_code, headers=response.headers, stream=httpx.ByteStream(response.content))
        self.deadline = time.monotonic() + seconds
        self.client = httpx.Client(transport=httpx.MockTransport(streaming_response), follow_redirects=False, trust_env=False)

    async def deferred_worker(service):
        while not service.stopping.is_set():
            await asyncio.sleep(0.01)

    monkeypatch.setattr(GitHubAPI, "__init__", mocked_api)
    monkeypatch.setattr("app.main.import_worker", deferred_worker)
    with TestClient(create_app(settings)) as client:
        signup = client.post("/auth/register", json={"email": "google-or-email@example.com", "name": "Person",
                                                     "password": "a-long-test-password"})
        client.csrf = {"X-CSRF-Token": signup.json()["csrf_token"]}
        yield client, state, settings


def connect(client):
    start = client.post("/github/connect", headers=client.csrf)
    assert start.status_code == 200
    query = parse_qs(urlsplit(start.json()["authorization_url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert "scope" not in query
    response = client.get("/github/callback", params={"state": query["state"][0], "code": "test-code"}, follow_redirects=False)
    assert response.status_code == 303
    return query


def queue(client):
    response = client.post("/github/imports", headers=client.csrf, json={"installation_id": 200, "repository_id": 300})
    assert response.status_code == 202
    return response.json()


def test_connection_binds_pkce_to_current_session_and_encrypts_credentials(github_client):
    client, state, _ = github_client
    assert client.post("/github/connect").status_code == 403
    query = connect(client)
    service = client.app.app.state.github
    connection = service.connection(client.get("/auth/me").json()["user"]["id"])
    assert connection["github_user_id"] == 12345
    assert "private-user-token" not in connection["credentials"]
    assert "private-refresh-token" not in connection["credentials"]
    assert "credentials" not in client.get("/github/connection").text
    assert client.get("/github/callback", params={"state": query["state"][0], "code": "replay"}).status_code == 400
    exchange = next(r for r in state["requests"] if r.url.path == "/login/oauth/access_token")
    verifier = parse_qs(exchange.content.decode())["code_verifier"][0]
    import base64
    assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode() == query["code_challenge"][0]


def test_invalid_state_or_rotated_session_never_exchanges_code(github_client):
    client, state, _ = github_client
    start = client.post("/github/connect", headers=client.csrf).json()
    query = parse_qs(urlsplit(start["authorization_url"]).query)
    client.post("/auth/login", json={"email": "google-or-email@example.com", "password": "a-long-test-password"})
    response = client.get("/github/callback", params={"state": query["state"][0], "code": "test-code"})
    assert response.status_code == 400
    assert not any(r.url.path == "/login/oauth/access_token" for r in state["requests"])


def test_denied_authorization_consumes_state_without_exchanging_a_code(github_client):
    client, state, _ = github_client
    start = client.post("/github/connect", headers=client.csrf).json()
    query = parse_qs(urlsplit(start["authorization_url"]).query)
    response = client.get("/github/callback", params={"state": query["state"][0], "error": "access_denied"})
    assert response.status_code == 400 and response.json()["code"] == "authorization_denied"
    assert not any(r.url.path == "/login/oauth/access_token" for r in state["requests"])
    assert client.get("/github/connection").json()["status"] == "disconnected"


def test_endpoint_allowlist_and_expired_deadline_fail_before_network(github_client):
    _, state, _ = github_client
    with GitHubAPI() as api:
        with pytest.raises(GitHubFailure) as failure:
            api.request("GET", "//attacker.example/source", "private-token")
        assert failure.value.code == "invalid_endpoint"
        api.deadline = time.monotonic() - 1
        with pytest.raises(GitHubFailure) as failure:
            api.request("GET", "/user", "private-token")
        assert failure.value.code == "timeout"
    assert state["requests"] == []


def test_installation_id_alone_is_not_permission_and_rate_limits_are_reported(github_client):
    client, state, _ = github_client
    connect(client)
    assert client.get("/github/repositories?installation_id=999").status_code == 403
    assert not any(r.url.path == "/user/installations/999/repositories" for r in state["requests"])
    result = client.get("/github/repositories?installation_id=200&page=1&per_page=1").json()
    assert result["repositories"][0]["id"] == 300
    request = next(r for r in state["requests"] if r.url.path == "/user/installations/200/repositories")
    assert request.url.params["per_page"] == "1"
    state["rate_limited"] = True
    response = client.get("/github/installations")
    assert response.status_code == 429 and response.headers["retry-after"] == "60"


def test_fixed_sha_import_survives_branch_change_and_hides_paths_and_tokens(github_client):
    client, state, settings = github_client
    connect(client)
    item = queue(client)
    assert item["status"] == "queued" and item["commit_sha"] == SHA and item["branch"] == "main"
    state["sha"] = "b" * 40
    service = client.app.app.state.github
    claimed = service.claim_import()
    assert client.get(f"/github/imports/{item['id']}").json()["status"] == "downloading"
    service.perform_import(claimed)
    response = client.get(f"/github/imports/{item['id']}")
    assert response.json()["status"] == "ready"
    assert response.json()["commit_sha"] == SHA
    assert response.json()["file_count"] == 1
    assert "snapshot_path" not in response.text and "private-" not in response.text
    user_id = client.get("/auth/me").json()["user"]["id"]
    snapshot = settings.import_workspace_path / user_id / item["id"]
    assert (snapshot / "main.py").read_text() == "print('source only')"
    assert snapshot.stat().st_mode & 0o777 == 0o700
    assert (snapshot / "main.py").stat().st_mode & 0o777 == 0o600
    assert not list(settings.import_workspace_path.rglob("source.tar.gz"))
    assert client.delete(f"/github/imports/{item['id']}").status_code == 403
    assert client.delete(f"/github/imports/{item['id']}", headers=client.csrf).status_code == 204
    assert not snapshot.exists()
    assert client.get(f"/github/imports/{item['id']}").json()["status"] == "deleted"


def test_worker_rechecks_access_and_disconnect_cancels_queued_import(github_client):
    client, state, _ = github_client
    connect(client)
    item = queue(client)
    state["accessible"] = False
    service = client.app.app.state.github
    service.perform_import(service.claim_import())
    assert client.get(f"/github/imports/{item['id']}").json()["failure_code"] == "access_denied"
    assert not any(r.url.path.endswith("/access_tokens") for r in state["requests"])
    state["accessible"] = True
    next_item = queue(client)
    assert client.delete("/github/connection", headers=client.csrf).status_code == 204
    assert client.get(f"/github/imports/{next_item['id']}").json()["status"] == "failed"
    user_id = client.get("/auth/me").json()["user"]["id"]
    assert service.connection(user_id)["credentials"] is None


def test_another_account_cannot_read_or_delete_imports(github_client):
    client, _, _ = github_client
    connect(client)
    item = queue(client)
    signup = client.post("/auth/register", json={"email": "other@example.com", "name": "Other", "password": "a-long-test-password"})
    headers = {"X-CSRF-Token": signup.json()["csrf_token"]}
    assert client.get(f"/github/imports/{item['id']}").status_code == 404
    assert client.delete(f"/github/imports/{item['id']}", headers=headers).status_code == 404
    assert client.get("/github/imports").json()["imports"] == []


def test_refresh_rotation_is_encrypted_and_download_size_failures_are_persisted(github_client):
    client, state, settings = github_client
    connect(client)
    service = client.app.app.state.github
    user_id = client.get("/auth/me").json()["user"]["id"]
    credentials = service.decrypt(service.connection(user_id)["credentials"])
    credentials["expires_at"] = int(time.time()) - 1
    with service.database.connect() as db:
        db.execute("UPDATE github_connections SET credentials=? WHERE user_id=?", (service.encrypt(credentials), user_id))
    assert client.get("/github/installations").status_code == 200
    assert any(b"grant_type=refresh_token" in request.content for request in state["requests"])
    assert service.decrypt(service.connection(user_id)["credentials"])["expires_at"] > int(time.time())
    item = queue(client)
    service.settings = replace(settings, import_download_bytes=1)
    service.perform_import(service.claim_import())
    result = client.get(f"/github/imports/{item['id']}").json()
    assert result["status"] == "failed" and result["failure_code"] == "download_limit"
    assert not service.source_path(user_id, item["id"]).exists()


def test_restart_preserves_queue_and_marks_interrupted_imports_failed(github_client):
    client, _, _ = github_client
    connect(client)
    first = queue(client)
    service = client.app.app.state.github
    service.claim_import()
    second = queue(client)
    service.recover()
    assert client.get(f"/github/imports/{first['id']}").json()["failure_code"] == "interrupted"
    assert client.get(f"/github/imports/{second['id']}").json()["status"] == "queued"


def test_installation_removal_cancels_import_without_trusting_sender_installation(github_client):
    client, _, settings = github_client
    connect(client)
    item = queue(client)
    body = json.dumps({"action": "deleted", "installation": {"id": 200, "app_id": 100}}).encode()
    headers = {"X-GitHub-Event": "installation", "X-GitHub-Delivery": str(uuid.uuid4()),
               "X-Hub-Signature-256": "sha256=" + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()}
    assert client.post("/github/webhook", content=body, headers=headers).status_code == 204
    assert client.get(f"/github/imports/{item['id']}").json()["failure_code"] == "access_revoked"
    assert client.get("/github/connection").json()["installation_ids"] == []


def test_signed_webhook_revokes_connection_and_is_idempotent(github_client):
    client, _, settings = github_client
    connect(client)
    item = queue(client)
    body = json.dumps({"action": "revoked", "sender": {"id": 12345}}).encode()
    signature = "sha256=" + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-GitHub-Event": "github_app_authorization", "X-GitHub-Delivery": str(uuid.uuid4()), "X-Hub-Signature-256": signature}
    assert client.post("/github/webhook", content=body, headers=headers).status_code == 204
    assert client.post("/github/webhook", content=body, headers=headers).status_code == 204
    assert client.get("/github/connection").json()["status"] == "revoked"
    assert client.get(f"/github/imports/{item['id']}").json()["status"] == "failed"
    assert client.post("/github/webhook", content=body + b" ", headers=headers).status_code == 401


def test_archive_leaves_links_out_and_never_creates_them(tmp_path):
    path = tmp_path / "source.tar.gz"
    path.write_bytes(source_archive([("agent.py", b"print(1)", tarfile.REGTYPE), ("CLAUDE.md", b"", tarfile.SYMTYPE), ("hard", b"", tarfile.LNKTYPE)]))
    settings = Settings(database_path=tmp_path / "db", secret_key="test-only-" * 4)
    result = extract_archive(path, tmp_path / "source", settings, lambda: None)
    assert result["file_count"] == 1 and "links_not_imported" in result["warnings"]
    assert sorted(p.name for p in (tmp_path / "source").iterdir()) == ["agent.py"]


@pytest.mark.parametrize("name,kind", [("../../escape", tarfile.REGTYPE), ("device", tarfile.CHRTYPE),
                                      ("/absolute", tarfile.REGTYPE), ("dir\\escape", tarfile.REGTYPE)])
def test_archive_rejects_unsafe_paths_and_links(tmp_path, name, kind):
    path = tmp_path / "source.tar.gz"
    path.write_bytes(source_archive([(name, b"source", kind)]))
    settings = Settings(database_path=tmp_path / "db", secret_key="test-only-" * 4)
    with pytest.raises(GitHubFailure) as failure:
        extract_archive(path, tmp_path / "source", settings, lambda: None)
    assert failure.value.code == "unsafe_archive"
    assert not (tmp_path / "escape").exists()


def test_archive_limits_and_submodule_lfs_warnings(tmp_path):
    settings = Settings(database_path=tmp_path / "db", secret_key="test-only-" * 4)
    path = tmp_path / "source.tar.gz"
    path.write_bytes(source_archive([(".gitmodules", b"[submodule]\n", tarfile.REGTYPE),
                                    ("weights.bin", b"version https://git-lfs.github.com/spec/v1\n", tarfile.REGTYPE)]))
    result = extract_archive(path, tmp_path / "source", settings, lambda: None)
    assert result["warnings"] == ["git_lfs_objects_not_imported", "submodules_not_imported"]
    with pytest.raises(GitHubFailure) as failure:
        extract_archive(path, tmp_path / "limited", replace(settings, import_extracted_bytes=1), lambda: None)
    assert failure.value.code == "extracted_limit"
    with pytest.raises(GitHubFailure) as failure:
        extract_archive(path, tmp_path / "entries", replace(settings, import_file_count=1), lambda: None)
    assert failure.value.code == "file_limit"


@pytest.mark.parametrize("url", ["http://codeload.github.com/owner/agent/legacy.tar.gz/" + SHA,
    "https://codeload.github.com.evil.test/owner/agent/legacy.tar.gz/" + SHA,
    "https://codeload.github.com/other/repo/legacy.tar.gz/" + SHA,
    "https://user@codeload.github.com/owner/agent/legacy.tar.gz/" + SHA,
    "https://codeload.github.com/owner/agent/legacy.tar.gz/" + "b" * 40])
def test_archive_redirect_is_bound_to_github_repository_and_sha(url):
    with pytest.raises(GitHubFailure):
        archive_redirect(url, "owner/agent", SHA)


@pytest.mark.parametrize("branch", ["../main", "main/../private", "main?ref=other", "main\\other", "main.lock"])
def test_branch_cannot_change_the_requested_endpoint(branch):
    with pytest.raises(GitHubFailure):
        branch_name(branch)


def test_folder_import_keeps_only_that_folder(tmp_path):
    import io, tarfile, types
    from app.github.archive import extract_archive
    from app.github.client import GitHubFailure
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, body in (("repo-abc/Backend/main.py", b"print(1)"), ("repo-abc/Backend/pkg/tool.py", b"x = 1"),
                           ("repo-abc/frontend/.env.production", b"SECRET=1"), ("repo-abc/README.md", b"hi")):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    settings = types.SimpleNamespace(import_extracted_bytes=10_000, import_file_count=100)
    result = extract_archive(archive, tmp_path / "out", settings, lambda: None, "Backend")
    assert result["file_count"] == 2
    assert sorted(str(p.relative_to(tmp_path / "out")) for p in (tmp_path / "out").rglob("*") if p.is_file()) == ["main.py", "pkg/tool.py"]
    with pytest.raises(GitHubFailure) as missing:
        extract_archive(archive, tmp_path / "none", settings, lambda: None, "nope")
    assert missing.value.code == "empty_folder"
