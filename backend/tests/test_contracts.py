import json

import pytest
from pydantic import ValidationError

from app.contracts.schemas import ContractInput
from tests.test_inspection import imported_client, configuration


def human(description="Preserve the declared behavior."):
    return {"description": description, "verification": "human_review", "review_guidance": "Compare the response to the task facts and requirements."}


def content(revision, base=None):
    return {"base_version": base, "configuration_revision": revision,
            "tasks": [{"name": "Missing order number", "description": "Ask for the missing order number.",
                       "input": {"message": "Where is my order?", "order_id": None},
                       "expected_output": {"status": "needs_information"}, "case_kind": "ordinary",
                       "required_fields": [{"pointer": "/status", "field_type": "string", "check_exact": True, "exact_value": "needs_information"}],
                       "required_facts": [human("Do not invent order facts.")], "required_evidence": []}],
            "acceptable_failures": {key: human() for key in ["missing_information", "denied_access", "tool_failure"]},
            "protected_behavior": {key: human() for key in ["instructions", "permissions", "freshness", "essential_information"]},
            "limits": {"max_runtime_seconds": 60, "max_model_calls": 10, "max_tool_calls": 20, "max_tokens": 10000, "max_spend_usd": 1.0}}


@pytest.fixture
def confirmed_client(imported_client):
    client, import_id, headers = imported_client
    findings = client.post(f"/github/imports/{import_id}/inspection", headers=headers).json()
    config = client.post(f"/github/imports/{import_id}/configuration", headers=headers, json=configuration(findings)).json()
    return client, import_id, headers, config


def test_explicit_limits_and_data_types():
    valid = content("a" * 32)
    assert ContractInput.model_validate(valid).limits.max_tokens == 10000
    for value in [None, -1, True, "10", 1000001]:
        invalid = content("a" * 32)
        invalid["limits"]["max_tokens"] = value
        with pytest.raises(ValidationError):
            ContractInput.model_validate(invalid)
    for value in [float("nan"), float("inf"), -1, 101]:
        invalid = content("a" * 32)
        invalid["limits"]["max_spend_usd"] = value
        with pytest.raises(ValidationError):
            ContractInput.model_validate(invalid)


def test_case_labels_exact_types_and_depth():
    invalid = content("a" * 32)
    invalid["tasks"][0]["case_kind"] = "injected_failure"
    with pytest.raises(ValidationError):
        ContractInput.model_validate(invalid)
    invalid["tasks"][0]["injection_description"] = "An injected timeout in the order lookup tool."
    ContractInput.model_validate(invalid)
    invalid["tasks"][0]["required_fields"][0]["field_type"] = "integer"
    with pytest.raises(ValidationError):
        ContractInput.model_validate(invalid)
    deep = {}
    for _ in range(14):
        deep = {"nested": deep}
    invalid = content("a" * 32)
    invalid["tasks"][0]["input"] = deep
    with pytest.raises(ValidationError):
        ContractInput.model_validate(invalid)


def test_history_is_preserved_and_confirmation_does_not_start_execution(confirmed_client):
    client, import_id, headers, config = confirmed_client
    endpoint = f"/github/imports/{import_id}/contract"
    body = content(config["configuration_revision"])
    assert client.post(endpoint, json=body).status_code == 403
    response = client.post(endpoint, headers=headers, json=body)
    assert response.status_code == 201
    first = response.json()
    assert first["version"] == 1 and first["can_confirm"]
    confirmed = client.post(endpoint + "/confirm", headers=headers, json={"version": 1, "configuration_revision": config["configuration_revision"]}).json()
    assert confirmed["status"] == "confirmed" and not confirmed["runnable"] and not confirmed["limits_enforced"]
    body["base_version"] = 1
    body["tasks"][0]["description"] = "Updated development task description."
    second = client.post(endpoint, headers=headers, json=body).json()
    assert second["version"] == 2 and second["status"] == "draft"
    history = client.get(endpoint + "?version=1").json()
    assert history["status"] == "confirmed" and history["contract"]["tasks"][0]["description"] != body["tasks"][0]["description"]
    assert client.post(endpoint, headers=headers, json=body).status_code == 409
    assert len(client.get(endpoint + "/versions").json()["versions"]) == 2
    third = client.post(endpoint, headers=headers, json=content(config["configuration_revision"], 2)).json()
    assert third["version"] == 3
    assert not client.get(endpoint + "?version=2").json()["can_confirm"]


def test_configuration_changes_make_contract_stale_and_require_new_version(confirmed_client):
    client, import_id, headers, config = confirmed_client
    endpoint = f"/github/imports/{import_id}/contract"
    client.post(endpoint, headers=headers, json=content(config["configuration_revision"]))
    client.post(endpoint + "/confirm", headers=headers, json={"version": 1, "configuration_revision": config["configuration_revision"]})
    updated = configuration(config)
    updated["approved_tools"] = ["requests"]
    newer = client.post(f"/github/imports/{import_id}/configuration", headers=headers, json=updated).json()
    assert newer["configuration_revision"] != config["configuration_revision"]
    assert client.get(endpoint).json()["stale"]
    assert client.post(endpoint + "/confirm", headers=headers, json={"version": 1, "configuration_revision": newer["configuration_revision"]}).status_code == 409
    latest = client.post(endpoint, headers=headers, json=content(newer["configuration_revision"], 1)).json()
    assert latest["version"] == 2 and not latest["stale"]
    confirmed = client.post(endpoint + "/confirm", headers=headers, json={"version": 2, "configuration_revision": newer["configuration_revision"]}).json()
    assert confirmed["status"] == "confirmed"
    assert client.get(endpoint + "?version=1").json()["stale"]
    repeated = client.post(f"/github/imports/{import_id}/configuration", headers=headers, json=updated).json()
    assert repeated["configuration_revision"] == newer["configuration_revision"]
    assert not client.get(endpoint).json()["stale"]


def test_incomplete_contract_has_missing_requirements_and_cannot_confirm(confirmed_client):
    client, import_id, headers, config = confirmed_client
    endpoint = f"/github/imports/{import_id}/contract"
    body = {"configuration_revision": config["configuration_revision"]}
    saved = client.post(endpoint, headers=headers, json=body).json()
    assert saved["missing_requirements"] and not saved["can_confirm"]
    assert client.post(endpoint + "/confirm", headers=headers, json={"version": 1, "configuration_revision": config["configuration_revision"]}).status_code == 422


def test_owner_scope_configuration_requirement_and_deletion(confirmed_client):
    client, import_id, headers, config = confirmed_client
    endpoint = f"/github/imports/{import_id}/contract"
    client.post(endpoint, headers=headers, json=content(config["configuration_revision"]))
    client.post('/auth/register', json={"email": "other@example.com", "password": "long-test-password", "name": "Other"})
    other_headers = {"X-CSRF-Token": client.get('/auth/me').json()["csrf_token"]}
    assert client.get(endpoint).status_code == 404
    assert client.get(endpoint + "/versions").status_code == 404
    assert client.post(endpoint, headers=other_headers, json=content(config["configuration_revision"])).status_code == 404
    login = client.post('/auth/login', json={"email": "owner@example.com", "password": "long-test-password"}).json()
    headers = {"X-CSRF-Token": login["csrf_token"]}
    assert client.delete(f"/github/imports/{import_id}", headers=headers).status_code == 204
    with client.app.app.state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM task_contracts").fetchone()[0] == 0
    assert client.get(endpoint).status_code == 404


def test_secrets_commands_labels_and_oversized_requests_are_rejected_without_echo(confirmed_client):
    client, import_id, headers, config = confirmed_client
    endpoint = f"/github/imports/{import_id}/contract"
    for key, value in [("api_key", "private-credential"), ("message", "sk-" + "a" * 40),
                       ("command", "echo hello"), ("evaluator_code", "def evaluate(): pass"), ("protected_labels", ["secret answers"])]:
        body = content(config["configuration_revision"])
        body["tasks"][0]["input"] = {key: value}
        response = client.post(endpoint, headers=headers, json=body)
        assert response.status_code == 422 and str(value) not in response.text
    response = client.post(endpoint, headers=headers, content=b" " * 131073)
    assert response.status_code == 413


def test_reinspection_invalidates_configuration_and_contract(confirmed_client):
    client, import_id, headers, config = confirmed_client
    endpoint = f"/github/imports/{import_id}/contract"
    client.post(endpoint, headers=headers, json=content(config["configuration_revision"]))
    client.post(f"/github/imports/{import_id}/inspection", headers=headers)
    assert client.get(endpoint).json()["stale"]
    assert client.post(endpoint, headers=headers, json=content(config["configuration_revision"], 1)).status_code == 409


def test_contract_requires_confirmed_configuration_and_confirmation_csrf(imported_client):
    client, import_id, headers = imported_client
    endpoint = f"/github/imports/{import_id}/contract"
    assert client.post(endpoint, headers=headers, json=content("a" * 32)).status_code == 409
    inspected = client.post(f"/github/imports/{import_id}/inspection", headers=headers).json()
    config = client.post(f"/github/imports/{import_id}/configuration", headers=headers, json=configuration(inspected)).json()
    client.post(endpoint, headers=headers, json=content(config["configuration_revision"]))
    assert client.post(endpoint + "/confirm", json={"version": 1, "configuration_revision": config["configuration_revision"]}).status_code == 403


def test_json_values_are_preserved_and_task_counts_and_json_sizes_are_bounded():
    body = content("a" * 32)
    body["tasks"][0]["input"] = {"message": "  preserve whitespace  ", "code": 403}
    assert ContractInput.model_validate(body).tasks[0].input == body["tasks"][0]["input"]
    body["tasks"] = [{**body["tasks"][0], "name": f"Task {i}"} for i in range(21)]
    with pytest.raises(ValidationError):
        ContractInput.model_validate(body)
    body = content("a" * 32)
    body["tasks"][0]["input"] = {str(i): "x" * 3000 for i in range(6)}
    with pytest.raises(ValidationError):
        ContractInput.model_validate(body)


def test_legacy_confirmed_configuration_gets_stable_revision_on_upgrade(confirmed_client):
    client, import_id, headers, config = confirmed_client
    database = client.app.app.state.database
    with database.connect() as db:
        db.execute("ALTER TABLE repository_inspections DROP COLUMN configuration_revision")
    database.initialize()
    upgraded = client.get(f"/github/imports/{import_id}/inspection").json()
    assert upgraded["status"] == "confirmed" and len(upgraded["configuration_revision"]) == 32
    database.initialize()
    assert client.get(f"/github/imports/{import_id}/inspection").json()["configuration_revision"] == upgraded["configuration_revision"]


def test_model_selection_change_makes_saved_contract_stale(confirmed_client):
    client, import_id, headers, config = confirmed_client
    endpoint = f'/github/imports/{import_id}/contract'
    assert client.post(endpoint, headers=headers, json=content(config['configuration_revision'])).status_code == 201
    updated = {**configuration(config), 'litellm_model': 'nova-pro'}
    saved = client.post(f'/github/imports/{import_id}/configuration', headers=headers, json=updated).json()
    assert saved['configuration_revision'] != config['configuration_revision']
    assert client.get(endpoint).json()['stale']
    repeated = client.post(f'/github/imports/{import_id}/configuration', headers=headers, json=updated).json()
    assert repeated['configuration_revision'] == saved['configuration_revision']
