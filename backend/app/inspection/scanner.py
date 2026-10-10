"""Bounded static metadata detection. Repository text is never an instruction."""
import ast
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat
import time
import tomllib

MAX_ENTRIES, MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 4000, 200, 65536, 2097152
PROVIDERS = {"openai": "openai", "anthropic": "anthropic", "google.generativeai": "google",
             "google.genai": "google", "boto3": "aws_bedrock", "litellm": "litellm",
             "langchain_openai": "openai", "langchain_anthropic": "anthropic", "langchain_google_genai": "google"}
INTEGRATIONS = {"requests", "httpx", "sqlite3", "sqlalchemy", "playwright", "selenium",
                "duckduckgo_search", "tavily", "chromadb", "pinecone", "subprocess", "os.system",
                "mcp", "langchain.tools", "langchain_community.tools"}
MANIFESTS = {"pyproject.toml", "setup.cfg", "setup.py", "Pipfile", "environment.yml"}
LOCKFILES = {"uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock", "requirements.lock"}
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
SAFE_PATH = re.compile(r"[A-Za-z0-9_./-]{1,240}\Z")
VERSION = re.compile(r"(?:[<>=!~^]{0,2}\d+(?:\.\d+){0,2}(?:\.\*)?|\*)(?:\s*(?:,|\|\|)\s*(?:[<>=!~^]{0,2}\d+(?:\.\d+){0,2}(?:\.\*)?|\*))*\Z")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,100}\Z")
MODEL = re.compile(r"(?:gpt-|o[134](?:-|$)|claude-|gemini-|llama|mistral|deepseek|amazon\.|anthropic\.|meta\.)[A-Za-z0-9._:/-]{0,100}\Z", re.I)
SECRET = re.compile(r"(?:api.?key|password|secret|access.?token|private.?key|bearer|sk-[A-Za-z0-9]|gh[pousr]_)", re.I)


def safe_path(value):
    return bool(SAFE_PATH.fullmatch(value)) and not SECRET.search(value) and not PurePosixPath(value).is_absolute() and ".." not in PurePosixPath(value).parts


def entrypoint(value):
    valid = isinstance(value, str) and len(value) <= 180 and not SECRET.search(value) and bool(
        re.fullmatch(r"(?:[A-Za-z_][\w.]*:[A-Za-z_][\w.]*|python(?:3(?:\.\d+)?)? (?:-m [A-Za-z_][\w.]*|[A-Za-z0-9_./-]+\.py))", value)
    ) and ".." not in value.split()[-1].split("/")
    if valid and value.startswith("python") and " -m " not in value:
        return safe_path(value.split()[-1])
    return valid


def scan(root):
    result = {"findings": [], "warnings": [], "conflicts": [], "missing": [], "partial": False,
              "scanned_files": 0, "scanned_bytes": 0, "python_files": [], "runnable": False}
    deadline, entries, seen = time.monotonic() + 5, 0, set()

    def warning(code):
        if code not in result["warnings"]:
            result["warnings"].append(code)

    def add(kind, value, path, location, explicit=True):
        if len(result["findings"]) >= 500:
            result["partial"] = True
            warning("finding_limit")
            return
        if len(str(value)) > (80 if kind == "python_version" else 240) or SECRET.search(str(value)) or not safe_path(path):
            warning("sensitive_metadata_omitted")
            return
        item = {"kind": kind, "value": value, "source_file": path,
                "location": location, "confidence": "explicit" if explicit else "inferred"}
        signature = json.dumps(item, sort_keys=True)
        if signature not in seen:
            seen.add(signature)
            result["findings"].append({"id": hashlib.sha256(signature.encode()).hexdigest()[:20], **item})

    def scalar(key, value, path, location):
        provider = {"OPENAI_API_KEY": "openai", "ANTHROPIC_API_KEY": "anthropic", "GOOGLE_API_KEY": "google", "GEMINI_API_KEY": "google"}.get(key.upper())
        if provider:
            add("model_provider", provider, path, location, False)
        if not isinstance(value, str) or SECRET.search(key) or SECRET.search(value):
            return
        if key.lower() in {"model", "model_id", "model_name", "openai_model", "anthropic_model", "google_model"} and MODEL.fullmatch(value):
            add("model_id", value, path, location)
        if key.lower() in {"provider", "model_provider"} and value.lower() in set(PROVIDERS.values()):
            add("model_provider", value.lower(), path, location)

    def config(data, path):
        stack, visited = [(data, "")], 0
        while stack and visited < 1000:
            node, prefix = stack.pop()
            visited += 1
            if isinstance(node, dict):
                for key, value in node.items():
                    # Only known key names become output locations; raw keys may contain credentials.
                    if not isinstance(key, str) or not IDENTIFIER.fullmatch(key):
                        continue
                    if SECRET.search(key):
                        scalar(key, None, path, "credential key presence")
                        continue
                    location = "configuration key " + key if key.lower() in {"model", "model_id", "model_name", "openai_model", "anthropic_model", "google_model", "provider", "model_provider"} else "configuration"
                    scalar(key, value, path, location)
                    if key.lower() in {"tools", "tool_integrations"} and isinstance(value, list):
                        for integration in value[:100]:
                            if isinstance(integration, str) and integration in INTEGRATIONS:
                                add("tool", integration, path, "configuration tools")
                    if isinstance(value, (dict, list)):
                        stack.append((value, location))
            elif isinstance(node, list):
                stack.extend((value, prefix) for value in node[:100] if isinstance(value, (dict, list)))
        if stack:
            result["partial"] = True
            warning("config_node_limit")

    def inspect_file(path, text):
        name = PurePosixPath(path).name
        if name == ".python-version":
            for number, line in enumerate(text.splitlines(), 1):
                value = line.strip()
                if VERSION.fullmatch(value):
                    add("python_version", value, path, f"line {number}")
        if name == "pyproject.toml":
            try:
                data = tomllib.loads(text)
                project = data.get("project", {})
                value = project.get("requires-python")
                if isinstance(value, str) and VERSION.fullmatch(value):
                    add("python_version", value, path, "project.requires-python")
                poetry = data.get("tool", {}).get("poetry", {})
                value = poetry.get("dependencies", {}).get("python")
                if isinstance(value, str) and VERSION.fullmatch(value):
                    add("python_version", value, path, "tool.poetry.dependencies.python")
                for table, location in [(project.get("scripts", {}), "project.scripts"),
                                         (poetry.get("scripts", {}), "tool.poetry.scripts")]:
                    if isinstance(table, dict):
                        for value in table.values():
                            if entrypoint(value):
                                add("entrypoint", value, path, location)
                config(data, path)
            except (ValueError, TypeError, AttributeError, RecursionError):
                warning("invalid_pyproject")
        elif name.endswith((".json", ".toml")):
            try:
                config(json.loads(text) if name.endswith(".json") else tomllib.loads(text), path)
            except (ValueError, RecursionError):
                warning("invalid_config")
        if name.lower().startswith("readme"):
            for number, line in enumerate(text.splitlines(), 1):
                if SECRET.search(line):
                    continue
                for match in re.finditer(r"\bpython(?:3(?:\.\d+)?)?\s+(?:-m\s+[A-Za-z_][\w.]*|[A-Za-z0-9_./-]+\.py)", line):
                    value = " ".join(match.group().split())
                    if entrypoint(value):
                        add("entrypoint", value, path, f"line {number}", False)
        if path.endswith(".py"):
            try:
                tree = ast.parse(text)
                for count, node in enumerate(ast.walk(tree)):
                    if count >= 10000 or time.monotonic() > deadline:
                        result["partial"] = True
                        warning("ast_work_limit")
                        break
                    location = f"line {getattr(node, 'lineno', 1)}"
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                        if isinstance(node, ast.ImportFrom) and node.module:
                            modules.extend(node.module + "." + alias.name for alias in node.names)
                        for module in modules:
                            for prefix, provider in PROVIDERS.items():
                                if module == prefix or module.startswith(prefix + "."):
                                    add("model_provider", provider, path, location, False)
                            for integration in INTEGRATIONS:
                                if module == integration or module.startswith(integration + "."):
                                    add("tool", integration, path, location, False)
                    if isinstance(node, ast.keyword) and isinstance(node.value, ast.Constant):
                        scalar(node.arg or "", node.value.value, path, location)
                    if isinstance(node, ast.keyword) and node.arg == "functions" and isinstance(node.value, (ast.List, ast.Tuple)):
                        for tool in node.value.elts[:100]:
                            if isinstance(tool, ast.Name) and IDENTIFIER.fullmatch(tool.id):
                                add("tool", tool.id, path, location)
                    if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple)) and any(isinstance(t, ast.Name) and t.id == "tools" for t in node.targets):
                        for tool in node.value.elts[:100]:
                            if isinstance(tool, ast.Name) and IDENTIFIER.fullmatch(tool.id):
                                add("tool", tool.id, path, location)
                    if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Constant):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        for target in targets:
                            if isinstance(target, ast.Name):
                                scalar(target.id, node.value.value, path, location)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                        integration = node.func.value.id + "." + node.func.attr
                        if integration in INTEGRATIONS:
                            add("tool", integration, path, location, False)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for decorator in node.decorator_list:
                            target = decorator.func if isinstance(decorator, ast.Call) else decorator
                            if (isinstance(target, ast.Name) and target.id == "tool") or (isinstance(target, ast.Attribute) and target.attr == "tool"):
                                if IDENTIFIER.fullmatch(node.name):
                                    add("tool", node.name, path, location)
                    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
                        test = node.test
                        if isinstance(test.left, ast.Name) and test.left.id == "__name__" and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in test.comparators):
                            add("entrypoint", "python " + path, path, location, False)
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                warning("python_parse_failed")
        # Environment/configuration lines yield identifiers only, never arbitrary values or excerpts.
        if name in {".env.example", ".env.sample", "config.ini", "setup.cfg"} or name.endswith((".yaml", ".yml")):
            for number, line in enumerate(text.splitlines(), 1):
                match = re.match(r"\s*([A-Za-z_][\w]*)\s*[:=]\s*[\"']?([^\"'\s#]+)", line)
                if match:
                    scalar(match[1], match[2], path, f"line {number}")

    def walk(directory, prefix="", depth=0):
        nonlocal entries
        with os.scandir(directory) as iterator:
            for item in iterator:
                entries += 1
                if entries > MAX_ENTRIES or result["scanned_files"] >= MAX_FILES or time.monotonic() > deadline:
                    result["partial"] = True
                    warning("scan_work_limit")
                    return
                path = prefix + item.name
                if not safe_path(path):
                    warning("unsafe_filename_omitted")
                    continue
                if item.is_symlink():
                    warning("symlink_skipped")
                    continue
                if item.is_dir(follow_symlinks=False):
                    if item.name not in SKIP and not item.name.startswith("."):
                        if depth >= 12:
                            result["partial"] = True
                            warning("directory_depth_limit")
                            continue
                        child = os.open(item.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                        try:
                            walk(child, path + "/", depth + 1)
                        finally:
                            os.close(child)
                    continue
                name = item.name
                if name in MANIFESTS or re.fullmatch(r"requirements(?:[A-Za-z0-9_.-]*)\.(?:txt|in)", name):
                    add("dependency_manifest", path, path, "file")
                if name in LOCKFILES or re.fullmatch(r"requirements(?:[A-Za-z0-9_.-]*)\.lock", name):
                    add("lockfile", path, path, "file")
                if path.endswith(".py"):
                    result["python_files"].append(path)
                eligible = name in {".python-version", ".env.example", ".env.sample", "config.ini", "setup.cfg"} or name.lower().startswith("readme") or name.endswith((".py", ".json", ".toml", ".yaml", ".yml"))
                if name in LOCKFILES:
                    eligible = False
                if not eligible or name == ".env" or SECRET.search(name):
                    continue
                fd = os.open(item.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                try:
                    size = os.fstat(fd)
                    if not stat.S_ISREG(size.st_mode):
                        warning("special_file_skipped")
                        continue
                    if size.st_size > MAX_FILE_BYTES or result["scanned_bytes"] + size.st_size > MAX_TOTAL_BYTES:
                        result["partial"] = True
                        warning("scan_byte_limit")
                        continue
                    with os.fdopen(fd, "rb", closefd=False) as handle:
                        raw = handle.read(MAX_FILE_BYTES + 1)
                    result["scanned_files"] += 1
                    result["scanned_bytes"] += len(raw)
                    if len(raw) > MAX_FILE_BYTES or result["scanned_bytes"] > MAX_TOTAL_BYTES:
                        result["partial"] = True
                        warning("scan_byte_limit")
                        continue
                    try:
                        inspect_file(path, raw.decode("utf-8"))
                    except UnicodeDecodeError:
                        warning("non_utf8_file_skipped")
                finally:
                    os.close(fd)

    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(fd)
    finally:
        os.close(fd)
    for kind in ("python_version", "entrypoint", "dependency_manifest", "model_provider", "model_id"):
        values = sorted({item["value"] for item in result["findings"] if item["kind"] == kind})
        if not values:
            result["missing"].append(kind)
        elif len(values) > 1:
            result["conflicts"].append({"kind": kind, "values": values,
                "reason": "Multiple declarations require review; version ranges may be compatible."})
    return result
