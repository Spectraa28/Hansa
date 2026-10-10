from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from starlette.config import Config


ROOT = Path(__file__).resolve().parents[2]


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

    def __post_init__(self):
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

    @property
    def allowed_origins(self) -> set[str]:
        return {self.app_url.rstrip("/"), self.frontend_origin.rstrip("/")}

    @classmethod
    def from_env(cls):
        config = Config(str(ROOT / ".env") if (ROOT / ".env").exists() else None)
        path = Path(config("AUTH_DATABASE_PATH", default="var/auth.sqlite3"))
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
        )
