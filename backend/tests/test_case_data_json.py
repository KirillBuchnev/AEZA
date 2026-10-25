"""The organizers' data.json as delivered: upload, scoring, money, sorting, metrics and plans."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.risk import DEFAULT_MODEL_SETTINGS, evaluate_customer
from app.schemas import SnapshotUpload

DATA_JSON = Path(__file__).resolve().parent / "fixtures" / "data.json"
CASE_JSON = Path(__file__).resolve().parents[1] / "app" / "seeds" / "case_snapshot.json"
NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
ADMIN_PASSWORD = "local-demo-change-this-password"

# Result on 25.10.2026 12:00 UTC: level, index, expected loss and maximum in euro cents, plan.
EXPECTED = {
    "1": ("high", 75.6, 0, 0, "data_quality"),
    "2": ("high", 99.9, 0, 0, "win_back"),
    "3": ("high", 100.0, 0, 0, "win_back"),
    "4": ("high", 75.6, 0, 0, "data_quality"),
    "5": ("high", 66.8, 0, 0, "data_quality"),
    "6": ("medium", 49.8, 272, 547, "manual_renewal"),
    "7": ("high", 99.9, 0, 0, "win_back"),
    "8": ("high", 100.0, 0, 0, "win_back"),
    "9": ("high", 95.3, 0, 0, "data_quality"),
    "10": ("high", 87.3, 0, 0, "data_quality"),
}


def raw_data() -> dict:
    return json.loads(DATA_JSON.read_text(encoding="utf-8"))


def evaluated() -> dict[str, dict]:
    customers = SnapshotUpload.model_validate(raw_data()).customers
    return {customer.id: evaluate_customer(customer.model_dump(), DEFAULT_MODEL_SETTINGS, NOW) for customer in customers}


def sign_in(client) -> None:
    assert client.post("/api/v1/auth/login", json={"username": "demo", "password": ADMIN_PASSWORD}).status_code == 200


def test_data_json_has_the_case_volume():
    data = raw_data()
    assert (len(data["accounts"]), len(data["services"]), len(data["transactions"])) == (10, 30, 100)


def test_data_json_is_the_same_data_as_the_built_in_case_snapshot():
    flat = SnapshotUpload.model_validate(raw_data()).customers
    nested = SnapshotUpload.model_validate(json.loads(CASE_JSON.read_text(encoding="utf-8"))).customers
    assert [c.model_dump(mode="json") for c in flat] == [c.model_dump(mode="json") for c in nested]


@pytest.mark.parametrize("customer_id", sorted(EXPECTED, key=int))
def test_each_customer_gets_the_expected_level_score_money_and_plan(customer_id):
    result = evaluated()[customer_id]
    level, score, expected, maximum, plan = EXPECTED[customer_id]
    assert result["risk_level"] == level
    assert result["risk_score"] == pytest.approx(score, abs=0.05)
    assert result["revenue_at_risk_minor"] == expected
    assert result["near_term_loss_minor"] == maximum
    assert result["action_plan"]["archetype"] == plan


def test_every_customer_is_scored_and_reason_points_add_up_to_the_score():
    for customer_id, result in evaluated().items():
        assert result["risk_score"] is not None, customer_id
        assert sum(r["points"] for r in result["reasons"]) == pytest.approx(result["risk_score"], abs=0.11), customer_id
        assert result["loyalty_score"] == pytest.approx(100 - result["risk_score"], abs=0.05)


def test_money_never_breaks_balance_part_within_expected_within_maximum():
    for customer_id, result in evaluated().items():
        assert 0 <= result["potential_loss_minor"] <= result["revenue_at_risk_minor"] <= result["near_term_loss_minor"], customer_id


def test_every_customer_gets_a_plan_with_facts_steps_and_channel():
    for customer_id, result in evaluated().items():
        plan = result["action_plan"]
        assert plan["steps"] and plan["channel"] and plan["segment"]["title"], customer_id
        if plan["archetype"] not in {"data_quality", "healthy"}:
            assert plan["message_subject"] and plan["message_template"], customer_id


def test_data_json_uploads_as_is_and_the_panel_api_reflects_it(open_app):
    with open_app(AEZA_SEED="empty") as (client, _):
        sign_in(client)
        response = client.put("/api/v1/source/snapshot", json=raw_data())
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] is True and body["customers_received"] == 10

        summary = client.get("/api/v1/analytics/summary").json()
        assert summary["customers_total"] == 10
        assert sum(summary["risk_counts"].values()) == 10

        metrics = client.get("/metrics").text
        for level, count in summary["risk_counts"].items():
            assert f'aeza_customers_total{{risk_level="{level}"}} {count}' in metrics


@pytest.mark.parametrize("sort_by, field, key", [
    ("id", "id", int),
    ("email", "email", str.casefold),
    ("balance", "balance_minor", int),
    ("total_replenished", "total_replenished_minor", int),
])
def test_data_json_sorts_both_ways_by_id_email_balance_and_replenished(open_app, sort_by, field, key):
    with open_app(AEZA_SEED="empty") as (client, _):
        sign_in(client)
        assert client.put("/api/v1/source/snapshot", json=raw_data()).status_code == 200
        for order in ("asc", "desc"):
            items = client.get(f"/api/v1/customers?sort_by={sort_by}&order={order}&limit=200").json()["items"]
            values = [item[field] for item in items]
            assert len(values) == 10
            assert values == sorted(values, key=key, reverse=order == "desc")
