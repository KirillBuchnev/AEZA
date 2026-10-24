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
    model_config = ConfigDict(populate_by_name=True, use_enum_values=True, extra="ignore")

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
    high_risk_min: int | None = Field(default=None, ge=1, le=100)
    medium_risk_min: int | None = Field(default=None, ge=0, le=99)
    weights: dict[str, int] | None = Field(default=None, max_length=4)


class RiskReason(BaseModel):
    code: str
    title: str
    # A contribution changes with time-to-renewal, balance shortfall and grace
    # progress; keeping one decimal prevents fixed stepwise buckets.
    points: float
    explanation: str


class CustomerListItem(BaseModel):
    id: str
    email: str
    balance_minor: int
    withdraw_balance_minor: int
    bonus_balance_minor: int
    bonus_spend_enabled: bool
    total_replenished_minor: int
    service_count: int
    risk_score: int | None
    risk_level: str | None
    risk_label: str
    reasons: list[RiskReason]
    due_revenue_minor: int
    potential_loss_minor: int
    account_risk_sum: int | None
    max_service_score: int | None
    high_count: int
    revenue_at_risk_minor: int
    uncovered_revenue_at_risk_minor: int


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
    risk_score: int | None
    risk_level: str | None
    risk_label: str
    reasons: list[RiskReason]
    due_revenue_minor: int
    available_balance_minor: int
    uncovered_revenue_minor: int
    potential_loss_minor: int
    revenue_at_risk_minor: int
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
    due_revenue_minor: int
    available_balance_minor: int
    uncovered_revenue_minor: int
    risk_score_index: int | None
    account_risk_sum: int | None
    max_service_score: int | None
    high_count: int
    revenue_at_risk_minor: int
    uncovered_revenue_at_risk_minor: int
    potential_loss_minor: int


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
    first_name: str
    last_name: str
    role: str


class PasswordResetTokenResponse(BaseModel):
    reset_token: str
    expires_at: datetime


class LoginResponse(BaseModel):
    user: UserResponse
    expires_at: datetime


class ModelSettingsResponse(BaseModel):
    version: int
    prediction_horizon_days: int
    high_risk_min: int
    medium_risk_min: int
    weights: dict[str, int]
    formula: dict[str, int]
    features: dict[str, str]
    recalculated: bool | None = None
    changed_at: datetime | None = None


class AnalyticsSummary(BaseModel):
    customers_total: int
    assessed_total: int
    risk_counts: dict[str, int]
    potential_loss_minor: int
    currency: str
    prediction_horizon_days: int
    source_kind: str
    source_updated_at: datetime | None
    calculated_at: datetime


class SnapshotImportResponse(BaseModel):
    accepted: bool
    customers_received: int
    summary: AnalyticsSummary
