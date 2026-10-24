from datetime import date, datetime, time, timedelta, timezone
from typing import Any


DEFAULT_MODEL_SETTINGS: dict[str, Any] = {
    "prediction_horizon_days": 30,
    "high_risk_min": 70,
    "medium_risk_min": 35,
    "weights": {
        "prolong_wait": 55,
        "autoprolong_disabled": 30,
        "insufficient_balance": 45,
        "failed_prolong_payment": 20,
    },
}

ELIGIBLE_STATUSES = {"active", "suspended", "prolong_wait"}


def _as_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _money(value: int) -> int:
    return int(value or 0)


def evaluate_customer(
    customer: dict[str, Any],
    model: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
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
    assessable = bool(eligible) and not missing_expiry

    due_services: list[dict[str, Any]] = []
    for service in eligible:
        expires_at = _as_utc(service["expires_at"])
        if service["status"] == "prolong_wait":
            due_services.append(service)
        elif expires_at and now <= expires_at <= horizon_end:
            due_services.append(service)

    due_revenue = sum(_money(service["price_minor"]) for service in due_services)
    usable_bonus = (
        _money(customer["bonus_balance_minor"])
        if customer["bonus_spend_enabled"]
        else 0
    )
    available_balance = _money(customer["balance_minor"]) + usable_bonus
    shortfall = max(0, due_revenue - available_balance)
    weights = model["weights"]
    signals = [
        (
            "prolong_wait",
            any(service["status"] == "prolong_wait" for service in eligible),
            "Услуга уже ожидает оплаты после окончания срока.",
        ),
        (
            "autoprolong_disabled",
            any(
                service in due_services
                and service["status"] != "prolong_wait"
                and not service["auto_prolong"]
                for service in eligible
            ),
            "Продление ожидается в ближайшие дни, но автопродление выключено.",
        ),
        (
            "insufficient_balance",
            due_revenue > available_balance and due_revenue > 0,
            "Доступного баланса не хватит на продления в выбранном периоде.",
        ),
        (
            "failed_prolong_payment",
            any(
                transaction["type"] == "prolong"
                and transaction["status"] == "not_performed"
                for transaction in transactions
            ),
            "В снимке есть неуспешная транзакция продления.",
        ),
    ]

    reasons: list[dict[str, Any]] = []
    if not assessable:
        if not eligible:
            message = "Нет активных или ожидающих продления услуг для оценки."
        else:
            message = "У одной или нескольких услуг не указана дата окончания."
        reasons.append({"code": "insufficient_data", "title": "Недостаточно данных", "points": 0, "explanation": message})
        score: int | None = None
        risk_level: str | None = None
    else:
        score = 0
        for code, active, explanation in signals:
            if active:
                points = weights[code]
                score += points
                reasons.append({
                    "code": code,
                    "title": _signal_title(code),
                    "points": points,
                    "explanation": explanation,
                })
        score = min(score, 100)
        if not reasons:
            reasons.append({
                "code": "no_active_signals",
                "title": "Активных сигналов риска нет",
                "points": 0,
                "explanation": "Доступные данные не показывают признаков скорого непродления.",
            })
        if score >= model["high_risk_min"]:
            risk_level = "high"
        elif score >= model["medium_risk_min"]:
            risk_level = "medium"
        else:
            risk_level = "low"

    exposure = (shortfall * score + 50) // 100 if score is not None else 0
    return {
        **customer,
        "risk_score": score,
        "risk_level": risk_level,
        "risk_label": _risk_label(risk_level),
        "reasons": reasons,
        "due_revenue_minor": due_revenue,
        "available_balance_minor": available_balance,
        "uncovered_revenue_minor": shortfall,
        "potential_loss_minor": exposure,
        "assessed_at": now.isoformat(),
        "calculation": {
            "horizon_days": model["prediction_horizon_days"],
            "due_revenue_minor": due_revenue,
            "available_balance_minor": available_balance,
            "uncovered_revenue_minor": shortfall,
            "risk_score_percent": score,
            "potential_loss_minor": exposure,
        },
    }


def _signal_title(code: str) -> str:
    return {
        "prolong_wait": "Услуга ожидает оплаты",
        "autoprolong_disabled": "Автопродление выключено",
        "insufficient_balance": "Не хватает средств",
        "failed_prolong_payment": "Не прошла оплата продления",
    }[code]


def _risk_label(level: str | None) -> str:
    return {
        "high": "Высокий",
        "medium": "Средний",
        "low": "Низкий",
        None: "Нет оценки",
    }[level]


def demo_snapshot() -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()

    def expiry(days: int) -> str:
        return datetime.combine(today + timedelta(days=days), time(hour=12), timezone.utc).isoformat()

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
