from datetime import datetime, timedelta, timezone

SNAPSHOT = "/api/v1/source/snapshot"
CUSTOMERS = "/api/v1/customers"
ADMIN_PASSWORD = "local-demo-change-this-password"


def sign_in(client) -> None:
    assert client.post("/api/v1/auth/login", json={"username": "demo", "password": ADMIN_PASSWORD}).status_code == 200


def days_from_now(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def account(services: list[dict], transactions: list[dict] | None = None) -> dict:
    return {"id": "1", "email": "a@example.test", "balance": 0, "services": services, "transactions": transactions or []}


def service(service_id: str, status: str = "active", expires_in_days: float = 30) -> dict:
    return {"id": service_id, "name": service_id, "price": 1000, "autoprolong": True, "paymentTerm": "month",
            "status": status, "expiresAt": days_from_now(expires_in_days)}


def detail(client) -> dict:
    return client.get(f"{CUSTOMERS}/1").json()


def test_an_unknown_service_status_does_not_reject_the_snapshot(open_app):
    with open_app() as (client, _):
        sign_in(client)
        response = client.put(SNAPSHOT, json={"customers": [account([service("a", status="frozen"), service("b")])]})
        assert response.status_code == 200
        issues = detail(client)["data_quality"]
        assert {"code": "unknown_status", "service_id": "a"}.items() <= next(i for i in issues if i["code"] == "unknown_status").items()
        assert [s["id"] for s in detail(client)["services"]] == ["b"]


def test_an_unknown_transaction_type_is_reported_and_ignored(open_app):
    transaction = {"id": "t1", "service_id": "a", "status": "not_performed", "type": "refund", "amount": 500,
                   "createdAt": days_from_now(-1)}
    with open_app() as (client, _):
        sign_in(client)
        assert client.put(SNAPSHOT, json={"customers": [account([service("a")], [transaction])]}).status_code == 200
        codes = [issue["code"] for issue in detail(client)["data_quality"]]
        assert "unknown_transaction" in codes


def test_waiting_longer_than_the_grace_period_is_flagged(open_app):
    with open_app() as (client, _):
        sign_in(client)
        assert client.put(SNAPSHOT, json={"customers": [account([service("a", status="prolong_wait", expires_in_days=-9)])]}).status_code == 200
        codes = [issue["code"] for issue in detail(client)["data_quality"]]
        assert "grace_expired" in codes


def test_flat_organizer_export_is_accepted_and_joined(open_app):
    with open_app() as (client, _):
        sign_in(client)
        response = client.put(SNAPSHOT, json={
            "accounts": [{
                "id": 7,
                "email": "flat@example.test",
                "balance": 5000,
                "withdrawBalance": 0,
                "bonusBalance": 0,
                "bonusState": "locked",
                "totalReplenished": 9000,
            }],
            "services": [{
                "id": 70,
                "ownerId": 7,
                "name": "Flat service",
                "price": 1000,
                "autoProlong": False,
                "paymentTerm": "month",
                "status": "active",
                "expiresAt": days_from_now(2),
            }],
            "transactions": [{
                "id": 700,
                "serviceId": 70,
                "amount": 1000,
                "status": "performed",
                "type": "order",
                "createdAt": days_from_now(-2),
            }],
        })
        assert response.status_code == 200
        detail_response = client.get(f"{CUSTOMERS}/7")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["email"] == "flat@example.test"
        assert detail["services"][0]["id"] == "70"
        assert detail["transactions"][0]["id"] == "700"
