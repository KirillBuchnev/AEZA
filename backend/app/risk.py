import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction
from typing import Any


DEFAULT_MODEL_SETTINGS: dict[str, Any] = {
    "prediction_horizon_days": 30,
    "urgency_days": 7,
    "grace_days": 5,
    "high_risk_min": 50,
    "medium_risk_min": 30,
    "customer_high_risk_min": 50,
    "customer_medium_risk_min": 30,
    "weights": {
        "payment_distress": 40,
        "manual_renewal": 45,
        "renewal_urgency": 20,
        "grace_period_progress": 5,
    },
}

ELIGIBLE_STATUSES = {"active", "suspended", "prolong_wait"}
PAYMENT_TERMS = {"hour", "week", "month", "quarter_year", "half_year", "year"}
MAX_RENEWAL_EVENTS = 250_000


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


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _renewal_at(anchor: datetime, term: str, index: int) -> datetime:
    if term == "hour":
        return anchor + timedelta(hours=index)
    if term == "week":
        return anchor + timedelta(weeks=index)
    months = {"month": 1, "quarter_year": 3, "half_year": 6, "year": 12}[term]
    month_index = anchor.year * 12 + anchor.month - 1 + index * months
    year, month = divmod(month_index, 12)
    month += 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return anchor.replace(year=year, month=month, day=day)


def _service_events(service: dict[str, Any], now: datetime, horizon_end: datetime) -> list[dict[str, Any]]:
    """Return renewals in the horizon; prolong_wait reserves only the current payment."""
    if service["status"] == "prolong_wait":
        return [{"service_id": service["id"], "at": now, "amount_minor": _money(service["price_minor"])}]
    due = _as_utc(service.get("expires_at"))
    if due is None or due < now:
        return []
    term = service.get("payment_term")
    if term not in PAYMENT_TERMS:
        return [{"service_id": service["id"], "at": due, "amount_minor": _money(service["price_minor"])}]
    events = []
    index = 0
    while True:
        at = _renewal_at(due, term, index)
        if at >= horizon_end:
            break
        if at >= now:
            events.append({"service_id": service["id"], "at": at,
                           "amount_minor": _money(service["price_minor"])})
        index += 1
        if len(events) > MAX_RENEWAL_EVENTS:
            raise ValueError("Слишком много продлений в горизонте; уменьшите горизонт или проверьте период оплаты.")
    return events


def _allocate_wallet(events: list[dict[str, Any]], balance_minor: int,
                     now: datetime, urgency_days: int) -> dict[str, Any]:
    """Allocate a shared balance chronologically, pro-rata for simultaneous payments."""
    grouped: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[event["at"]].append(event)
    remaining = balance_minor
    allocations: dict[str, dict[str, Any]] = {}
    scheduled = 0
    for at in sorted(grouped):
        group = grouped[at]
        group_total = sum(event["amount_minor"] for event in group)
        covered = min(remaining, group_total)
        remaining -= covered
        scheduled += group_total
        for event in group:
            amount = event["amount_minor"]
            uncovered = Fraction(amount * (group_total - covered), group_total) if group_total else Fraction(0)
            entry = allocations.setdefault(event["service_id"], {
                "scheduled_minor": 0, "uncovered_fractional": Fraction(0),
                "funding_pressure": 0.0, "risk_weighted_gross_fractional": Fraction(0),
                "risk_weighted_unfunded_fractional": Fraction(0),
            })
            entry["scheduled_minor"] += amount
            entry["uncovered_fractional"] += uncovered
            urgency = _clip(1.0 - (at - now).total_seconds() / (urgency_days * 86400))
            if amount:
                entry["funding_pressure"] = max(entry["funding_pressure"],
                                                 float(uncovered / amount) * urgency)
    return {"scheduled_minor": scheduled, "uncovered_fractional": Fraction(max(0, scheduled - balance_minor)),
            "allocations": allocations}


def _round_fraction(value: Fraction) -> int:
    """Round a non-negative rational amount to minor currency units, half up."""
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _risk_level(score: float | None, medium: float, high: float) -> str | None:
    if score is None:
        return None
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def evaluate_customer(
    customer: dict[str, Any],
    model: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _as_utc(now or datetime.now(timezone.utc))
    assert now is not None
    horizon_end = now + timedelta(days=model["prediction_horizon_days"])
    services = customer["services"]
    eligible = [service for service in services if service["status"] in ELIGIBLE_STATUSES]
    available_bonus = _money(customer["bonus_balance_minor"]) if customer["bonus_spend_enabled"] else 0
    available_balance = _money(customer["balance_minor"]) + available_bonus
    if not eligible:
        return _unscored(customer, now, model, "Нет услуг, доступных для обычного продления.", "not_applicable")

    events: list[dict[str, Any]] = []
    date_by_service: dict[str, datetime | None] = {}
    grace_by_service: dict[str, float] = {}
    for service in eligible:
        sid = str(service["id"])
        due = _as_utc(service.get("expires_at"))
        date_by_service[sid] = due
        if service["status"] != "prolong_wait" and (due is None or due < now):
            grace_by_service[sid] = 0.0
            continue
        if service["status"] == "prolong_wait":
            grace = 0.0
            if due is not None:
                elapsed = (now - due).total_seconds()
                grace_seconds = model["grace_days"] * 86400
                if 0 <= elapsed < grace_seconds:
                    grace = elapsed / grace_seconds
            grace_by_service[sid] = grace
        else:
            grace_by_service[sid] = 0.0
        events.extend(_service_events(service, now, horizon_end))
        if len(events) > MAX_RENEWAL_EVENTS:
            raise ValueError("Слишком много продлений в горизонте; уменьшите горизонт или проверьте входные данные.")

    allocation = _allocate_wallet(events, available_balance, now, model["urgency_days"])
    weights = model["weights"]
    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise ValueError("Сумма весов факторов должна быть больше нуля.")
    service_results = []
    weighted_gross = Fraction(0)
    weighted_unfunded = Fraction(0)
    for service in services:
        result_service = dict(service)
        if service["status"] not in ELIGIBLE_STATUSES:
            result_service.update(risk_score=None, risk_level=None, factors=[], assessment_status="not_applicable")
            service_results.append(result_service)
            continue
        sid = str(service["id"])
        due = date_by_service[sid]
        if service["status"] != "prolong_wait" and (due is None or due < now):
            result_service.update(risk_score=None, risk_level=None, factors=[], assessment_status="unknown",
                                  scheduled_minor=0, uncovered_minor=0)
            service_results.append(result_service)
            continue
        urgency_at = max(due, now) if due is not None else now
        urgency = _clip(1.0 - (urgency_at - now).total_seconds() / (model["urgency_days"] * 86400))
        service_allocation = allocation["allocations"].get(sid, {
            "scheduled_minor": 0, "uncovered_fractional": Fraction(0), "funding_pressure": 0.0,
            "risk_weighted_gross_fractional": Fraction(0), "risk_weighted_unfunded_fractional": Fraction(0),
        })
        funding_pressure = service_allocation["funding_pressure"]
        values = {
            "payment_distress": funding_pressure,
            "manual_renewal": (1.0 if not service["auto_prolong"] else 0.0) * urgency,
            "renewal_urgency": urgency if (not service["auto_prolong"] or funding_pressure > 0) else 0.0,
            "grace_period_progress": grace_by_service[sid],
        }
        factors = []
        for code, value in values.items():
            weight = weights[code]
            points = 100.0 * value * (weight / total_weight)
            factors.append({"code": code, "value": round(value, 8), "weight": weight,
                            "points": round(points, 6), "title": _signal_title(code),
                            "explanation": _factor_explanation(code, value)})
        score = round(min(100.0, sum(factor["points"] for factor in factors)), 6)
        level = _risk_level(score, model["medium_risk_min"], model["high_risk_min"])
        score_fraction = Fraction(str(score)) / 100
        service_allocation["risk_weighted_gross_fractional"] = Fraction(service_allocation["scheduled_minor"]) * score_fraction
        service_allocation["risk_weighted_unfunded_fractional"] = service_allocation["uncovered_fractional"] * score_fraction
        weighted_gross += service_allocation["risk_weighted_gross_fractional"]
        weighted_unfunded += service_allocation["risk_weighted_unfunded_fractional"]
        result_service.update(risk_score=score, risk_level=level, factors=factors,
                              assessment_status="assessed", scheduled_minor=service_allocation["scheduled_minor"],
                              uncovered_minor=_round_fraction(service_allocation["uncovered_fractional"]))
        service_results.append(result_service)

    assessed_services = [item for item in service_results if item["assessment_status"] == "assessed"]
    account_score = round(sum(item["risk_score"] for item in assessed_services), 6) if assessed_services else None
    account_level = _risk_level(account_score, model["customer_medium_risk_min"], model["customer_high_risk_min"])
    reason_map: dict[str, dict[str, Any]] = {}
    for service in assessed_services:
        for factor in service["factors"]:
            if factor["points"] <= 0:
                continue
            row = reason_map.setdefault(factor["code"], {
                "code": factor["code"], "title": factor["title"], "points": 0.0,
                "explanation": factor["explanation"], "service_ids": [],
            })
            row["points"] = round(row["points"] + factor["points"], 6)
            row["service_ids"].append(service["id"])
    reasons = sorted(reason_map.values(), key=lambda item: (-item["points"], item["code"]))
    if not reasons and assessed_services:
        reasons = [{"code": "no_active_signals", "title": "Активных сигналов риска нет", "points": 0.0,
                    "explanation": "Доступные данные не показывают признаков скорого непродления.",
                    "service_ids": []}]
    high_service_count = sum(item["risk_level"] == "high" for item in assessed_services)
    any_unknown = any(item["assessment_status"] == "unknown" for item in service_results)
    assessment_status = "insufficient_data" if any_unknown else "assessed"
    uncovered_minor = max(0, allocation["scheduled_minor"] - available_balance)
    potential_loss = _round_fraction(weighted_gross)
    uncovered_potential_loss = _round_fraction(weighted_unfunded)
    risk_counts = {level: sum(item["risk_level"] == level for item in assessed_services)
                   for level in ("low", "medium", "high")}
    return {
        **customer,
        "assessment_status": assessment_status,
        "risk_score": account_score,
        "risk_level": account_level if account_score is not None else "unscored",
        "risk_label": _risk_label(account_level if account_score is not None else "unscored"),
        "reasons": reasons,
        "services": service_results,
        "service_risk_counts": risk_counts,
        "max_service_score": max((item["risk_score"] for item in assessed_services), default=None),
        "at_risk_services_count": high_service_count,
        "medium_or_high_services_count": risk_counts["medium"] + risk_counts["high"],
        "assessed_service_count": len(assessed_services),
        "risk_aggregation": "sum_of_assessed_service_scores",
        "due_revenue_minor": allocation["scheduled_minor"],
        "available_balance_minor": available_balance,
        "uncovered_revenue_minor": uncovered_minor,
        "potential_loss_minor": potential_loss,
        "uncovered_potential_loss_minor": uncovered_potential_loss,
        "assessed_at": now.isoformat(),
        "calculation": {
            "horizon_days": model["prediction_horizon_days"],
            "urgency_days": model["urgency_days"],
            "grace_days": model["grace_days"],
            "due_revenue_minor": allocation["scheduled_minor"],
            "available_balance_minor": available_balance,
            "uncovered_revenue_minor": uncovered_minor,
            "risk_score_index": account_score,
            "service_risk_counts": risk_counts,
            "max_service_score": max((item["risk_score"] for item in assessed_services), default=None),
            "account_risk_thresholds": {"medium": model["customer_medium_risk_min"],
                                         "high": model["customer_high_risk_min"]},
            "potential_loss_minor": potential_loss,
            "uncovered_potential_loss_minor": uncovered_potential_loss,
            "estimate_kind": "expert_weighted_renewal_scenario_not_expected_loss",
        },
    }


def _unscored(customer: dict[str, Any], now: datetime, model: dict[str, Any], message: str,
              status: str, services: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    reasons = [{"code": "insufficient_data" if status != "not_applicable" else "no_renewable_services",
                "title": "Недостаточно данных" if status != "not_applicable" else "Нет услуг для оценки",
                "points": 0.0, "explanation": message, "service_ids": []}]
    return {
        **customer, "services": services if services is not None else customer["services"],
        "assessment_status": status, "risk_score": None,
        "risk_level": None if status == "not_applicable" else "unscored",
        "risk_label": _risk_label(None), "reasons": reasons,
        "service_risk_counts": {"low": 0, "medium": 0, "high": 0},
        "max_service_score": None, "at_risk_services_count": 0,
        "medium_or_high_services_count": 0, "assessed_service_count": 0,
        "risk_aggregation": "sum_of_assessed_service_scores",
        "due_revenue_minor": 0,
        "available_balance_minor": (_money(customer["balance_minor"])
                                     + (_money(customer["bonus_balance_minor"])
                                        if customer["bonus_spend_enabled"] else 0)),
        "uncovered_revenue_minor": 0, "potential_loss_minor": 0,
        "uncovered_potential_loss_minor": 0, "assessed_at": now.isoformat(),
        "calculation": {"horizon_days": model["prediction_horizon_days"],
                        "urgency_days": model["urgency_days"], "grace_days": model["grace_days"],
                        "due_revenue_minor": 0,
                        "available_balance_minor": (_money(customer["balance_minor"])
                                                     + (_money(customer["bonus_balance_minor"])
                                                        if customer["bonus_spend_enabled"] else 0)),
                        "uncovered_revenue_minor": 0, "risk_score_index": None,
                        "potential_loss_minor": 0, "uncovered_potential_loss_minor": 0,
                        "estimate_kind": "expert_weighted_renewal_scenario_not_expected_loss"},
    }


def _signal_title(code: str) -> str:
    return {
        "payment_distress": "Нехватка средств на продление",
        "manual_renewal": "Требуется ручное продление",
        "renewal_urgency": "Скоро срок продления",
        "grace_period_progress": "Идёт срок ожидания оплаты",
    }[code]


def _factor_explanation(code: str, value: float) -> str:
    explanations = {
        "payment_distress": "Доля ближайшего платежа, не покрытая общим доступным балансом, с учётом срочности.",
        "manual_renewal": "Автопродление выключено; фактор усиливается по мере приближения срока.",
        "renewal_urgency": "Срок близок и требуется ручное действие или недостаточно средств.",
        "grace_period_progress": "Доля согласованного пятидневного срока ожидания, которая уже прошла.",
    }
    return explanations[code] if value > 0 else "Признак не добавляет баллы при текущих данных."


def _risk_label(level: str | None) -> str:
    return {
        "high": "Высокий",
        "medium": "Средний",
        "low": "Низкий",
        "unscored": "Нет оценки",
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
