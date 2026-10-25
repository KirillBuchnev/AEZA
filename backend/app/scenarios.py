"""Сценарные аккаунты: по одной ситуации брифа на аккаунт, показываются рядом с датасетом кейса.

В датасете кейса балансы намного выше цен, а даты размазаны по году, поэтому почти ни один аккаунт
не в зоне риска и денежная оценка остаётся нулевой. Эти аккаунты строятся относительно текущего
времени, поэтому не устаревают. Id S01-S14 и домен scenario.example помечают их как сценарные.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def scenario_customers(now: datetime | None = None) -> list[dict[str, Any]]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def at(days: float = 0.0, hours: float = 0.0) -> str:
        return (now + timedelta(days=days, hours=hours)).isoformat()

    def service(
        owner: str,
        number: int,
        name: str,
        price: int,
        *,
        auto: bool,
        expires: str | None,
        term: str = "month",
        status: str = "active",
    ) -> dict[str, Any]:
        return {
            "id": f"{owner}-{number}",
            "name": name,
            "price_minor": price,
            "auto_prolong": auto,
            "payment_term": term,
            "status": status,
            "expires_at": expires,
        }

    def prolong(owner: str, number: int, service_id: str, amount: int, when: str, performed: bool = True) -> dict[str, Any]:
        return {
            "id": f"T-{owner}-{number}",
            "service_id": service_id,
            "status": "performed" if performed else "not_performed",
            "type": "prolong",
            "amount_minor": amount,
            "created_at": when,
        }

    def account(
        owner: str,
        slug: str,
        balance: int,
        replenished: int,
        services: list[dict[str, Any]],
        transactions: list[dict[str, Any]],
        *,
        bonus: int = 0,
        bonus_enabled: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": owner,
            "email": f"{owner.lower()}-{slug}@scenario.example",
            "balance_minor": balance,
            "withdraw_balance_minor": 0,
            "bonus_balance_minor": bonus,
            "bonus_spend_enabled": bonus_enabled,
            "total_replenished_minor": replenished,
            "services": services,
            "transactions": transactions,
        }

    return [
        # Ручное продление завтра, деньги на месте: клиент должен сам о нём вспомнить.
        account("S01", "manual-soon", 5000, 30000,
                [service("S01", 1, "Виртуальный сервер", 900, auto=False, expires=at(hours=20))],
                [prolong("S01", 1, "S01-1", 900, at(days=-30))]),
        # Автопродление включено, но баланс покрывает лишь пятую часть цены.
        account("S02", "short-balance", 300, 20000,
                [service("S02", 1, "Виртуальный сервер Pro", 1500, auto=True, expires=at(days=2))],
                [prolong("S02", 1, "S02-1", 1500, at(days=-28))]),
        # Контрольный кейс a: ожидание оплаты и денег нет.
        account("S03", "wait-no-funds", 0, 15000,
                [service("S03", 1, "Выделенный сервер Mini", 6000, auto=True, status="prolong_wait", expires=at(days=-1))],
                [prolong("S03", 1, "S03-1", 6000, at(days=-31))]),
        # Контрольный кейс d: тот же статус при деньгах на балансе — неуспешное списание, а не потеря.
        account("S04", "wait-has-funds", 10000, 24000,
                [service("S04", 1, "Облачный сервер", 1200, auto=True, status="prolong_wait", expires=at(days=-1))],
                [prolong("S04", 1, "S04-1", 1200, at(days=-31))]),
        # Три сервера: баланс оплачивает первые два, а на третье, ручное, его не хватает.
        account("S05", "big-account", 12000, 250000,
                [
                    service("S05", 1, "Выделенный сервер EPYC", 9000, auto=True, expires=at(days=1)),
                    service("S05", 2, "Облачный сервер 1", 2500, auto=True, expires=at(days=2)),
                    service("S05", 3, "Облачный сервер 2", 2500, auto=False, expires=at(days=3)),
                ],
                [
                    prolong("S05", 1, "S05-1", 9000, at(days=-29)),
                    prolong("S05", 2, "S05-2", 2500, at(days=-28)),
                    prolong("S05", 3, "S05-3", 2500, at(days=-27)),
                ]),
        # Крупный годовой контракт с ручным продлением через пять дней: низкий риск, высокая ценность.
        account("S06", "big-annual", 90000, 400000,
                [service("S06", 1, "Выделенный сервер Xeon", 72000, auto=False, term="year", expires=at(days=5))],
                [prolong("S06", 1, "S06-1", 72000, at(days=-360))]),
        # Бонусный баланс можно тратить (bonusState включён): он оплачивает продление.
        account("S07", "bonus-open", 200, 5000,
                [service("S07", 1, "Облачный сервер", 1200, auto=True, expires=at(days=1))],
                [prolong("S07", 1, "S07-1", 1200, at(days=-29))],
                bonus=3000, bonus_enabled=True),
        # Тот же бонусный баланс, но тратить нельзя: нехватка реальна.
        account("S08", "bonus-locked", 200, 5000,
                [service("S08", 1, "Облачный сервер", 1200, auto=True, expires=at(days=1))],
                [prolong("S08", 1, "S08-1", 1200, at(days=-29))],
                bonus=3000, bonus_enabled=False),
        # Почасовая тарификация: следующее списание — центы, месячная стоимость — нет.
        account("S09", "hourly-low", 4, 3000,
                [service("S09", 1, "Виртуальный сервер (почасовой)", 12, auto=True, term="hour", expires=at(hours=0.4))],
                [prolong("S09", 1, "S09-1", 12, at(hours=-1))]),
        # Деньги сейчас есть, но последняя попытка продления два дня назад провалилась.
        account("S10", "failed-payment", 8000, 18000,
                [service("S10", 1, "Облачный сервер", 1500, auto=True, expires=at(days=3))],
                [
                    prolong("S10", 1, "S10-1", 1500, at(days=-33)),
                    prolong("S10", 2, "S10-1", 1500, at(days=-2), performed=False),
                ]),
        # Зелёная база: автопродление включено, солидный баланс, близких платежей нет.
        account("S11", "healthy", 20000, 90000,
                [
                    service("S11", 1, "Виртуальный сервер", 1500, auto=True, expires=at(days=20)),
                    service("S11", 2, "Облачный диск", 800, auto=True, term="quarter_year", expires=at(days=45)),
                ],
                [prolong("S11", 1, "S11-1", 1500, at(days=-10)), prolong("S11", 2, "S11-2", 800, at(days=-45))]),
        # Частичный отток: одна услуга удалена десять дней назад, другая продолжает жить.
        account("S12", "partial-churn", 3000, 40000,
                [
                    service("S12", 1, "Облачный сервер", 2000, auto=True, status="deleted", expires=at(days=-10)),
                    service("S12", 2, "Облачный диск", 800, auto=True, expires=at(days=15)),
                ],
                [prolong("S12", 1, "S12-2", 800, at(days=-15))]),
        # Полный отток: продлевать нечего, значит и оценивать нечего.
        account("S13", "churned", 500, 22000,
                [
                    service("S13", 1, "Выделенный сервер", 3000, auto=False, status="deleted", expires=at(days=-25)),
                    service("S13", 2, "Облачный сервер", 1200, auto=True, status="blocked", expires=at(days=-12)),
                ],
                [prolong("S13", 1, "S13-1", 3000, at(days=-55))]),
        # Недостающие данные: нет даты окончания, риск не считается, и карточка объясняет почему.
        account("S14", "no-expiry", 5000, 12000,
                [service("S14", 1, "Виртуальный сервер", 900, auto=True, expires=None)],
                [prolong("S14", 1, "S14-1", 900, at(days=-20))]),
    ]
