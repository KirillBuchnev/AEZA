from datetime import datetime, timedelta, timezone
import json

from app.database import Database


ADMIN_USERNAME = "demo"
ADMIN_PASSWORD = "local-demo-change-this-password"
SNAPSHOT = "/api/v1/source/snapshot"
CUSTOMERS = "/api/v1/customers"
SETTINGS = "/api/v1/model/settings"
OUTFLOW = "/api/v1/analytics/outflow"


def days_from_now(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def service(
    service_id: str,
    *,
    status: str = "active",
    expires_in_days: float | None = 45,
    price: int = 1_000,
    auto: bool = True,
    term: str = "month",
) -> dict:
    return {
        "id": service_id,
        "name": f"Service {service_id}",
        "price": price,
        "autoprolong": auto,
        "paymentTerm": term,
        "status": status,
        "expiresAt": None if expires_in_days is None else days_from_now(expires_in_days),
    }


def customer(customer_id: str, services: list[dict], *, balance: int = 0) -> dict:
    return {
        "id": customer_id,
        "email": f"client{customer_id}@example.com",
        "balance": balance,
        "bonusBalance": 0,
        "bonusState": "locked",
        "totalReplenished": 10_000,
        "services": services,
        "transactions": [],
    }


def sign_in(client) -> None:
    response = client.post("/api/v1/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert response.status_code == 200


def put_snapshot(client, *customers: dict):
    return client.put(SNAPSHOT, json={"customers": list(customers)})


def test_journal_records_renewals_entries_deletions_and_removals(open_app, tmp_path):
    with open_app() as (client, _):
        sign_in(client)
        first = put_snapshot(
            client,
            customer("1", [
                service("s-deleted", expires_in_days=20, price=1_000),
                service("s-waiting", expires_in_days=20, price=2_000),
                service("s-renewed", status="prolong_wait", expires_in_days=-1, price=3_000),
                service("s-removed", expires_in_days=20, price=500),
            ]),
        )
        assert first.status_code == 200
        assert first.json()["events_recorded"] == 0

        second = put_snapshot(
            client,
            customer("1", [
                service("s-deleted", status="deleted", expires_in_days=20, price=1_000),
                service("s-waiting", status="prolong_wait", expires_in_days=-1, price=2_000),
                service("s-renewed", expires_in_days=45, price=3_000),
            ]),
        )
        body = second.json()
        assert body["events_recorded"] == 4
        assert body["snapshot_id"] != first.json()["snapshot_id"]

        facts = client.get(OUTFLOW, params={"days": 7}).json()["facts"]
        totals = facts["totals"]
        assert totals["deleted"] == 1
        assert totals["removed"] == 1
        assert totals["entered_wait"] == 1
        assert totals["renewed"] == 1
        assert totals["deleted_amount_minor"] == 1_000 + 500
        assert facts["snapshots_observed"] == 1


def test_outflow_separates_facts_from_forecast(open_app):
    with open_app() as (client, _):
        sign_in(client)
        put_snapshot(client, customer("1", [service("s-1", expires_in_days=2, auto=False)], balance=0))
        put_snapshot(client, customer("1", [service("s-1", expires_in_days=2, auto=False)], balance=0))

        payload = client.get(OUTFLOW, params={"days": 7}).json()
        assert len(payload["facts"]["days"]) == 8
        assert payload["facts"]["source"] == "snapshot_journal"
        forecast = payload["forecast"]
        assert forecast["buckets"][0]["services_due"] == 1
        assert forecast["buckets"][0]["services_at_risk"] == 1
        assert "не калибровано" in forecast["method"].lower()


def test_customers_sort_both_ways_and_unscored_stay_last(open_app):
    with open_app() as (client, _):
        sign_in(client)
        put_snapshot(
            client,
            customer("1", [service("a", price=1_000, expires_in_days=45, auto=True)], balance=5_000),
            customer("2", [service("b", price=5_000, expires_in_days=2, auto=False)], balance=0),
            customer("3", [service("c", price=2_000, expires_in_days=None)], balance=0),
        )

        def ids(**params) -> list[str]:
            response = client.get(CUSTOMERS, params=params)
            assert response.status_code == 200
            return [item["id"] for item in response.json()["items"]]

        assert ids(sort_by="monthly_cost", order="asc") == ["1", "3", "2"]
        assert ids(sort_by="monthly_cost", order="desc") == ["2", "3", "1"]
        assert ids(sort_by="risk_score", order="asc") == ["1", "2", "3"]
        assert ids(sort_by="risk_score", order="desc") == ["2", "1", "3"]
        assert ids(sort_by="email", order="asc") == ["1", "2", "3"]


def test_id_sort_accepts_non_ascii_digits(open_app):
    with open_app() as (client, _):
        sign_in(client)
        put_snapshot(
            client,
            customer("١٢", [service("x")], balance=0),
            customer("7", [service("y")], balance=0),
        )
        response = client.get(CUSTOMERS, params={"sort_by": "id", "order": "asc"})
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == ["7", "١٢"]


def test_model_changes_bump_calculation_version_and_are_validated(open_app):
    with open_app() as (client, _):
        sign_in(client)
        before = client.get(SETTINGS).json()
        assert before["revision"] == 1
        assert before["calculation_version"] == "3.1"
        assert before["normalizer"] == 110

        after = client.patch(SETTINGS, json={"weights": {"renewal_urgency": 30}}).json()
        assert after["revision"] == 2
        assert after["calculation_version"] == "3.2"
        assert after["weights"]["renewal_urgency"] == 30
        assert after["normalizer"] == 120

        unknown = client.patch(SETTINGS, json={"weights": {"failed_prolong_payment": 20}})
        assert unknown.status_code == 422
        inverted = client.patch(SETTINGS, json={"high_risk_min": 20, "medium_risk_min": 30})
        assert inverted.status_code == 422
        zero = client.patch(SETTINGS, json={"weights": {"prolong_wait": 0, "autoprolong_disabled": 0, "insufficient_balance": 0, "renewal_urgency": 0}})
        assert zero.status_code == 422


def test_customer_detail_argues_reasons_and_pins_the_snapshot(open_app):
    with open_app() as (client, _):
        sign_in(client)
        snapshot = put_snapshot(client, customer("42", [service("s-42", expires_in_days=3 / 24, auto=False, price=10_000)], balance=0))
        detail = client.get(f"{CUSTOMERS}/42").json()

        assert detail["snapshot_id"] == snapshot.json()["snapshot_id"]
        assert detail["calculation_version"] == "3.1"
        reasons = detail["services"][0]["reasons"]
        assert {reason["code"] for reason in reasons} == {"autoprolong_disabled", "insufficient_balance", "renewal_urgency"}
        assert all(reason["explanation"] for reason in reasons)
        shortage = next(reason for reason in reasons if reason["code"] == "insufficient_balance")
        assert shortage["evidence"]["shortfall_minor"] == 10_000
        assert detail["recommended_action"]["code"] == "top_up"
        assert detail["calculation"]["normalizer"] == 110


def test_upgrade_keeps_custom_weights_and_thresholds(open_app, tmp_path):
    database = Database(str(tmp_path / "aeza.db"))
    database.initialize(admin_profile=None)
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
        "formula": {"normalizer": 110, "urgency_weight": 20},
    }
    with database.connection() as connection:
        connection.execute("UPDATE app_state SET value = ? WHERE key = 'model_settings'", (json.dumps(stored),))

    with open_app() as (client, _):
        sign_in(client)
        settings = client.get(SETTINGS).json()
        assert settings["version"] == 3
        assert settings["high_risk_min"] == 60
        assert settings["prediction_horizon_days"] == 45
        assert settings["weights"]["autoprolong_disabled"] == 50
        assert "failed_prolong_payment" not in settings["weights"]
