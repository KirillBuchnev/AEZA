from dataclasses import dataclass
import os
from urllib.parse import urlsplit

def _boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

@dataclass(frozen=True)
class AppConfig:
    environment: str
    admin_username: str
    admin_password: str
    rate_limit_secret: bytes
    database_url: str
    cookie_secure: bool
    session_days: int
    metrics_token: str
    allowed_origins: tuple[str, ...]
    docs_enabled: bool

def _resolve_database_url() -> str:
    explicit = os.getenv("DATABASE_URL", "").strip() or os.getenv("AEZA_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    return f"sqlite+pysqlite:///{os.getenv('AEZA_DATABASE_PATH', 'data/aeza.db')}"

def load_config() -> AppConfig:
    environment = os.getenv("AEZA_ENVIRONMENT", "development").strip().lower()
    if environment not in {"development", "production"}:
        raise ValueError("AEZA_ENVIRONMENT must be 'development' or 'production'.")

    username = os.getenv("AEZA_ADMIN_USERNAME", "admin")
    password = os.getenv("AEZA_ADMIN_PASSWORD", "demo-local-only-change-me")
    cookie_secure = _boolean("AEZA_COOKIE_SECURE")
    metrics_token = os.getenv("AEZA_METRICS_TOKEN", "")
    configured_rate_limit_secret = os.getenv("AEZA_RATE_LIMIT_SECRET", "").strip()
    rate_limit_secret = configured_rate_limit_secret or f"development:{password}"
    origins = os.getenv(
        "AEZA_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8001,http://127.0.0.1:8001",
    )

    allowed_origins = tuple(origin.strip().rstrip("/") for origin in origins.split(",") if origin.strip())
    docs_enabled = _boolean("AEZA_DOCS_ENABLED", default=environment != "production")
    session_days = int(os.getenv("AEZA_SESSION_DAYS", "7"))
    if not 1 <= session_days <= 30:
        raise ValueError("AEZA_SESSION_DAYS must be between 1 and 30.")

    if environment == "production":
        if username.lower() in {"admin", "demo"} or len(password) < 16 or password == "local-demo-change-this-password":
            raise ValueError("Production requires a non-default admin username and a password of at least 16 characters.")
        if not cookie_secure:
            raise ValueError("AEZA_COOKIE_SECURE=true is required in production.")
        if len(configured_rate_limit_secret) < 32 or configured_rate_limit_secret == "local-demo-rate-limit-secret-change-this-before-production":
            raise ValueError("Production requires AEZA_RATE_LIMIT_SECRET with at least 32 characters.")
        if metrics_token and len(metrics_token) < 32:
            raise ValueError("AEZA_METRICS_TOKEN must have at least 32 characters in production.")
        if not allowed_origins or any(
            urlsplit(origin).scheme != "https" or not urlsplit(origin).hostname or urlsplit(origin).path not in {"", "/"} or urlsplit(origin).query or urlsplit(origin).fragment or urlsplit(origin).username or urlsplit(origin).password
            for origin in allowed_origins
        ):
            raise ValueError("Production AEZA_ALLOWED_ORIGINS must contain only HTTPS origins.")

    return AppConfig(
        environment=environment,
        admin_username=username,
        admin_password=password,
        rate_limit_secret=rate_limit_secret.encode("utf-8"),
        database_url=_resolve_database_url(),
        cookie_secure=cookie_secure,
        session_days=session_days,
        metrics_token=metrics_token,
        allowed_origins=allowed_origins,
        docs_enabled=docs_enabled,
    )