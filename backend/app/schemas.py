from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

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
    # Known values: active, suspended, prolong_wait, deleted, blocked. Unknown values are kept
    # and reported in data_quality instead of rejecting the whole snapshot.
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
    # Known values: performed, not_performed / prolong, order. Unknown values are reported, not rejected.
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

    customers: list[CustomerSnapshot] = Field(max_length=5_000)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=120)
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    middle_name: str | None = Field(default=None, max_length=120)
    password: str = Field(min_length=1, max_length=256)
    password_confirm: str = Field(min_length=1, max_length=256)
    codeword: str = Field(min_length=1, max_length=256)


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
    # Account indices are sums of service indices, so the thresholds may exceed 100.
    high_risk_min: int | None = Field(default=None, ge=1, le=100)
    medium_risk_min: int | None = Field(default=None, ge=0, le=99)
    account_high_risk_min: int | None = Field(default=None, ge=1, le=1_000)
    account_medium_risk_min: int | None = Field(default=None, ge=0, le=999)
    weights: dict[str, int] | None = Field(default=None, max_length=4)


class SsoMethod(BaseModel):
    enabled: bool
    label: str


class AuthMethodsResponse(BaseModel):
    password: bool
    registration: bool
    sso: SsoMethod


class RecommendedAction(BaseModel):
    code: str
    text: str


class RiskReason(BaseModel):
    code: str
    title: str
    # Points are the factor's share of the 0-100 index, with one decimal.
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
    account_risk_sum: float | None
    max_service_score: float | None
    high_count: int
    unscored_services_count: int
    data_issues_count: int


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
    account_risk_sum: float | None
    max_service_score: float | None
    high_count: int
    revenue_at_risk_minor: int
    potential_loss_minor: int
    monthly_cost_minor: int


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


class UserResponse(BaseModel):
    username: str
    first_name: str
    last_name: str
    middle_name: str | None = None
    full_name: str
    role: str


class PasswordResetTokenResponse(BaseModel):
    reset_token: str
    expires_at: datetime


class LoginResponse(BaseModel):
    user: UserResponse
    expires_at: datetime


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
    potential_loss_minor: int


class AnalyticsSummary(BaseModel):
    customers_total: int
    assessed_total: int
    risk_counts: dict[str, int]
    reason_counts: dict[str, int]
    potential_loss_by_level_minor: dict[str, int]
    top_exposure: list[ExposureItem]
    potential_loss_minor: int
    revenue_at_risk_minor: int
    monthly_cost_minor: int
    currency: str
    prediction_horizon_days: int
    source_kind: str
    source_updated_at: datetime | None
    snapshot_id: str | None
    calculation_version: str
    calculated_at: datetime


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
    services_at_risk: int
    expected_non_renewals: float
    expected_loss_minor: int


class WaitingNow(BaseModel):
    services: int
    expected_non_renewals: float
    expected_loss_minor: int


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

