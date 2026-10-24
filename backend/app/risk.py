from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any


MODEL_VERSION = 3
ACTION_HORIZON_DAYS = 7
GRACE_PERIOD_DAYS = 5
ELIGIBLE_STATUSES = {"active", "suspended", "prolong_wait"}
# Months covered by one payment, for the case terms: hour and week are fractions of a month (30-day month).
PAYMENT_TERM_MONTHS = {
    "hour": 1 / 720,
    "week": 7 / 30,
    "month": 1,
    "quarter_year": 3,
    "quarter": 3,
    "half_year": 6,
    "year": 12,
}
# Starting expert coefficients agreed with the mentor. They make the control cases
# of the brief land in the expected levels. They were not fitted to outcomes.
DEFAULT_WEIGHTS: dict[str, int] = {
    "prolong_wait": 5,
    "autoprolong_disabled": 45,
    "insufficient_balance": 40,
    "renewal_urgency": 20,
}
# Order of factors in reasons and on the model page. Adding a factor means adding
# a weight, an entry here and a branch in _explain.
FACTORS: tuple[dict[str, str], ...] = (
    {
        "code": "autoprolong_disabled",
        "title": "Ручное продление",
        "description": "Автопродление выключено, срок близко: клиент должен продлить услугу сам.",
    },
    {
        "code": "insufficient_balance",
        "title": "Не хватает средств",
        "description": "Доступного баланса не хватает на продление. Вклад пропорционален недостающей доле цены.",
    },
    {
        "code": "renewal_urgency",
        "title": "Срочность продления",
        "description": "Чем ближе срок продления, тем больше вклад. За 7 дней он растёт от нуля до полного веса.",
    },
    {
        "code": "prolong_wait",
        "title": "Ожидание оплаты",
        "description": "Услуга уже ожидает оплаты. Вклад растёт в течение пятидневного grace-периода.",
    },
)
FACTOR_TITLES = {factor["code"]: factor["title"] for factor in FACTORS}
FACTOR_TITLES["insufficient_data"] = "Недостаточно данных"

DEFAULT_MODEL_SETTINGS: dict[str, Any] = {
    "version": MODEL_VERSION,
    "revision": 1,
    "prediction_horizon_days": 30,
    "high_risk_min": 50,
    "medium_risk_min": 30,
    # The account index is a sum of service indices and grows with the number of
    # services, so its levels are edited separately from the service levels.
    "account_high_risk_min": 50,
    "account_medium_risk_min": 30,
    "weights": dict(DEFAULT_WEIGHTS),
}


def merge_model_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Return a complete model contract while accepting rows written by older versions."""
    current = settings or {}
    stored_weights = current.get("weights") or {}
    weights = dict(DEFAULT_WEIGHTS)
    for code in DEFAULT_WEIGHTS:
        if code in stored_weights:
            weights[code] = int(stored_weights[code])
    # Version 2 kept the renewal urgency weight in the formula block. Carry a custom value over.
    legacy_urgency = (current.get("formula") or {}).get("urgency_weight")
    if "renewal_urgency" not in stored_weights and legacy_urgency is not None:
        weights["renewal_urgency"] = int(legacy_urgency)
    return {
        "version": MODEL_VERSION,
        "revision": int(current.get("revision", DEFAULT_MODEL_SETTINGS["revision"])),
        "prediction_horizon_days": int(
            current.get("prediction_horizon_days", DEFAULT_MODEL_SETTINGS["prediction_horizon_days"])
        ),
        "high_risk_min": int(current.get("high_risk_min", DEFAULT_MODEL_SETTINGS["high_risk_min"])),
        "medium_risk_min": int(current.get("medium_risk_min", DEFAULT_MODEL_SETTINGS["medium_risk_min"])),
        "account_high_risk_min": int(
            current.get("account_high_risk_min", DEFAULT_MODEL_SETTINGS["account_high_risk_min"])
        ),
        "account_medium_risk_min": int(
            current.get("account_medium_risk_min", DEFAULT_MODEL_SETTINGS["account_medium_risk_min"])
        ),
        "weights": weights,
    }


def model_divisor(model: dict[str, Any]) -> int:
    """The index normalizer is the sum of weights, so a full set of signals gives 100."""
    return sum(model["weights"].values()) or 1


def as_utc(value: datetime | str | None) -> datetime | None:
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
    """One decimal, as in the control values of the brief, without float noise."""
    rounded = round(value, 1)
    return 0.0 if abs(rounded) < 0.05 else rounded


def euro(amount_minor: int) -> str:
    text = f"{amount_minor / 100:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} €"


def _due_text(seconds: float | None) -> str:
    if seconds is None:
        return "без даты окончания"
    if seconds <= 0:
        return "срок уже наступил"
    hours = seconds / 3600
    if hours < 48:
        return f"через {max(1, round(hours))} ч"
    return f"через {round(seconds / 86400)} дн."


def _grace_text(remaining: int | None) -> str:
    if remaining is None:
        return "срок grace-периода неизвестен"
    if remaining == 0:
        return "grace-период закончился"
    return f"осталось {remaining} дн. grace-периода"


def _decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _urgency(expires_at: datetime, now: datetime) -> float:
    seconds_left = (expires_at - now).total_seconds()
    return _clip(1 - seconds_left / (ACTION_HORIZON_DAYS * 86400))


def _grace(expires_at: datetime | None, now: datetime) -> tuple[float, float | None, int | None]:
    """Return grace progress, elapsed days and whole days left for a waiting service."""
    if expires_at is None:
        return 0.0, None, None
    elapsed_days = max(0.0, (now - expires_at).total_seconds() / 86400)
    remaining = max(0, ceil(GRACE_PERIOD_DAYS - elapsed_days))
    return _clip(elapsed_days / GRACE_PERIOD_DAYS), elapsed_days, remaining


def _is_failed_prolong(transaction: dict[str, Any], now: datetime) -> bool:
    if transaction.get("type") != "prolong" or transaction.get("status") != "not_performed":
        return False
    created_at = as_utc(transaction.get("created_at"))
    return created_at is not None and created_at >= now - timedelta(days=ACTION_HORIZON_DAYS)


def _monthly_cost(price: int, payment_term: str | None) -> int:
    months = PAYMENT_TERM_MONTHS.get(payment_term or "month", 1)
    return round(price / months)


def _risk_label(level: str | None) -> str:
    return {
        "high": "Высокий",
        "medium": "Средний",
        "low": "Низкий",
        None: "Нет оценки",
    }[level]


def _risk_level(score: float | None, model: dict[str, Any]) -> str | None:
    if score is None:
        return None
    if score >= model["high_risk_min"]:
        return "high"
    if score >= model["medium_risk_min"]:
        return "medium"
    return "low"


def _account_level(score: float | None, model: dict[str, Any]) -> str | None:
    if score is None:
        return None
    if score >= model["account_high_risk_min"]:
        return "high"
    if score >= model["account_medium_risk_min"]:
        return "medium"
    return "low"


def _allocate_balance(due_services: list[dict[str, Any]], available_balance: int) -> dict[str, int]:
    """Spread a shared account balance over due services in the order they are paid."""
    remaining = available_balance
    allocation: dict[str, int] = {}
    for service in due_services:
        price = _money(service["price_minor"])
        applied = min(remaining, price)
        allocation[str(service["id"])] = price - applied
        remaining -= applied
    return allocation


def _due_order(service: dict[str, Any]) -> tuple[int, datetime]:
    expires_at = as_utc(service.get("expires_at"))
    waiting = service["status"] == "prolong_wait"
    return (0 if waiting else 1, expires_at or datetime.max.replace(tzinfo=timezone.utc))


def _is_due(service: dict[str, Any], now: datetime, horizon_end: datetime) -> bool:
    if service["status"] == "prolong_wait":
        return True
    expires_at = as_utc(service["expires_at"])
    return expires_at is not None and now <= expires_at <= horizon_end


def _explain(
    code: str,
    *,
    price: int,
    shortfall: int,
    urgency: float,
    expires_at: datetime | None,
    now: datetime,
    is_waiting: bool,
    grace_elapsed: float | None,
    grace_remaining: int | None,
) -> tuple[str, dict[str, Any]]:
    seconds_left = (expires_at - now).total_seconds() if expires_at else None
    days_left = round(seconds_left / 86400, 2) if seconds_left is not None else None
    if code == "insufficient_balance":
        available = price - shortfall
        return (
            f"На продление хватает {euro(available)} из {euro(price)}, не хватает {euro(shortfall)}. "
            "Без пополнения списание не пройдёт.",
            {"price_minor": price, "available_minor": available, "shortfall_minor": shortfall},
        )
    if code == "autoprolong_disabled":
        if is_waiting:
            text = "Автопродление выключено и услуга ждёт оплаты: списания не будет, клиент должен оплатить сам."
        else:
            text = (
                f"Автопродление выключено, продление {_due_text(seconds_left)}. "
                "Клиент должен продлить услугу сам, иначе она уйдёт в ожидание оплаты."
            )
        return text, {"auto_prolong": False, "days_to_due": days_left}
    if code == "renewal_urgency":
        if is_waiting:
            text = "Срок продления уже прошёл: срочность максимальная."
        else:
            text = f"До продления {_due_text(seconds_left)}: на решение остаётся мало времени."
        return text, {"urgency": round(urgency, 3), "days_to_due": days_left}
    return (
        f"Услуга ожидает оплаты {_decimal(grace_elapsed or 0)} дн. после окончания срока; {_grace_text(grace_remaining)}.",
        {"grace_elapsed_days": round(grace_elapsed or 0, 2), "grace_remaining_days": grace_remaining},
    )


def _service_action(
    *,
    issue: str | None,
    is_waiting: bool,
    shortfall: int,
    urgency: float,
    manual: float,
    due: bool,
    recent_failed: bool,
    seconds_left: float | None,
    grace_remaining: int | None,
) -> dict[str, str]:
    if issue == "missing_expiry":
        action = {"code": "fix_data", "text": "Укажите дату окончания услуги: без неё риск не рассчитывается."}
    elif issue == "expired_active":
        action = {"code": "fix_data", "text": "Дата окончания прошла, а услуга активна: проверьте статус и дату в источнике."}
    elif is_waiting and shortfall > 0:
        action = {
            "code": "top_up",
            "text": f"Напомнить об оплате и попросить пополнить баланс на {euro(shortfall)}; {_grace_text(grace_remaining)}.",
        }
    elif is_waiting and manual > 0:
        action = {
            "code": "manual_reminder",
            "text": f"Напомнить оплатить услугу вручную: автопродление выключено; {_grace_text(grace_remaining)}.",
        }
    elif is_waiting:
        action = {
            "code": "check_payment",
            "text": "Баланса хватает, но услуга ждёт оплаты: проверить списание и повторить его.",
        }
    elif shortfall > 0 and urgency > 0:
        action = {
            "code": "top_up",
            "text": f"Попросить пополнить баланс на {euro(shortfall)} ({_due_text(seconds_left)}), иначе списание не пройдёт.",
        }
    elif manual > 0:
        action = {"code": "manual_reminder", "text": f"Напомнить продлить услугу вручную ({_due_text(seconds_left)})."}
    elif due and shortfall > 0:
        # Outside the 7-day action window the index is zero, but the shortfall is still real money.
        action = {
            "code": "forecast_only",
            "text": f"Срок продления вне 7-дневного окна ({_due_text(seconds_left)}), но на продление не хватает {euro(shortfall)}: запланировать пополнение заранее.",
        }
    else:
        action = {"code": "none", "text": "Действий не требуется: признаков непродления нет."}
    if recent_failed:
        if action["code"] == "none":
            action = {"code": "check_payment", "text": "Проверить причину последней неуспешной оплаты продления."}
        elif action["code"] != "check_payment":
            action["text"] += " Также проверить причину последней неуспешной оплаты продления."
    return action


def _evaluate_service(
    service: dict[str, Any],
    *,
    due: bool,
    shortfall: int,
    model: dict[str, Any],
    now: datetime,
    recent_failed: bool,
) -> dict[str, Any]:
    weights = model["weights"]
    divisor = model_divisor(model)
    price = _money(service["price_minor"])
    expires_at = as_utc(service["expires_at"])
    is_waiting = service["status"] == "prolong_wait"

    issue: str | None = None
    if expires_at is None:
        issue = "missing_expiry"
    elif not is_waiting and expires_at < now:
        issue = "expired_active"

    urgency = 0.0
    if issue is None and due:
        urgency = 1.0 if is_waiting else _urgency(expires_at, now)
    distress = _clip(shortfall / price) * urgency if price else 0.0
    manual = 0.0 if service["auto_prolong"] or issue else urgency
    renewal = urgency if manual > 0 or distress > 0 else 0.0
    grace_progress, grace_elapsed, grace_remaining = (
        _grace(expires_at, now) if is_waiting else (0.0, None, None)
    )

    contributions = {
        "autoprolong_disabled": weights["autoprolong_disabled"] * manual,
        "insufficient_balance": weights["insufficient_balance"] * distress,
        "renewal_urgency": weights["renewal_urgency"] * renewal,
        "prolong_wait": weights["prolong_wait"] * grace_progress,
    }
    score = None if issue else round(_clip(sum(contributions.values()) / divisor) * 100, 1)

    reasons: list[dict[str, Any]] = []
    if score is not None:
        for factor in FACTORS:
            code = factor["code"]
            if contributions[code] <= 0:
                continue
            explanation, evidence = _explain(
                code,
                price=price,
                shortfall=shortfall,
                urgency=urgency,
                expires_at=expires_at,
                now=now,
                is_waiting=is_waiting,
                grace_elapsed=grace_elapsed,
                grace_remaining=grace_remaining,
            )
            reasons.append({
                "code": code,
                "title": factor["title"],
                "points": _points(contributions[code] / divisor * 100),
                "explanation": explanation,
                "evidence": evidence,
            })
    if not reasons and score is not None:
        explanation = (
            f"Срок вне 7-дневного окна, но на продление не хватает {euro(shortfall)}: индекс 0, сумма учтена в деньгах."
            if shortfall > 0
            else "Баланс покрывает продление, автопродление включено, срок не близко."
        )
        reasons.append({
            "code": "no_active_signals",
            "title": "Признаков непродления нет",
            "points": 0.0,
            "explanation": explanation,
            "evidence": {"shortfall_minor": shortfall},
        })
    if issue:
        reasons.append({
            "code": "insufficient_data",
            "title": FACTOR_TITLES["insufficient_data"],
            "points": 0.0,
            "explanation": "Услуге не назначен риск: " + (
                "нет даты окончания." if issue == "missing_expiry" else "дата окончания уже прошла."
            ),
            "evidence": {},
        })

    seconds_left = (expires_at - now).total_seconds() if expires_at else None
    action = _service_action(
        issue=issue,
        is_waiting=is_waiting,
        shortfall=shortfall,
        urgency=urgency,
        manual=manual,
        due=due,
        recent_failed=recent_failed,
        seconds_left=seconds_left,
        grace_remaining=grace_remaining,
    )
    level = _risk_level(score, model)
    return {
        **service,
        "risk_score": score,
        "risk_level": level,
        "risk_label": _risk_label(level),
        "reasons": reasons,
        "recommended_action": action,
        "data_issue": issue,
        "due": due,
        "recent_failed_payment": recent_failed,
        "due_revenue_minor": price if due else 0,
        "available_balance_minor": price - shortfall if due else 0,
        "uncovered_revenue_minor": shortfall,
        "potential_loss_minor": round(shortfall * score / 100) if score is not None else 0,
        "revenue_at_risk_minor": round(price * score / 100) if score is not None else 0,
        "monthly_cost_minor": _monthly_cost(price, service.get("payment_term")),
        "grace_remaining_days": grace_remaining,
    }


def _account_reasons(assessed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for service in assessed:
        for reason in service["reasons"]:
            if reason["code"] not in FACTOR_TITLES or reason["code"] == "insufficient_data":
                continue
            entry = totals.setdefault(reason["code"], {"points": 0.0, "services": 0, "shortfall_minor": 0})
            entry["points"] += reason["points"]
            entry["services"] += 1
            entry["shortfall_minor"] += reason["evidence"].get("shortfall_minor", 0)

    explanations = {
        "autoprolong_disabled": "Автопродление выключено: клиент должен продлить эти услуги сам.",
        "insufficient_balance": f"Не хватает средств на продление. Недостаток: {{shortfall}}.",
        "renewal_urgency": f"Срок продления в пределах {ACTION_HORIZON_DAYS} дней.",
        "prolong_wait": "Услуги ожидают оплаты в grace-периоде.",
    }
    reasons: list[dict[str, Any]] = []
    for factor in FACTORS:
        entry = totals.get(factor["code"])
        if entry is None:
            continue
        text = explanations[factor["code"]].replace("{shortfall}", euro(entry["shortfall_minor"]))
        reasons.append({
            "code": factor["code"],
            "title": factor["title"],
            "points": _points(entry["points"]),
            "explanation": f"{text} Затронуто услуг: {entry['services']}.",
            "evidence": {"services": entry["services"], "shortfall_minor": entry["shortfall_minor"]},
        })
    reasons.sort(key=lambda reason: reason["points"], reverse=True)
    return reasons


def evaluate_customer(
    customer: dict[str, Any],
    model: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    model = merge_model_settings(model)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    horizon_end = now + timedelta(days=model["prediction_horizon_days"])
    eligible = [service for service in customer["services"] if service["status"] in ELIGIBLE_STATUSES]
    due_services = sorted((s for s in eligible if _is_due(s, now, horizon_end)), key=_due_order)
    due_ids = {str(service["id"]) for service in due_services}

    usable_bonus = _money(customer["bonus_balance_minor"]) if customer["bonus_spend_enabled"] else 0
    available_balance = _money(customer["balance_minor"]) + usable_bonus
    due_revenue = sum(_money(service["price_minor"]) for service in due_services)
    uncovered_total = max(0, due_revenue - available_balance)
    shortfalls = _allocate_balance(due_services, available_balance)

    # A failed payment without a service id cannot be attributed to one service: it is ignored.
    failed_service_ids = {
        transaction["service_id"]
        for transaction in customer["transactions"]
        if transaction.get("service_id") and _is_failed_prolong(transaction, now)
    }

    service_results = [
        _evaluate_service(
            service,
            due=str(service["id"]) in due_ids,
            shortfall=shortfalls.get(str(service["id"]), 0),
            model=model,
            now=now,
            recent_failed=str(service["id"]) in failed_service_ids,
        )
        for service in eligible
    ]

    assessed = [service for service in service_results if service["risk_score"] is not None]
    unscored = [service for service in service_results if service["risk_score"] is None]
    complete = bool(service_results) and not unscored
    # The account index is the sum of service indices, as agreed with the mentor.
    # Its level comes from the same thresholds as the service level.
    account_sum = round(sum(service["risk_score"] for service in assessed), 1) if complete else None
    level = _account_level(account_sum, model)
    divisor = model_divisor(model)
    max_score = max((service["risk_score"] for service in assessed), default=None)
    high_count = sum(service["risk_level"] == "high" for service in assessed)
    potential_loss = sum(service["potential_loss_minor"] for service in service_results)
    revenue_at_risk = sum(service["revenue_at_risk_minor"] for service in service_results)
    monthly_cost = sum(service["monthly_cost_minor"] for service in service_results)

    reasons = _account_reasons(assessed)
    if not service_results:
        reasons.insert(0, _insufficient("Нет активных или ожидающих продления услуг для оценки."))
    elif unscored:
        reasons.insert(0, _insufficient(
            f"Риск не рассчитан для аккаунта: не хватает данных у услуг ({len(unscored)} из {len(service_results)})."
        ))

    data_quality = [
        {"code": service["data_issue"], "service_id": str(service["id"]), "message": service["recommended_action"]["text"]}
        for service in unscored
    ]
    for service in eligible:
        term = service.get("payment_term")
        if term is not None and term not in PAYMENT_TERM_MONTHS:
            data_quality.append({
                "code": "unknown_payment_term",
                "service_id": str(service["id"]),
                "message": f"Срок оплаты «{term}» не распознан: услуга считается ежемесячной.",
            })

    if not service_results:
        action = {"code": "none", "text": "Нет активных услуг для оценки."}
    elif unscored:
        action = unscored[0]["recommended_action"]
    else:
        actionable = [service for service in service_results if service["recommended_action"]["code"] != "none"]
        action = (
            max(actionable, key=lambda service: service["risk_score"])["recommended_action"]
            if actionable
            else {"code": "none", "text": "Действий не требуется: признаков непродления нет."}
        )

    return {
        **customer,
        "services": service_results,
        "risk_score": account_sum,
        "risk_level": level,
        "risk_label": _risk_label(level),
        "reasons": reasons,
        "recommended_action": action,
        "data_quality": data_quality,
        "due_revenue_minor": due_revenue,
        "available_balance_minor": available_balance,
        "uncovered_revenue_minor": uncovered_total,
        "potential_loss_minor": potential_loss,
        "revenue_at_risk_minor": revenue_at_risk,
        "monthly_cost_minor": monthly_cost,
        "account_risk_sum": account_sum,
        "max_service_score": max_score,
        "high_count": high_count,
        "unscored_services_count": len(unscored),
        "service_count": len(service_results),
        "assessed_at": now.isoformat(),
        "calculation": {
            "horizon_days": model["prediction_horizon_days"],
            "normalizer": divisor,
            "weights": dict(model["weights"]),
            "due_revenue_minor": due_revenue,
            "available_balance_minor": available_balance,
            "uncovered_revenue_minor": uncovered_total,
            "risk_score_index": account_sum,
            "account_risk_sum": account_sum,
            "max_service_score": max_score,
            "high_count": high_count,
            "revenue_at_risk_minor": revenue_at_risk,
            "potential_loss_minor": potential_loss,
            "monthly_cost_minor": monthly_cost,
        },
    }


def _insufficient(message: str) -> dict[str, Any]:
    return {
        "code": "insufficient_data",
        "title": FACTOR_TITLES["insufficient_data"],
        "points": 0.0,
        "explanation": message,
        "evidence": {},
    }


def outflow_forecast(
    evaluated: list[dict[str, Any]],
    now: datetime,
    horizon_days: int,
) -> dict[str, Any]:
    """Expected non-renewals by due day. This is index-based, not a calibrated probability."""
    buckets: dict[str, dict[str, Any]] = {}
    waiting_services = 0
    waiting_expected = 0.0
    waiting_loss = 0
    for customer in evaluated:
        for service in customer["services"]:
            if not service["due"] or service["risk_score"] is None:
                continue
            expected = service["risk_score"] / 100
            if service["status"] == "prolong_wait":
                waiting_services += 1
                waiting_expected += expected
                waiting_loss += service["potential_loss_minor"]
                continue
            day = as_utc(service["expires_at"]).date().isoformat()
            bucket = buckets.setdefault(day, {
                "date": day,
                "services_due": 0,
                "services_at_risk": 0,
                "expected_non_renewals": 0.0,
                "expected_loss_minor": 0,
            })
            bucket["services_due"] += 1
            bucket["services_at_risk"] += service["risk_level"] in {"high", "medium"}
            bucket["expected_non_renewals"] += expected
            bucket["expected_loss_minor"] += service["potential_loss_minor"]

    ordered = [buckets[key] for key in sorted(buckets)]
    for bucket in ordered:
        bucket["expected_non_renewals"] = round(bucket["expected_non_renewals"], 2)
    return {
        "method": "Сумма индексов риска услуг по дням продления (индекс / 100). Не калибровано по историческим исходам.",
        "horizon_days": horizon_days,
        "from_date": now.date().isoformat(),
        "buckets": ordered,
        "waiting_now": {
            "services": waiting_services,
            "expected_non_renewals": round(waiting_expected, 2),
            "expected_loss_minor": waiting_loss,
        },
        "totals": {
            "services_due": sum(bucket["services_due"] for bucket in ordered) + waiting_services,
            "services_at_risk": sum(bucket["services_at_risk"] for bucket in ordered),
            "expected_non_renewals": round(
                sum(bucket["expected_non_renewals"] for bucket in ordered) + waiting_expected, 2
            ),
        },
    }


def control_cases(model: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    """The four control accounts from the mentor's answer, scored with the current model."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def account(balance: int, auto: bool, status: str, expires_at: datetime) -> dict[str, Any]:
        return {
            "id": "control",
            "email": "control@example.com",
            "balance_minor": balance,
            "withdraw_balance_minor": 0,
            "bonus_balance_minor": 0,
            "bonus_spend_enabled": False,
            "total_replenished_minor": 0,
            "services": [{
                "id": "control-service",
                "name": "Control service",
                "price_minor": 10_000,
                "auto_prolong": auto,
                "payment_term": "month",
                "status": status,
                "expires_at": expires_at.isoformat(),
            }],
            "transactions": [],
        }

    cases = (
        ("a", "Ожидает оплаты 1 день, баланса нет", account(0, True, "prolong_wait", now - timedelta(days=1)), "high"),
        ("b", "Ручное продление через 3 часа, деньги есть", account(10_000, False, "active", now + timedelta(hours=3)), "high"),
        ("c", "Автопродление через 3 часа, баланса нет", account(0, True, "active", now + timedelta(hours=3)), "high"),
        ("d", "Ожидает оплаты 1 день, деньги есть", account(10_000, True, "prolong_wait", now - timedelta(days=1)), "low"),
    )
    result = []
    for key, title, customer, expected in cases:
        evaluated = evaluate_customer(customer, model, now)
        service = evaluated["services"][0]
        result.append({
            "key": key,
            "title": title,
            "risk_score": service["risk_score"],
            "risk_level": service["risk_level"],
            "expected_level": expected,
            "matches": service["risk_level"] == expected,
        })
    return result


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
