"""Regression coverage for static inspection and configuration trust boundaries."""
import json
import uuid

from fastapi.testclient import TestClient
from fastapi import HTTPException
import pytest

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.inspection.scanner import MAX_FILE_BYTES, scan

SHA = "a" * 40


def source(root):
    root.mkdir(parents=True)
    (root / ".python-version").write_text("3.12\n")
    (root / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.12"\n[project.scripts]\nagent = "agent:main"\n')
    (root / "uv.lock").write_text("version = 1")
    (root / "agent.py").write_text('import openai\nimport requests\nmodel = "gpt-4o"\nAPI_KEY = "private-test-credential"\ndef main():\n    raise RuntimeError("Never execute imported code")\n')


def test_static_scan_reports_evidence_conflicts_and_does_not_echo_credentials(tmp_path):
    source(tmp_path / "source")
    result = scan(tmp_path / "source")
    assert not result["runnable"]
    assert {f["value"] for f in result["findings"] if f["kind"] == "python_version"} == {"3.12", ">=3.12"}
    assert any(c["kind"] == "python_version" for c in result["conflicts"])
    assert any(f["value"] == "gpt-4o" and f["location"] == "line 3" for f in result["findings"])
    assert any(f["kind"] == "tool" and f["confidence"] == "inferred" for f in result["findings"])
    assert "private-test-credential" not in json.dumps(result)


def test_scan_skips_links_private_env_and_oversized_files(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (tmp_path / "outside.py").write_text('model = "gpt-outside"')
    (root / "linked.py").symlink_to(tmp_path / "outside.py")
    (root / ".env").write_text('OPENAI_MODEL=gpt-private\nOPENAI_API_KEY=private-test-credential')
    (root / "huge.py").write_text("x" * (MAX_FILE_BYTES + 1))
    result = scan(root)
    assert result["partial"]
    assert "symlink_skipped" in result["warnings"]
    assert "scan_byte_limit" in result["warnings"]
    assert "gpt-outside" not in json.dumps(result)
    assert "gpt-private" not in json.dumps(result)


def test_readme_and_decorated_tools_are_inferred_without_running(tmp_path):
    (tmp_path / "README.md").write_text("Run `python agent.py`.\n")
    (tmp_path / "agent.py").write_text('@tool\ndef search_orders():\n    pass\nif __name__ == "__main__":\n    main()\n')
    result = scan(tmp_path)
    assert any(f["kind"] == "entrypoint" and f["source_file"] == "README.md" and f["confidence"] == "inferred" for f in result["findings"])
    assert any(f["kind"] == "tool" and f["value"] == "search_orders" for f in result["findings"])


@pytest.fixture
def imported_client(tmp_path):
    settings = Settings(database_path=tmp_path / "auth.sqlite3", secret_key="test-only-secret-" * 4,
                        import_workspace_path=tmp_path / "imports")
    with TestClient(create_app(settings)) as client:
        login = client.post('/auth/register', json={"email": "owner@example.com", "password": "long-test-password", "name": "Owner"}).json()
        app = client.app.app
        import_id = str(uuid.uuid4())
        root = app.state.github.source_path(login["user"]["id"], import_id)
        source(root)
        with app.state.database.connect() as db:
            db.execute('''INSERT INTO repository_imports
                (id,user_id,connection_generation,installation_id,repository_id,repository_name,branch,commit_sha,snapshot_path,status,created_at,updated_at)
                VALUES (?,?,'test',1,2,'owner/agent','main',?,?,'ready',1,1)''',
                (import_id, login["user"]["id"], SHA, str(root)))
        yield client, import_id, {"X-CSRF-Token": login["csrf_token"]}


def configuration(result):
    return {"revision": result["revision"], "commit_sha": SHA, "python_version": "3.12",
            "entrypoint": "agent:main", "dependency_manifests": ["pyproject.toml"],
            "model_provider": "openai", "model_id": "gpt-4o", "approved_tools": []}


def test_inspection_and_confirmation_require_csrf_and_persist(imported_client):
    client, import_id, headers = imported_client
    endpoint = f"/github/imports/{import_id}/inspection"
    assert client.post(endpoint).status_code == 403
    response = client.post(endpoint, headers=headers)
    assert response.status_code == 200
    result = response.json()
    assert result["suggested_configuration"]["python_version"] is None
    assert result["suggested_configuration"]["model_id"] == "gpt-4o"
    assert client.get(endpoint).json() == result
    body = configuration(result)
    config_endpoint = f"/github/imports/{import_id}/configuration"
    assert client.post(config_endpoint, json=body).status_code == 403
    saved = client.post(config_endpoint, headers=headers, json=body).json()
    assert saved["status"] == "confirmed" and saved["runnable"] is False
    assert saved["configuration"]["tool_permissions"] == [{"tool": "requests", "approved": False}]
    body["approved_tools"] = ["requests"]
    saved = client.post(config_endpoint, headers=headers, json=body).json()
    assert saved["configuration"]["tool_permissions"] == [{"tool": "requests", "approved": True}]


def test_reinspection_invalidates_confirmation_and_stale_writes(imported_client):
    client, import_id, headers = imported_client
    endpoint = f"/github/imports/{import_id}/inspection"
    old = client.post(endpoint, headers=headers).json()
    newer = client.post(endpoint, headers=headers).json()
    assert newer["revision"] != old["revision"]
    assert client.post(f"/github/imports/{import_id}/configuration", headers=headers, json=configuration(old)).status_code == 409
    assert newer["configuration"] is None


def test_owner_scope_and_ready_status(imported_client):
    client, import_id, headers = imported_client
    endpoint = f"/github/imports/{import_id}/inspection"
    with client.app.app.state.database.connect() as db:
        db.execute("UPDATE repository_imports SET status='downloading' WHERE id=?", (import_id,))
    assert client.post(endpoint, headers=headers).status_code == 409
    client.post('/auth/register', json={"email": "other@example.com", "password": "long-test-password", "name": "Other"})
    other_csrf = client.get('/auth/me').json()["csrf_token"]
    assert client.get(endpoint).status_code == 404
    assert client.post(endpoint, headers={"X-CSRF-Token": other_csrf}).status_code == 404


def test_no_arbitrary_tool_approval_and_no_secret_echo(imported_client):
    client, import_id, headers = imported_client
    result = client.post(f"/github/imports/{import_id}/inspection", headers=headers).json()
    body = configuration(result)
    body["approved_tools"] = ["unknown_tool"]
    endpoint = f"/github/imports/{import_id}/configuration"
    assert client.post(endpoint, headers=headers, json=body).status_code == 422
    body["approved_tools"] = []
    body["model_id"] = 'sk-private-test-credential'
    response = client.post(endpoint, headers=headers, json=body)
    assert response.status_code == 422 and 'sk-private-test-credential' not in response.text


def test_deletion_removes_saved_findings(imported_client):
    client, import_id, headers = imported_client
    client.post(f"/github/imports/{import_id}/inspection", headers=headers)
    assert client.delete(f"/github/imports/{import_id}", headers=headers).status_code == 204
    assert client.get(f"/github/imports/{import_id}/inspection").status_code == 404
    with client.app.app.state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM repository_inspections").fetchone()[0] == 0


def test_model_picker_persists_and_mints_owner_scoped_fixed_key(imported_client):
    import time
    from backend.app.sessions import token_hash

    client, import_id, headers = imported_client
    state = client.app.app.state
    user_id = client.get('/auth/me').json()['user']['id']
    findings = client.post(f'/github/imports/{import_id}/inspection', headers=headers).json()
    assert findings['litellm_models'] == ['nova-micro', 'nova-lite', 'nova-pro', 'nova-2-lite',
                                        'claude-haiku', 'claude-sonnet-4.6', 'claude-opus-4.6']
    limits = dict(max_calls=10, max_spend_usd=1, expires_at=int(time.time()) + 60)
    with pytest.raises(HTTPException) as missing:
        state.gateway.mint_for_import(user_id, import_id, 'test', **limits)
    assert missing.value.status_code == 409
    body = {**configuration(findings), 'litellm_model': 'claude-sonnet-4.6'}
    endpoint = f'/github/imports/{import_id}/configuration'
    assert client.post(endpoint, json=body).status_code == 403
    saved = client.post(endpoint, json=body, headers=headers).json()
    assert saved['configuration']['model_id'] == 'gpt-4o'
    assert saved['configuration']['model_provider'] == 'openai'
    assert saved['configuration']['litellm_model'] == 'claude-sonnet-4.6'
    assert client.get(f'/github/imports/{import_id}/inspection').json()['configuration'] == saved['configuration']
    key = state.gateway.mint_for_import(user_id, import_id, 'test', **limits)
    assert state.gateway.prepare(key, {'model': 'gpt-4o', 'messages': []})[0] == 'claude-sonnet-4.6'
    body['litellm_model'] = 'nova-lite'
    changed = client.post(endpoint, json=body, headers=headers).json()
    assert changed['configuration_revision'] != saved['configuration_revision']
    assert state.gateway.prepare(key, {'model': 'gpt-4o', 'messages': []})[0] == 'claude-sonnet-4.6'
    with state.database.connect() as db:
        assert db.execute('SELECT litellm_model FROM gateway_keys WHERE key_hash=?', (token_hash(key),)).fetchone()[0] == 'claude-sonnet-4.6'
    with pytest.raises(HTTPException) as denied:
        state.gateway.mint_for_import('another-owner', import_id, 'test', **limits)
    assert denied.value.status_code == 404
    client.post(f'/github/imports/{import_id}/inspection', headers=headers)
    with pytest.raises(HTTPException) as reinspected:
        state.gateway.mint_for_import(user_id, import_id, 'test', **limits)
    assert reinspected.value.status_code == 409


@pytest.mark.parametrize('model', ['gpt-4o', 'https://custom-provider.test/v1', 'sk-private-test-credential'])
def test_model_picker_rejects_unlisted_models_without_echo(imported_client, model):
    client, import_id, headers = imported_client
    findings = client.post(f'/github/imports/{import_id}/inspection', headers=headers).json()
    response = client.post(f'/github/imports/{import_id}/configuration', headers=headers,
                           json={**configuration(findings), 'litellm_model': model})
    assert response.status_code == 422
    assert model not in response.text
