"""Trust-boundary tests; optional Docker cases execute only the sample agent."""
import json
import os
from pathlib import Path
import shutil
import zipfile
from contextlib import contextmanager

from fastapi import HTTPException
import pytest

from backend.app.config import Settings, ROOT
from backend.app.runner.service import command, copy_snapshot, requirements, limits, finite_float
from backend.tests.test_inspection import imported_client, configuration


@pytest.fixture
def configured_runner(imported_client):
    client, import_id, headers = imported_client
    state = client.app.app.state
    with state.database.connect() as db:
        owner = db.execute("SELECT user_id FROM repository_imports WHERE id=?", (import_id,)).fetchone()[0]
    snapshot = state.github.source_path(owner, import_id)
    shutil.rmtree(snapshot)
    shutil.copytree(ROOT / "examples/one_call", snapshot, ignore=shutil.ignore_patterns("__pycache__"))
    findings = state.inspection.inspect(owner, import_id)
    body = configuration(findings)
    body.update(entrypoint="python agent.py", dependency_manifests=["requirements.txt"], litellm_model="claude-haiku")
    assert client.post(f"/github/imports/{import_id}/configuration", headers=headers, json=body).status_code == 200
    return state, owner, import_id


def test_python_commands_are_shell_free():
    assert command("python agent.py") == ["/usr/local/bin/python", "-u", "-B", "agent.py"]
    assert command("python -m agent")[-2:] == ["-m", "agent"]
    assert "importlib" in command("agent:main")[-1]
    for invalid in ["python ../agent.py", "sh agent.py", "python agent.py;env", "python -c anything"]:
        with pytest.raises(ValueError):
            command(invalid)
    args = limits()
    assert args[args.index("--user") + 1] == "65532:65532"
    assert "ALL" in args and "no-new-privileges:true" in args and "none" in args
    assert finite_float("1.5") == 1.5
    with pytest.raises(ValueError):
        finite_float("1e999")


def test_snapshot_copy_rejects_links_secrets_special_files_and_caps(tmp_path):
    settings = Settings(database_path=tmp_path / "db", secret_key="test" * 10, import_extracted_bytes=10)
    source = tmp_path / "source"
    source.mkdir()
    (source / "agent.py").write_text("print(1)")
    digest = copy_snapshot(source, tmp_path / "copy", settings)
    assert len(digest) == 64 and (tmp_path / "copy/agent.py").read_text() == "print(1)"
    (source / ".env").write_text("secret")
    with pytest.raises(ValueError, match="credential"):
        copy_snapshot(source, tmp_path / "secrets", settings)
    (source / ".env").unlink()
    (source / "link").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="links"):
        copy_snapshot(source, tmp_path / "links", settings)
    (source / "link").unlink()
    os.mkfifo(source / "pipe")
    with pytest.raises(ValueError, match="special"):
        copy_snapshot(source, tmp_path / "fifo", settings)
    (source / "pipe").unlink()
    (source / "large").write_bytes(b"x" * 11)
    with pytest.raises(ValueError, match="limits"):
        copy_snapshot(source, tmp_path / "large", settings)


def test_dependencies_are_offline_exact_pins(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("# comment\nhttpx==0.28.1\n")
    assert requirements(tmp_path, [path.name]) == ["httpx==0.28.1"]
    for invalid in ["-r elsewhere.txt", "--index-url https://private", "package>=1", "./package", "package @ https://x", "package==1 ; marker"]:
        path.write_text(invalid)
        with pytest.raises(ValueError):
            requirements(tmp_path, [path.name])
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["httpx==0.28.1"]')
    assert requirements(tmp_path, ["pyproject.toml"]) == ["httpx==0.28.1"]


def test_owner_readiness_stale_build_and_limits_before_docker(configured_runner):
    state, owner, imported = configured_runner
    runner = state.runner
    with pytest.raises(HTTPException) as exc:
        runner.configuration("other-owner", imported)
    assert exc.value.status_code == 404
    for values in [{"timeout_seconds": float("nan")}, {"cpus": True}, {"memory_mb": 1}, {"pids": 0}]:
        with pytest.raises(ValueError):
            runner.run(owner, imported, "missing", {}, **values)
    with pytest.raises(HTTPException) as exc:
        runner.run(owner, imported, "missing", {})
    assert exc.value.status_code == 409
    with state.database.connect() as db:
        db.execute("UPDATE repository_imports SET status='downloading' WHERE id=?", (imported,))
    with pytest.raises(HTTPException) as exc:
        runner.configuration(owner, imported)
    assert exc.value.status_code == 409


def test_import_deletion_removes_run_content(configured_runner):
    state, owner, imported = configured_runner
    with state.database.connect() as db:
        db.execute("INSERT INTO runner_builds VALUES ('build',?,'sha','revision','digest','image',1)", (imported,))
        db.execute("INSERT INTO runner_runs VALUES ('run',?,'build','{}',1)", (imported,))
    state.github.delete_import(owner, imported)
    with state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM runner_runs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM runner_builds").fetchone()[0] == 0


def test_startup_failure_is_recorded_and_key_revoked(configured_runner, monkeypatch, tmp_path):
    state, owner, imported = configured_runner
    config, digest = state.runner.stage(owner, imported, tmp_path)
    with state.database.connect() as db:
        db.execute("INSERT INTO runner_builds VALUES ('build',?,?,?,?,?,1)",
                   (imported, config["commit_sha"], config["configuration_revision"], digest, "image"))

    @contextmanager
    def broker(*args):
        yield

    def fail(*args, **kwargs):
        raise RuntimeError("private error must not escape")

    monkeypatch.setattr("backend.app.runner.service.gateway_socket", broker)
    monkeypatch.setattr("backend.app.runner.service.docker", fail)
    result = state.runner.run(owner, imported, "build", {}, max_calls=0)
    assert result["stop_reason"] == "infrastructure_error" and result["cleanup_complete"]
    assert "private error" not in json.dumps(result)
    assert state.runner.get(owner, imported, result["run_id"]) == result
    with state.database.connect() as db:
        assert db.execute("SELECT revoked FROM gateway_keys").fetchone()[0] == 1


@pytest.mark.skipif(os.getenv("RUNNER_DOCKER_TEST") != "1", reason="Requires explicit local Docker test invocation.")
def test_real_docker_lifecycle_and_isolation(configured_runner):
    state, owner, imported = configured_runner
    runner = state.runner
    build = runner.build(owner, imported)
    for mode, reason, exit_code in [("isolation", "completed", 0), ("timeout", "timeout", 137),
                                    ("overflow", "output_limit", 137), ("invalid_json", "invalid_json", 0),
                                    ("exit", "exit_nonzero", 7)]:
        result = runner.run(owner, imported, build["build_id"], {"mode": mode},
                            timeout_seconds=1 if mode == "timeout" else 10, max_calls=0)
        assert result["stop_reason"] == reason and result["exit_code"] == exit_code
        assert not result["container_running"] and result["cleanup_complete"]
        assert result["gateway"]["calls"] == 0
        assert runner.get(owner, imported, result["run_id"]) == result
        if mode == "isolation":
            assert all(result["output"]["isolation"].values())
    with state.database.connect() as db:
        assert db.execute("SELECT count(*) FROM gateway_keys WHERE revoked=0").fetchone()[0] == 0
    # Source content must match the built digest, even if someone alters it without changing the SHA.
    snapshot = state.github.source_path(owner, imported)
    (snapshot / "agent.py").write_text("print('{}')")
    with pytest.raises(HTTPException) as exc:
        runner.run(owner, imported, build["build_id"], {})
    assert exc.value.status_code == 409
    # Synthetic wheel verifies real offline installation without executing package code on the host.
    (snapshot / "requirements.txt").write_text("runner_fixture_dep==1.0\n")
    (snapshot / "agent.py").write_text("import json,runner_fixture_dep; print(json.dumps({'dependency':runner_fixture_dep.VALUE}))")
    findings = state.inspection.inspect(owner, imported)
    from backend.app.inspection.schemas import ConfirmInput
    body = configuration(findings)
    body.update(entrypoint="python agent.py", dependency_manifests=["requirements.txt"], litellm_model="claude-haiku")
    state.inspection.confirm(owner, imported, ConfirmInput(**body))
    wheels = snapshot.parent / "reviewed-wheels"
    wheels.mkdir()
    with zipfile.ZipFile(wheels / "runner_fixture_dep-1.0-py3-none-any.whl", "w") as wheel:
        wheel.writestr("runner_fixture_dep.py", "VALUE = 'installed-offline'\n")
        wheel.writestr("runner_fixture_dep-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: runner-fixture-dep\nVersion: 1.0\n")
        wheel.writestr("runner_fixture_dep-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        wheel.writestr("runner_fixture_dep-1.0.dist-info/RECORD", "")
    dependency_build = runner.build(owner, imported, wheelhouse=wheels)
    result = runner.run(owner, imported, dependency_build["build_id"], {}, max_calls=0)
    assert result["output"] == {"dependency": "installed-offline"} and result["stop_reason"] == "completed"
