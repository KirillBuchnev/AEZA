import unittest
from datetime import datetime, timedelta, timezone

from app.risk import (
    DEFAULT_MODEL_SETTINGS,
    control_cases,
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
        self.assertEqual([bucket["services_due"] for bucket in forecast["buckets"]], [2, 1])
        bucket, waiting = forecast["buckets"]
        self.assertEqual(bucket["expected_non_renewals"], round((58.0 + 53.6) / 100, 2))
        self.assertEqual(forecast["waiting_now"]["services"], 1)
        self.assertEqual(forecast["waiting_now"]["expected_non_renewals"], 0.56)
        self.assertEqual(forecast["totals"]["services_due"], 3)
        self.assertEqual(waiting["services_waiting"], 1)
        self.assertIn("не калибровано", forecast["method"].lower())

    def test_waiting_service_is_placed_on_the_day_its_grace_ends(self) -> None:
        # Expired one day ago, so the five-day grace ends in four days.
        waiting = evaluated(service(status="prolong_wait", expires_in_days=-1), balance=0)
        forecast = outflow_forecast([waiting], NOW, 30)
        self.assertEqual([bucket["date"] for bucket in forecast["buckets"]], ["2026-10-28"])
        self.assertEqual(forecast["buckets"][0]["services_waiting"], 1)

    def test_waiting_service_past_its_grace_is_counted_aside_not_forecast(self) -> None:
        stale = evaluated(service(status="prolong_wait", expires_in_days=-30), balance=0)
        forecast = outflow_forecast([stale], NOW, 30)
        self.assertEqual(forecast["buckets"], [])
        self.assertEqual(forecast["waiting_now"]["services"], 0)
        self.assertEqual(forecast["waiting_now"]["beyond_grace_services"], 1)
        self.assertEqual(forecast["totals"]["expected_non_renewals"], 0)

    def test_waiting_service_whose_grace_ends_after_the_horizon_is_not_drawn(self) -> None:
        waiting = evaluated(service(status="prolong_wait", expires_in_days=-1), balance=0)
        forecast = outflow_forecast([waiting], NOW, 2)
        self.assertEqual(forecast["buckets"], [])
        self.assertEqual(forecast["waiting_now"]["services"], 1)


class NearTermLossTest(unittest.TestCase):
    """Possible losses in the 7-day action window: full price of renewals at medium or high risk."""

    def test_high_renewal_inside_window_counts_at_full_price(self) -> None:
        result = evaluated(service(auto_prolong=False, expires_in_days=3 / 24), balance=10_000)
        self.assertEqual(result["services"][0]["risk_level"], "high")
        self.assertEqual(result["near_term_loss_minor"], 10_000)
        self.assertEqual(result["revenue_at_risk_minor"], 5_800)

    def test_medium_renewal_inside_window_counts_at_full_price(self) -> None:
        result = evaluated(service(auto_prolong=True, expires_in_days=3), balance=0)
        self.assertEqual(result["services"][0]["risk_level"], "medium")
        self.assertEqual(result["near_term_loss_minor"], 10_000)

    def test_low_renewal_is_excluded_though_it_is_at_risk_money(self) -> None:
        result = evaluated(service(auto_prolong=True, expires_in_days=3), balance=9_000)
        self.assertEqual(result["services"][0]["risk_level"], "low")
        self.assertGreater(result["revenue_at_risk_minor"], 0)
        self.assertEqual(result["near_term_loss_minor"], 0)

    def test_renewal_outside_the_action_window_is_not_near_term(self) -> None:
        result = evaluated(service(auto_prolong=False, expires_in_days=20), balance=0)
        self.assertEqual(result["near_term_loss_minor"], 0)
        self.assertEqual(result["revenue_at_risk_minor"], 0)

    def test_waiting_service_at_risk_counts_as_near_term(self) -> None:
        result = evaluated(service(status="prolong_wait", auto_prolong=False, expires_in_days=-1), balance=0)
        self.assertEqual(result["near_term_loss_minor"], 10_000)

    def test_near_term_loss_sums_only_services_in_the_window(self) -> None:
        result = evaluated(
            service(service_id="a", auto_prolong=False, expires_in_days=3 / 24),
            service(service_id="b", price=4_000, auto_prolong=False, expires_in_days=20),
            balance=10_000,
        )
        self.assertEqual(result["near_term_loss_minor"], 10_000)
        self.assertEqual(result["calculation"]["near_term_loss_minor"], 10_000)
        self.assertEqual(sum(s["near_term_loss_minor"] for s in result["services"]), 10_000)


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


class AccountThresholdsTest(unittest.TestCase):
    def test_account_level_uses_its_own_thresholds(self) -> None:
        model = merge_model_settings({**DEFAULT_MODEL_SETTINGS, "account_high_risk_min": 150, "account_medium_risk_min": 100})
        result = evaluate_customer(
            customer(
                balance=20_000,
                services=[
                    service(service_id="s-1", expires_in_days=3 / 24, auto_prolong=False),
                    service(service_id="s-2", expires_in_days=3 / 24, auto_prolong=False),
                ],
            ),
            model,
            NOW,
        )
        self.assertEqual(result["risk_score"], 116.0)
        self.assertEqual(result["risk_level"], "medium")
        self.assertEqual([item["risk_level"] for item in result["services"]], ["high", "high"])


class ReviewFixesTest(unittest.TestCase):
    def test_waiting_service_without_autoprolong_is_high(self) -> None:
        # Without autoprolong nobody else pays: manual 45 + urgency 20 + grace 5 * 0.2 over 110.
        result = evaluated(service(status="prolong_wait", expires_in_days=-1, auto_prolong=False), balance=10_000)
        self.assertEqual(result["services"][0]["risk_score"], 60.0)
        self.assertEqual(result["services"][0]["risk_level"], "high")
        self.assertEqual(result["services"][0]["recommended_action"]["code"], "manual_reminder")

    def test_waiting_service_without_expiry_is_unscored(self) -> None:
        result = evaluated(service(status="prolong_wait", expires_in_days=None), balance=0)
        self.assertIsNone(result["services"][0]["risk_score"])
        self.assertIsNone(result["risk_level"])
        self.assertEqual(result["data_quality"][0]["code"], "missing_expiry")

    def test_failed_payment_applies_only_to_its_own_service(self) -> None:
        other = {
            "id": "t-2", "service_id": "service-2", "status": "not_performed", "type": "prolong",
            "amount_minor": 10_000, "created_at": (NOW - timedelta(days=1)).isoformat(),
        }
        result = evaluate_customer(
            {
                **customer(balance=10_000, services=[service(service_id="service-1", expires_in_days=40, auto_prolong=True)],
                           transactions=[other]),
            },
            DEFAULT_MODEL_SETTINGS,
            NOW,
        )
        self.assertFalse(result["services"][0]["recent_failed_payment"])
        self.assertNotIn("неуспешной", result["services"][0]["recommended_action"]["text"])

    def test_deficit_outside_action_window_is_visible_as_forecast_action(self) -> None:
        result = evaluated(service(expires_in_days=20, auto_prolong=True), balance=0)
        self.assertEqual(result["services"][0]["recommended_action"]["code"], "forecast_only")
        self.assertEqual(result["uncovered_revenue_minor"], 10_000)
        self.assertIn("не хватает", result["services"][0]["reasons"][0]["explanation"])

    def test_control_cases_reproduce_the_mentor_levels(self) -> None:
        cases = control_cases(DEFAULT_MODEL_SETTINGS, NOW)
        self.assertEqual([case["risk_score"] for case in cases], [55.5, 58.0, 53.6, 0.9])
        self.assertTrue(all(case["matches"] for case in cases))
