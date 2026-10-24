from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any


ACTION_HORIZON_DAYS = 7
GRACE_PERIOD_DAYS = 5
MODEL_VERSION = 2

DEFAULT_MODEL_SETTINGS: dict[str, Any] = {
    "version": MODEL_VERSION,
    "prediction_horizon_days": 30,
    "high_risk_min": 50,
    "medium_risk_min": 30,
    "weights": {
        # The four visible controls map to the explainable service formula.
        "prolong_wait": 5,
        "autoprolong_disabled": 45,
        "insufficient_balance": 40,
        "failed_prolong_payment": 20,
    },
    "formula": {
        "normalizer": 110,
        "urgency_weight": 20,
        "action_horizon_days": ACTION_HORIZON_DAYS,
        "grace_period_days": GRACE_PERIOD_DAYS,
    },
}

ELIGIBLE_STATUSES = {"active", "suspended", "prolong_wait"}


def merge_model_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Return a complete model contract while tolerating older SQLite rows."""
    current = settings or {}
    weights = {
        **DEFAULT_MODEL_SETTINGS["weights"],
        **(current.get("weights") or {}),
    }
    formula = {
        **DEFAULT_MODEL_SETTINGS["formula"],
        **(current.get("formula") or {}),
    }
    return {
        **DEFAULT_MODEL_SETTINGS,
        **current,
        "version": MODEL_VERSION,
        "weights": weights,
        "formula": formula,
    }


def _as_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _money(value: int | None) -> int:
    return int(value or 0)


def _clip(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _points(value: float) -> float:
    """Keep the explainable contribution precise without exposing float noise."""
    rounded = round(value, 1)
    return 0.0 if abs(rounded) < 0.05 else rounded


def _urgency(expires_at: datetime | None, now: datetime, horizon_days: int) -> float:
    if expires_at is None:
        return 0.0
    seconds_until_expiry = (expires_at - now).total_seconds()
    return _clip(1 - seconds_until_expiry / (horizon_days * 86400))


def _grace_progress(
    expires_at: datetime | None,
    now: datetime,
    grace_period_days: int,
) -> tuple[float, int | None]:
    if expires_at is None:
        return 0.0, None
    elapsed_days = max(0.0, (now - expires_at).total_seconds() / 86400)
    progress = _clip(elapsed_days / grace_period_days)
    remaining = max(0, ceil(grace_period_days - elapsed_days))
    return progress, remaining


def _transaction_is_recent(transaction: dict[str, Any], service_id: str, now: datetime) -> bool:
    if transaction.get("type") != "prolong" or transaction.get("status") != "not_performed":
        return False
    created_at = _as_utc(transaction.get("created_at"))
    if created_at is None or created_at < now - timedelta(days=ACTION_HORIZON_DAYS):
        return False
    transaction_service_id = transaction.get("service_id")
    return transaction_service_id in {None, service_id}


def _risk_label(level: str | None) -> str:
    return {
        "high": "Высокий",
        "medium": "Средний",
        "low": "Низкий",
        None: "Нет оценки",
    }[level]


def _risk_level(score: int | None, model: dict[str, Any]) -> str | None:
    if score is None:
        return None
    if score >= model["high_risk_min"]:
        return "high"
    if score >= model["medium_risk_min"]:
        return "medium"
    return "low"


def _signal_title(code: str) -> str:
    return {
        "prolong_wait": "Услуга ожидает оплаты",
        "autoprolong_disabled": "Автопродление выключено",
        "insufficient_balance": "Не хватает средств",
        "failed_prolong_payment": "Не прошла оплата продления",
        "no_active_signals": "Активных сигналов риска нет",
        "insufficient_data": "Недостаточно данных",
    }[code]


def _allocate_balance(
    due_services: list[dict[str, Any]], available_balance: int
) -> dict[str, int]:
    """Allocate a shared account balance deterministically by the nearest due date."""
    remaining = available_balance
    allocation: dict[str, int] = {}
    for service in due_services:
        price = _money(service["price_minor"])
        applied = min(remaining, price)
        allocation[str(service["id"])] = max(0, price - applied)
        remaining -= applied
    return allocation


def evaluate_customer(
    customer: dict[str, Any],
    model: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    model = merge_model_settings(model)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    horizon_end = now + timedelta(days=model["prediction_horizon_days"])
    services = customer["services"]
    transactions = customer["transactions"]
    eligible = [service for service in services if service["status"] in ELIGIBLE_STATUSES]
    missing_expiry = [
        service
        for service in eligible
        if service["status"] != "prolong_wait" and not service["expires_at"]
    ]
    expired_active = [
        service
        for service in eligible
        if service["status"] != "prolong_wait"
        and service["expires_at"]
        and (_as_utc(service["expires_at"]) or now) < now
    ]
    assessable = bool(eligible) and not missing_expiry and not expired_active

    due_services: list[dict[str, Any]] = []
    for service in eligible:
        expires_at = _as_utc(service["expires_at"])
        if service["status"] == "prolong_wait":
            due_services.append(service)
        elif expires_at and now <= expires_at <= horizon_end:
            due_services.append(service)
    due_services.sort(
        key=lambda service: _as_utc(service.get("expires_at"))
        or datetime.max.replace(tzinfo=timezone.utc)
    )

    usable_bonus = (
        _money(customer["bonus_balance_minor"])
        if customer["bonus_spend_enabled"]
        else 0
    )
    available_balance = _money(customer["balance_minor"]) + usable_bonus
    due_revenue = sum(_money(service["price_minor"]) for service in due_services)
    uncovered_total = max(0, due_revenue - available_balance)
    service_shortfalls = _allocate_balance(due_services, available_balance)
    weights = model["weights"]
    formula = model["formula"]
    service_results: list[dict[str, Any]] = []

    for service in eligible:
        service_id = str(service["id"])
        expires_at = _as_utc(service.get("expires_at"))
        due = service in due_services
        urgency = _urgency(expires_at, now, formula["action_horizon_days"]) if due else 0.0
        manual_factor = (
            urgency
            if due and service["status"] != "prolong_wait" and not service["auto_prolong"]
            else 0.0
        )
        price = _money(service["price_minor"])
        shortfall = service_shortfalls.get(service_id, 0)
        payment_distress = _clip(shortfall / price) * urgency if price else 0.0
        renewal_urgency = urgency if manual_factor > 0 or payment_distress > 0 else 0.0
        grace_progress, grace_remaining_days = (
            _grace_progress(expires_at, now, formula["grace_period_days"])
            if service["status"] == "prolong_wait"
            else (0.0, None)
        )
        recent_failed_payment = any(
            _transaction_is_recent(transaction, service_id, now)
            for transaction in transactions
        )

        components = {
            "prolong_wait": weights["prolong_wait"] * grace_progress,
            "autoprolong_disabled": weights["autoprolong_disabled"] * manual_factor,
            "insufficient_balance": weights["insufficient_balance"] * payment_distress,
            "failed_prolong_payment": weights["failed_prolong_payment"]
            * (urgency if recent_failed_payment else 0),
            "renewal_urgency": formula["urgency_weight"] * renewal_urgency,
        }
        weighted_score = sum(components.values())
        score = round(_clip(weighted_score / formula["normalizer"], 0, 1) * 100)
        service_reasons: list[dict[str, Any]] = []
        point_scale = 100 / formula["normalizer"]

        # Renewal urgency is a dynamic multiplier in the formula, not a separate
        # step or hidden contribution. Attach it to the active user-facing signal;
        # if both signals are active, split it so displayed +points add up to the
        # same weighted score used for the index.
        urgency_shares = {
            "autoprolong_disabled": 0.0,
            "insufficient_balance": 0.0,
        }
        active_urgency_signals = [
            code for code, active in (
                ("autoprolong_disabled", manual_factor > 0),
                ("insufficient_balance", payment_distress > 0),
            ) if active
        ]
        if active_urgency_signals:
            share = components["renewal_urgency"] / len(active_urgency_signals)
            urgency_shares.update({code: share for code in active_urgency_signals})

        for code in (
            "prolong_wait",
            "autoprolong_disabled",
            "insufficient_balance",
            "failed_prolong_payment",
        ):
            points = _points(
                (components[code] + urgency_shares.get(code, 0.0)) * point_scale
            )
            active = {
                "prolong_wait": service["status"] == "prolong_wait",
                "autoprolong_disabled": manual_factor > 0,
                "insufficient_balance": payment_distress > 0,
                "failed_prolong_payment": recent_failed_payment and urgency > 0,
            }[code]
            if active:
                explanations = {
                    "prolong_wait": "Услуга уже ожидает оплаты после окончания срока.",
                    "autoprolong_disabled": "Продление ожидается в ближайшие дни, но автопродление выключено.",
                    "insufficient_balance": "Доступного баланса не хватит на продление этой услуги.",
                    "failed_prolong_payment": "За последние 7 дней есть неуспешная транзакция продления.",
                }
                service_reasons.append(
                    {
                        "code": code,
                        "title": _signal_title(code),
                        "points": points,
                        "explanation": explanations[code],
                    }
                )
        if not service_reasons:
            service_reasons.append(
                {
                    "code": "no_active_signals",
                    "title": _signal_title("no_active_signals"),
                    "points": 0.0,
                    "explanation": "Доступные данные не показывают признаков скорого непродления.",
                }
            )

        service_score = score if assessable else None
        service_level = _risk_level(service_score, model)
        service_exposure = (
            (price * score + 50) // 100
            if service_score is not None and due
            else 0
        )
        service_uncovered_exposure = (
            (shortfall * score + 50) // 100 if service_score is not None else 0
        )
        service_results.append(
            {
                **service,
                "risk_score": service_score,
                "risk_level": service_level,
                "risk_label": _risk_label(service_level),
                "reasons": service_reasons,
                "due_revenue_minor": price if due else 0,
                "available_balance_minor": max(0, price - shortfall) if due else 0,
                "uncovered_revenue_minor": shortfall,
                "potential_loss_minor": service_uncovered_exposure,
                "revenue_at_risk_minor": service_exposure,
                "grace_remaining_days": grace_remaining_days,
            }
        )

    scores = [
        service["risk_score"]
        for service in service_results
        if service["risk_score"] is not None
    ]
    account_risk_sum = sum(scores) if assessable else None
    max_service_score = max(scores) if scores else None
    high_count = (
        sum(service["risk_level"] == "high" for service in service_results)
        if assessable
        else 0
    )
    revenue_at_risk = sum(service["revenue_at_risk_minor"] for service in service_results)
    uncovered_revenue_at_risk = sum(
        service["potential_loss_minor"] for service in service_results
    )

    reasons: list[dict[str, Any]] = []
    if not assessable:
        if not eligible:
            message = "Нет активных или ожидающих продления услуг для оценки."
        elif expired_active:
            message = "У активной услуги дата окончания уже в прошлом — проверьте источник данных."
        else:
            message = "У одной или нескольких услуг не указана дата окончания."
        reasons.append(
            {
                "code": "insufficient_data",
                "title": _signal_title("insufficient_data"),
                "points": 0.0,
                "explanation": message,
            }
        )
        score = None
        risk_level = None
    else:
        score = max_service_score or 0
        reason_totals: dict[str, int] = {}
        reason_explanations: dict[str, str] = {}
        for service in service_results:
            for reason in service["reasons"]:
                if reason["code"] == "no_active_signals":
                    continue
                reason_totals[reason["code"]] = (
                    reason_totals.get(reason["code"], 0) + reason["points"]
                )
                reason_explanations[reason["code"]] = reason["explanation"]
        for code, points in reason_totals.items():
            reasons.append(
                {
                    "code": code,
                    "title": _signal_title(code),
                    "points": _points(min(points, 100)),
                    "explanation": reason_explanations[code],
                }
            )
        if not reasons:
            reasons.append(
                {
                    "code": "no_active_signals",
                    "title": _signal_title("no_active_signals"),
                    "points": 0.0,
                    "explanation": "Доступные данные не показывают признаков скорого непродления.",
                }
            )
        risk_level = _risk_level(score, model)

    return {
        **customer,
        "services": service_results,
        "risk_score": score,
        "risk_level": risk_level,
        "risk_label": _risk_label(risk_level),
        "reasons": reasons,
        "due_revenue_minor": due_revenue,
        "available_balance_minor": available_balance,
        "uncovered_revenue_minor": uncovered_total,
        "potential_loss_minor": uncovered_revenue_at_risk,
        "account_risk_sum": account_risk_sum,
        "max_service_score": max_service_score,
        "high_count": high_count,
        "revenue_at_risk_minor": revenue_at_risk,
        "uncovered_revenue_at_risk_minor": uncovered_revenue_at_risk,
        "assessed_at": now.isoformat(),
        "calculation": {
            "horizon_days": model["prediction_horizon_days"],
            "due_revenue_minor": due_revenue,
            "available_balance_minor": available_balance,
            "uncovered_revenue_minor": uncovered_total,
            "risk_score_index": score,
            "account_risk_sum": account_risk_sum,
            "max_service_score": max_service_score,
            "high_count": high_count,
            "revenue_at_risk_minor": revenue_at_risk,
            "uncovered_revenue_at_risk_minor": uncovered_revenue_at_risk,
            "potential_loss_minor": uncovered_revenue_at_risk,
        },
    }


def demo_snapshot() -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()

    def expiry(days: int) -> str:
        return datetime.combine(today + timedelta(days=days), datetime.min.time(), timezone.utc).isoformat()

    def service(
        service_id: str,
        name: str,
        price: int,
        auto: bool,
        status: str,
        days: int | None,
        term: str = "month",
    ) -> dict[str, Any]:
        return {
            "id": service_id,
            "name": name,
            "price_minor": price,
            "auto_prolong": auto,
            "payment_term": term,
            "status": status,
            "expires_at": expiry(days) if days is not None else None,
        }

    def customer(
        customer_id: str,
        email: str,
        balance: int,
        replenished: int,
        services: list[dict[str, Any]],
        transactions: list[dict[str, Any]] | None = None,
        bonus: int = 0,
        bonus_enabled: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": customer_id,
            "email": email,
            "balance_minor": balance,
            "withdraw_balance_minor": 0,
            "bonus_balance_minor": bonus,
            "bonus_spend_enabled": bonus_enabled,
            "total_replenished_minor": replenished,
            "services": services,
            "transactions": transactions or [],
        }

    return [
        customer("1201", "ops@altair.example", 280, 41200,
                 [service("s-1201", "Виртуальный сервер", 32000, False, "active", 2)]),
        customer("1042", "marina.v@example.com", 320, 18420,
                 [service("s-1042", "Облачный сервер", 8400, True, "active", 1)]),
        customer("1088", "oleg.p@example.net", 0, 64000,
                 [service("s-1088", "Выделенный сервер", 6200, True, "prolong_wait", -1)],
                 [{"id": "t-1088", "service_id": "s-1088", "status": "not_performed", "type": "prolong", "amount_minor": 6200, "created_at": expiry(-1)}]),
        customer("1184", "billing@pixelbase.example", 410, 128000,
                 [service("s-1184", "Облачный сервер", 14000, True, "active", 5)],
                 [{"id": "t-1184", "service_id": "s-1184", "status": "not_performed", "type": "prolong", "amount_minor": 14000, "created_at": expiry(-1)}]),
        customer("1270", "dev@riverhost.example", 1280, 95000,
                 [service("s-1270", "Виртуальный сервер", 1900, True, "active", 8)]),
        customer("1409", "help@orbit.example", 700, 32000,
                 [service("s-1409", "Облачный диск", 2400, True, "active", 12)]),
        customer("1306", "studio@mono.example", 5020, 214000,
                 [service("s-1306", "Виртуальный сервер", 4820, True, "active", 10)]),
        customer("1620", "ok@fluent.example", 10000, 330000,
                 [service("s-1620", "Облачный сервер", 4800, True, "active", 24)]),
        customer("1722", "new@orbit.example", 0, 0, []),
    ]
