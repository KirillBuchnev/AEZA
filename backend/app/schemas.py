from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_MONEY_MINOR = 9_000_000_000_000


def _normalize_identifier(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("identifier must be a string or integer")
    return str(value).strip()


def _normalize_optional_identifier(value: Any) -> str | None:
    return None if value is None else _normalize_identifier(value)


class ServiceSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True, use_enum_values=True, extra="ignore")

    id: str | None = Field(default=None, min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    price_minor: int = Field(ge=0, le=MAX_MONEY_MINOR, validation_alias=AliasChoices("price_minor", "price"))
    auto_prolong: bool = Field(
        validation_alias=AliasChoices("auto_prolong", "autoprolong", "autoProlong")
    )
    payment_term: str | None = Field(
        default=None,
        max_length=120,
        validation_alias=AliasChoices("payment_term", "paymentTerm"),
    )
    # Известные значения: active, suspended, prolong_wait, deleted, blocked. Неизвестные сохраняются
    # и попадают в data_quality вместо отклонения всего снапшота.
    status: str = Field(min_length=1, max_length=40)
    expires_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("expires_at", "expiresAt"),
    )

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> str | None:
        return _normalize_optional_identifier(value)


class TransactionSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True, use_enum_values=True, extra="ignore")

    id: str | None = Field(default=None, min_length=1, max_length=120)
    service_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        validation_alias=AliasChoices("service_id", "serviceId"),
    )
    # Известные значения: performed, not_performed / prolong, order. Неизвестные сообщаются, а не отклоняются.
    status: str = Field(min_length=1, max_length=40)
    type: str = Field(min_length=1, max_length=40)
    amount_minor: int = Field(ge=0, le=MAX_MONEY_MINOR, validation_alias=AliasChoices("amount_minor", "amount"))
    created_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("created_at", "createdAt"),
    )

    @field_validator("id", "service_id", mode="before")
    @classmethod
    def normalize_optional_ids(cls, value: Any) -> str | None:
        return _normalize_optional_identifier(value)


class CustomerSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True, use_enum_values=True, extra="ignore")

    id: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    balance_minor: int = Field(ge=0, le=MAX_MONEY_MINOR, validation_alias=AliasChoices("balance_minor", "balance"))
    withdraw_balance_minor: int = Field(
        default=0,
        ge=0,
        le=MAX_MONEY_MINOR,
        validation_alias=AliasChoices("withdraw_balance_minor", "withdrawBalance"),
    )
    bonus_balance_minor: int = Field(
        default=0,
        ge=0,
        le=MAX_MONEY_MINOR,
        validation_alias=AliasChoices("bonus_balance_minor", "bonusBalance"),
    )
    bonus_spend_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("bonus_spend_enabled", "bonusState"),
    )
    total_replenished_minor: int = Field(
        default=0,
        ge=0,
        le=MAX_MONEY_MINOR,
        validation_alias=AliasChoices("total_replenished_minor", "totalReplenished"),
    )
    services: list[ServiceSnapshot] = Field(default_factory=list, max_length=5_000)
    transactions: list[TransactionSnapshot] = Field(default_factory=list, max_length=10_000)

    @field_validator("bonus_spend_enabled", mode="before")
    @classmethod
    def normalize_bonus_state(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"unlocked", "enabled", "true", "1", "yes", "on"}:
                return True
            if normalized in {"locked", "disabled", "false", "0", "no", "off"}:
                return False
        raise ValueError("bonusState must be a boolean or unlocked/locked")

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> str:
        return _normalize_identifier(value)


class SnapshotUpload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    customers: list[CustomerSnapshot] = Field(default_factory=list, max_length=5_000)
    # Плоский экспорт организатора принимается тем же эндпоинтом и нормализуется ниже.
    accounts: list[dict[str, Any]] | None = Field(default=None, max_length=5_000)
    services: list[dict[str, Any]] | None = Field(default=None, max_length=25_000)
    transactions: list[dict[str, Any]] | None = Field(default=None, max_length=50_000)

    @model_validator(mode="before")
    @classmethod
    def normalize_flat_source_export(cls, value: Any) -> Any:
        """Принимает плоский data.json организаторов наряду с вложенным форматом API."""
        if not isinstance(value, dict) or value.get("customers") is not None:
            return value
        accounts = value.get("accounts")
        services = value.get("services")
        transactions = value.get("transactions")
        if not isinstance(accounts, list) or not isinstance(services, list) or not isinstance(transactions, list):
            return value

        services_by_owner: dict[str, list[dict[str, Any]]] = {}
        owner_by_service: dict[str, str] = {}
        for service in services:
            if not isinstance(service, dict):
                continue
            service_id = str(service.get("id"))
            owner_id = str(service.get("ownerId"))
            owner_by_service[service_id] = owner_id
            services_by_owner.setdefault(owner_id, []).append({
                "id": service.get("id"),
                "name": service.get("name"),
                "price": service.get("price"),
                "autoprolong": service.get("autoProlong"),
                "paymentTerm": service.get("paymentTerm"),
                "status": service.get("status"),
                "expiresAt": service.get("expiresAt"),
            })

        transactions_by_owner: dict[str, list[dict[str, Any]]] = {}
        for transaction in transactions:
            if not isinstance(transaction, dict):
                continue
            service_id = str(transaction.get("serviceId"))
            owner_id = owner_by_service.get(service_id)
            if owner_id is None:
                raise ValueError(f"Транзакция {transaction.get('id')} ссылается на неизвестную услугу")
            transactions_by_owner.setdefault(owner_id, []).append({
                "id": transaction.get("id"),
                "serviceId": transaction.get("serviceId"),
                "status": transaction.get("status"),
                "type": transaction.get("type"),
                "amount": transaction.get("amount"),
                "createdAt": transaction.get("createdAt"),
            })

        customers = []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            account_id = str(account.get("id"))
            customers.append({
                "id": account.get("id"),
                "email": account.get("email"),
                "balance": account.get("balance"),
                "withdrawBalance": account.get("withdrawBalance", 0),
                "bonusBalance": account.get("bonusBalance", 0),
                "bonusState": account.get("bonusState", "locked"),
                "totalReplenished": account.get("totalReplenished", 0),
                "services": services_by_owner.get(account_id, []),
                "transactions": transactions_by_owner.get(account_id, []),
            })
        return {"customers": customers}


class CustomerPatch(BaseModel):
    """Поля, которые оператор может исправить, не заменяя весь снапшот источника."""

    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, min_length=3, max_length=254)
    balance_minor: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    withdraw_balance_minor: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    bonus_balance_minor: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    bonus_spend_enabled: bool | None = None
    total_replenished_minor: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)


class ServicePatch(BaseModel):
    """Редактируемые поля услуги для сценария исправления качества данных."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=160)
    price_minor: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    auto_prolong: bool | None = None
    payment_term: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    expires_at: datetime | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)


class VerifyCodewordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=120)
    codeword: str = Field(min_length=1, max_length=256)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset_token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)
    new_password_confirm: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)
    new_password_confirm: str = Field(min_length=1, max_length=256)


class ModelSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_horizon_days: int | None = Field(default=None, ge=1, le=365)
    # Индекс аккаунта — 0-100, как и индекс услуги, поэтому обе пары порогов живут на одной шкале.
    high_risk_min: int | None = Field(default=None, ge=1, le=100)
    medium_risk_min: int | None = Field(default=None, ge=0, le=99)
    account_high_risk_min: int | None = Field(default=None, ge=1, le=100)
    account_medium_risk_min: int | None = Field(default=None, ge=0, le=99)
    weights: dict[str, int] | None = Field(default=None, max_length=4)


class SsoMethod(BaseModel):
    enabled: bool
    label: str


class AuthMethodsResponse(BaseModel):
    password: bool
    sso: SsoMethod


class RecommendedAction(BaseModel):
    code: str
    text: str


class ActionSegment(BaseModel):
    code: str
    title: str
    reason: str


class ActionStep(BaseModel):
    when: str
    text: str


class ActionPlan(BaseModel):
    """Решение для маркетолога: диагноз, деньги, дедлайн и следующее действие."""

    archetype: str
    title: str
    priority: float
    diagnosis: str
    next_best_action: str
    message_template: str
    expected_revenue_at_risk_minor: int
    deadline: datetime | None = None
    confidence: float
    evidence: dict[str, Any] = Field(default_factory=dict)
    message_subject: str = ""
    urgency_label: str = ""
    segment: ActionSegment | None = None
    channel: str = ""
    offer: str | None = None
    signals: list[str] = Field(default_factory=list)
    steps: list[ActionStep] = Field(default_factory=list)


class LtvSummary(BaseModel):
    """Объяснимый LTV-прокси; сознательно называется прокси, пока нет фактических исходов."""

    current_mrr_minor: int = 0
    historical_revenue_minor: int = 0
    historical_months: float = 0.0
    expected_lifetime_months: float = 0.0
    gross_ltv_minor: int = 0
    at_risk_ltv_minor: int = 0
    payment_success_rate: float | None = None
    confidence: float = 0.0
    method: str = "risk-adjusted recurring revenue proxy"


class RiskReason(BaseModel):
    code: str
    title: str
    # Баллы — доля фактора в индексе 0-100, с одним десятичным знаком.
    points: float
    explanation: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class DataQualityIssue(BaseModel):
    code: str
    service_id: str | None = None
    message: str


class CustomerListItem(BaseModel):
    id: str
    email: str
    balance_minor: int
    withdraw_balance_minor: int
    bonus_balance_minor: int
    bonus_spend_enabled: bool
    total_replenished_minor: int
    service_count: int
    risk_score: float | None
    risk_level: str | None
    risk_label: str
    reasons: list[RiskReason]
    recommended_action: RecommendedAction
    due_revenue_minor: int
    monthly_cost_minor: int
    potential_loss_minor: int
    revenue_at_risk_minor: int
    near_term_loss_minor: int
    account_risk_sum: float | None
    real_revenue_at_risk_minor: int = 0
    real_near_term_loss_minor: int = 0
    action_plan: ActionPlan
    loyalty_score: float | None = None
    ltv: LtvSummary = Field(default_factory=LtvSummary)
    max_service_score: float | None
    high_count: int
    unscored_services_count: int
    data_issues_count: int
    data_coverage: float = 0.0
    risky_service_count: int = 0
    service_risk_share: float = 0.0
    service_count_adjustment: float = 1.0


class CustomerListResponse(BaseModel):
    items: list[CustomerListItem]
    total: int
    limit: int
    offset: int
    sort_by: str
    order: str
    snapshot_id: str | None
    calculation_version: str
    as_of: datetime


class ServiceDetail(BaseModel):
    id: str
    name: str
    price_minor: int
    auto_prolong: bool
    payment_term: str | None
    status: str
    expires_at: datetime | None
    risk_score: float | None
    risk_level: str | None
    risk_label: str
    reasons: list[RiskReason]
    recommended_action: RecommendedAction
    data_issue: str | None
    due: bool
    recent_failed_payment: bool
    due_revenue_minor: int
    available_balance_minor: int
    uncovered_revenue_minor: int
    potential_loss_minor: int
    revenue_at_risk_minor: int
    near_term_loss_minor: int
    monthly_cost_minor: int
    grace_remaining_days: int | None


class TransactionDetail(BaseModel):
    id: str
    service_id: str | None
    status: str
    type: str
    amount_minor: int
    created_at: datetime | None


class CustomerCalculation(BaseModel):
    horizon_days: int
    normalizer: int
    weights: dict[str, int]
    due_revenue_minor: int
    available_balance_minor: int
    uncovered_revenue_minor: int
    risk_score_index: float | None
    data_coverage: float = 0.0
    account_risk_sum: float | None
    max_service_score: float | None
    high_count: int
    revenue_at_risk_minor: int
    near_term_loss_minor: int
    potential_loss_minor: int
    monthly_cost_minor: int
    real_revenue_at_risk_minor: int = 0
    real_near_term_loss_minor: int = 0
    loyalty_score: float | None = None
    ltv: LtvSummary = Field(default_factory=LtvSummary)
    cashflow: dict[str, Any] = Field(default_factory=dict)
    real_monetisation_alpha: float = 1.0
    risky_service_count: int = 0
    service_risk_share: float = 0.0
    service_count_adjustment: float = 1.0


class CustomerDetail(CustomerListItem):
    services: list[ServiceDetail]
    transactions: list[TransactionDetail]
    data_quality: list[DataQualityIssue]
    available_balance_minor: int
    uncovered_revenue_minor: int
    assessed_at: datetime
    snapshot_id: str | None
    calculation_version: str
    calculation: CustomerCalculation
    cashflow: dict[str, Any] = Field(default_factory=dict)
    real_monetisation_alpha: float = 1.0


class UserResponse(BaseModel):
    username: str
    first_name: str
    last_name: str
    middle_name: str | None = None
    full_name: str
    role: str
    # False у сотрудников, которые входят только через SSO: панель скрывает для них смену пароля.
    has_password: bool = True


class PasswordResetTokenResponse(BaseModel):
    reset_token: str
    expires_at: datetime


class LoginResponse(BaseModel):
    user: UserResponse
    expires_at: datetime


class AdminUserCreate(BaseModel):
    """Сотрудника заводит администратор, а затем он входит через SSO."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=120)
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    middle_name: str | None = Field(default=None, max_length=60)
    role: Literal["analyst", "admin"] = "analyst"


class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["analyst", "admin"] | None = None
    active: bool | None = None


class AdminUserItem(BaseModel):
    username: str
    first_name: str
    last_name: str
    middle_name: str | None = None
    full_name: str
    role: str
    active: bool
    has_password: bool
    created_at: str


class AdminUsersResponse(BaseModel):
    items: list[AdminUserItem]


class FeatureDescription(BaseModel):
    code: str
    title: str
    description: str
    weight: int


class ControlCase(BaseModel):
    key: str
    title: str
    risk_score: float | None
    risk_level: str | None
    expected_level: str
    matches: bool


class ModelSettingsResponse(BaseModel):
    version: int
    revision: int
    calculation_version: str
    prediction_horizon_days: int
    high_risk_min: int
    medium_risk_min: int
    account_high_risk_min: int
    account_medium_risk_min: int
    weights: dict[str, int]
    normalizer: int
    features: list[FeatureDescription]
    control_cases: list[ControlCase]
    recalculated: bool | None = None
    changed_at: datetime | None = None


class DataQualityReport(BaseModel):
    customers_total: int
    customers_unscored: int
    issues: dict[str, int]


class ExposureItem(BaseModel):
    id: str
    email: str
    revenue_at_risk_minor: int
    near_term_loss_minor: int
    potential_loss_minor: int


class AnalyticsSummary(BaseModel):
    customers_total: int
    assessed_total: int
    risk_counts: dict[str, int]
    reason_counts: dict[str, int]
    potential_loss_by_level_minor: dict[str, int]
    revenue_at_risk_by_level_minor: dict[str, int]
    top_exposure: list[ExposureItem]
    exposed_services: int
    potential_loss_minor: int
    revenue_at_risk_minor: int
    near_term_loss_minor: int
    monthly_cost_minor: int
    currency: str
    prediction_horizon_days: int
    source_kind: str
    source_updated_at: datetime | None
    snapshot_id: str | None
    calculation_version: str
    calculated_at: datetime
    ltv_total_minor: int = 0
    ltv_at_risk_minor: int = 0
    ltv_by_level_minor: dict[str, int] = Field(default_factory=dict)


class SnapshotImportResponse(BaseModel):
    accepted: bool
    customers_received: int
    snapshot_id: str
    events_recorded: int
    data_quality: DataQualityReport
    summary: AnalyticsSummary


class OutflowFactDay(BaseModel):
    date: str
    removed: int
    deleted: int
    blocked: int
    renewed: int
    entered_wait: int
    deleted_amount_minor: int


class OutflowFacts(BaseModel):
    source: str
    estimated: bool = False
    from_date: str
    to_date: str
    snapshots_observed: int
    days: list[OutflowFactDay]
    totals: dict[str, int]


class OutflowForecastDay(BaseModel):
    date: str
    services_due: int
    services_waiting: int = 0
    services_at_risk: int
    expected_non_renewals: float
    expected_loss_minor: int


class WaitingNow(BaseModel):
    services: int
    expected_non_renewals: float
    expected_loss_minor: int
    beyond_grace_services: int = 0


class OutflowForecast(BaseModel):
    method: str
    horizon_days: int
    from_date: str
    buckets: list[OutflowForecastDay]
    waiting_now: WaitingNow
    totals: dict[str, float]


class ServicesAtRisk(BaseModel):
    total: int
    high: int
    medium: int


class OutflowResponse(BaseModel):
    as_of: datetime
    snapshot_id: str | None
    calculation_version: str
    facts: OutflowFacts
    forecast: OutflowForecast
    services_at_risk: ServicesAtRisk

