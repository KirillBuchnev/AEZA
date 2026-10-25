from dataclasses import dataclass
import ipaddress
import os
from urllib.parse import urlsplit


def _boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_database_url(url: str) -> str:
    """Принимаем общепринятые варианты написания параметров PostgreSQL и отображаем их на драйвер psycopg 3, который поставляется с этим сервисом."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url.removeprefix(prefix)
    if not url.startswith(("postgresql+psycopg://", "sqlite:///")):
        raise ValueError("The database URL must start with postgresql+psycopg:// or sqlite:///.")
    return url


def _database_url() -> str:
    """AEZA_DATABASE_URL включает PostgreSQL. Без неё приложение продолжает использовать файл SQLite из AEZA_DATABASE_PATH."""
    url = os.getenv("AEZA_DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{os.getenv('AEZA_DATABASE_PATH', 'data/aeza.db')}"
    return normalize_database_url(url)


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
    trusted_proxy_ips: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    docs_enabled: bool
    admin_codeword: str
    admin_first_name: str
    admin_last_name: str
    registration_enabled: bool
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    oidc_redirect_uri: str
    oidc_scopes: str
    oidc_auto_provision: bool
    oidc_username_claim: str
    oidc_internal_issuer: str
    seed: str


def load_config() -> AppConfig:
    environment = os.getenv("AEZA_ENVIRONMENT", "development").strip().lower()
    if environment not in {"development", "production"}:
        raise ValueError("AEZA_ENVIRONMENT must be 'development' or 'production'.")

    username = os.getenv("AEZA_ADMIN_USERNAME", "admin")
    password = os.getenv("AEZA_ADMIN_PASSWORD", "demo-local-only-change-me")
    codeword = os.getenv("AEZA_ADMIN_CODEWORD", "").strip()
    if not codeword and environment != "production":
        codeword = "demo-codeword"
    cookie_secure = _boolean("AEZA_COOKIE_SECURE")
    metrics_token = os.getenv(
        "AEZA_METRICS_TOKEN",
        "local-demo-metrics-token-change-this-before-production",
    ).strip()
    configured_rate_limit_secret = os.getenv("AEZA_RATE_LIMIT_SECRET", "").strip()
    rate_limit_secret = configured_rate_limit_secret or f"development:{password}"
    origins = os.getenv(
        "AEZA_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8001,http://127.0.0.1:8001",
    )

    allowed_origins = tuple(origin.strip().rstrip("/") for origin in origins.split(",") if origin.strip())
    trusted_proxy_ips = tuple(
        address.strip()
        for address in os.getenv("AEZA_TRUSTED_PROXY_IPS", "").split(",")
        if address.strip()
    )
    for address in trusted_proxy_ips:
        try:
            ipaddress.ip_address(address)
        except ValueError as error:
            raise ValueError("AEZA_TRUSTED_PROXY_IPS must contain valid IP addresses.") from error
    docs_enabled = _boolean("AEZA_DOCS_ENABLED", default=environment != "production")
    seed = os.getenv("AEZA_SEED", "case").strip().lower() or "case"
    if seed not in {"case", "showcase", "demo", "empty"}:
        raise ValueError("AEZA_SEED must be case, showcase, demo or empty.")
    session_days = int(os.getenv("AEZA_SESSION_DAYS", "7"))
    if not 1 <= session_days <= 30:
        raise ValueError("AEZA_SESSION_DAYS must be between 1 and 30.")

    oidc_issuer = os.getenv("AEZA_OIDC_ISSUER", "").strip().rstrip("/")
    oidc_client_id = os.getenv("AEZA_OIDC_CLIENT_ID", "").strip()
    oidc_client_secret = os.getenv("AEZA_OIDC_CLIENT_SECRET", "").strip()
    oidc_redirect_uri = os.getenv("AEZA_OIDC_REDIRECT_URI", "").strip()
    oidc_scopes = os.getenv("AEZA_OIDC_SCOPES", "openid profile email").strip() or "openid profile email"
    oidc_auto_provision = _boolean("AEZA_OIDC_AUTO_PROVISION")
    oidc_username_claim = os.getenv("AEZA_OIDC_USERNAME_CLAIM", "preferred_username").strip() or "preferred_username"
    oidc_internal_issuer = os.getenv("AEZA_OIDC_INTERNAL_ISSUER", "").strip().rstrip("/")
    if (oidc_issuer or oidc_client_id) and not (oidc_issuer and oidc_client_id and oidc_redirect_uri):
        raise ValueError(
            "AEZA_OIDC_ISSUER, AEZA_OIDC_CLIENT_ID and AEZA_OIDC_REDIRECT_URI must be set together."
        )
    if oidc_issuer and urlsplit(oidc_issuer).scheme not in {"https", "http"}:
        raise ValueError("AEZA_OIDC_ISSUER must be an http(s) URL.")
    if environment == "production" and oidc_issuer and urlsplit(oidc_issuer).scheme != "https":
        raise ValueError("Production requires an HTTPS AEZA_OIDC_ISSUER.")

    if environment == "production":
        if username.lower() in {"admin", "demo"} or len(password) < 16 or password in {"local-demo-change-this-password", "demo-local-only-change-me"}:
            raise ValueError("Production requires a non-default admin username and a password of at least 16 characters.")
        if (
            len(codeword) < 8
            or codeword == "demo-codeword"
            or codeword.isdigit()
            or codeword.casefold() in {"password", "qwerty", "codeword", "letmein", "aeza"}
        ):
            raise ValueError("Production requires AEZA_ADMIN_CODEWORD with at least 8 characters.")
        if not cookie_secure:
            raise ValueError("AEZA_COOKIE_SECURE=true is required in production.")
        if (
            len(configured_rate_limit_secret) < 32
            or configured_rate_limit_secret == "local-demo-rate-limit-secret-change-this-before-production"
        ):
            raise ValueError("Production requires AEZA_RATE_LIMIT_SECRET with at least 32 characters.")
        if (
            len(metrics_token) < 32
            or metrics_token == "local-demo-metrics-token-change-this-before-production"
        ):
            raise ValueError("Production requires a non-default AEZA_METRICS_TOKEN with at least 32 characters.")
        if not allowed_origins or any(
            urlsplit(origin).scheme != "https"
            or not urlsplit(origin).hostname
            or urlsplit(origin).path not in {"", "/"}
            or urlsplit(origin).query
            or urlsplit(origin).fragment
            or urlsplit(origin).username
            or urlsplit(origin).password
            for origin in allowed_origins
        ):
            raise ValueError("Production AEZA_ALLOWED_ORIGINS must contain only HTTPS origins.")

    return AppConfig(
        environment=environment,
        admin_username=username,
        admin_password=password,
        rate_limit_secret=rate_limit_secret.encode("utf-8"),
        database_url=_database_url(),
        cookie_secure=cookie_secure,
        session_days=session_days,
        metrics_token=metrics_token,
        trusted_proxy_ips=trusted_proxy_ips,
        allowed_origins=allowed_origins,
        docs_enabled=docs_enabled,
        admin_codeword=codeword,
        admin_first_name=os.getenv("AEZA_ADMIN_FIRST_NAME", "Демо").strip() or "Демо",
        admin_last_name=os.getenv("AEZA_ADMIN_LAST_NAME", "Аналитик").strip() or "Аналитик",
        registration_enabled=_boolean("AEZA_REGISTRATION_ENABLED", default=environment != "production"),
        oidc_issuer=oidc_issuer,
        oidc_client_id=oidc_client_id,
        oidc_client_secret=oidc_client_secret,
        oidc_redirect_uri=oidc_redirect_uri,
        oidc_scopes=oidc_scopes,
        oidc_auto_provision=oidc_auto_provision,
        oidc_username_claim=oidc_username_claim,
        oidc_internal_issuer=oidc_internal_issuer,
        seed=seed,
    )
