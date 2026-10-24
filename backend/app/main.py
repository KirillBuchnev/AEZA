import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import sqlite3
from typing import Any, AsyncIterator, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.security import APIKeyCookie

from .config import load_config
from .database import Database
from .risk import DEFAULT_MODEL_SETTINGS, evaluate_customer
from .schemas import (
    AnalyticsSummary,
    CustomerDetail,
    CustomerListResponse,
    LoginRequest,
    LoginResponse,
    ModelSettingsPatch,
    ModelSettingsResponse,
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


def _admin_profile() -> dict[str, str]:
    return {
        "username": normalize_username(config.admin_username),
        "first_name": config.admin_first_name,
        "last_name": config.admin_last_name,
        "password_hash": hash_secret(config.admin_password),
        "codeword_hash": hash_secret(normalize_codeword(config.admin_codeword)),
    }


PUBLISHED_DEMO_PASSWORDS = ("local-demo-change-this-password", "demo-local-only-change-me")


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


app = FastAPI(
    title="AEZA Retention Risk API",
    description="API аналитики риска непродления услуг и потенциальной выручки.",
    version="1.0.0",
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
async def security_middleware(request: Request, call_next: Any) -> Response:
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
FEATURES = {
    "prolong_wait": "Услуга ожидает оплаты",
    "autoprolong_disabled": "Автопродление выключено",
    "insufficient_balance": "Не хватает средств",
    "failed_prolong_payment": "Не прошла оплата продления",
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


def _customers_with_scores() -> list[dict[str, Any]]:
    model = database.model_settings()
    return [evaluate_customer(customer, model) for customer in database.customer_rows()]


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
        "due_revenue_minor": customer["due_revenue_minor"],
        "potential_loss_minor": customer["potential_loss_minor"],
        "account_risk_sum": customer["account_risk_sum"],
        "max_service_score": customer["max_service_score"],
        "high_count": customer["high_count"],
        "revenue_at_risk_minor": customer["revenue_at_risk_minor"],
        "uncovered_revenue_at_risk_minor": customer["uncovered_revenue_at_risk_minor"],
    }


def _summary() -> dict[str, Any]:
    customers = _customers_with_scores()
    counts = {"high": 0, "medium": 0, "low": 0, "unscored": 0}
    for customer in customers:
        level = customer["risk_level"] or "unscored"
        counts[level] += 1
    model = database.model_settings()
    source = database.source_info()
    return {
        "customers_total": len(customers),
        "assessed_total": len(customers) - counts["unscored"],
        "risk_counts": counts,
        "potential_loss_minor": sum(customer["potential_loss_minor"] for customer in customers),
        "currency": "EUR",
        "prediction_horizon_days": model["prediction_horizon_days"],
        "source_kind": source.get("source_kind", "demo"),
        "source_updated_at": source.get("source_updated_at"),
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/healthz", tags=["system"], summary="Проверка доступности API")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
    return {
        "username": user["username"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
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
    if not first_name or not last_name:
        raise HTTPException(status_code=422, detail="Укажите имя и фамилию.")
    if len(first_name) > 60 or len(last_name) > 60:
        raise HTTPException(status_code=422, detail="Имя и фамилия должны быть не длиннее 60 символов.")
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
    sort_by: Literal["id", "email", "balance", "total_replenished", "risk_score", "potential_loss"] = "risk_score",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    customers = [_customer_list_item(customer) for customer in _customers_with_scores()]
    if query:
        needle = query.casefold()
        customers = [
            customer for customer in customers
            if needle in customer["email"].casefold() or needle in customer["id"].casefold()
        ]
    if risk_level:
        customers = [
            customer for customer in customers
            if (customer["risk_level"] or "unscored") == risk_level
        ]

    sort_fields = {
        "id": "id",
        "email": "email",
        "balance": "balance_minor",
        "total_replenished": "total_replenished_minor",
        "risk_score": "risk_score",
        "potential_loss": "potential_loss_minor",
    }
    field = sort_fields[sort_by]
    present = [customer for customer in customers if customer[field] is not None]
    missing = [customer for customer in customers if customer[field] is None]
    if sort_by == "id":
        sort_key = lambda customer: (0, int(customer[field])) if customer[field].isdigit() else (1, customer[field].casefold())
    else:
        sort_key = lambda customer: customer[field].casefold() if isinstance(customer[field], str) else customer[field]
    present.sort(key=sort_key, reverse=order == "desc")
    customers = present + missing
    total = len(customers)
    return {
        "items": customers[offset:offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "order": order,
    }


@app.get("/api/v1/customers/{customer_id}", tags=["customers"], summary="Подробности риска клиента", response_model=CustomerDetail)
def get_customer(
    customer_id: str,
    _: str = Depends(require_session),
) -> dict[str, Any]:
    for customer in _customers_with_scores():
        if customer["id"] != customer_id:
            continue
        customer["service_count"] = len(customer["services"])
        for service in customer["services"]:
            service["price_minor"] = int(service["price_minor"])
        return customer
    raise HTTPException(status_code=404, detail="Клиент не найден.")


@app.get("/api/v1/analytics/summary", tags=["analytics"], summary="Сводка риска и денежной оценки", response_model=AnalyticsSummary)
def analytics_summary(_: str = Depends(require_session)) -> dict[str, Any]:
    return _summary()


@app.get("/api/v1/model/settings", tags=["model"], summary="Действующие коэффициенты модели", response_model=ModelSettingsResponse, response_model_exclude_none=True)
def get_model_settings(_: str = Depends(require_session)) -> dict[str, Any]:
    return {**database.model_settings(), "features": FEATURES}


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
        unknown = set(weights) - set(DEFAULT_MODEL_SETTINGS["weights"])
        if unknown:
            raise HTTPException(status_code=422, detail="В запросе есть неизвестный признак риска.")
        if any(value < 0 or value > 100 for value in weights.values()):
            raise HTTPException(status_code=422, detail="Вес признака должен быть от 0 до 100.")
        current["weights"].update(weights)
    current.update(changes)
    if current["high_risk_min"] <= current["medium_risk_min"]:
        raise HTTPException(status_code=422, detail="Порог высокого риска должен быть выше среднего.")

    database.save_model_settings(current)
    await events.publish({"type": "model_settings_changed", "changed_at": datetime.now(timezone.utc).isoformat()})
    return {
        **current,
        "features": FEATURES,
        "recalculated": True,
        "changed_at": datetime.now(timezone.utc).isoformat(),
    }


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
    database.replace_snapshot(normalized)
    await events.publish({"type": "source_snapshot_changed", "changed_at": datetime.now(timezone.utc).isoformat()})
    return {
        "accepted": True,
        "customers_received": len(normalized),
        "summary": _summary(),
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

    result = _summary()
    lines = [
        "# HELP aeza_customers_total Number of customers by risk level.",
        "# TYPE aeza_customers_total gauge",
    ]
    for level, count in result["risk_counts"].items():
        lines.append(f'aeza_customers_total{{risk_level="{level}"}} {count}')
    amount_eur = result["potential_loss_minor"] / 100
    lines.extend([
        "# HELP aeza_revenue_at_risk_eur Estimated uncovered renewal revenue weighted by risk.",
        "# TYPE aeza_revenue_at_risk_eur gauge",
        f"aeza_revenue_at_risk_eur {amount_eur:.2f}",
        "# HELP aeza_customers_assessed_total Number of customers with a calculated score.",
        "# TYPE aeza_customers_assessed_total gauge",
        f"aeza_customers_assessed_total {result['assessed_total']}",
    ])
    return PlainTextResponse("\n".join(lines) + "\n", headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"})
