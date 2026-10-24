from datetime import datetime, timedelta, timezone

OUTFLOW = "/api/v1/analytics/outflow"
SNAPSHOT = "/api/v1/source/snapshot"
ADMIN_PASSWORD = "local-demo-change-this-password"


def sign_in(client) -> None:
    assert client.post("/api/v1/auth/login", json={"username": "demo", "password": ADMIN_PASSWORD}).status_code == 200


def days_from_now(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def customer(customer_id: str, services: list[dict]) -> dict:
    return {"id": customer_id, "email": f"c{customer_id}@example.test", "balance": 0, "services": services, "transactions": []}


def service(service_id: str, *, status: str = "active", expires_in_days: float = 20, auto: bool = True) -> dict:
    return {"id": service_id, "name": service_id, "price": 1000, "autoprolong": auto, "paymentTerm": "month",
            "status": status, "expiresAt": days_from_now(expires_in_days)}


def test_first_start_shows_historical_deletions_from_the_snapshot_as_an_estimate(open_app):
    with open_app() as (client, _):
        sign_in(client)
        facts = client.get(OUTFLOW, params={"days": 365}).json()["facts"]
        assert facts["source"] == "snapshot_estimate"
        assert facts["estimated"] is True
        assert facts["totals"]["deleted"] >= 1


def test_journal_replaces_the_estimate_once_it_has_transitions(open_app):
    with open_app() as (client, _):
        sign_in(client)
        client.put(SNAPSHOT, json={"customers": [customer("1", [service("a", expires_in_days=-1, status="prolong_wait")])]})
        client.put(SNAPSHOT, json={"customers": [customer("1", [service("a", status="deleted", expires_in_days=-1)])]})
        facts = client.get(OUTFLOW, params={"days": 7}).json()["facts"]
        assert facts["source"] == "snapshot_journal"
        assert facts["estimated"] is False
        assert facts["totals"]["deleted"] == 1


def test_services_at_risk_now_are_counted_in_the_response(open_app):
    with open_app() as (client, _):
        sign_in(client)
        client.put(SNAPSHOT, json={"customers": [customer("1", [
            service("manual", expires_in_days=3 / 24, auto=False),
            service("safe", expires_in_days=60),
        ])]})
        at_risk = client.get(OUTFLOW).json()["services_at_risk"]
        assert at_risk["total"] == 1
        assert at_risk["high"] == 1
        assert at_risk["medium"] == 0
