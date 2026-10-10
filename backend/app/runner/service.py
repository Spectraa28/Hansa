"""No imported Python is loaded in this process. Docker is a trusted local service."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import tomllib
import uuid

from fastapi import FastAPI, HTTPException
import uvicorn

from ..contracts.schemas import bounded_data
from ..gateway.routes import router as gateway_router
from ..inspection.scanner import entrypoint
from ..sessions import token_hash


BASE_IMAGE = "python:3.12-slim"
HERE = Path(__file__).parent
MAX_OUTPUT = 1024 * 1024
STDERR_TAIL = 16384
PIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9.!+_-]*\Z")
RUN_LOCK = threading.Lock()


def docker(*arguments, timeout=30, input=None):
    try:
        result = subprocess.run(["docker", *arguments], input=input, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Docker is unavailable or the operation timed out.") from None
    if result.returncode:
        # Docker errors can contain container environment values; do not echo them.
        raise RuntimeError("Docker operation failed; check the local daemon and runner prerequisites.")
    return result.stdout.decode()


def copy_snapshot(source, destination, settings):
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Snapshot must be a real directory.")
    destination.mkdir()
    count, total, digest = 0, 0, hashlib.sha256()
    deadline = time.monotonic() + 30
    for root, dirs, files in os.walk(source, followlinks=False):
        dirs.sort()
        files.sort()
        for name in dirs + files:
            path = Path(root) / name
            relative = path.relative_to(source)
            if (name in {".git", ".aws", ".ssh", ".env"} or name.startswith(".env.")
                    or name.endswith((".pem", ".key"))):
                raise ValueError("Snapshot contains a credential/configuration path; remove it before execution.")
            if time.monotonic() > deadline:
                raise ValueError("Snapshot copy time limit exceeded.")
            info = path.lstat()
            target = destination / relative
            if stat.S_ISDIR(info.st_mode):
                target.mkdir()
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Snapshot links and special files are unsupported.")
            count += 1
            total += info.st_size
            if count > settings.import_file_count or total > settings.import_extracted_bytes:
                raise ValueError("Snapshot copy exceeds import limits.")
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("Snapshot changed while copying.")
                content = stream.read(info.st_size + 1)
            if len(content) != info.st_size:
                raise ValueError("Snapshot changed while copying.")
            target.write_bytes(content)
            target.chmod(0o444)
            digest.update(str(relative).encode() + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def requirements(snapshot, manifests):
    pins = []
    for name in manifests:
        path = snapshot / name
        if path.stat().st_size > 65536:
            raise ValueError("Dependency manifest exceeds 64 KiB.")
        if path.name == "requirements.txt":
            values = [line.strip() for line in path.read_text().splitlines()
                      if line.strip() and not line.lstrip().startswith("#")]
        elif path.name == "pyproject.toml":
            values = tomllib.loads(path.read_text()).get("project", {}).get("dependencies", [])
        else:
            raise ValueError("Use requirements.txt or pyproject.toml with exact package==version dependencies.")
        if not isinstance(values, list) or any(not isinstance(v, str) or not PIN.fullmatch(v) for v in values):
            raise ValueError("Offline builds require exact package==version dependencies without URLs/options.")
        pins.extend(values)
    if len(pins) > 200:
        raise ValueError("Too many dependencies.")
    return sorted(set(pins))


def command(value):
    if not entrypoint(value):
        raise ValueError("Invalid confirmed Python entrypoint.")
    if value.startswith("python"):
        parts = value.split()[1:]
        return ["/usr/local/bin/python", "-u", "-B", *parts]
    module, function = value.split(":")
    code = ("import importlib; f=importlib.import_module(" + repr(module) + "); "
            + "\nfor part in " + repr(function.split(".")) + ": f=getattr(f,part)\nf()")
    return ["/usr/local/bin/python", "-u", "-B", "-c", code]


@contextmanager
def gateway_socket(gateway, directory):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.gateway = gateway
    app.include_router(gateway_router)
    path = directory / "gateway.sock"
    server = uvicorn.Server(uvicorn.Config(app, uds=str(path), log_level="critical", access_log=False,
                                          lifespan="off", timeout_graceful_shutdown=70))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Gateway socket failed to start.")
            time.sleep(0.02)
        path.chmod(0o666)
        yield
    finally:
        server.should_exit = True
        thread.join(75)
        if thread.is_alive():
            raise RuntimeError("Gateway did not drain; model accounting may still be pending.")


def limits(memory=256, cpus=1.0, pids=64):
    return ["--read-only", "--user", "65532:65532", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--memory", f"{memory}m",
            "--memory-swap", f"{memory}m", "--cpus", str(cpus), "--pids-limit", str(pids),
            "--ulimit", "nofile=128:128", "--ulimit", "core=0:0", "--log-driver", "none"]


def kill(container):
    result = subprocess.run(["docker", "kill", container], capture_output=True, timeout=10)
    if result.returncode:
        state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
        if state["Running"]:
            raise RuntimeError("Container could not be killed.")


def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite output number.")
    return result


def collect(container, task, timeout):
    """Drain both pipes without unbounded buffering; kill the whole container on limits."""
    process = subprocess.Popen(["docker", "start", "--attach", "--interactive", container],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.monotonic()
    output, error = bytearray(), bytearray()
    reason, total = None, 0
    kill_thread, kill_errors = None, []

    def terminate():
        try:
            kill(container)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            kill_errors.append(type(exc).__name__)

    def send():
        try:
            process.stdin.write(task)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    writer = threading.Thread(target=send, daemon=True)
    writer.start()
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                elapsed = time.monotonic() - started
                if reason is None and elapsed >= timeout:
                    reason = "timeout"
                    kill_thread = threading.Thread(target=terminate, daemon=True)
                    kill_thread.start()
                for key, _ in selector.select(0.05):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if key.fileobj is process.stdout:
                        output.extend(chunk[:max(0, MAX_OUTPUT - len(output))])
                    else:
                        error.extend(chunk)
                        del error[:-STDERR_TAIL]
                    if reason is None and total > MAX_OUTPUT:
                        reason = "output_limit"
                        kill_thread = threading.Thread(target=terminate, daemon=True)
                        kill_thread.start()
                if reason is not None and time.monotonic() - started > timeout + 10:
                    raise RuntimeError("Container attachment failed to drain after termination.")
        process.wait(timeout=10)
        if kill_thread:
            kill_thread.join(12)
            if kill_thread.is_alive() or kill_errors:
                raise RuntimeError("Container termination failed.")
        state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
        if state["Running"]:
            raise RuntimeError("Container is still running after attachment closed.")
        if reason is None:
            reason = "oom" if state["OOMKilled"] else "completed" if state["ExitCode"] == 0 else "exit_nonzero"
        value = None
        try:
            value = json.loads(output.decode("utf-8"), parse_float=finite_float,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, RecursionError):
            if reason == "completed":
                reason = "invalid_json"
        return {"exit_code": state["ExitCode"], "output": value,
                "stderr_tail": error.decode("utf-8", errors="replace"),
                "wall_time_seconds": round(time.monotonic() - started, 6), "stop_reason": reason,
                "output_bytes": total, "container_running": state["Running"]}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
            process.stdout.close()
            process.stderr.close()
            docker("rm", "--force", container)
        writer.join(1)
        for stream in (process.stdout, process.stderr, process.stdin):
            stream.close()


class RunnerService:
    def __init__(self, settings, database, inspection, gateway):
        self.settings, self.database = settings, database
        self.inspection, self.gateway = inspection, gateway

    def configuration(self, user_id, import_id):
        result = self.inspection.get(user_id, import_id)
        config = result["configuration"]
        if result["status"] != "confirmed" or not config or not config.get("litellm_model"):
            raise HTTPException(409, "Confirm configuration and a LiteLLM model before building/running.")
        if config.get("python_version") != "3.12":
            raise HTTPException(422, "This runner supports confirmed Python 3.12 only.")
        command(config["entrypoint"])
        return result

    def stage(self, user_id, import_id, directory):
        with self.inspection.github.lock:
            config = self.configuration(user_id, import_id)
            with self.database.connect() as db:
                row = self.inspection.ready(db, user_id, import_id)
                expected = self.inspection.github.source_path(user_id, import_id)
                if row["snapshot_path"] != str(expected):
                    raise HTTPException(409, "Import snapshot location is inconsistent.")
            digest = copy_snapshot(expected, directory / "snapshot", self.settings)
        return config, digest

    def build(self, user_id, import_id, *, wheelhouse=None):
        with RUN_LOCK, tempfile.TemporaryDirectory(prefix="ouro-build-") as temporary:
            root = Path(temporary)
            config, digest = self.stage(user_id, import_id, root)
            pins = requirements(root / "snapshot", config["configuration"]["dependency_manifests"])
            context = root / "context"
            context.mkdir()
            wheels = context / "wheels"
            wheels.mkdir()
            if pins and wheelhouse is None:
                raise ValueError("Provide a reviewed wheelhouse containing all pinned dependencies and transitive wheels.")
            if wheelhouse is not None:
                wheelhouse = Path(wheelhouse)
                total = 0
                for path in wheelhouse.iterdir():
                    if path.is_symlink() or not path.is_file() or path.suffix != ".whl":
                        raise ValueError("Wheelhouse may contain only regular .whl files.")
                    total += path.stat().st_size
                    if total > 500 * 1024 * 1024:
                        raise ValueError("Wheelhouse exceeds 500 MiB.")
                    shutil.copyfile(path, wheels / path.name)
            (context / "requirements.txt").write_text("\n".join(pins) + "\n")
            # Only a trusted generated Dockerfile enters the build; no repository Dockerfile or source.
            base = json.loads(docker("image", "inspect", BASE_IMAGE))[0]["Id"]
            (context / "Dockerfile").write_text(f"FROM {base}\nCOPY wheels /wheels\nCOPY requirements.txt /requirements.txt\n"
                "RUN python -m pip --isolated install --no-index --find-links=/wheels --only-binary=:all: "
                "--no-compile --target=/opt/deps -r /requirements.txt && rm -rf /wheels /requirements.txt\n"
                "USER 65532:65532\n")
            build_id = uuid.uuid4().hex
            docker("build", "--network", "none", "--no-cache", "--tag", "ouro-deps:" + build_id,
                   str(context), timeout=300)
            image = json.loads(docker("image", "inspect", "ouro-deps:" + build_id))[0]["Id"]
            with self.inspection.github.lock, self.database.connect() as db:
                current = self.configuration(user_id, import_id)
                if current["configuration_revision"] != config["configuration_revision"]:
                    raise HTTPException(409, "Configuration changed during build.")
                db.execute("INSERT INTO runner_builds VALUES (?,?,?,?,?,?,?)", (build_id, import_id,
                    config["commit_sha"], config["configuration_revision"], digest, image, int(time.time())))
            return {"build_id": build_id, "image_id": image, "snapshot_digest": digest, "dependencies": pins}

    def run(self, user_id, import_id, build_id, task, *, timeout_seconds=60, max_calls=10,
            max_spend_usd=0.01, memory_mb=256, cpus=1.0, pids=64):
        bounded_data(task, 16384)
        if (type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or not 0.1 <= timeout_seconds <= 300
                or type(memory_mb) is not int or not 64 <= memory_mb <= 4096
                or type(cpus) not in {int, float} or not math.isfinite(cpus) or not 0.1 <= cpus <= 4
                or type(pids) is not int or not 8 <= pids <= 256):
            raise ValueError("Invalid runner resource limits.")
        with RUN_LOCK, tempfile.TemporaryDirectory(prefix="ouro-run-") as temporary:
            root = Path(temporary)
            config, digest = self.stage(user_id, import_id, root)
            with self.database.connect() as db:
                build = db.execute("SELECT * FROM runner_builds WHERE id=? AND import_id=?", (build_id, import_id)).fetchone()
            if (not build or build["commit_sha"] != config["commit_sha"]
                    or build["configuration_revision"] != config["configuration_revision"]
                    or build["snapshot_digest"] != digest):
                raise HTTPException(409, "Build is absent or stale. Build this confirmed snapshot again.")
            run_id = uuid.uuid4().hex
            relay, container = "ouro-relay-" + run_id, "ouro-run-" + run_id
            with self.inspection.github.lock:
                current = self.configuration(user_id, import_id)
                if current["configuration_revision"] != config["configuration_revision"]:
                    raise HTTPException(409, "Configuration changed before execution.")
                key = self.gateway.mint_for_import(user_id, import_id, run_id, max_calls=max_calls,
                    max_spend_usd=max_spend_usd, expires_at=int(time.time()) + math.ceil(timeout_seconds) + 90)
            broker = root / "broker"
            broker.mkdir(mode=0o755)
            relay_created, created = False, False
            began = time.monotonic()
            try:
                with gateway_socket(self.gateway, broker):
                    docker("create", "--name", relay, "--network", "none", *limits(64, 0.5, 32),
                           "--mount", f"type=bind,src={broker},dst=/broker,readonly",
                           "--mount", f"type=bind,src={HERE / 'relay.py'},dst=/relay.py,readonly",
                           "--entrypoint", "/usr/local/bin/python", BASE_IMAGE, "-I", "-B", "/relay.py")
                    relay_created = True
                    docker("start", relay)
                    docker("exec", relay, "/usr/local/bin/python", "-c",
                           "import socket,time\nfor _ in range(100):\n try:\n  s=socket.create_connection(('127.0.0.1',8000),.1); s.close(); break\n except OSError: time.sleep(.02)\nelse: raise RuntimeError('relay unavailable')")
                    docker("create", "--name", container, "--interactive", "--network", "container:" + relay,
                           *limits(memory_mb, cpus, pids), "--workdir", "/snapshot",
                           "--tmpfs", "/scratch:rw,noexec,nosuid,nodev,size=64m,mode=1777",
                           "--mount", f"type=bind,src={root / 'snapshot'},dst=/snapshot,readonly",
                           "--entrypoint", "/usr/bin/env", build["image_id"], "-i",
                           "PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/scratch", "TMPDIR=/scratch", "LANG=C.UTF-8",
                           "PYTHONPATH=/snapshot:/snapshot/src:/opt/deps",
                           "OPENAI_BASE_URL=http://127.0.0.1:8000/gateway/v1", "OPENAI_API_KEY=" + key,
                           *command(config["configuration"]["entrypoint"]))
                    created = True
                    result = collect(container, json.dumps(task, allow_nan=False).encode() + b"\n", timeout_seconds)
                    state = json.loads(docker("inspect", container))[0]
                    result["isolation"] = {"network": state["HostConfig"]["NetworkMode"],
                        "user": state["Config"]["User"], "read_only_root": state["HostConfig"]["ReadonlyRootfs"],
                        "memory_bytes": state["HostConfig"]["Memory"], "nano_cpus": state["HostConfig"]["NanoCpus"],
                        "pids_limit": state["HostConfig"]["PidsLimit"], "relay_network": "none"}
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                result = {"exit_code": None, "output": None, "stderr_tail": "",
                          "wall_time_seconds": round(time.monotonic() - began, 6),
                          "stop_reason": "infrastructure_error", "container_running": None}
            finally:
                with self.database.connect() as db:
                    db.execute("UPDATE gateway_keys SET revoked=1 WHERE key_hash=?", (token_hash(key),))
                try:
                    if created:
                        docker("rm", "--force", container)
                finally:
                    if relay_created:
                        docker("rm", "--force", relay)
            # Remove scoped credentials even if the untrusted program echoes its environment.
            encoded = json.dumps(result, ensure_ascii=True)
            for secret in (key, self.settings.litellm_api_key):
                if secret:
                    encoded = encoded.replace(secret, "[redacted]")
            result = json.loads(encoded)
            result.update({"run_id": run_id, "import_id": import_id, "commit_sha": config["commit_sha"],
                           "configuration_revision": config["configuration_revision"], "build_id": build_id,
                           "gateway": self.gateway.summarize_key(key), "cleanup_complete": True})
            with self.inspection.github.lock, self.database.connect() as db:
                self.inspection.ready(db, user_id, import_id)
                db.execute("INSERT INTO runner_runs VALUES (?,?,?,?,?)", (run_id, import_id, build_id,
                           json.dumps(result, allow_nan=False), int(time.time())))
            return result

    def get(self, user_id, import_id, run_id):
        with self.database.connect() as db:
            self.inspection.ready(db, user_id, import_id)
            row = db.execute("SELECT result FROM runner_runs WHERE id=? AND import_id=?", (run_id, import_id)).fetchone()
        if not row:
            raise HTTPException(404, "Run not found.")
        return json.loads(row["result"])
