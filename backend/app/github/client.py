import base64
import json
import re
import time
from urllib.parse import quote, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import httpx


SUPPORTED_ENDPOINTS = {
    "GET": re.compile(r"/(?:app|user|user/installations|user/installations/[1-9][0-9]*/repositories|"
                      r"repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:branches(?:/[^/]+)?|commits/[0-9a-f]{40}|git/trees/[0-9a-f]{40}))"),
    "POST": re.compile(r"/(?:login/oauth/access_token|app/installations/[1-9][0-9]*/access_tokens)"),
}


class GitHubFailure(Exception):
    def __init__(self, code: str, reason: str, status: int = 400, retry_after: int | None = None):
        super().__init__(reason)
        self.code, self.reason, self.status, self.retry_after = code, reason, status, retry_after


def check_response(response):
    if response.status_code < 300:
        return
    if response.status_code == 429 or (response.status_code == 403 and (
        response.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in response.headers
    )):
        try:
            retry = int(response.headers.get("retry-after", "0")) or max(
                1, int(response.headers.get("x-ratelimit-reset", "0")) - int(time.time()))
        except ValueError:
            retry = 60
        raise GitHubFailure("rate_limited", "GitHub rate limit reached. Retry later.", 429, max(1, retry))
    if response.status_code == 401:
        raise GitHubFailure("authorization_expired", "GitHub authorization expired or was revoked. Reconnect GitHub.", 401)
    if response.status_code in {403, 404}:
        raise GitHubFailure("access_denied", "Repository access denied or unavailable. Check selected repositories, organization approval, and installation status.", 403)
    if response.status_code == 409:
        raise GitHubFailure("empty_repository", "The repository has no commits to import.", 409)
    raise GitHubFailure("github_unavailable", "GitHub could not complete the request. Try again.", 502)


def repository_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) or any(
        part in {".", ".."} for part in value.split("/")
    ):
        raise GitHubFailure("invalid_repository", "GitHub returned an invalid repository name.", 502)
    return value


def branch_name(value: str) -> str:
    if (not value or len(value) > 255 or value == "@" or value.startswith(("/", "-"))
        or value.endswith(("/", ".")) or ".." in value or "@{" in value
        or any(ord(c) <= 32 or ord(c) == 127 or c in '~^:?*[\\' for c in value)
        or any(not part or part.startswith(".") or part.endswith(".lock") for part in value.split("/"))):
        raise GitHubFailure("invalid_branch", "Select a valid Git branch name.")
    return value


def commit_sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise GitHubFailure("invalid_commit", "GitHub returned an invalid commit SHA.", 502)
    return value


def archive_redirect(location: str, name: str, sha: str) -> str:
    parsed = urlsplit(location)
    expected = f"/{repository_name(name)}/legacy.tar.gz/{commit_sha(sha)}"
    if (parsed.scheme != "https" or parsed.netloc != "codeload.github.com"
        or parsed.username or parsed.password or parsed.fragment or parsed.path != expected):
        raise GitHubFailure("unsafe_redirect", "GitHub returned an unsupported archive redirect.", 502)
    return location


class GitHubAPI:
    def __init__(self, seconds: int = 120):
        self.deadline = time.monotonic() + seconds
        self.client = httpx.Client(follow_redirects=False, trust_env=False, timeout=15)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def check_time(self):
        if time.monotonic() >= self.deadline:
            raise GitHubFailure("timeout", "GitHub import exceeded its time limit.", 504)

    def headers(self, token: str) -> dict:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10",
                   "Accept-Encoding": "identity"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def request(self, method: str, path: str, token: str = "", *, data=None, body=None, params=None):
        # Callers construct paths; never follow API pagination URLs or browser-supplied URLs.
        if method not in SUPPORTED_ENDPOINTS or not SUPPORTED_ENDPOINTS[method].fullmatch(path):
            raise GitHubFailure("invalid_endpoint", "Unsupported GitHub endpoint.")
        url = "https://github.com/login/oauth/access_token" if path == "/login/oauth/access_token" else f"https://api.github.com{path}"
        self.check_time()
        headers = self.headers(token)
        if path == "/login/oauth/access_token":
            headers["Accept"] = "application/json"
        try:
            with self.client.stream(method, url, headers=headers, data=data, json=body, params=params,
                                    timeout=min(15, max(0.1, self.deadline - time.monotonic()))) as response:
                check_response(response)
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise GitHubFailure("invalid_response", "Unsupported GitHub response encoding.", 502)
                raw = bytearray()
                for chunk in response.iter_raw():
                    self.check_time()
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise GitHubFailure("response_too_large", "GitHub API response exceeded its limit.", 502)
                result = json.loads(raw)
                expects_list = method == "GET" and bool(re.fullmatch(r"/repos/[^/]+/[^/]+/branches", path))
                if not isinstance(result, list if expects_list else dict):
                    raise ValueError
                if expects_list and not all(isinstance(item, dict) for item in result):
                    raise ValueError
                if path == "/login/oauth/access_token" and result.get("error"):
                    raise GitHubFailure("authorization_expired", "GitHub denied or expired authorization. Reconnect GitHub.", 401)
                self.has_next = "next" in response.links
                return result
        except httpx.HTTPError:
            raise GitHubFailure("github_unavailable", "GitHub request failed or timed out. Try again.", 502) from None
        except (ValueError, TypeError):
            raise GitHubFailure("invalid_response", "GitHub returned an invalid response.", 502) from None

    def pages(self, path: str, token: str, key: str):
        for page in range(1, 101):
            result = self.request("GET", path, token, params={"page": page, "per_page": 100})
            items = result.get(key)
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise GitHubFailure("invalid_response", "GitHub returned an invalid access listing.", 502)
            yield from items
            if len(items) < 100:
                return
        raise GitHubFailure("listing_limit", "Too many GitHub results. Narrow the App's selected repositories.", 413)

    def installation_token(self, jwt: str, installation_id: int, repository_id: int) -> str:
        result = self.request("POST", f"/app/installations/{installation_id}/access_tokens", jwt,
                              body={"repository_ids": [repository_id],
                                    "permissions": {"contents": "read", "metadata": "read"}})
        return result["token"]

    def branch(self, token: str, name: str, branch: str) -> str:
        try:
            result = self.request("GET", f"/repos/{repository_name(name)}/branches/{quote(branch_name(branch), safe='')}", token)
        except GitHubFailure as exc:
            if exc.code == "access_denied":
                raise GitHubFailure("branch_unavailable", "Selected branch is unavailable or repository access was removed.", 409) from None
            raise
        return commit_sha(result["commit"]["sha"])

    def download(self, token: str, name: str, sha: str, destination, limit: int, check_active):
        try:
            url = f"https://api.github.com/repos/{repository_name(name)}/tarball/{commit_sha(sha)}"
            self.check_time()
            with self.client.stream("GET", url, headers=self.headers(token),
                                    timeout=min(15, max(0.1, self.deadline - time.monotonic()))) as response:
                if response.status_code != 302:
                    check_response(response)
                    raise GitHubFailure("invalid_archive", "GitHub did not return an archive redirect.", 502)
                location = archive_redirect(response.headers.get("location", ""), name, sha)
            self.check_time()
            # The signed redirect provides access. Never forward the bearer token to codeload.
            with self.client.stream("GET", location, headers={"Accept-Encoding": "identity"},
                                    timeout=min(15, max(0.1, self.deadline - time.monotonic()))) as response:
                check_response(response)
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise GitHubFailure("invalid_archive", "Unsupported archive transport encoding.", 502)
                declared = response.headers.get("content-length")
                if declared and int(declared) > limit:
                    raise GitHubFailure("download_limit", "Repository archive exceeds the download size limit.", 413)
                count = 0
                with destination.open("xb") as output:
                    destination.chmod(0o600)
                    for chunk in response.iter_raw():
                        self.check_time()
                        check_active()
                        count += len(chunk)
                        if count > limit:
                            raise GitHubFailure("download_limit", "Repository archive exceeds the download size limit.", 413)
                        output.write(chunk)
        except httpx.HTTPError:
            raise GitHubFailure("github_unavailable", "Archive download failed or timed out. Try again.", 502) from None


def load_app_key(path):
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ValueError("GitHub App private key must be RSA with at least 2048 bits.")
    return key


def app_jwt(app_id: int, key) -> str:
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")
    now = int(time.time())
    header = encode(b'{"alg":"RS256","typ":"JWT"}')
    payload = encode(json.dumps({"iat": now - 60, "exp": now + 540, "iss": str(app_id)}).encode())
    message = header + b"." + payload
    signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return (message + b"." + encode(signature)).decode()
