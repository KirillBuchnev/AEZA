import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import load_config
from app.risk import DEFAULT_MODEL_SETTINGS, evaluate_customer

ROOT = Path(__file__).resolve().parents[2]
SEED_SQL = ROOT / "db" / "002_seed.sql"
CASE_JSON = ROOT / "backend" / "app" / "seeds" / "case_snapshot.json"
BUILD_SCRIPT = ROOT / "backend" / "scripts" / "build_case_snapshot.py"
ADMIN_PASSWORD = "local-demo-change-this-password"
SETTINGS = "/api/v1/model/settings"
SUMMARY = "/api/v1/analytics/summary"
CUSTOMERS = "/api/v1/customers"
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def sign_in(client) -> None:
    assert client.post("/api/v1/auth/login", json={"username": "demo", "password": ADMIN_PASSWORD}).status_code == 200


def test_committed_case_snapshot_matches_the_seed_file():
    spec = importlib.util.spec_from_file_location("build_case_snapshot", BUILD_SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.build(SEED_SQL.read_text(encoding="utf-8")) == json.loads(CASE_JSON.read_text(encoding="utf-8"))


def test_case_snapshot_has_the_dataset_sizes():
    data = json.loads(CASE_JSON.read_text(encoding="utf-8"))
    assert len(data["customers"]) == 10
    assert sum(len(customer["services"]) for customer in data["customers"]) == 30
    assert sum(len(customer["transactions"]) for customer in data["customers"]) == 100


def test_case_dataset_is_the_default_seed(open_app):
    with open_app() as (client, _):
        sign_in(client)
        summary = client.get(SUMMARY).json()
        assert summary["customers_total"] == 10
        assert summary["source_kind"] == "case"


def test_case_expired_services_show_up_as_data_issues(open_app):
    with open_app() as (client, _):
        sign_in(client)
        issues = client.get(CUSTOMERS, params={"data_status": "issues", "limit": 200}).json()
        assert issues["total"] >= 1


def test_empty_seed_starts_without_customers(open_app):
    with open_app(AEZA_SEED="empty") as (client, _):
        sign_in(client)
        summary = client.get(SUMMARY).json()
        assert summary["customers_total"] == 0
        assert summary["source_kind"] == "empty"


def test_demo_seed_keeps_the_synthetic_customers(open_app):
    with open_app(AEZA_SEED="demo") as (client, _):
        sign_in(client)
        summary = client.get(SUMMARY).json()
        assert summary["customers_total"] == 9
        assert summary["source_kind"] == "demo"


def test_unknown_seed_is_rejected(monkeypatch):
    monkeypatch.setenv("AEZA_SEED", "production-dump")
    with pytest.raises(ValueError, match="AEZA_SEED"):
        load_config()


def _customer(services: list[dict]) -> dict:
    return {
        "id": "c", "email": "c@example.com", "balance_minor": 0, "withdraw_balance_minor": 0,
        "bonus_balance_minor": 0, "bonus_spend_enabled": False, "total_replenished_minor": 0,
        "services": services, "transactions": [],
    }


def _service(term: str, price: int) -> dict:
    return {
        "id": f"s-{term}", "name": "s", "price_minor": price, "auto_prolong": True,
        "payment_term": term, "status": "active",
        "expires_at": (NOW + timedelta(days=40)).isoformat(),
    }


class PaymentTermsTest(unittest.TestCase):
    def test_quarter_year_is_a_quarter_of_a_year(self) -> None:
        result = evaluate_customer(_customer([_service("quarter_year", 3000)]), DEFAULT_MODEL_SETTINGS, NOW)
        self.assertEqual(result["monthly_cost_minor"], 1000)
        self.assertNotIn("unknown_payment_term", {issue["code"] for issue in result["data_quality"]})

    def test_hour_and_week_terms_convert_to_a_monthly_cost(self) -> None:
        hourly = evaluate_customer(_customer([_service("hour", 95)]), DEFAULT_MODEL_SETTINGS, NOW)
        weekly = evaluate_customer(_customer([_service("week", 700)]), DEFAULT_MODEL_SETTINGS, NOW)
        self.assertEqual(hourly["monthly_cost_minor"], 95 * 720)
        self.assertEqual(weekly["monthly_cost_minor"], 3000)

    def test_an_unknown_term_is_still_reported(self) -> None:
        result = evaluate_customer(_customer([_service("fortnight", 1000)]), DEFAULT_MODEL_SETTINGS, NOW)
        self.assertIn("unknown_payment_term", {issue["code"] for issue in result["data_quality"]})
