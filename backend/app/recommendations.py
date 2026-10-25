"""Deterministic cashflow and next-best-action helpers.

The source snapshot does not contain enough labelled outcomes to train a reliable
black-box model.  These functions therefore keep every decision auditable: the
waterfall produces the cash gap, and the action plan points at the exact service
and money amount that caused it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


OPERATIONAL_HORIZON_DAYS = 14
FINANCIAL_HORIZON_DAYS = 30
BONUS_HUNTER_ALPHA = 0.15
GRACE_PERIOD_DAYS = 5


def _money(value: Any) -> int:
    return int(value or 0)


def _as_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def monthly_multiplier(payment_term: str | None) -> float:
    """Convert one payment into a monthly recurring revenue multiplier."""
    return {
        "hour": 720.0,
        "week": 30.0 / 7.0,
        "month": 1.0,
        "quarter": 1.0 / 3.0,
        "quarter_year": 1.0 / 3.0,
        "half_year": 1.0 / 6.0,
        "year": 1.0 / 12.0,
    }.get(payment_term or "month", 1.0)


def is_bonus_hunter(customer: dict[str, Any]) -> bool:
    """A bonus-only account should not inflate real-cash exposure."""
    return (
        _money(customer.get("total_replenished_minor")) == 0
        and _money(customer.get("balance_minor")) == 0
        and _money(customer.get("bonus_balance_minor")) > 0
    )


def real_monetisation_alpha(customer: dict[str, Any]) -> float:
    return BONUS_HUNTER_ALPHA if is_bonus_hunter(customer) else 1.0


def ltv_estimate(
    customer: dict[str, Any],
    services: list[dict[str, Any]],
    risk_score: float | None,
    now: datetime,
) -> dict[str, Any]:
    """Calculate an explainable, risk-adjusted LTV proxy from the snapshot.

    The snapshot has no margin, refunds, acquisition cost or labelled lifetime,
    so a true finance-grade LTV is impossible. We blend current recurring value
    with observed successful payments, use the risk index only as a churn proxy,
    and expose the inputs and confidence instead of hiding them in one number.
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    active = [
        service for service in services
        if service.get("status") in {"active", "suspended", "prolong_wait"}
    ]
    current_mrr = sum(
        round(_money(service.get("price_minor")) * monthly_multiplier(service.get("payment_term")))
        for service in active
    )
    performed = [
        transaction for transaction in customer.get("transactions", [])
        if transaction.get("status") == "performed" and _money(transaction.get("amount_minor")) > 0
    ]
    failed = [
        transaction for transaction in customer.get("transactions", [])
        if transaction.get("type") == "prolong" and transaction.get("status") == "not_performed"
    ]
    historical_revenue = sum(_money(transaction.get("amount_minor")) for transaction in performed)
    dates = [
        _as_utc(transaction.get("created_at"))
        for transaction in performed
        if _as_utc(transaction.get("created_at")) is not None
    ]
    first_payment = min(dates) if dates else None
    historical_months = max(1.0, min(60.0, ((now - first_payment).total_seconds() / 2_592_000))) if first_payment else 0.0
    historical_mrr = round(historical_revenue / historical_months) if historical_revenue and historical_months else 0
    if current_mrr and historical_mrr:
        blended_mrr = round(0.7 * current_mrr + 0.3 * historical_mrr)
    else:
        blended_mrr = current_mrr or historical_mrr

    attempts = len(performed) + len(failed)
    success_rate = round(len(performed) / attempts, 3) if attempts else None
    churn_proxy = max(0.05, min(0.95, (float(risk_score) / 100) if risk_score is not None else 0.35))
    expected_lifetime = max(1.0, min(24.0, 1.0 / churn_proxy))
    # Repeated failed renewals shorten the expected lifetime, but never erase all value.
    if success_rate is not None:
        expected_lifetime *= 0.5 + 0.5 * success_rate
    expected_lifetime = round(max(1.0, min(24.0, expected_lifetime)), 1)
    gross_ltv = round(blended_mrr * expected_lifetime)
    at_risk_ltv = round(gross_ltv * churn_proxy)
    confidence = 0.35
    if active:
        confidence += 0.2
    if risk_score is not None:
        confidence += 0.2
    if len(performed) >= 3:
        confidence += 0.15
    if success_rate is not None:
        confidence += 0.1
    confidence = round(min(0.95, confidence), 2)
    return {
        "current_mrr_minor": current_mrr,
        "historical_revenue_minor": historical_revenue,
        "historical_months": round(historical_months, 1),
        "expected_lifetime_months": expected_lifetime,
        "gross_ltv_minor": gross_ltv,
        "at_risk_ltv_minor": at_risk_ltv,
        "payment_success_rate": success_rate,
        "confidence": confidence,
        "method": "Оценка: текущий MRR + успешные платежи, срок скорректирован индексом риска",
    }


def cashflow_waterfall(
    customer: dict[str, Any],
    services: list[dict[str, Any]],
    now: datetime,
    *,
    operational_days: int = OPERATIONAL_HORIZON_DAYS,
    financial_days: int = FINANCIAL_HORIZON_DAYS,
) -> dict[str, Any]:
    """Simulate chronological debits from the spendable wallet.

    Waiting services are due at t=0.  The balance is consumed in chronological
    order, so a large later renewal cannot incorrectly hide an earlier cash gap.
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    liquid = _money(customer.get("balance_minor"))
    if customer.get("bonus_spend_enabled"):
        liquid += _money(customer.get("bonus_balance_minor"))
    hidden_reserve = _money(customer.get("withdraw_balance_minor"))
    if not customer.get("bonus_spend_enabled"):
        hidden_reserve += _money(customer.get("bonus_balance_minor"))

    end = now + timedelta(days=financial_days)
    due: list[tuple[datetime, dict[str, Any]]] = []
    for service in services:
        if service.get("status") not in {"active", "suspended", "prolong_wait"}:
            continue
        expires = _as_utc(service.get("expires_at"))
        if service.get("status") == "prolong_wait":
            decision = now
        elif expires is not None and now <= expires <= end:
            decision = expires
        else:
            continue
        due.append((decision, service))
    due.sort(key=lambda item: (item[0], str(item[1].get("id", ""))))

    remaining = liquid
    events: list[dict[str, Any]] = []
    t_zero_days: float | None = None
    for decision, service in due:
        price = _money(service.get("price_minor"))
        covered = min(remaining, price)
        deficit = price - covered
        remaining -= covered
        delta_days = max(0.0, (decision - now).total_seconds() / 86400)
        if deficit and t_zero_days is None:
            t_zero_days = delta_days
        events.append({
            "service_id": str(service.get("id")),
            "date": decision.date().isoformat(),
            "days_from_now": round(delta_days, 2),
            "price_minor": price,
            "covered_minor": covered,
            "deficit_minor": deficit,
            "status": service.get("status"),
            "payment_term": service.get("payment_term"),
        })

    operational = [event for event in events if event["days_from_now"] <= operational_days]
    financial = events
    operational_deficit = sum(event["deficit_minor"] for event in operational)
    financial_deficit = sum(event["deficit_minor"] for event in financial)
    return {
        "operational_horizon_days": operational_days,
        "financial_horizon_days": financial_days,
        "liquid_balance_minor": liquid,
        "hidden_reserve_minor": hidden_reserve,
        "mrr_minor": sum(
            round(_money(service.get("price_minor")) * monthly_multiplier(service.get("payment_term")))
            for service in services
            if service.get("status") in {"active", "suspended", "prolong_wait"}
        ),
        "events": events,
        "operational_events": operational,
        "operational_deficit_minor": operational_deficit,
        "financial_deficit_minor": financial_deficit,
        "t_zero_days": t_zero_days,
        "cash_gap": financial_deficit > 0,
    }


def build_action_plan(
    customer: dict[str, Any],
    services: list[dict[str, Any]],
    waterfall: dict[str, Any],
) -> dict[str, Any]:
    """Return a marketer-ready diagnosis, priority and next-best action."""
    scored = [service for service in services if service.get("risk_score") is not None]
    exposed = [service for service in scored if service.get("revenue_at_risk_minor", 0) > 0]
    exposed.sort(key=lambda service: (service.get("revenue_at_risk_minor", 0), service.get("risk_score", 0)), reverse=True)
    top = exposed[0] if exposed else None
    deficit = waterfall["financial_deficit_minor"]
    bonus_locked = _money(customer.get("bonus_balance_minor")) > 0 and not customer.get("bonus_spend_enabled")
    reserve_available = _money(waterfall.get("hidden_reserve_minor"))

    if top is None and (customer.get("risk_score") is None or customer.get("data_quality")):
        archetype = "data_quality"
        title = "Исправить данные"
        action = "Проверить активные услуги, статусы и даты окончания в источнике"
        message = "Проверьте статус и дату окончания услуги, чтобы мы смогли рассчитать риск."
        diagnosis = "Недостаточно данных для надёжной оценки клиента."
        expected = 0
    elif top is None:
        archetype = "healthy"
        title = "Продление без сигнала риска"
        action = "Наблюдать по стандартному сценарию"
        message = "Здравствуйте! Сейчас по вашим услугам нет признаков проблемы с продлением."
        diagnosis = "В ближайшем горизонте нет услуги с положительным индексом риска."
        expected = 0
    elif deficit > 0 and bonus_locked:
        archetype = "unlock_bonus"
        title = "Разблокировать бонусы"
        action = f"Включить использование бонусов на {(_money(customer.get('bonus_balance_minor')) / 100):.2f} € и отправить уведомление"
        message = "Разблокируйте бонусный баланс — он может покрыть ближайшее продление без пополнения."
        diagnosis = "Есть кассовый разрыв, но на счёте есть замороженный бонусный баланс."
        expected = top.get("revenue_at_risk_minor", 0)
    elif deficit > 0 and reserve_available >= deficit:
        archetype = "move_reserve"
        title = "Перевести резерв"
        action = f"Перевести {deficit / 100:.2f} € с реферального резерва и предложить бонус 5%"
        message = f"Переведите {deficit / 100:.2f} € с резервного баланса, чтобы сохранить услугу."
        diagnosis = "Ближайшие списания не покрыты ликвидным балансом, но резерв достаточен."
        expected = top.get("revenue_at_risk_minor", 0)
    elif deficit > 0:
        archetype = "top_up"
        title = "Пополнить баланс"
        action = f"Попросить пополнить баланс на {deficit / 100:.2f} € до ближайшего списания"
        message = f"Пополните баланс минимум на {deficit / 100:.2f} €, чтобы продление прошло автоматически."
        diagnosis = "Денег на балансе не хватит до ближайшего списания."
        expected = top.get("revenue_at_risk_minor", 0)
    elif top.get("recommended_action", {}).get("code") == "manual_reminder":
        archetype = "manual_renewal"
        title = "Напомнить о ручном продлении"
        action = "Отправить напоминание с точным сроком и названием услуги"
        message = "Напоминаем: продление нужно подтвердить вручную до даты окончания услуги."
        diagnosis = "Автопродление выключено, а срок услуги находится в рабочем горизонте."
        expected = top.get("revenue_at_risk_minor", 0)
    elif top.get("recommended_action", {}).get("code") == "check_payment":
        archetype = "check_payment"
        title = "Проверить платёж"
        action = "Проверить последний платёж и повторить списание"
        message = "Платёж продления не завершился. Проверьте причину и повторите списание."
        diagnosis = "Услуга ждёт оплаты при достаточном балансе или есть неуспешная попытка."
        expected = top.get("revenue_at_risk_minor", 0)
    else:
        archetype = "data_quality"
        title = "Исправить данные"
        action = "Проверить статус и дату окончания услуги в источнике"
        message = "Нужно уточнить статус или дату окончания услуги, чтобы продолжить расчёт."
        diagnosis = "Для части услуг недостаточно данных или есть противоречивый статус."
        expected = 0

    risk = float(customer.get("risk_score") or 0)
    exposure = min(100.0, expected / max(1, _money(customer.get("monthly_cost_minor"))) * 100)
    urgency = 100.0 if top and top.get("status") == "prolong_wait" else min(100.0, float(top.get("risk_score") or 0) if top else 0)
    priority = round(min(100.0, 0.45 * risk + 0.35 * exposure + 0.20 * urgency), 1)
    return {
        "archetype": archetype,
        "title": title,
        "priority": priority,
        "diagnosis": diagnosis,
        "next_best_action": action,
        "message_template": message,
        "expected_revenue_at_risk_minor": int(expected),
        "deadline": top.get("expires_at") if top else None,
        "confidence": round(1.0 if not customer.get("data_quality") else max(0.35, 1 - 0.15 * len(customer["data_quality"])), 2),
        "evidence": {
            "service_id": top.get("id") if top else None,
            "risk_score": top.get("risk_score") if top else None,
            "financial_deficit_minor": deficit,
            "operational_deficit_minor": waterfall["operational_deficit_minor"],
            "t_zero_days": waterfall["t_zero_days"],
            "real_monetisation_alpha": real_monetisation_alpha(customer),
        },
    }
