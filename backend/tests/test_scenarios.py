"""The scenario accounts are the executable list of situations an analyst has to recognise."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.risk import DEFAULT_MODEL_SETTINGS, evaluate_customer
from app.schemas import SnapshotUpload
from app.scenarios import scenario_customers

CASE_JSON = Path(__file__).resolve().parents[1] / "app" / "seeds" / "case_snapshot.json"
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
ADMIN_PASSWORD = "local-demo-change-this-password"
SUMMARY = "/api/v1/analytics/summary"
CUSTOMERS = "/api/v1/customers"
SNAPSHOT = "/api/v1/source/snapshot"

# level, recommended action, maximum (near-term loss) and balance part (potential loss) in euro cents
EXPECTED = {
    "S01": ("high", "manual_reminder", 900, 0),
    "S02": ("medium", "top_up", 1500, 406),
    "S03": ("high", "top_up", 6000, 3330),
    "S04": ("low", "check_payment", 1200, 0),
    "S05": ("high", "top_up", 2500, 1008),
    "S06": ("low", "manual_reminder", 72_000, 0),
    "S07": ("low", "none", 0, 0),
    "S08": ("medium", "top_up", 1200, 416),
    "S09": ("medium", "top_up", 12, 3),
    "S10": ("low", "check_payment", 0, 0),
    "S11": ("low", "none", 0, 0),
    "S12": ("low", "none", 0, 0),
    "S13": (None, "none", 0, 0),
    "S14": (None, "fix_data", 0, 0),
}


def evaluated() -> dict[str, dict]:
    return {
        customer["id"]: evaluate_customer(customer, DEFAULT_MODEL_SETTINGS, NOW)
        for customer in scenario_customers(NOW)
    }


def sign_in(client) -> None:
    assert client.post("/api/v1/auth/login", json={"username": "demo", "password": ADMIN_PASSWORD}).status_code == 200


@pytest.mark.parametrize("scenario_id", sorted(EXPECTED))
def test_each_scenario_gives_its_expected_level_action_and_money(scenario_id):
    level, action, near_term, loss = EXPECTED[scenario_id]
    result = evaluated()[scenario_id]
    assert result["risk_level"] == level
    assert result["recommended_action"]["code"] == action
    assert result["near_term_loss_minor"] == near_term
    assert result["potential_loss_minor"] == loss


def test_waiting_for_payment_is_a_risk_only_without_money():
    results = evaluated()
    assert results["S03"]["risk_level"] == "high"
    assert results["S04"]["risk_level"] == "low"
    assert results["S03"]["services"][0]["status"] == results["S04"]["services"][0]["status"] == "prolong_wait"


def test_bonus_balance_counts_only_when_spending_is_allowed():
    results = evaluated()
    assert results["S07"]["uncovered_revenue_minor"] == 0
    assert results["S08"]["uncovered_revenue_minor"] == 1000
    assert results["S07"]["services"][0]["price_minor"] == results["S08"]["services"][0]["price_minor"]


def test_shortfall_of_a_large_account_lands_on_the_last_due_service():
    scores = [service["risk_score"] for service in evaluated()["S05"]["services"]]
    assert scores[:2] == [0.0, 0.0]
    assert scores[2] > 50
    assert evaluated()["S05"]["uncovered_revenue_minor"] == 2000
    # The other two services carry no risk, so the account index is the index of the third one.
    assert evaluated()["S05"]["risk_score"] == scores[2]


def test_in_every_scenario_the_balance_part_is_within_the_expected_loss_within_the_maximum():
    for scenario_id, result in evaluated().items():
        assert result["potential_loss_minor"] <= result["revenue_at_risk_minor"] <= result["near_term_loss_minor"], scenario_id


def test_a_big_annual_renewal_is_low_risk_but_carries_the_most_money_at_risk():
    results = evaluated()
    others = sum(r["revenue_at_risk_minor"] for key, r in results.items() if key != "S06")
    assert results["S06"]["risk_level"] == "low"
    assert results["S06"]["revenue_at_risk_minor"] > others


def test_hourly_service_has_tiny_next_charge_and_large_monthly_cost():
    result = evaluated()["S09"]
    assert result["due_revenue_minor"] == 12
    assert result["monthly_cost_minor"] == 8_640


def test_unscored_scenarios_explain_why():
    results = evaluated()
    assert results["S13"]["reasons"][0]["code"] == "insufficient_data"
    assert [issue["code"] for issue in results["S14"]["data_quality"]] == ["missing_expiry"]


def test_scenario_dates_follow_the_current_time():
    first = scenario_customers(NOW)
    later = scenario_customers(datetime(2026, 11, 24, 12, tzinfo=timezone.utc))
    assert first[0]["services"][0]["expires_at"] != later[0]["services"][0]["expires_at"]
    assert {customer["id"] for customer in first} == set(EXPECTED)


def test_case_snapshot_has_useful_scores_for_at_least_seventy_percent_of_customers():
    payload = json.loads(CASE_JSON.read_text(encoding="utf-8"))
    customers = SnapshotUpload.model_validate(payload).customers
    evaluated_case = [
        evaluate_customer(customer.model_dump(), DEFAULT_MODEL_SETTINGS, NOW)
        for customer in customers
    ]
    scored = [customer for customer in evaluated_case if customer["risk_score"] is not None]
    assert len(scored) >= int(len(evaluated_case) * 0.70 + 0.999)
    assert all(customer["data_coverage"] >= 0.70 for customer in scored)


def test_reason_points_add_up_to_the_account_score_for_case_and_scenario_customers():
    payload = json.loads(CASE_JSON.read_text(encoding="utf-8"))
    case = [customer.model_dump() for customer in SnapshotUpload.model_validate(payload).customers]
    for customer in [*case, *scenario_customers(NOW)]:
        result = evaluate_customer(customer, DEFAULT_MODEL_SETTINGS, NOW)
        if not result["risk_score"]:
            continue
        points = sum(reason["points"] for reason in result["reasons"])
        assert points == pytest.approx(result["risk_score"], abs=0.11), customer["id"]


def test_showcase_seed_keeps_the_case_accounts_and_adds_the_scenarios(open_app):
    case = json.loads(CASE_JSON.read_text(encoding="utf-8"))["customers"]
    with open_app(AEZA_SEED="showcase") as (client, _):
        sign_in(client)
        summary = client.get(SUMMARY).json()
        assert summary["source_kind"] == "showcase"
        assert summary["customers_total"] == len(case) + len(EXPECTED)
        items = {item["id"]: item for item in client.get(CUSTOMERS, params={"limit": 200}).json()["items"]}
        assert {str(customer["id"]) for customer in case} <= set(items)
        assert set(EXPECTED) <= set(items)
        for customer in case:
            assert items[str(customer["id"])]["balance_minor"] == customer["balance"]
        assert summary["potential_loss_minor"] > 0
        assert summary["near_term_loss_minor"] >= summary["revenue_at_risk_minor"] >= summary["potential_loss_minor"]
        assert summary["exposed_services"] > 0
        assert items["S03"]["risk_level"] == "high"
        # The default queue goes by the expected loss: the big annual renewal leads, though its risk is low.
        queue = client.get(CUSTOMERS).json()
        assert queue["sort_by"] == "revenue_at_risk"
        assert [item["id"] for item in queue["items"][:2]] == ["S06", "S03"]


def test_showcase_is_rebuilt_on_restart_but_an_uploaded_snapshot_is_kept(open_app):
    with open_app(AEZA_SEED="showcase") as (client, _):
        sign_in(client)
        first = client.get(SUMMARY).json()["source_updated_at"]
    with open_app(AEZA_SEED="showcase") as (client, _):
        sign_in(client)
        second = client.get(SUMMARY).json()
        assert second["source_updated_at"] > first
        upload = {"customers": [{"id": "7", "email": "kept@example.test", "balance": 0, "services": [], "transactions": []}]}
        assert client.put(SNAPSHOT, json=upload).status_code == 200
    with open_app(AEZA_SEED="showcase") as (client, _):
        sign_in(client)
        summary = client.get(SUMMARY).json()
        assert summary["source_kind"] == "uploaded"
        assert summary["customers_total"] == 1
