from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from starlette.config import Config


# ROOT is the repository: .env and the ignored var/ runtime data live there, beside backend/ and frontend/.
ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_path: Path
    secret_key: str
    app_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:5173"
    cookie_secure: bool = False
    email_login_enabled: bool = True
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    github_app_id: int = 0
    github_app_client_id: str = ""
    github_app_client_secret: str = ""
    github_app_private_key_path: Path | None = None
    github_app_callback_url: str = ""
    github_token_encryption_key: str = ""
    github_webhook_secret: str = ""
    import_workspace_path: Path = ROOT / "var/imports"
    import_download_bytes: int = 100 * 1024 * 1024
    import_extracted_bytes: int = 500 * 1024 * 1024
    import_file_count: int = 20_000
    import_timeout_seconds: int = 120
    litellm_base_url: str = ""
    runner_internet: bool = True
    runner_parallel: int = 3
    agent_model: str = "claude-sonnet-4.6"
    agent_context: str = "managed"
    neatlogs_mcp_url: str = "https://ingest.neatlogs.com/mcp"
    neatlogs_api_key: str = field(default="", repr=False)
    trace_content: bool = True
    litellm_api_key: str = field(default="", repr=False)

    def __post_init__(self):
        if not 1 <= self.runner_parallel <= 8:
            raise ValueError("RUNNER_PARALLEL must be between 1 and 8.")
        if self.agent_context not in {"managed", "naive"}:
            raise ValueError("AGENT_CONTEXT must be managed or naive.")
        if not self.neatlogs_mcp_url.startswith("https://"):
            raise ValueError("NEATLOGS_MCP_URL must be HTTPS.")
        if self.litellm_base_url:
            parsed = urlsplit(self.litellm_base_url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.query or parsed.fragment
                    or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
                raise ValueError("LITELLM_BASE_URL must be HTTPS (HTTP only on localhost), without credentials or query.")
        if len(self.secret_key) < 32:
            raise ValueError("AUTH_SECRET_KEY must contain at least 32 random characters.")
        for value in (self.app_url, self.frontend_origin):
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("APP_URL and FRONTEND_ORIGIN must be HTTP(S) origins.")
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("HTTP is allowed only for local development; use HTTPS when hosted.")
        if self.app_url.startswith("https://") and not self.cookie_secure:
            raise ValueError("Set AUTH_COOKIE_SECURE=true when APP_URL uses HTTPS.")
        if self.cookie_secure and not self.app_url.startswith("https://"):
            raise ValueError("Secure cookies require an HTTPS APP_URL.")
        if self.github_app_callback_url and self.github_app_callback_url != f"{self.app_url.rstrip('/')}/github/callback":
            raise ValueError("GITHUB_APP_CALLBACK_URL must be APP_URL + /github/callback.")
        if min(self.import_download_bytes, self.import_extracted_bytes,
               self.import_file_count, self.import_timeout_seconds) <= 0:
            raise ValueError("Import limits must be positive.")
        if self.github_app_enabled:
            from cryptography.fernet import Fernet
            Fernet(self.github_token_encryption_key.encode())
            if self.app_url.startswith("https://") and len(self.github_webhook_secret) < 32:
                raise ValueError("Hosted GitHub imports require a random GITHUB_WEBHOOK_SECRET of at least 32 characters.")

    @property
    def github_app_enabled(self) -> bool:
        return bool(self.github_app_id > 0 and self.github_app_client_id and self.github_app_client_secret
                    and self.github_app_private_key_path and self.github_app_callback_url
                    and self.github_token_encryption_key)

    @property
    def allowed_origins(self) -> set[str]:
        return {self.app_url.rstrip("/"), self.frontend_origin.rstrip("/")}

    @classmethod
    def from_env(cls):
        config = Config(str(ROOT / ".env") if (ROOT / ".env").exists() else None)
        path = Path(config("AUTH_DATABASE_PATH", default="var/auth.sqlite3"))
        private_key = config("GITHUB_APP_PRIVATE_KEY_PATH", default="")
        workspace = Path(config("IMPORT_WORKSPACE_PATH", default="var/imports"))
        return cls(
            database_path=path if path.is_absolute() else ROOT / path,
            secret_key=config("AUTH_SECRET_KEY", default=""),
            app_url=config("APP_URL", default="http://localhost:8000").rstrip("/"),
            frontend_origin=config("FRONTEND_ORIGIN", default="http://localhost:5173").rstrip("/"),
            cookie_secure=config("AUTH_COOKIE_SECURE", cast=bool, default=False),
            email_login_enabled=config("AUTH_EMAIL_LOGIN_ENABLED", cast=bool, default=True),
            google_client_id=config("GOOGLE_CLIENT_ID", default=""),
            google_client_secret=config("GOOGLE_CLIENT_SECRET", default=""),
            github_client_id=config("GITHUB_CLIENT_ID", default=""),
            github_client_secret=config("GITHUB_CLIENT_SECRET", default=""),
            github_app_id=int(config("GITHUB_APP_ID", default="0") or "0"),
            github_app_client_id=config("GITHUB_APP_CLIENT_ID", default=""),
            github_app_client_secret=config("GITHUB_APP_CLIENT_SECRET", default=""),
            github_app_private_key_path=(ROOT / private_key).resolve() if private_key else None,
            github_app_callback_url=config("GITHUB_APP_CALLBACK_URL", default=""),
            github_token_encryption_key=config("GITHUB_TOKEN_ENCRYPTION_KEY", default=""),
            github_webhook_secret=config("GITHUB_WEBHOOK_SECRET", default=""),
            import_workspace_path=workspace if workspace.is_absolute() else ROOT / workspace,
            import_download_bytes=config("IMPORT_DOWNLOAD_BYTES", cast=int, default=100 * 1024 * 1024),
            import_extracted_bytes=config("IMPORT_EXTRACTED_BYTES", cast=int, default=500 * 1024 * 1024),
            import_file_count=config("IMPORT_FILE_COUNT", cast=int, default=20_000),
            import_timeout_seconds=config("IMPORT_TIMEOUT_SECONDS", cast=int, default=120),
            litellm_base_url=config("LITELLM_BASE_URL", default="").rstrip("/"),
            runner_internet=config("RUNNER_INTERNET", cast=bool, default=True),
            runner_parallel=config("RUNNER_PARALLEL", cast=int, default=3),
            agent_model=config("AGENT_MODEL", default="claude-sonnet-4.6"),
            agent_context=config("AGENT_CONTEXT", default="managed"),
            neatlogs_mcp_url=config("NEATLOGS_MCP_URL", default="https://ingest.neatlogs.com/mcp"),
            neatlogs_api_key=config("NEATLOGS_API_KEY", default=""),
            trace_content=config("TRACE_CONTENT", cast=bool, default=True),
            litellm_api_key=config("LITELLM_API_KEY", default=""),
        )
