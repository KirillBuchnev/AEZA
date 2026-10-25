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
    """Четыре контрольных аккаунта из ответа ментора: a, b и c — высокие, d — низкий."""

    def test_control_values_match_the_team_formula(self) -> None:
        # a) prolong_wait один день, баланс нулевой: 40 + 20 + 5 * 0.2 из 110.
        a = evaluated(service(status="prolong_wait", expires_in_days=-1, auto_prolong=True), balance=0)
        # b) продление через три часа, автопродление выключено, денег хватает: (45 + 20) * urgency из 110.
        b = evaluated(service(expires_in_days=3 / 24, auto_prolong=False), balance=10_000)
        # c) продление через три часа, автопродление включено, баланс нулевой: (40 + 20) * urgency из 110.
        c = evaluated(service(expires_in_days=3 / 24, auto_prolong=True), balance=0)
        # d) prolong_wait один день, денег хватает: только прогресс льготного периода 5 * 0.2 из 110.
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
    def test_account_index_is_the_chance_that_at_least_one_service_fails(self) -> None:
        result = evaluated(
            service(service_id="s-1", expires_in_days=3 / 24, auto_prolong=False),
            service(service_id="s-2", expires_in_days=3 / 24, auto_prolong=False),
            balance=20_000,
        )
        self.assertEqual(result["account_risk_sum"], 116.0)  # простая сумма остаётся для справки
        self.assertEqual(result["risk_score"], 82.4)  # 1 - (1 - 0.58) ** 2
        self.assertEqual(result["calculation"]["risk_score_index"], 82.4)
        self.assertEqual(result["max_service_score"], 58.0)
        self.assertEqual(result["high_count"], 2)

    def test_account_index_of_one_service_equals_the_service_index(self) -> None:
        result = evaluated(service(expires_in_days=3 / 24, auto_prolong=False), balance=20_000)
        self.assertEqual(result["risk_score"], result["services"][0]["risk_score"])

    def test_account_index_never_leaves_the_scale(self) -> None:
        services = [
            service(service_id=f"s-{index}", price=1_000, expires_in_days=3 / 24, auto_prolong=False)
            for index in range(30)
        ]
        result = evaluated(*services, balance=100_000)
        self.assertLessEqual(result["risk_score"], 100.0)
        self.assertGreater(result["risk_score"], 99.0)

    def test_large_portfolio_does_not_overstate_one_risky_service(self) -> None:
        services = [
            service(service_id="risky", expires_in_days=3 / 24, auto_prolong=False),
            *[
                service(service_id=f"healthy-{index}", expires_in_days=40, auto_prolong=True)
                for index in range(9)
            ],
        ]
        result = evaluated(*services, balance=100_000)
        self.assertEqual(result["risky_service_count"], 1)
        self.assertEqual(result["service_risk_share"], 0.1)
        self.assertEqual(result["service_count_adjustment"], 0.775)
        self.assertEqual(result["risk_score"], 44.9)

    def test_breadth_adjustment_applies_after_three_risky_services(self) -> None:
        services = [
            service(service_id=f"risky-{index}", expires_in_days=3 / 24, auto_prolong=False)
            for index in range(4)
        ] + [
            service(service_id=f"healthy-{index}", expires_in_days=40, auto_prolong=True)
            for index in range(6)
        ]
        result = evaluated(*services, balance=100_000)
        self.assertEqual(result["risky_service_count"], 4)
        self.assertEqual(result["service_risk_share"], 0.4)
        self.assertEqual(result["service_count_adjustment"], 0.85)
        self.assertLess(result["risk_score"], 90.0)

    def test_account_reasons_add_up_to_the_account_index(self) -> None:
        result = evaluated(
            service(service_id="s-1", expires_in_days=3 / 24, auto_prolong=False),
            service(service_id="s-2", expires_in_days=3 / 24, auto_prolong=True),
            balance=0,
        )
        points = sum(reason["points"] for reason in result["reasons"])
        self.assertEqual(round(points, 1), result["risk_score"])

    def test_displayed_points_add_up_exactly_to_every_index(self) -> None:
        # Каждый балл округляется до одного знака; округление не должно оставлять 0.1 между слагаемыми и индексом.
        cases = [
            ([service(price=500, expires_in_days=2.75)], 300),
            ([service(price=10_000, expires_in_days=3.24)], 1_000),
            (
                [
                    service(service_id="s-1", price=900, expires_in_days=3.58),
                    service(service_id="s-2", price=500, auto_prolong=False, expires_in_days=4.04),
                    service(service_id="s-3", price=4_000, auto_prolong=False, expires_in_days=2.81),
                ],
                1_000,
            ),
        ]
        for services, balance in cases:
            result = evaluated(*services, balance=balance)
            self.assertEqual(round(sum(reason["points"] for reason in result["reasons"]), 1), result["risk_score"])
            for item in result["services"]:
                self.assertEqual(
                    round(sum(reason["points"] for reason in item["reasons"]), 1),
                    item["risk_score"],
                )

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
        self.assertEqual(result["risk_level"], "low")
        self.assertGreaterEqual(result["calculation"]["data_coverage"], 0.70)

    def test_seventy_percent_data_coverage_returns_a_partial_score(self) -> None:
        services = [
            service(service_id=f"valid-{index}", expires_in_days=1 if index == 0 else 40, auto_prolong=index == 0)
            for index in range(7)
        ] + [
            service(service_id=f"missing-{index}", expires_in_days=None)
            for index in range(3)
        ]
        result = evaluated(*services, balance=0)
        self.assertEqual(result["calculation"]["data_coverage"], 0.7)
        self.assertIsNotNone(result["risk_score"])
        self.assertIsNotNone(result["risk_level"])
        self.assertEqual(result["unscored_services_count"], 3)

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
        # Просрочена день назад, поэтому пятидневный льготный период кончается через четыре дня.
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
    """Пара на одной выборке: услуги с некоторым риском, решение ещё впереди.

    Ожидаемые потери (выручка под риском) — цена x индекс / 100, максимум (близкие потери) — полная цена."""

    def test_high_renewal_inside_window_counts_at_full_price(self) -> None:
        result = evaluated(service(auto_prolong=False, expires_in_days=3 / 24), balance=10_000)
        self.assertEqual(result["services"][0]["risk_level"], "high")
        self.assertEqual(result["near_term_loss_minor"], 10_000)
        self.assertEqual(result["revenue_at_risk_minor"], 5_800)

    def test_medium_renewal_inside_window_counts_at_full_price(self) -> None:
        result = evaluated(service(auto_prolong=True, expires_in_days=3), balance=0)
        self.assertEqual(result["services"][0]["risk_level"], "medium")
        self.assertEqual(result["near_term_loss_minor"], 10_000)

    def test_low_renewal_is_in_the_sample_but_barely_in_the_expected_loss(self) -> None:
        result = evaluated(service(auto_prolong=True, expires_in_days=3), balance=9_000)
        self.assertEqual(result["services"][0]["risk_level"], "low")
        self.assertEqual(result["near_term_loss_minor"], 10_000)  # риск есть: максимум — полная цена
        self.assertEqual(result["revenue_at_risk_minor"], 1_250)  # индекс 12.5 от цены

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

    def test_balance_part_never_exceeds_expected_and_expected_never_exceeds_maximum(self) -> None:
        for result in (
            evaluated(service(auto_prolong=False, expires_in_days=3 / 24), balance=0),
            evaluated(service(auto_prolong=True, expires_in_days=3), balance=9_000),
            evaluated(service(status="prolong_wait", expires_in_days=-1), balance=0),
            evaluated(service(service_id="a", expires_in_days=1), service(service_id="b", expires_in_days=20), balance=5_000),
        ):
            self.assertLessEqual(result["potential_loss_minor"], result["revenue_at_risk_minor"])
            self.assertLessEqual(result["revenue_at_risk_minor"], result["near_term_loss_minor"])

    def test_waiting_service_past_its_grace_is_left_out_of_the_money(self) -> None:
        stale = evaluated(service(status="prolong_wait", auto_prolong=False, expires_in_days=-30), balance=0)
        self.assertGreater(stale["risk_score"], 0)  # сам риск всё равно показывается
        self.assertEqual(stale["revenue_at_risk_minor"], 0)
        self.assertEqual(stale["near_term_loss_minor"], 0)
        self.assertEqual(stale["potential_loss_minor"], 0)
        self.assertEqual(stale["exposed_services"], 0)

    def test_exposed_services_counts_the_services_of_the_sample(self) -> None:
        result = evaluated(
            service(service_id="a", auto_prolong=False, expires_in_days=3 / 24),
            service(service_id="b", expires_in_days=20),
            balance=10_000,
        )
        self.assertEqual(result["exposed_services"], 1)


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

    def test_account_thresholds_of_older_rows_are_clamped_to_the_index_scale(self) -> None:
        # Пока индекс аккаунта был суммой индексов услуг, его пороги могли превышать 100.
        migrated = merge_model_settings({"account_high_risk_min": 150, "account_medium_risk_min": 120})
        self.assertEqual(migrated["account_high_risk_min"], 100)
        self.assertEqual(migrated["account_medium_risk_min"], 99)
        in_range = merge_model_settings({"account_high_risk_min": 70, "account_medium_risk_min": 40})
        self.assertEqual((in_range["account_high_risk_min"], in_range["account_medium_risk_min"]), (70, 40))


if __name__ == "__main__":
    unittest.main()


class AccountThresholdsTest(unittest.TestCase):
    def test_account_level_uses_its_own_thresholds(self) -> None:
        model = merge_model_settings({**DEFAULT_MODEL_SETTINGS, "account_high_risk_min": 90, "account_medium_risk_min": 70})
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
        self.assertEqual(result["risk_score"], 82.4)
        self.assertEqual(result["risk_level"], "medium")
        self.assertEqual([item["risk_level"] for item in result["services"]], ["high", "high"])


class ReviewFixesTest(unittest.TestCase):
    def test_waiting_service_without_autoprolong_is_high(self) -> None:
        # Без автопродления платить больше некому: ручное 45 + срочность 20 + льгота 5 * 0.2 из 110.
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
