from datetime import datetime, timedelta, timezone

from app.recommendations import (
    BONUS_HUNTER_ALPHA,
    build_action_plan,
    cashflow_waterfall,
    monthly_multiplier,
    real_monetisation_alpha,
)


NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def service(service_id: str, *, days: int, price: int, risk: float = 60.0, action: str = "top_up") -> dict:
    return {
        "id": service_id,
        "name": service_id,
        "status": "active",
        "expires_at": (NOW + timedelta(days=days)).isoformat(),
        "price_minor": price,
        "payment_term": "month",
        "risk_score": risk,
        "revenue_at_risk_minor": round(price * risk / 100),
        "recommended_action": {"code": action, "text": action},
    }


def test_monthly_multipliers_cover_short_and_long_payment_terms():
    assert monthly_multiplier("hour") == 720
    assert monthly_multiplier("week") == 30 / 7
    assert monthly_multiplier("year") == 1 / 12


def test_waterfall_spends_balance_in_due_date_order_and_finds_first_cash_gap():
    customer = {"balance_minor": 1_500, "bonus_balance_minor": 0, "bonus_spend_enabled": False, "withdraw_balance_minor": 0}
    result = cashflow_waterfall(customer, [
        {**service("later", days=5, price=1_500), "status": "active"},
        {**service("first", days=1, price=1_000), "status": "active"},
    ], NOW)

    assert [event["service_id"] for event in result["events"]] == ["first", "later"]
    assert result["events"][0]["deficit_minor"] == 0
    assert result["events"][1]["deficit_minor"] == 1_000
    assert result["t_zero_days"] == 5.0
    assert result["operational_deficit_minor"] == 1_000


def test_bonus_only_customer_is_discounted_and_gets_unlock_action():
    customer = {
        "balance_minor": 0,
        "bonus_balance_minor": 2_000,
        "bonus_spend_enabled": False,
        "withdraw_balance_minor": 0,
        "total_replenished_minor": 0,
        "risk_score": 60,
        "monthly_cost_minor": 1_000,
        "data_quality": [],
    }
    assert real_monetisation_alpha(customer) == BONUS_HUNTER_ALPHA
    svc = service("bonus", days=1, price=1_000)
    waterfall = cashflow_waterfall(customer, svc and [svc], NOW)
    plan = build_action_plan(customer, [svc], waterfall)
    assert plan["archetype"] == "unlock_bonus"
    assert plan["evidence"]["real_monetisation_alpha"] == BONUS_HUNTER_ALPHA


def test_reserve_action_is_selected_when_reserve_covers_the_gap():
    customer = {
        "balance_minor": 0,
        "bonus_balance_minor": 0,
        "bonus_spend_enabled": False,
        "withdraw_balance_minor": 2_000,
        "total_replenished_minor": 100,
        "risk_score": 60,
        "monthly_cost_minor": 1_000,
        "data_quality": [],
    }
    svc = service("reserve", days=1, price=1_000)
    waterfall = cashflow_waterfall(customer, [svc], NOW)
    plan = build_action_plan(customer, [svc], waterfall)
    assert plan["archetype"] == "move_reserve"


def test_unscored_customer_gets_data_quality_action_instead_of_healthy_verdict():
    customer = {
        "balance_minor": 0,
        "bonus_balance_minor": 0,
        "bonus_spend_enabled": False,
        "withdraw_balance_minor": 0,
        "total_replenished_minor": 0,
        "risk_score": None,
        "monthly_cost_minor": 0,
        "data_quality": [{"code": "missing_expiry"}],
    }
    waterfall = cashflow_waterfall(customer, [], NOW)
    plan = build_action_plan(customer, [], waterfall)
    assert plan["archetype"] == "data_quality"
