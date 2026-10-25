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


MONTHS = ("янв.", "февр.", "марта", "апр.", "мая", "июня", "июля", "авг.", "сент.", "окт.", "нояб.", "дек.")
TERM_TEXT = {
    "hour": "в час",
    "week": "в неделю",
    "month": "в месяц",
    "quarter": "в квартал",
    "quarter_year": "в квартал",
    "half_year": "за полгода",
    "year": "в год",
}
LOST_STATUSES = {"deleted", "blocked"}
KEY_REPLENISHED_MINOR = 100_000
KEY_MONTHLY_MINOR = 10_000
REGULAR_REPLENISHED_MINOR = 10_000


def _eur(amount_minor: int) -> str:
    text = f"{amount_minor / 100:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} €"


def _date_text(value: datetime | None) -> str:
    return f"{value.day} {MONTHS[value.month - 1]}" if value else "без даты"


def _when_text(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "срок не указан"
    hours = (value - now).total_seconds() / 3600
    if hours <= 0:
        return f"срок прошёл ({_date_text(value)})"
    if hours < 48:
        return f"через {max(1, round(hours))} ч ({_date_text(value)})"
    return f"через {round(hours / 24)} дн. ({_date_text(value)})"


def _services_word(count: int) -> str:
    return "услуги" if count % 10 == 1 and count % 100 != 11 else "услуг"


def _segment(customer: dict[str, Any]) -> dict[str, str]:
    replenished = _money(customer.get("total_replenished_minor"))
    monthly = _money(customer.get("monthly_cost_minor"))
    facts = f"пополнено {_eur(replenished)}" + (f", услуги {_eur(monthly)} в месяц" if monthly else "")
    if is_bonus_hunter(customer):
        return {"code": "bonus_only", "title": "Только бонусы", "reason": "Живых пополнений нет, на счёте только бонусы."}
    if replenished >= KEY_REPLENISHED_MINOR or monthly >= KEY_MONTHLY_MINOR:
        return {"code": "key", "title": "Ключевой клиент", "reason": f"Крупный клиент: {facts}."}
    if replenished >= REGULAR_REPLENISHED_MINOR:
        return {"code": "regular", "title": "Постоянный клиент", "reason": f"Платит регулярно: {facts}."}
    return {"code": "new", "title": "Новый клиент", "reason": f"Небольшая история: {facts}."}


def _channel(archetype: str, segment: str) -> str:
    if archetype == "data_quality":
        return "Задача в биллинг, клиенту пока не писать"
    if archetype == "healthy":
        return "Обычная рассылка"
    if segment == "key":
        return "Личное письмо и звонок менеджера"
    if segment == "regular":
        return "Письмо и уведомление в панели"
    return "Автоматическое письмо"


def _signals(
    customer: dict[str, Any],
    services: list[dict[str, Any]],
    waterfall: dict[str, Any],
    top: dict[str, Any] | None,
    lost: list[dict[str, Any]],
    now: datetime,
) -> list[str]:
    facts: list[str] = []
    if top is not None:
        expires = _as_utc(top.get("expires_at"))
        price = f"{_eur(_money(top.get('price_minor')))} {TERM_TEXT.get(top.get('payment_term') or 'month', '')}".strip()
        if top.get("status") == "prolong_wait":
            deleted_at = expires + timedelta(days=GRACE_PERIOD_DAYS) if expires else None
            facts.append(f"«{top.get('name')}» ({price}) ждёт оплаты, удаление {_when_text(deleted_at, now)}.")
        else:
            facts.append(f"«{top.get('name')}» ({price}) продлевается {_when_text(expires, now)}.")
    live = [service for service in services if service.get("status") not in LOST_STATUSES]
    manual = [service for service in live if service.get("auto_prolong") is False]
    if manual:
        facts.append(f"Автопродление выключено у {len(manual)} из {len(live)} {_services_word(len(live))}.")
    due_total = sum(event["price_minor"] for event in waterfall.get("events", []))
    if due_total:
        facts.append(
            f"Доступно {_eur(waterfall['liquid_balance_minor'])} при списаниях "
            f"{_eur(due_total)} за {waterfall['financial_horizon_days']} дней."
        )
    if waterfall.get("financial_deficit_minor"):
        days = waterfall.get("t_zero_days")
        if days is None:
            start = ""
        elif days < 1 / 24:
            start = ", деньги нужны уже сейчас"
        elif days < 2:
            start = f", деньги кончатся через {max(1, round(days * 24))} ч"
        else:
            start = f", деньги кончатся через {round(days)} дн."
        facts.append(f"Не хватит {_eur(waterfall['financial_deficit_minor'])}{start}".rstrip(".") + ".")
    bonus = _money(customer.get("bonus_balance_minor"))
    if bonus and not customer.get("bonus_spend_enabled"):
        facts.append(f"Заморожено бонусов: {_eur(bonus)}.")
    reserve = _money(customer.get("withdraw_balance_minor"))
    if reserve and waterfall.get("financial_deficit_minor"):
        facts.append(f"На реферальном балансе {_eur(reserve)}.")
    transactions = customer.get("transactions") or []
    renewals = [t for t in transactions if t.get("type") == "prolong"]
    failed = [t for t in renewals if t.get("status") == "not_performed"]
    if renewals:
        facts.append(f"Оплат продления в истории: {len(renewals)}, неуспешных {len(failed)}.")
    if lost:
        names = ", ".join(f"«{service.get('name')}»" for service in lost[:3])
        more = f" и ещё {len(lost) - 3}" if len(lost) > 3 else ""
        facts.append(f"Уже потеряно услуг: {len(lost)} ({names}{more}).")
    return facts[:7]


def _offer(archetype: str, segment: str, services: list[dict[str, Any]], customer: dict[str, Any]) -> str | None:
    manual = any(
        service.get("auto_prolong") is False and service.get("status") not in LOST_STATUSES
        for service in services
    )
    if archetype == "unlock_bonus":
        return f"Разрешить списание бонусов: {_eur(_money(customer.get('bonus_balance_minor')))} покроют продление без пополнения."
    if archetype == "move_reserve":
        return "Перевести деньги с реферального баланса на основной, клиенту не нужно платить заново."
    if archetype == "top_up" and segment in {"key", "regular"}:
        return "Бонус 5 % к пополнению, если клиент пополнит баланс до срока."
    if archetype == "win_back" and segment in {"key", "regular"}:
        return "Персональное предложение вернуться: восстановить услугу с прежними настройками."
    if manual and archetype in {"manual_renewal", "healthy", "top_up"}:
        return "Включить автопродление: следующие продления пройдут сами."
    return None


def _steps(archetype: str, segment: str, plan: dict[str, Any], top: dict[str, Any] | None) -> list[dict[str, str]]:
    deficit = plan["evidence"]["financial_deficit_minor"]
    waiting = top is not None and top.get("status") == "prolong_wait"
    call = segment == "key"
    if archetype == "top_up":
        steps = [
            {"when": "Сейчас", "text": f"Отправить письмо: сумма пополнения {_eur(deficit)} и срок."},
            {"when": "За 24 часа до списания", "text": "Если баланс не пополнен, повторить напоминание."},
        ]
        if waiting:
            steps[1] = {"when": "Через 2 дня", "text": f"Если оплаты нет, напомнить: через {GRACE_PERIOD_DAYS} дней ожидания услуга удаляется."}
        steps.append({"when": "Если не помогло", "text": "Позвонить клиенту." if call else "Отправить последнее предупреждение перед удалением."})
        steps.append({"when": "После оплаты", "text": "Предложить включить автопродление и держать запас на балансе."})
        return steps
    if archetype == "unlock_bonus":
        bonus = _money(plan["evidence"].get("bonus_balance_minor"))
        return [
            {"when": "Сейчас", "text": "Разрешить списание бонусов в биллинге."},
            {"when": "Сразу после", "text": "Сообщить клиенту, что продление покроют бонусы."},
        ] + (
            [{"when": "Бонусов не хватит", "text": f"Попросить пополнить ещё на {_eur(deficit - bonus)}."}]
            if bonus < deficit else []
        )
    if archetype == "move_reserve":
        return [
            {"when": "Сейчас", "text": f"Предложить перевести {_eur(deficit)} с реферального баланса."},
            {"when": "За 24 часа до списания", "text": "Проверить, что перевод прошёл, иначе напомнить."},
        ]
    if archetype == "manual_renewal":
        return [
            {"when": "Сейчас", "text": "Напомнить о продлении: название услуги, дата и ссылка на оплату."},
            {"when": "За 24 часа до срока", "text": "Если не продлил, повторить напоминание."},
            {"when": "В день срока", "text": "Позвонить клиенту." if call else "Отправить последнее напоминание."},
            {"when": "После продления", "text": "Предложить включить автопродление."},
        ]
    if archetype == "check_payment":
        return [
            {"when": "Сейчас", "text": "Найти последнюю попытку оплаты в биллинге и её причину."},
            {"when": "Сразу после", "text": "Повторить списание: деньги на балансе есть."},
            {"when": "Если отказ повторился", "text": "Написать клиенту и попросить проверить способ оплаты."},
        ]
    if archetype == "win_back":
        return [
            {"when": "Сейчас", "text": "Узнать в биллинге и поддержке, почему услуги удалены или заблокированы."},
            {"when": "Если причина не в нарушении", "text": "Предложить вернуть услугу." if not call else "Позвонить и предложить вернуть услугу."},
            {"when": "Через неделю", "text": "Если ответа нет, отправить короткий опрос о причине ухода."},
        ]
    if archetype == "data_quality":
        return [
            {"when": "Сейчас", "text": "Передать в биллинг: проверить статусы и даты окончания услуг."},
            {"when": "После исправления", "text": "Оценка пересчитается сама, тогда решить, писать ли клиенту."},
        ]
    return [{"when": "Планово", "text": "Обычная рассылка, отдельных действий не нужно."}]


def _message(archetype: str, plan: dict[str, Any], top: dict[str, Any] | None, customer: dict[str, Any], now: datetime) -> tuple[str, str]:
    name = f"«{top.get('name')}»" if top else "ваших услуг"
    expires = _as_utc(top.get("expires_at")) if top else None
    price = _eur(_money(top.get("price_minor"))) if top else ""
    deficit = _eur(plan["evidence"]["financial_deficit_minor"])
    waiting = top is not None and top.get("status") == "prolong_wait"
    if archetype == "top_up" and waiting:
        deleted_at = expires + timedelta(days=GRACE_PERIOD_DAYS) if expires else None
        return (
            f"Услуга {name} ждёт оплаты",
            f"Здравствуйте! Услуга {name} ждёт оплаты {price}. Пополните баланс на {deficit} до {_date_text(deleted_at)}, "
            "иначе услуга будет удалена вместе с данными.",
        )
    if archetype == "top_up":
        return (
            f"Пополните баланс для продления {name}",
            f"Здравствуйте! {_date_text(expires)} продлевается услуга {name} за {price}. На балансе не хватает {deficit}. "
            "Пополните баланс заранее, и продление пройдёт автоматически.",
        )
    if archetype == "unlock_bonus":
        return (
            f"Бонусы покроют продление {name}",
            f"Здравствуйте! Мы разрешили оплату бонусами: продление {name} за {price} {_date_text(expires)} пройдёт без пополнения.",
        )
    if archetype == "move_reserve":
        return (
            f"Продление {name}: переведите средства с реферального баланса",
            f"Здравствуйте! Для продления {name} не хватает {deficit}. Переведите эту сумму с реферального баланса на основной, "
            "и услуга продлится автоматически.",
        )
    if archetype == "manual_renewal":
        return (
            f"Продлите {name} до {_date_text(expires)}",
            f"Здравствуйте! У услуги {name} выключено автопродление, срок заканчивается {_when_text(expires, now)}. "
            f"Продлите её в панели за {price}, чтобы сервер продолжил работу. Включите автопродление, и напоминать больше не придётся.",
        )
    if archetype == "check_payment":
        return (
            f"Оплата продления {name} не прошла",
            f"Здравствуйте! Мы не смогли списать оплату за {name}, хотя деньги на балансе есть. "
            "Мы повторим списание. Если ошибка повторится, проверьте, пожалуйста, способ оплаты.",
        )
    if archetype == "win_back":
        return (
            "Вернём ваши услуги в Aéza",
            "Здравствуйте! Мы заметили, что ваши услуги больше не работают. Расскажите, что пошло не так: "
            "поможем восстановить сервер с прежними настройками.",
        )
    if archetype == "data_quality":
        return ("", "")
    return ("", "")


def _urgency_label(top: dict[str, Any] | None, priority: float, now: datetime, archetype: str = "") -> str:
    if archetype == "win_back":
        return "На этой неделе"
    if top is not None:
        expires = _as_utc(top.get("expires_at"))
        if top.get("status") == "prolong_wait" or (expires and (expires - now).total_seconds() < 48 * 3600):
            return "Срочно"
        if expires and (expires - now).days < 7:
            return "На этой неделе"
    return "Срочно" if priority >= 60 else "Планово"


def build_action_plan(
    customer: dict[str, Any],
    services: list[dict[str, Any]],
    waterfall: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a marketer-ready diagnosis, priority, steps and a ready message."""
    now = _as_utc(now) or datetime.now(timezone.utc)
    scored = [service for service in services if service.get("risk_score") is not None]
    exposed = [service for service in scored if service.get("revenue_at_risk_minor", 0) > 0]
    exposed.sort(key=lambda service: (service.get("revenue_at_risk_minor", 0), service.get("risk_score", 0)), reverse=True)
    top = exposed[0] if exposed else None
    lost = [service for service in services if service.get("status") in LOST_STATUSES]
    deficit = waterfall["financial_deficit_minor"]
    bonus_locked = _money(customer.get("bonus_balance_minor")) > 0 and not customer.get("bonus_spend_enabled")
    reserve_available = _money(waterfall.get("hidden_reserve_minor"))

    if top is None and lost:
        archetype = "win_back"
        title = "Вернуть клиента"
        action = "Выяснить причину ухода и предложить вернуть услуги"
        diagnosis = f"Клиент уже потерял {len(lost)} из {len(services)} {_services_word(len(services))}: они удалены или заблокированы."
        expected = 0
    elif top is None and (customer.get("risk_score") is None or customer.get("data_quality")):
        archetype = "data_quality"
        title = "Исправить данные"
        action = "Проверить активные услуги, статусы и даты окончания в источнике"
        diagnosis = "Данных не хватает для надёжной оценки: у услуг нет даты окончания или статус противоречит сроку."
        expected = 0
    elif top is None:
        archetype = "healthy"
        title = "Продление без сигнала риска"
        action = "Наблюдать по стандартному сценарию"
        diagnosis = "В ближайшие 7 дней нет услуг с риском непродления."
        expected = 0
    elif deficit > 0 and bonus_locked:
        archetype = "unlock_bonus"
        title = "Разблокировать бонусы"
        action = f"Включить оплату бонусами на {_eur(_money(customer.get('bonus_balance_minor')))} и сообщить клиенту"
        diagnosis = "Денег на балансе не хватает, но на счёте лежат замороженные бонусы."
        expected = top.get("revenue_at_risk_minor", 0)
    elif deficit > 0 and reserve_available >= deficit:
        archetype = "move_reserve"
        title = "Перевести резерв"
        action = f"Предложить перевести {_eur(deficit)} с реферального баланса"
        diagnosis = "Основного баланса не хватает на продления, но реферальный баланс их покрывает."
        expected = top.get("revenue_at_risk_minor", 0)
    elif deficit > 0:
        archetype = "top_up"
        title = "Пополнить баланс"
        action = f"Попросить пополнить баланс на {_eur(deficit)} до ближайшего списания"
        diagnosis = "Денег на балансе не хватит до ближайшего списания."
        expected = top.get("revenue_at_risk_minor", 0)
    elif top.get("recommended_action", {}).get("code") == "manual_reminder":
        archetype = "manual_renewal"
        title = "Напомнить о ручном продлении"
        action = "Отправить напоминание с точным сроком и названием услуги"
        diagnosis = "Автопродление выключено, а срок услуги наступает в ближайшие 7 дней. Деньги есть, нужен только сам клиент."
        expected = top.get("revenue_at_risk_minor", 0)
    elif top.get("recommended_action", {}).get("code") == "check_payment":
        archetype = "check_payment"
        title = "Проверить платёж"
        action = "Проверить последний платёж и повторить списание"
        diagnosis = "Услуга ждёт оплаты, хотя денег на балансе хватает: похоже на сбой списания."
        expected = top.get("revenue_at_risk_minor", 0)
    else:
        archetype = "data_quality"
        title = "Исправить данные"
        action = "Проверить статус и дату окончания услуги в источнике"
        diagnosis = "Для части услуг не хватает данных или статус противоречит сроку."
        expected = 0

    risk = float(customer.get("risk_score") or 0)
    exposure = min(100.0, expected / max(1, _money(customer.get("monthly_cost_minor"))) * 100)
    urgency = 100.0 if top and top.get("status") == "prolong_wait" else min(100.0, float(top.get("risk_score") or 0) if top else 0)
    priority = round(min(100.0, 0.45 * risk + 0.35 * exposure + 0.20 * urgency), 1)
    segment = _segment(customer)
    plan = {
        "archetype": archetype,
        "title": title,
        "priority": priority,
        "diagnosis": diagnosis,
        "next_best_action": action,
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
            "bonus_balance_minor": _money(customer.get("bonus_balance_minor")),
        },
    }
    subject, body = _message(archetype, plan, top, customer, now)
    plan.update({
        "message_subject": subject,
        "message_template": body,
        "urgency_label": _urgency_label(top, priority, now, archetype),
        "segment": segment,
        "channel": _channel(archetype, segment["code"]),
        "offer": _offer(archetype, segment["code"], services, customer),
        "signals": _signals(customer, services, waterfall, top, lost, now),
        "steps": _steps(archetype, segment["code"], plan, top),
    })
    return plan
