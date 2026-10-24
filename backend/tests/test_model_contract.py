import unittest
from datetime import datetime, timedelta, timezone

from app.risk import (
    DEFAULT_MODEL_SETTINGS,
    evaluate_customer,
    merge_model_settings,
    model_divisor,
    outflow_forecast,
)


NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def customer(
    *,
    balance: int,
    services: list[dict],
    transactions: list[dict] | None = None,
) -> dict:
    return {
        "id": "c-1",
        "email": "client@example.com",
        "balance_minor": balance,
        "withdraw_balance_minor": 0,
        "bonus_balance_minor": 0,
        "bonus_spend_enabled": False,
        "total_replenished_minor": 0,
        "services": services,
        "transactions": transactions or [],
    }


def service(
    *,
    service_id: str = "s-1",
    price: int = 10_000,
    auto_prolong: bool = True,
    status: str = "active",
    expires_in_days: float | None = 1,
    payment_term: str | None = "month",
) -> dict:
    expires_at = None if expires_in_days is None else (NOW + timedelta(days=expires_in_days)).isoformat()
    return {
        "id": service_id,
        "name": "Service",
        "price_minor": price,
        "auto_prolong": auto_prolong,
        "payment_term": payment_term,
        "status": status,
        "expires_at": expires_at,
    }


def evaluated(*services: dict, balance: int = 0, transactions: list[dict] | None = None) -> dict:
    return evaluate_customer(
        customer(balance=balance, services=list(services), transactions=transactions),
        DEFAULT_MODEL_SETTINGS,
        NOW,
    )


class MentorControlCasesTest(unittest.TestCase):
    """The four control accounts from the mentor's answer: a, b and c are high, d is low."""

    def test_control_values_match_the_team_formula(self) -> None:
        # a) prolong_wait one day, balance zero: 40 + 20 + 5 * 0.2 over 110.
        a = evaluated(service(status="prolong_wait", expires_in_days=-1, auto_prolong=True), balance=0)
        # b) renewal in three hours, autoprolong off, enough money: (45 + 20) * urgency over 110.
        b = evaluated(service(expires_in_days=3 / 24, auto_prolong=False), balance=10_000)
        # c) renewal in three hours, autoprolong on, balance zero: (40 + 20) * urgency over 110.
        c = evaluated(service(expires_in_days=3 / 24, auto_prolong=True), balance=0)
        # d) prolong_wait one day, enough money: only the grace progress 5 * 0.2 over 110.
        d = evaluated(service(status="prolong_wait", expires_in_days=-1, auto_prolong=True), balance=10_000)

        self.assertEqual(a["services"][0]["risk_score"], 55.5)
        self.assertEqual(b["services"][0]["risk_score"], 58.0)
        self.assertEqual(c["services"][0]["risk_score"], 53.6)
        self.assertEqual(d["services"][0]["risk_score"], 0.9)

    def test_levels_follow_the_mentor_answer(self) -> None:
        levels = [
            evaluated(service(status="prolong_wait", expires_in_days=-1), balance=0)["risk_level"],
            evaluated(service(expires_in_days=3 / 24, auto_prolong=False), balance=10_000)["risk_level"],
            evaluated(service(expires_in_days=3 / 24, auto_prolong=True), balance=0)["risk_level"],
            evaluated(service(status="prolong_wait", expires_in_days=-1), balance=10_000)["risk_level"],
        ]
        self.assertEqual(levels, ["high", "high", "high", "low"])

    def test_reasons_argue_each_factor_with_numbers(self) -> None:
        result = evaluated(service(expires_in_days=3 / 24, auto_prolong=True), balance=0)
        reasons = {reason["code"]: reason for reason in result["services"][0]["reasons"]}

        self.assertEqual(set(reasons), {"insufficient_balance", "renewal_urgency"})
        shortage = reasons["insufficient_balance"]
        self.assertEqual(shortage["evidence"]["shortfall_minor"], 10_000)
        self.assertIn("100,00 €", shortage["explanation"])
        self.assertIn("через 3 ч", reasons["renewal_urgency"]["explanation"])
        self.assertAlmostEqual(sum(reason["points"] for reason in result["services"][0]["reasons"]), 53.6, delta=0.1)

    def test_manual_renewal_reason_names_the_disabled_autoprolong(self) -> None:
        result = evaluated(service(expires_in_days=3 / 24, auto_prolong=False), balance=10_000)
        codes = [reason["code"] for reason in result["services"][0]["reasons"]]
        self.assertEqual(codes, ["autoprolong_disabled", "renewal_urgency"])
        self.assertIn("Автопродление выключено", result["services"][0]["reasons"][0]["explanation"])
        self.assertEqual(result["services"][0]["recommended_action"]["code"], "manual_reminder")


class AccountAggregationTest(unittest.TestCase):
    def test_account_index_is_the_sum_of_service_indices(self) -> None:
        result = evaluated(
            service(service_id="s-1", expires_in_days=3 / 24, auto_prolong=False),
            service(service_id="s-2", expires_in_days=3 / 24, auto_prolong=False),
            balance=20_000,
        )
        self.assertEqual(result["account_risk_sum"], 116.0)
        self.assertEqual(result["risk_score"], 116.0)
        self.assertEqual(result["max_service_score"], 58.0)
        self.assertEqual(result["high_count"], 2)

    def test_account_with_missing_expiry_is_unscored_but_services_keep_scores(self) -> None:
        result = evaluated(
            service(service_id="s-1", expires_in_days=3 / 24, auto_prolong=False),
            service(service_id="s-2", expires_in_days=None),
            balance=20_000,
        )
        self.assertIsNone(result["risk_level"])
        self.assertIsNone(result["account_risk_sum"])
        self.assertEqual(result["unscored_services_count"], 1)
        self.assertEqual(result["services"][0]["risk_score"], 58.0)
        self.assertIsNone(result["services"][1]["risk_score"])
        self.assertEqual(result["recommended_action"]["code"], "fix_data")
        self.assertEqual(result["data_quality"][0]["code"], "missing_expiry")

    def test_large_account_is_scored_per_service(self) -> None:
        services = [
            service(service_id=f"s-{index}", price=1_000, expires_in_days=None if index == 0 else 40, auto_prolong=True)
            for index in range(200)
        ]
        result = evaluated(*services, balance=0)
        self.assertEqual(len(result["services"]), 200)
        self.assertEqual(result["services"][1]["risk_score"], 0.0)
        self.assertIsNone(result["risk_level"])

    def test_failed_payment_does_not_change_the_index_but_is_in_the_action(self) -> None:
        failed = {
            "id": "t-1",
            "service_id": "s-1",
            "status": "not_performed",
            "type": "prolong",
            "amount_minor": 10_000,
            "created_at": (NOW - timedelta(days=1)).isoformat(),
        }
        without = evaluated(service(expires_in_days=3 / 24, auto_prolong=True), balance=0)
        with_failure = evaluated(service(expires_in_days=3 / 24, auto_prolong=True), balance=0, transactions=[failed])
        self.assertEqual(without["services"][0]["risk_score"], with_failure["services"][0]["risk_score"])
        self.assertTrue(with_failure["services"][0]["recent_failed_payment"])
        self.assertIn("неуспешной оплаты", with_failure["services"][0]["recommended_action"]["text"])
        self.assertNotIn("failed_prolong_payment", {reason["code"] for reason in with_failure["services"][0]["reasons"]})


class MoneyAndForecastTest(unittest.TestCase):
    def test_monthly_cost_normalises_payment_terms(self) -> None:
        result = evaluated(
            service(service_id="m", price=1_000, payment_term="month"),
            service(service_id="y", price=12_000, payment_term="year", expires_in_days=60),
            service(service_id="q", price=3_000, payment_term="quarter", expires_in_days=60),
            balance=100_000,
        )
        self.assertEqual(result["monthly_cost_minor"], 3_000)

    def test_potential_loss_is_shortfall_weighted_by_index(self) -> None:
        result = evaluated(service(status="prolong_wait", expires_in_days=-1, auto_prolong=True), balance=0)
        self.assertEqual(result["potential_loss_minor"], round(10_000 * 55.5 / 100))
        self.assertEqual(result["revenue_at_risk_minor"], round(10_000 * 55.5 / 100))

    def test_forecast_buckets_sum_service_indices_by_due_day(self) -> None:
        evaluated_customers = [
            evaluated(service(service_id="s-1", expires_in_days=3 / 24, auto_prolong=False), balance=20_000),
            evaluated(service(service_id="s-2", expires_in_days=3 / 24, auto_prolong=True), balance=0),
            evaluated(service(service_id="s-3", status="prolong_wait", expires_in_days=-1), balance=0),
        ]
        forecast = outflow_forecast(evaluated_customers, NOW, 30)
        self.assertEqual(len(forecast["buckets"]), 1)
        bucket = forecast["buckets"][0]
        self.assertEqual(bucket["services_due"], 2)
        self.assertEqual(bucket["expected_non_renewals"], round((58.0 + 53.6) / 100, 2))
        self.assertEqual(forecast["waiting_now"]["services"], 1)
        self.assertEqual(forecast["waiting_now"]["expected_non_renewals"], 0.56)
        self.assertIn("не калибровано", forecast["method"].lower())


class ModelSettingsTest(unittest.TestCase):
    def test_divisor_is_the_sum_of_weights(self) -> None:
        self.assertEqual(model_divisor(merge_model_settings(DEFAULT_MODEL_SETTINGS)), 110)

    def test_version_two_settings_keep_custom_weights_and_drop_failed_payment_weight(self) -> None:
        stored = {
            "version": 2,
            "prediction_horizon_days": 45,
            "high_risk_min": 60,
            "medium_risk_min": 25,
            "weights": {
                "prolong_wait": 7,
                "autoprolong_disabled": 50,
                "insufficient_balance": 35,
                "failed_prolong_payment": 20,
            },
            "formula": {"normalizer": 110, "urgency_weight": 15},
        }
        migrated = merge_model_settings(stored)
        self.assertEqual(migrated["version"], 3)
        self.assertEqual(migrated["high_risk_min"], 60)
        self.assertEqual(migrated["prediction_horizon_days"], 45)
        self.assertEqual(migrated["weights"]["autoprolong_disabled"], 50)
        self.assertEqual(migrated["weights"]["renewal_urgency"], 15)
        self.assertNotIn("failed_prolong_payment", migrated["weights"])


if __name__ == "__main__":
    unittest.main()
