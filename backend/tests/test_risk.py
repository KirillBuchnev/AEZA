import unittest
from datetime import datetime, timedelta, timezone

from app.risk import DEFAULT_MODEL_SETTINGS, evaluate_customer
from app.schemas import SnapshotUpload


NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def make_customer(
    *,
    balance: int,
    auto_prolong: bool,
    status: str = "active",
    days_until_expiry: float = 1,
    price: int = 10_000,
    transactions: list[dict] | None = None,
) -> dict:
    expires_at = NOW + timedelta(days=days_until_expiry)
    return {
        "id": "test-customer",
        "email": "test@example.com",
        "balance_minor": balance,
        "withdraw_balance_minor": 0,
        "bonus_balance_minor": 0,
        "bonus_spend_enabled": False,
        "total_replenished_minor": 0,
        "services": [
            {
                "id": "service-1",
                "name": "Test service",
                "price_minor": price,
                "auto_prolong": auto_prolong,
                "payment_term": "month",
                "status": status,
                "expires_at": expires_at.isoformat(),
            }
        ],
        "transactions": transactions or [],
    }


class RiskScenariosTest(unittest.TestCase):
    def test_acceptance_scenarios_a_to_e(self) -> None:
        scenarios = {
            "A": make_customer(balance=10_000, auto_prolong=False, days_until_expiry=3 / 24),
            "B": make_customer(balance=0, auto_prolong=True, days_until_expiry=3 / 24),
            "C": make_customer(balance=0, auto_prolong=True, status="prolong_wait", days_until_expiry=-1),
            "D": make_customer(balance=10_000, auto_prolong=True, status="prolong_wait", days_until_expiry=-1),
            "E": make_customer(balance=10_000, auto_prolong=True, days_until_expiry=1),
        }
        scenarios["E"]["services"][0]["expires_at"] = None

        result_a = evaluate_customer(scenarios["A"], DEFAULT_MODEL_SETTINGS, NOW)
        result_b = evaluate_customer(scenarios["B"], DEFAULT_MODEL_SETTINGS, NOW)
        result_c = evaluate_customer(scenarios["C"], DEFAULT_MODEL_SETTINGS, NOW)
        result_d = evaluate_customer(scenarios["D"], DEFAULT_MODEL_SETTINGS, NOW)
        result_e = evaluate_customer(scenarios["E"], DEFAULT_MODEL_SETTINGS, NOW)

        self.assertEqual(result_a["risk_level"], "high")
        self.assertEqual(result_b["risk_level"], "high")
        self.assertEqual(result_c["risk_level"], "high")
        self.assertEqual(result_d["risk_level"], "low")
        self.assertIsNone(result_e["risk_score"])

    def test_expired_active_service_is_data_quality_issue(self) -> None:
        result = evaluate_customer(
            make_customer(balance=100_000, auto_prolong=True, days_until_expiry=-1),
            DEFAULT_MODEL_SETTINGS,
            NOW,
        )
        self.assertIsNone(result["risk_score"])
        self.assertEqual(result["reasons"][0]["code"], "insufficient_data")

    def test_old_failed_payment_does_not_raise_score(self) -> None:
        old_payment = {
            "id": "transaction-1",
            "service_id": "service-1",
            "status": "not_performed",
            "type": "prolong",
            "amount_minor": 10_000,
            "created_at": (NOW - timedelta(days=30)).isoformat(),
        }
        result = evaluate_customer(
            make_customer(
                balance=10_000,
                auto_prolong=True,
                days_until_expiry=1,
                transactions=[old_payment],
            ),
            DEFAULT_MODEL_SETTINGS,
            NOW,
        )
        self.assertNotIn("failed_prolong_payment", {reason["code"] for reason in result["reasons"]})

    def test_reason_points_follow_continuous_urgency(self) -> None:
        early = evaluate_customer(
            make_customer(balance=10_000, auto_prolong=False, days_until_expiry=3),
            DEFAULT_MODEL_SETTINGS,
            NOW,
        )
        late = evaluate_customer(
            make_customer(balance=10_000, auto_prolong=False, days_until_expiry=1),
            DEFAULT_MODEL_SETTINGS,
            NOW,
        )
        early_points = early["services"][0]["reasons"][0]["points"]
        late_points = late["services"][0]["reasons"][0]["points"]
        self.assertGreater(late_points, early_points)
        self.assertNotEqual(late_points, DEFAULT_MODEL_SETTINGS["weights"]["autoprolong_disabled"])

        combined = evaluate_customer(
            make_customer(balance=0, auto_prolong=False, days_until_expiry=1),
            DEFAULT_MODEL_SETTINGS,
            NOW,
        )
        visible_points = sum(
            reason["points"] for reason in combined["services"][0]["reasons"]
        )
        self.assertAlmostEqual(visible_points, combined["services"][0]["risk_score"], delta=0.2)

    def test_large_snapshot_and_tolerant_fields(self) -> None:
        payload = SnapshotUpload.model_validate(
            {
                "customers": [
                    {
                        "id": "bulk-1",
                        "email": "bulk@example.com",
                        "balance": 0,
                        "bonusState": "unlocked",
                        "customerNote": "ignored by the importer",
                        "services": [
                            {
                                "id": f"service-{index}",
                                "name": "Bulk service",
                                "price": 100,
                                "autoprolong": True,
                                "status": "active",
                                "expiresAt": (NOW + timedelta(days=1)).isoformat(),
                            }
                            for index in range(200)
                        ],
                    }
                ]
            }
        )
        self.assertEqual(len(payload.customers[0].services), 200)
        self.assertTrue(payload.customers[0].bonus_spend_enabled)


if __name__ == "__main__":
    unittest.main()
