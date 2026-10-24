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


class ServiceStatus(str, Enum):
    active = "active"
    suspended = "suspended"
    prolong_wait = "prolong_wait"
    deleted = "deleted"
    blocked = "blocked"


class TransactionStatus(str, Enum):
    performed = "performed"
    not_performed = "not_performed"


class TransactionType(str, Enum):
    prolong = "prolong"
    order = "order"


class ServiceSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True, use_enum_values=True, extra="forbid")

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
    status: ServiceStatus
    expires_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("expires_at", "expiresAt"),
    )

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> str | None:
        return _normalize_optional_identifier(value)


class TransactionSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True, use_enum_values=True, extra="forbid")

    id: str | None = Field(default=None, min_length=1, max_length=120)
    service_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        validation_alias=AliasChoices("service_id", "serviceId"),
    )
    status: TransactionStatus
    type: TransactionType
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
    model_config = ConfigDict(populate_by_name=True, use_enum_values=True, extra="forbid")

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
    services: list[ServiceSnapshot] = Field(default_factory=list, max_length=200)
    transactions: list[TransactionSnapshot] = Field(default_factory=list, max_length=250)

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> str:
        return _normalize_identifier(value)


class SnapshotUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customers: list[CustomerSnapshot] = Field(max_length=5_000)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)


class ModelSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_horizon_days: int | None = Field(default=None, ge=1, le=365)
    urgency_days: int | None = Field(default=None, ge=1, le=30)
    grace_days: int | None = Field(default=None, ge=1, le=14)
    high_risk_min: int | None = Field(default=None, ge=1, le=100)
    medium_risk_min: int | None = Field(default=None, ge=0, le=99)
    customer_high_risk_min: int | None = Field(default=None, ge=1, le=20_000)
    customer_medium_risk_min: int | None = Field(default=None, ge=0, le=19_999)
    weights: dict[str, int] | None = Field(default=None, max_length=4)


class RiskReason(BaseModel):
    code: str
    title: str
    points: float
    explanation: str
    service_ids: list[str] = Field(default_factory=list)


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
    due_revenue_minor: int
    potential_loss_minor: int
    max_service_score: float | None = None
    at_risk_services_count: int = 0
    medium_or_high_services_count: int = 0
    uncovered_potential_loss_minor: int = 0


class CustomerListResponse(BaseModel):
    items: list[CustomerListItem]
    total: int
    limit: int
    offset: int
    sort_by: str
    order: str


class ServiceDetail(BaseModel):
    id: str
    name: str
    price_minor: int
    auto_prolong: bool
    payment_term: str | None
    status: str
    expires_at: datetime | None
    risk_score: float | None = None
    risk_level: str | None = None
    assessment_status: str | None = None
    factors: list[dict[str, Any]] = Field(default_factory=list)
    scheduled_minor: int | None = None
    uncovered_minor: int | None = None


class TransactionDetail(BaseModel):
    id: str
    service_id: str | None
    status: str
    type: str
    amount_minor: int
    created_at: datetime | None


class CustomerCalculation(BaseModel):
    horizon_days: int
    due_revenue_minor: int
    available_balance_minor: int
    uncovered_revenue_minor: int
    risk_score_index: float | None
    potential_loss_minor: int
    uncovered_potential_loss_minor: int = 0
    estimate_kind: str = "expert_weighted_renewal_scenario_not_expected_loss"


class CustomerDetail(CustomerListItem):
    services: list[ServiceDetail]
    transactions: list[TransactionDetail]
    due_revenue_minor: int
    available_balance_minor: int
    uncovered_revenue_minor: int
    assessed_at: datetime
    calculation: CustomerCalculation


class UserResponse(BaseModel):
    username: str
    role: str


class LoginResponse(BaseModel):
    user: UserResponse
    expires_at: datetime


class ModelSettingsResponse(BaseModel):
    prediction_horizon_days: int
    urgency_days: int
    grace_days: int
    high_risk_min: int
    medium_risk_min: int
    customer_high_risk_min: int
    customer_medium_risk_min: int
    weights: dict[str, int]
    features: dict[str, str]
    recalculated: bool | None = None
    changed_at: datetime | None = None


class AnalyticsSummary(BaseModel):
    customers_total: int
    assessed_total: int
    risk_counts: dict[str, int]
    potential_loss_minor: int
    uncovered_potential_loss_minor: int = 0
    currency: str
    prediction_horizon_days: int
    source_kind: str
    source_updated_at: datetime | None
    calculated_at: datetime


class SnapshotImportResponse(BaseModel):
    accepted: bool
    customers_received: int
    summary: AnalyticsSummary
