from datetime import datetime, timedelta, timezone

from app.risk import DEFAULT_MODEL_SETTINGS, evaluate_customer


NOW = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)


def make_customer(*, status="active", hours=3, auto=False, balance=0, services=None, transactions=None):
    due = NOW + timedelta(hours=hours)
    return {
        "id": "customer-1",
        "email": "customer@example.test",
        "balance_minor": balance,
        "withdraw_balance_minor": 0,
        "bonus_balance_minor": 0,
        "bonus_spend_enabled": False,
        "total_replenished_minor": 0,
        "services": services or [{
            "id": "service-1", "name": "Server", "price_minor": 1000,
            "auto_prolong": auto, "payment_term": "month", "status": status,
            "expires_at": (due if status != "prolong_wait" else NOW - timedelta(days=1)).isoformat(),
        }],
        "transactions": transactions or [],
    }


def score(customer):
    return evaluate_customer(customer, DEFAULT_MODEL_SETTINGS, NOW)


def test_mentor_scenarios_have_expected_order_and_levels():
    cases = [
        make_customer(status="prolong_wait", hours=-24, auto=True, balance=0),
        make_customer(status="active", hours=3, auto=False, balance=1000),
        make_customer(status="active", hours=3, auto=True, balance=0),
        make_customer(status="prolong_wait", hours=-24, auto=True, balance=1000),
    ]
    results = [score(customer) for customer in cases]
    assert all(item["risk_level"] == "high" for item in results[:3])
    assert results[3]["risk_level"] == "low"
    assert all(results[index]["risk_score"] > results[3]["risk_score"] for index in range(3))


def test_account_score_is_sum_of_service_scores_and_supports_200_services():
    services = [{
        "id": f"service-{index}", "name": "Server", "price_minor": 1000,
        "auto_prolong": False, "payment_term": "month", "status": "active",
        "expires_at": (NOW + timedelta(hours=3)).isoformat(),
    } for index in range(200)]
    result = score(make_customer(services=services, balance=200_000))
    assert result["assessed_service_count"] == 200
    assert result["risk_score"] == round(sum(item["risk_score"] for item in result["services"]), 6)
    assert result["risk_score"] > 100


def test_shared_wallet_is_allocated_by_due_time_and_bonus_only_when_unlocked():
    services = [
        {"id": "first", "name": "First", "price_minor": 1000, "auto_prolong": True,
         "payment_term": "month", "status": "active", "expires_at": (NOW + timedelta(hours=1)).isoformat()},
        {"id": "later", "name": "Later", "price_minor": 1000, "auto_prolong": True,
         "payment_term": "month", "status": "active", "expires_at": (NOW + timedelta(days=2)).isoformat()},
    ]
    customer = make_customer(services=services, balance=0)
    customer["bonus_balance_minor"] = 1000
    customer["bonus_spend_enabled"] = True
    result = score(customer)
    assert result["available_balance_minor"] == 1000
    assert result["services"][0]["uncovered_minor"] == 0
    assert result["services"][1]["uncovered_minor"] == 1000
    customer["bonus_spend_enabled"] = False
    result = score(customer)
    assert result["available_balance_minor"] == 0
    assert result["services"][0]["uncovered_minor"] == 1000


def test_not_performed_transaction_is_not_a_predictive_feature():
    plain = make_customer(status="active", hours=20, auto=True, balance=100_000)
    with_transaction = make_customer(status="active", hours=20, auto=True, balance=100_000,
                                     transactions=[{"type": "prolong", "status": "not_performed"}])
    assert score(plain)["risk_score"] == score(with_transaction)["risk_score"]


def test_one_bad_expiry_does_not_hide_assessable_services():
    services = [
        {"id": "unknown", "name": "Unknown", "price_minor": 1000, "auto_prolong": False,
         "payment_term": "month", "status": "active", "expires_at": None},
        {"id": "known", "name": "Known", "price_minor": 1000, "auto_prolong": False,
         "payment_term": "month", "status": "active", "expires_at": (NOW + timedelta(hours=3)).isoformat()},
    ]
    result = score(make_customer(services=services, balance=1000))
    assert result["assessment_status"] == "insufficient_data"
    assert result["assessed_service_count"] == 1
    assert result["services"][0]["assessment_status"] == "unknown"
    assert result["services"][1]["risk_score"] is not None
