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
from backend.app.runner.service import egress_log
from backend.app.runner.egress import parse_target, public_address
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


def test_dependencies_accept_constraints_but_reject_urls_and_options(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("# comment\nhttpx==0.28.1\n")
    assert requirements(tmp_path, [path.name]) == ["httpx==0.28.1"]
    for invalid in ["-r elsewhere.txt", "--index-url https://private", "./package", "package @ https://x", "package==1 ; invalid_marker"]:
        path.write_text(invalid)
        with pytest.raises(ValueError):
            requirements(tmp_path, [path.name])
    path.write_text('openai>=1.33.0\nnumpy\nhttpx[http2]>=0.28; python_version >= "3.12"')
    assert len(requirements(tmp_path, [path.name])) == 3
    (tmp_path / "setup.cfg").write_text('[options]\ninstall_requires =\n    openai>=1.33.0\n    pydantic\n')
    assert requirements(tmp_path, ["setup.cfg"]) == ["openai>=1.33.0", "pydantic"]
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["httpx==0.28.1"]')
    assert requirements(tmp_path, ["pyproject.toml"]) == ["httpx==0.28.1"]


@pytest.mark.parametrize("constraint, accepted", [("3.12", True), (">=3.10", True),
    (">=3.12,<3.14", True), ("~=3.12", True), ("==3.12.*", True),
    ("<3.12", False), (">=3.13", False), ("!=3.12", False)])
def test_python_constraint_accepts_312(configured_runner, constraint, accepted):
    state, owner, imported = configured_runner
    with state.database.connect() as db:
        row = db.execute("SELECT configuration FROM repository_inspections WHERE import_id=?", (imported,)).fetchone()
        config = json.loads(row[0])
        config["python_version"] = constraint
        db.execute("UPDATE repository_inspections SET configuration=? WHERE import_id=?", (json.dumps(config), imported))
    if accepted:
        assert state.runner.configuration(owner, imported)["configuration"]["python_version"] == constraint
    else:
        with pytest.raises(HTTPException) as exc:
            state.runner.configuration(owner, imported)
        assert exc.value.status_code == 422


def test_resolver_has_no_source_secrets_or_build_backend_and_cleans_timeout(tmp_path, monkeypatch):
    from backend.app.runner.service import resolve_wheels
    (tmp_path / "wheels").mkdir()
    (tmp_path / "requirements.txt").write_text("httpx>=0.28")
    calls = []
    def fake(*args, **kwargs):
        calls.append(args)
        if args[0] == "start":
            raise RuntimeError("timeout")
        return ""
    monkeypatch.setattr("backend.app.runner.service.docker", fake)
    with pytest.raises(RuntimeError):
        resolve_wheels(tmp_path)
    create = calls[0]
    assert create[create.index("--network") + 1] == "bridge"
    assert "--only-binary=:all:" in create and "--isolated" in create and "-i" in create
    mounts = [create[i + 1] for i, arg in enumerate(create) if arg == "--mount"]
    assert len(mounts) == 2 and all("snapshot" not in mount for mount in mounts)
    assert not any("KEY=" in arg or "SECRET=" in arg for arg in create)
    assert calls[-1][:2] == ("rm", "--force")


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


@pytest.mark.skipif(os.getenv("RUNNER_DOCKER_TEST") != "1", reason="Requires Docker and public PyPI access.")
def test_real_binary_resolution_and_offline_install(configured_runner):
    state, owner, imported = configured_runner
    snapshot = state.github.source_path(owner, imported)
    (snapshot / "requirements.txt").write_text("httpx>=0.28,<1\n")
    (snapshot / "agent.py").write_text("import json,httpx; print(json.dumps({'version':httpx.__version__}))")
    findings = state.inspection.inspect(owner, imported)
    from backend.app.inspection.schemas import ConfirmInput
    body = configuration(findings)
    body.update(entrypoint="python agent.py", dependency_manifests=["requirements.txt"], litellm_model="claude-haiku")
    state.inspection.confirm(owner, imported, ConfirmInput(**body))
    build = state.runner.build(owner, imported)
    assert build["resolved_dependencies"] and all("==" in pin and "--hash=sha256:" in pin for pin in build["resolved_dependencies"])
    with state.database.connect() as db:
        assert json.loads(db.execute("SELECT resolved FROM runner_dependencies WHERE build_id=?", (build["build_id"],)).fetchone()[0]) == build["resolved_dependencies"]
    result = state.runner.run(owner, imported, build["build_id"], {}, max_calls=0)
    assert result["stop_reason"] == "completed" and result["output"]["version"]


@pytest.mark.parametrize("address, public", [
    ("93.184.216.34", True), ("1.1.1.1", True),
    ("169.254.169.254", False), ("10.0.0.1", False), ("172.17.0.1", False), ("192.168.1.1", False),
    ("127.0.0.1", False), ("100.64.0.1", False), ("0.0.0.0", False), ("224.0.0.1", False), ("not-an-address", False),
])
def test_egress_allows_only_public_addresses(address, public):
    assert public_address(address) is public


def test_egress_targets_are_bounded_to_web_ports_and_plain_hosts():
    assert parse_target("CONNECT", "api.example.com:443") == ("api.example.com", 443, None)
    assert parse_target("GET", "http://Example.com/a?b=1") == ("example.com", 80, "/a?b=1")
    assert parse_target("GET", "http://example.com") == ("example.com", 80, "/")
    for method, target in [("CONNECT", "example.com:22"), ("CONNECT", "example.com"), ("GET", "https://example.com/"),
                           ("GET", "http://user@example.com/"), ("GET", "http://example.com:8081/"),
                           ("CONNECT", "exa mple.com:443"), ("GET", "/relative"), ("CONNECT", "[::1]:443")]:
        with pytest.raises(ValueError):
            parse_target(method, target)


def test_egress_log_summarises_hosts_and_ignores_malformed_lines():
    lines = [json.dumps({"host": "api.example.com", "port": 443, "kind": "connect", "method": "CONNECT", "allowed": True,
                         "reason": None, "started_at": 1.0, "duration_ms": 120, "bytes_up": 10, "bytes_down": 900,
                         "unexpected": "dropped"}),
             json.dumps({"host": "api.example.com", "port": 443, "kind": "connect", "method": "CONNECT", "allowed": True,
                         "reason": None, "started_at": 2.0, "duration_ms": 80, "bytes_up": 10, "bytes_down": 100}),
             json.dumps({"host": "169.254.169.254", "port": 80, "kind": "http", "method": "GET", "allowed": False,
                         "reason": "Destination is not a public address.", "started_at": 3.0, "duration_ms": 0,
                         "bytes_up": 0, "bytes_down": 0}),
             "not json", json.dumps(["list"]), json.dumps({"allowed": "yes"})]
    summary = egress_log("\n".join(lines))
    assert summary["allowed"] == 2 and summary["denied"] == 1 and not summary["truncated"]
    assert summary["hosts"] == {"api.example.com": {"connections": 2, "duration_ms": 200, "bytes_down": 1000}}
    assert all("unexpected" not in record for record in summary["connections"])


def test_internet_flag_is_validated_before_docker(configured_runner):
    state, owner, imported = configured_runner
    with pytest.raises(ValueError):
        state.runner.run(owner, imported, "build", {}, internet="yes")


@pytest.mark.skipif(os.getenv("RUNNER_DOCKER_TEST") != "1", reason="Requires Docker and public internet access.")
def test_real_filtered_internet_reaches_public_web_only(configured_runner):
    state, owner, imported = configured_runner
    build = state.runner.build(owner, imported)
    result = state.runner.run(owner, imported, build["build_id"], {"mode": "internet"},
                              timeout_seconds=60, max_calls=0, internet=True)
    assert result["stop_reason"] == "completed" and result["cleanup_complete"]
    # The container still has no direct route anywhere; only the proxy path reaches the public web.
    assert all(result["output"]["isolation"].values())
    assert result["output"]["internet"] == {"https_public": 200, "http_public": 200, "metadata": 403,
                                            "private": 403, "docker_host": 403, "other_port": 403}
    assert result["isolation"]["internet"] == "filtered_proxy" and result["isolation"]["relay_network"] == "internal"
    assert result["egress"]["allowed"] == 2 and result["egress"]["denied"] == 4
    assert set(result["egress"]["hosts"]) == {"example.com"}
    # Without the flag the same task has no path out at all.
    offline = state.runner.run(owner, imported, build["build_id"], {"mode": "internet"}, timeout_seconds=60, max_calls=0)
    assert "egress" not in offline and offline["isolation"]["internet"] == "none"
    assert offline["output"]["internet"]["https_public"] != 200
    names = os.popen("docker ps -a --format '{{.Names}}'; docker network ls --format '{{.Name}}'").read()
    assert "ouro-egress-" not in names and "ouro-net-" not in names and "ouro-run-" not in names
