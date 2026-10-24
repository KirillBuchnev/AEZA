import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import logging
import sqlite3
from typing import Any, AsyncIterator, Callable, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.security import APIKeyCookie

from .config import load_config
from .database import Database
from .oidc import OidcClient, OidcError
from .risk import DEFAULT_WEIGHTS, FACTORS, MODEL_VERSION, evaluate_customer, model_divisor, outflow_forecast
from .schemas import (
    AnalyticsSummary,
    AuthMethodsResponse,
    CustomerDetail,
    CustomerListResponse,
    LoginRequest,
    LoginResponse,
    ModelSettingsPatch,
    ModelSettingsResponse,
    OutflowResponse,
    PasswordChangeRequest,
    PasswordResetRequest,
    PasswordResetTokenResponse,
    RegisterRequest,
    SnapshotImportResponse,
    SnapshotUpload,
    UserResponse,
    VerifyCodewordRequest,
)
from .security import (
    DUMMY_HASH,
    RESET_TOKEN_MINUTES,
    codeword_error,
    hash_secret,
    new_token,
    normalize_codeword,
    normalize_username,
    password_error,
    username_error,
    verify_secret,
)


config = load_config()
database = Database(config.database_path)
logger = logging.getLogger("aeza")


def _admin_profile() -> dict[str, str]:
    return {
        "username": normalize_username(config.admin_username),
        "first_name": config.admin_first_name,
        "last_name": config.admin_last_name,
        "password_hash": hash_secret(config.admin_password),
        "codeword_hash": hash_secret(normalize_codeword(config.admin_codeword)),
    }


PUBLISHED_DEMO_PASSWORDS = ("local-demo-change-this-password", "demo-local-only-change-me")
# Accounts created through SSO have no local secret. This value is not a scrypt
# hash, so password and codeword checks always fail for them.
OIDC_ONLY_SECRET = "oidc-only-account"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    database.initialize(admin_profile=_admin_profile())
    if config.environment == "production":
        # Any account, including rows left by a development run, must not keep a published demo password.
        for user in database.list_users():
            if any(verify_secret(password, user["password_hash"]) for password in PUBLISHED_DEMO_PASSWORDS):
                raise RuntimeError(
                    "Production refuses to start: an account has a published demo password. "
                    "Use a new AEZA_DATABASE_PATH volume, or change that password in the panel first."
                )
    yield


def _build_oidc_client() -> OidcClient | None:
    if not (config.oidc_issuer and config.oidc_client_id and config.oidc_redirect_uri):
        return None
    return OidcClient(
        database=database,
        issuer=config.oidc_issuer,
        client_id=config.oidc_client_id,
        client_secret=config.oidc_client_secret,
        redirect_uri=config.oidc_redirect_uri,
        scopes=config.oidc_scopes,
    )


# Replaced in tests with a client that talks to a fake identity provider.
oidc_client: OidcClient | None = _build_oidc_client()

app = FastAPI(
    title="AEZA Retention Risk API",
    description="API аналитики риска непродления услуг, оттока и денежной экспозиции.",
    version="1.1.0",
    docs_url="/api/v1/docs" if config.docs_enabled else None,
    redoc_url=None,
    openapi_url="/api/v1/openapi.json" if config.docs_enabled else None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def security_middleware(request: Request, call_next: Callable[[Request], Any]) -> Response:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in config.allowed_origins:
            response = JSONResponse(
                status_code=403,
                content={"detail": "Запрос отклонён: источник не разрешён."},
            )
        elif request.headers.get("sec-fetch-site", "").lower() == "cross-site":
            response = JSONResponse(
                status_code=403,
                content={"detail": "Запрос отклонён политикой безопасности."},
            )
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/") or request.url.path == "/metrics":
        response.headers["Cache-Control"] = "no-store"
    if config.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


class EventBroker:
    max_subscribers = 250
    queue_size = 8

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]] | None:
        if len(self._subscribers) >= self.max_subscribers:
            return None
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)


events = EventBroker()
SESSION_COOKIE = "aeza_session"
session_cookie = APIKeyCookie(name=SESSION_COOKIE, scheme_name="sessionCookie", auto_error=False)

# Sort keys accepted by GET /api/v1/customers and the customer field they read.
SORT_FIELDS = {
    "id": "id",
    "email": "email",
    "balance": "balance_minor",
    "total_replenished": "total_replenished_minor",
    "monthly_cost": "monthly_cost_minor",
    "due_revenue": "due_revenue_minor",
    "risk_score": "risk_score",
    "max_service_score": "max_service_score",
    "high_count": "high_count",
    "potential_loss": "potential_loss_minor",
    "revenue_at_risk": "revenue_at_risk_minor",
    "service_count": "service_count",
}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _throttle_key(scope: str, value: str) -> str:
    """Return a keyed, non-reversible identifier for an attempt counter."""
    return hmac.new(
        config.rate_limit_secret,
        f"{scope}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _scoped_client_key(request: Request, scope: str) -> str:
    return _throttle_key(scope, _client_key(request))


def _too_many_attempts(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="Слишком много попыток. Попробуйте позже.",
        headers={"Retry-After": str(retry_after)},
    )


def _client_key(request: Request) -> str:
    """Return a keyed, non-reversible identifier for login throttling."""
    socket_address = request.client.host if request.client else "unknown"
    try:
        normalized_socket = ipaddress.ip_address(socket_address).compressed
    except ValueError:
        normalized_socket = socket_address
    forwarded_address = ""
    if normalized_socket in config.trusted_proxy_ips:
        forwarded_address = request.headers.get("x-real-ip", "")
    try:
        client_address = ipaddress.ip_address(forwarded_address or normalized_socket).compressed
    except ValueError:
        client_address = normalized_socket
    return _throttle_key("ip", client_address)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Войдите, чтобы продолжить.")


def require_session(token: str | None = Depends(session_cookie)) -> str:
    if not token:
        raise _unauthorized()
    username = database.session_username(_token_hash(token))
    if not username:
        raise _unauthorized()
    return username


def _calculation_version(model: dict[str, Any]) -> str:
    return f"{MODEL_VERSION}.{model['revision']}"


def _score_all() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Score every customer against the current snapshot and model settings."""
    model = database.model_settings()
    now = datetime.now(timezone.utc)
    customers = [evaluate_customer(customer, model, now) for customer in database.customer_rows()]
    meta = {
        **database.snapshot_meta(),
        "as_of": now,
        "calculation_version": _calculation_version(model),
    }
    return customers, model, meta


def _customer_list_item(customer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": customer["id"],
        "email": customer["email"],
        "balance_minor": customer["balance_minor"],
        "withdraw_balance_minor": customer["withdraw_balance_minor"],
        "bonus_balance_minor": customer["bonus_balance_minor"],
        "bonus_spend_enabled": customer["bonus_spend_enabled"],
        "total_replenished_minor": customer["total_replenished_minor"],
        "service_count": len(customer["services"]),
        "risk_score": customer["risk_score"],
        "risk_level": customer["risk_level"],
        "risk_label": customer["risk_label"],
        "reasons": customer["reasons"],
        "recommended_action": customer["recommended_action"],
        "due_revenue_minor": customer["due_revenue_minor"],
        "monthly_cost_minor": customer["monthly_cost_minor"],
        "potential_loss_minor": customer["potential_loss_minor"],
        "revenue_at_risk_minor": customer["revenue_at_risk_minor"],
        "account_risk_sum": customer["account_risk_sum"],
        "max_service_score": customer["max_service_score"],
        "high_count": customer["high_count"],
        "unscored_services_count": customer["unscored_services_count"],
        "data_issues_count": len(customer["data_quality"]),
    }


def _summary(customers: list[dict[str, Any]], model: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    counts = {"high": 0, "medium": 0, "low": 0, "unscored": 0}
    reason_counts = {factor["code"]: 0 for factor in FACTORS}
    for customer in customers:
        counts[customer["risk_level"] or "unscored"] += 1
        for code in {reason["code"] for reason in customer["reasons"]} & set(reason_counts):
            reason_counts[code] += 1
    exposed = sorted(
        (customer for customer in customers if customer["potential_loss_minor"] > 0),
        key=lambda customer: customer["potential_loss_minor"],
        reverse=True,
    )[:5]
    return {
        "reason_counts": reason_counts,
        "top_exposure": [
            {"id": customer["id"], "email": customer["email"], "potential_loss_minor": customer["potential_loss_minor"]}
            for customer in exposed
        ],
        "customers_total": len(customers),
        "assessed_total": len(customers) - counts["unscored"],
        "risk_counts": counts,
        "potential_loss_minor": sum(customer["potential_loss_minor"] for customer in customers),
        "revenue_at_risk_minor": sum(customer["revenue_at_risk_minor"] for customer in customers),
        "monthly_cost_minor": sum(customer["monthly_cost_minor"] for customer in customers),
        "currency": "EUR",
        "prediction_horizon_days": model["prediction_horizon_days"],
        "source_kind": meta["source_kind"],
        "source_updated_at": meta["source_updated_at"],
        "snapshot_id": meta["snapshot_id"],
        "calculation_version": meta["calculation_version"],
        "calculated_at": meta["as_of"],
    }


def _data_quality_report(customers: list[dict[str, Any]]) -> dict[str, Any]:
    issues: dict[str, int] = {}
    for customer in customers:
        for issue in customer["data_quality"]:
            issues[issue["code"]] = issues.get(issue["code"], 0) + 1
    return {
        "customers_total": len(customers),
        "customers_unscored": sum(customer["risk_level"] is None for customer in customers),
        "issues": issues,
    }


def _model_response(model: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "version": model["version"],
        "revision": model["revision"],
        "calculation_version": _calculation_version(model),
        "prediction_horizon_days": model["prediction_horizon_days"],
        "high_risk_min": model["high_risk_min"],
        "medium_risk_min": model["medium_risk_min"],
        "account_high_risk_min": model["account_high_risk_min"],
        "account_medium_risk_min": model["account_medium_risk_min"],
        "weights": dict(model["weights"]),
        "normalizer": model_divisor(model),
        "features": [
            {**factor, "weight": model["weights"][factor["code"]]}
            for factor in FACTORS
        ],
        **extra,
    }


def _facts_payload(raw: dict[str, Any], days: int, now: datetime) -> dict[str, Any]:
    start = now.date() - timedelta(days=days)
    by_day = {
        (start + timedelta(days=offset)).isoformat(): {
            "date": (start + timedelta(days=offset)).isoformat(),
            "removed": 0,
            "deleted": 0,
            "blocked": 0,
            "renewed": 0,
            "entered_wait": 0,
            "deleted_amount_minor": 0,
        }
        for offset in range(days + 1)
    }
    for row in raw["rows"]:
        bucket = by_day.get(row["day"])
        if bucket is None:
            continue
        if row["event_type"] in bucket:
            bucket[row["event_type"]] += row["services"]
        if row["event_type"] in {"deleted", "removed"}:
            bucket["deleted_amount_minor"] += row["amount_minor"]
    days_list = list(by_day.values())
    totals = {
        key: sum(day[key] for day in days_list)
        for key in ("removed", "deleted", "blocked", "renewed", "entered_wait", "deleted_amount_minor")
    }
    return {
        "source": "snapshot_journal",
        "from_date": start.isoformat(),
        "to_date": now.date().isoformat(),
        "snapshots_observed": raw["snapshots"],
        "days": days_list,
        "totals": totals,
    }


def _sort_key(sort_by: str, field: str) -> Callable[[dict[str, Any]], Any]:
    def key(customer: dict[str, Any]) -> Any:
        value = customer[field]
        if sort_by == "id":
            identifier = customer["id"]
            # Only ASCII digits are numeric: str.isdigit() accepts other scripts and breaks int().
            if identifier.isascii() and identifier.isdecimal():
                return (0, int(identifier), identifier)
            return (1, 0, identifier.casefold())
        if isinstance(value, str):
            return (value.casefold(), customer["id"])
        return (value, customer["id"])

    return key


def _oidc_user(issuer: str, claims: dict[str, Any]) -> dict[str, Any] | None:
    subject = str(claims["sub"])
    username = database.oidc_identity(issuer, subject)
    if username is not None:
        return database.get_user(username)
    if not config.oidc_auto_provision:
        return None
    claimed = claims.get(config.oidc_username_claim) or claims.get("email")
    if not isinstance(claimed, str):
        return None
    username = normalize_username(claimed)
    if username_error(username) or database.get_user(username) is not None:
        # Never link an SSO identity to an existing local account automatically.
        return None
    first_name = str(claims.get("given_name") or "SSO").strip()[:60] or "SSO"
    last_name = str(claims.get("family_name") or "SSO").strip()[:60] or "SSO"
    try:
        database.create_user(username, first_name, last_name, OIDC_ONLY_SECRET, OIDC_ONLY_SECRET)
    except sqlite3.IntegrityError:
        return None
    database.link_oidc_identity(issuer, subject, username)
    return database.get_user(username)


def _sso_redirect(reason: str) -> RedirectResponse:
    return RedirectResponse(f"/?sso={reason}", status_code=303)


@app.get("/healthz", tags=["system"], summary="Проверка доступности API")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/auth/methods", tags=["auth"], summary="Доступные способы входа", response_model=AuthMethodsResponse)
def auth_methods() -> dict[str, Any]:
    return {
        "password": True,
        "registration": config.registration_enabled,
        "sso": {"enabled": oidc_client is not None, "label": "Войти через SSO"},
    }


@app.post("/api/v1/auth/login", tags=["auth"], summary="Войти по логину и паролю", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    username = normalize_username(body.username)
    client_key = _client_key(request)
    account_key = _throttle_key("login-user", username)
    for key, limit in ((client_key, 5), (account_key, 10)):
        retry_after = database.begin_login_attempt(key, max_attempts=limit)
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="Слишком много попыток входа. Попробуйте позже.",
                headers={"Retry-After": str(retry_after)},
            )

    user = database.get_user(username)
    password_ok = verify_secret(body.password, user["password_hash"] if user else DUMMY_HASH)
    if user is None or not password_ok:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль.")

    database.clear_login_attempts(client_key)
    database.clear_login_attempts(account_key)
    return _start_session(response, user)


@app.get("/api/v1/auth/oidc/login", tags=["auth"], summary="Начать вход через OIDC")
def oidc_login(request: Request) -> RedirectResponse:
    if oidc_client is None:
        raise HTTPException(status_code=404, detail="Вход через SSO не настроен.")
    retry_after = database.begin_login_attempt(_scoped_client_key(request, "oidc-start"), max_attempts=30)
    if retry_after:
        return _sso_redirect("failed")
    try:
        authorization_url = oidc_client.start_login()
    except OidcError as error:
        logger.warning("OIDC login could not start: %s", error)
        return _sso_redirect("unavailable")
    return RedirectResponse(authorization_url, status_code=302)


@app.get("/api/v1/auth/oidc/callback", tags=["auth"], summary="Завершить вход через OIDC")
def oidc_callback(
    request: Request,
    state: str | None = Query(default=None, max_length=256),
    code: str | None = Query(default=None, max_length=4096),
    error: str | None = Query(default=None, max_length=120),
) -> RedirectResponse:
    if oidc_client is None:
        raise HTTPException(status_code=404, detail="Вход через SSO не настроен.")
    if error or not state or not code:
        return _sso_redirect("failed")
    client_key = _scoped_client_key(request, "oidc-callback")
    retry_after = database.begin_login_attempt(client_key, max_attempts=20)
    if retry_after:
        return _sso_redirect("failed")
    try:
        claims = oidc_client.complete_login(state=state, code=code)
    except OidcError as reason:
        logger.warning("OIDC login rejected: %s", reason)
        return _sso_redirect("failed")
    user = _oidc_user(oidc_client.issuer, claims)
    if user is None:
        return _sso_redirect("denied")
    database.clear_login_attempts(client_key)
    response = RedirectResponse("/", status_code=303)
    _start_session(response, user)
    return response


@app.get("/api/v1/auth/me", tags=["auth"], summary="Получить текущего пользователя", response_model=UserResponse)
def current_user(username: str = Depends(require_session)) -> dict[str, Any]:
    user = database.get_user(username)
    if user is None:
        raise _unauthorized()
    return _profile(user)


@app.post("/api/v1/auth/logout", status_code=204, tags=["auth"], summary="Завершить сессию")
def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        database.delete_session(_token_hash(token))
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
    )
    response.status_code = 204
    return response


def _profile(user: dict[str, Any]) -> dict[str, Any]:
    middle_name = user.get("middle_name") or None
    return {
        "username": user["username"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "middle_name": middle_name,
        "full_name": " ".join(part for part in (user["last_name"], user["first_name"], middle_name) if part),
        "role": user["role"],
    }


def _start_session(response: Response, user: dict[str, Any]) -> dict[str, Any]:
    token = new_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=config.session_days)
    database.create_session(_token_hash(token), user["username"], expires_at.isoformat())
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=config.session_days * 24 * 60 * 60,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"user": _profile(user), "expires_at": expires_at.isoformat()}


@app.post("/api/v1/auth/register", status_code=201, tags=["auth"], summary="Зарегистрироваться", response_model=LoginResponse)
def register(body: RegisterRequest, request: Request, response: Response) -> dict[str, Any]:
    if not config.registration_enabled:
        raise HTTPException(status_code=403, detail="Регистрация отключена администратором.")
    client_key = _scoped_client_key(request, "register")
    retry_after = database.begin_login_attempt(client_key, max_attempts=10)
    if retry_after:
        raise _too_many_attempts(retry_after)

    username = normalize_username(body.username)
    first_name = body.first_name.strip()
    last_name = body.last_name.strip()
    middle_name = (body.middle_name or "").strip() or None
    if not first_name or not last_name:
        raise HTTPException(status_code=422, detail="Укажите имя и фамилию.")
    if len(first_name) > 60 or len(last_name) > 60 or len(middle_name or "") > 60:
        raise HTTPException(status_code=422, detail="Имя, фамилия и отчество должны быть не длиннее 60 символов.")
    error = username_error(username)
    if error:
        raise HTTPException(status_code=422, detail=error)
    if body.password != body.password_confirm:
        raise HTTPException(status_code=422, detail="Пароли не совпадают.")
    error = password_error(body.password, username)
    if error:
        raise HTTPException(status_code=422, detail=error)
    error = codeword_error(body.codeword, body.password)
    if error:
        raise HTTPException(status_code=422, detail=error)
    if database.get_user(username) is not None:
        raise HTTPException(status_code=409, detail="Логин уже занят.")
    try:
        database.create_user(
            username,
            first_name,
            last_name,
            hash_secret(body.password),
            hash_secret(normalize_codeword(body.codeword)),
            middle_name=middle_name,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Логин уже занят.")

    database.clear_login_attempts(client_key)
    return _start_session(response, database.get_user(username))


@app.post("/api/v1/auth/password/verify-codeword", tags=["auth"], summary="Проверить кодовое слово для сброса", response_model=PasswordResetTokenResponse)
def verify_codeword(body: VerifyCodewordRequest, request: Request) -> dict[str, Any]:
    username = normalize_username(body.username)
    address_key = _scoped_client_key(request, "reset-ip")
    retry_after = database.begin_login_attempt(address_key, max_attempts=30)
    if retry_after:
        raise _too_many_attempts(retry_after)
    client_key = _throttle_key("reset", username)
    retry_after = database.begin_login_attempt(client_key)
    if retry_after:
        raise _too_many_attempts(retry_after)

    user = database.get_user(username)
    stored = user["codeword_hash"] if user else DUMMY_HASH
    codeword_ok = verify_secret(normalize_codeword(body.codeword), stored)
    if user is None or not codeword_ok:
        raise HTTPException(status_code=401, detail="Неверный логин или кодовое слово.")

    database.clear_login_attempts(client_key)
    token = new_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_MINUTES)
    database.create_password_reset(_token_hash(token), username, expires_at.isoformat())
    return {"reset_token": token, "expires_at": expires_at.isoformat()}


@app.post("/api/v1/auth/password/reset", status_code=204, tags=["auth"], summary="Задать новый пароль после проверки кодового слова")
def reset_password(body: PasswordResetRequest) -> Response:
    if body.new_password != body.new_password_confirm:
        raise HTTPException(status_code=422, detail="Пароли не совпадают.")
    token = _token_hash(body.reset_token)
    expired = HTTPException(status_code=400, detail="Ссылка для сброса устарела. Начните восстановление заново.")
    username = database.peek_password_reset(token)
    if username is None:
        raise expired
    error = password_error(body.new_password, username)
    if error:
        raise HTTPException(status_code=422, detail=error)
    if database.consume_password_reset(token) is None:
        raise expired

    database.replace_password(username, hash_secret(body.new_password))
    return Response(status_code=204)


@app.post("/api/v1/auth/password/change", status_code=204, tags=["auth"], summary="Сменить пароль текущего пользователя")
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    username: str = Depends(require_session),
) -> Response:
    user = database.get_user(username)
    if user is None:
        raise _unauthorized()
    change_key = _throttle_key("change-password", username)
    retry_after = database.begin_login_attempt(change_key, max_attempts=5)
    if retry_after:
        raise _too_many_attempts(retry_after)
    if not verify_secret(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно.")
    database.clear_login_attempts(change_key)
    if body.new_password != body.new_password_confirm:
        raise HTTPException(status_code=422, detail="Пароли не совпадают.")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=422, detail="Новый пароль должен отличаться от текущего.")
    error = password_error(body.new_password, username)
    if error:
        raise HTTPException(status_code=422, detail=error)

    database.replace_password(
        username,
        hash_secret(body.new_password),
        keep_token_hash=_token_hash(request.cookies.get(SESSION_COOKIE, "")),
    )
    return Response(status_code=204)


@app.get("/api/v1/customers", tags=["customers"], summary="Список клиентов с оценкой риска", response_model=CustomerListResponse)
def list_customers(
    _: str = Depends(require_session),
    query: str | None = Query(default=None, alias="q", max_length=120),
    risk_level: Literal["high", "medium", "low", "unscored"] | None = None,
    reason: Literal["autoprolong_disabled", "insufficient_balance", "renewal_urgency", "prolong_wait"] | None = None,
    data_status: Literal["all", "clean", "issues"] = "all",
    sort_by: Literal[
        "id", "email", "balance", "total_replenished", "monthly_cost", "due_revenue",
        "risk_score", "max_service_score", "high_count", "potential_loss", "revenue_at_risk", "service_count",
    ] = "risk_score",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    customers, _model, meta = _score_all()
    items = customers
    if query:
        needle = query.casefold()
        items = [
            customer for customer in items
            if needle in customer["email"].casefold() or needle in customer["id"].casefold()
        ]
    if risk_level:
        items = [customer for customer in items if (customer["risk_level"] or "unscored") == risk_level]
    if reason:
        items = [customer for customer in items if any(item["code"] == reason for item in customer["reasons"])]
    if data_status == "clean":
        items = [customer for customer in items if not customer["data_quality"]]
    elif data_status == "issues":
        items = [customer for customer in items if customer["data_quality"]]

    field = SORT_FIELDS[sort_by]
    # Customers without a value (unscored) always go last, in both directions.
    present = [customer for customer in items if customer[field] is not None]
    missing = [customer for customer in items if customer[field] is None]
    present.sort(key=_sort_key(sort_by, field), reverse=order == "desc")
    ordered = [_customer_list_item(customer) for customer in present + missing]
    return {
        "items": ordered[offset:offset + limit],
        "total": len(ordered),
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "order": order,
        "snapshot_id": meta["snapshot_id"],
        "calculation_version": meta["calculation_version"],
        "as_of": meta["as_of"],
    }


@app.get("/api/v1/customers/{customer_id}", tags=["customers"], summary="Подробности риска клиента", response_model=CustomerDetail)
def get_customer(
    customer_id: str,
    _: str = Depends(require_session),
) -> dict[str, Any]:
    customers, _model, meta = _score_all()
    for customer in customers:
        if customer["id"] != customer_id:
            continue
        return {
            **_customer_list_item(customer),
            "services": customer["services"],
            "transactions": customer["transactions"],
            "data_quality": customer["data_quality"],
            "available_balance_minor": customer["available_balance_minor"],
            "uncovered_revenue_minor": customer["uncovered_revenue_minor"],
            "assessed_at": customer["assessed_at"],
            "snapshot_id": meta["snapshot_id"],
            "calculation_version": meta["calculation_version"],
            "calculation": customer["calculation"],
        }
    raise HTTPException(status_code=404, detail="Клиент не найден.")


@app.get("/api/v1/analytics/summary", tags=["analytics"], summary="Сводка риска и денежной оценки", response_model=AnalyticsSummary)
def analytics_summary(_: str = Depends(require_session)) -> dict[str, Any]:
    customers, model, meta = _score_all()
    return _summary(customers, model, meta)


@app.get("/api/v1/analytics/outflow", tags=["analytics"], summary="Отток: факты журнала и прогноз непродлений", response_model=OutflowResponse)
def analytics_outflow(
    days: int = Query(default=30, ge=7, le=365),
    _: str = Depends(require_session),
) -> dict[str, Any]:
    customers, model, meta = _score_all()
    now = meta["as_of"]
    facts = database.outflow_facts((now - timedelta(days=days)).isoformat())
    return {
        "as_of": now,
        "snapshot_id": meta["snapshot_id"],
        "calculation_version": meta["calculation_version"],
        "facts": _facts_payload(facts, days, now),
        "forecast": outflow_forecast(customers, now, model["prediction_horizon_days"]),
    }


@app.get("/api/v1/model/settings", tags=["model"], summary="Действующие коэффициенты модели", response_model=ModelSettingsResponse)
def get_model_settings(_: str = Depends(require_session)) -> dict[str, Any]:
    return _model_response(database.model_settings())


@app.patch("/api/v1/model/settings", tags=["model"], summary="Изменить настройки и пересчитать оценки", response_model=ModelSettingsResponse)
async def patch_model_settings(
    patch: ModelSettingsPatch,
    _: str = Depends(require_session),
) -> dict[str, Any]:
    changes = patch.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Укажите хотя бы одну настройку.")
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Настройки не могут быть null.")

    current = database.model_settings()
    weights = changes.pop("weights", None)
    if weights is not None:
        unknown = set(weights) - set(DEFAULT_WEIGHTS)
        if unknown:
            raise HTTPException(status_code=422, detail="В запросе есть неизвестный признак риска.")
        if any(value < 0 or value > 100 for value in weights.values()):
            raise HTTPException(status_code=422, detail="Вес признака должен быть от 0 до 100.")
        current["weights"].update(weights)
        if sum(current["weights"].values()) <= 0:
            raise HTTPException(status_code=422, detail="Хотя бы один вес должен быть больше нуля.")
    current.update(changes)
    if current["high_risk_min"] <= current["medium_risk_min"]:
        raise HTTPException(status_code=422, detail="Порог высокого риска должен быть выше среднего.")
    if current["account_high_risk_min"] <= current["account_medium_risk_min"]:
        raise HTTPException(status_code=422, detail="Порог высокого риска аккаунта должен быть выше среднего.")

    current["revision"] = int(current.get("revision", 1)) + 1
    database.save_model_settings(current)
    changed_at = datetime.now(timezone.utc).isoformat()
    await events.publish({"type": "model_settings_changed", "changed_at": changed_at})
    return _model_response(database.model_settings(), recalculated=True, changed_at=changed_at)


@app.put("/api/v1/source/snapshot", tags=["source"], summary="Заменить снимок исходных данных", response_model=SnapshotImportResponse)
async def replace_source_snapshot(
    payload: SnapshotUpload,
    _: str = Depends(require_session),
) -> dict[str, Any]:
    service_count = sum(len(customer.services) for customer in payload.customers)
    transaction_count = sum(len(customer.transactions) for customer in payload.customers)
    if service_count > 50_000 or transaction_count > 50_000:
        raise HTTPException(status_code=422, detail="Снимок превышает допустимое число услуг или транзакций.")

    customer_ids = [customer.id for customer in payload.customers]
    if len(customer_ids) != len(set(customer_ids)):
        raise HTTPException(status_code=422, detail="ID клиентов в снимке должны быть уникальными.")
    service_ids = [
        str(service.id or f"{customer.id}-service-{index}")
        for customer in payload.customers
        for index, service in enumerate(customer.services, start=1)
    ]
    if len(service_ids) != len(set(service_ids)):
        raise HTTPException(status_code=422, detail="ID услуг в снимке должны быть уникальными.")
    transaction_ids = [
        str(transaction.id or f"{customer.id}-transaction-{index}")
        for customer in payload.customers
        for index, transaction in enumerate(customer.transactions, start=1)
    ]
    if len(transaction_ids) != len(set(transaction_ids)):
        raise HTTPException(status_code=422, detail="ID транзакций в снимке должны быть уникальными.")

    normalized = [customer.model_dump(mode="json") for customer in payload.customers]
    stored = database.replace_snapshot(normalized)
    await events.publish({"type": "source_snapshot_changed", "changed_at": stored["observed_at"]})
    customers, model, meta = _score_all()
    return {
        "accepted": True,
        "customers_received": len(normalized),
        "snapshot_id": stored["snapshot_id"],
        "events_recorded": stored["events_recorded"],
        "data_quality": _data_quality_report(customers),
        "summary": _summary(customers, model, meta),
    }


@app.get("/api/v1/events", tags=["updates"], summary="События обновления данных")
async def event_stream(_: str = Depends(require_session)) -> StreamingResponse:
    queue = events.subscribe()
    if queue is None:
        raise HTTPException(status_code=503, detail="Слишком много активных потоков обновления.")

    async def stream() -> AsyncIterator[str]:
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: data_changed\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            events.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/metrics", tags=["metrics"], summary="Prometheus-метрики")
def prometheus_metrics(request: Request) -> PlainTextResponse:
    session_token = request.cookies.get(SESSION_COOKIE)
    session_ok = bool(session_token and database.session_username(_token_hash(session_token)))
    bearer = request.headers.get("Authorization", "")
    token_ok = bool(
        config.metrics_token
        and bearer.startswith("Bearer ")
        and hmac.compare_digest(bearer.removeprefix("Bearer "), config.metrics_token)
    )
    if not (session_ok or token_ok):
        raise _unauthorized()

    customers, model, meta = _score_all()
    summary = _summary(customers, model, meta)
    forecast = outflow_forecast(customers, meta["as_of"], model["prediction_horizon_days"])
    services_at_risk = sum(
        1
        for customer in customers
        for service in customer["services"]
        if service["risk_level"] in {"high", "medium"}
    )
    lines = [
        "# HELP aeza_customers_total Number of customers by risk level.",
        "# TYPE aeza_customers_total gauge",
    ]
    for level, count in summary["risk_counts"].items():
        lines.append(f'aeza_customers_total{{risk_level="{level}"}} {count}')
    lines.extend([
        "# HELP aeza_potential_loss_eur Expected loss on uncovered renewals, weighted by the risk index.",
        "# TYPE aeza_potential_loss_eur gauge",
        f"aeza_potential_loss_eur {summary['potential_loss_minor'] / 100:.2f}",
        "# HELP aeza_revenue_at_risk_eur Renewal value weighted by the risk index.",
        "# TYPE aeza_revenue_at_risk_eur gauge",
        f"aeza_revenue_at_risk_eur {summary['revenue_at_risk_minor'] / 100:.2f}",
        "# HELP aeza_monthly_cost_eur Monthly cost of eligible services.",
        "# TYPE aeza_monthly_cost_eur gauge",
        f"aeza_monthly_cost_eur {summary['monthly_cost_minor'] / 100:.2f}",
        "# HELP aeza_services_at_risk Services with a medium or high index.",
        "# TYPE aeza_services_at_risk gauge",
        f"aeza_services_at_risk {services_at_risk}",
        "# HELP aeza_expected_non_renewals Forecast of non-renewals in the horizon, index based.",
        "# TYPE aeza_expected_non_renewals gauge",
        f"aeza_expected_non_renewals {forecast['totals']['expected_non_renewals']:.2f}",
        "# HELP aeza_customers_assessed_total Number of customers with a calculated score.",
        "# TYPE aeza_customers_assessed_total gauge",
        f"aeza_customers_assessed_total {summary['assessed_total']}",
    ])
    return PlainTextResponse("\n".join(lines) + "\n", headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"})
