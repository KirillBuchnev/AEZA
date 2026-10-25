import json
from pathlib import Path

import pytest

from .conftest import ADMIN_PASSWORD

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "openapi.json"
SUMMARY = "/api/v1/analytics/summary"
METRICS = "/metrics"
SETTINGS = "/api/v1/model/settings"
SNAPSHOT = "/api/v1/source/snapshot"
REQUIRED_PATHS = {
    "/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/auth/logout",
    "/api/v1/customers", "/api/v1/customers/{customer_id}", "/api/v1/analytics/summary",
    "/api/v1/model/settings", "/api/v1/source/snapshot", "/api/v1/events", "/metrics",
}


def sign_in(client) -> None:
    assert client.post("/api/v1/auth/login", json={"username": "demo", "password": ADMIN_PASSWORD}).status_code == 200


def test_committed_openapi_matches_the_application(open_app):
    with open_app() as (_client, main):
        generated = main.app.openapi()
    committed = json.loads(SPEC.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(generated))


def test_every_required_endpoint_is_in_the_spec():
    paths = set(json.loads(SPEC.read_text(encoding="utf-8"))["paths"])
    assert REQUIRED_PATHS <= paths


def test_metrics_need_a_session_or_the_token(open_app):
    token = "prometheus-scrape-token-" + "x" * 16
    with open_app(AEZA_METRICS_TOKEN=token) as (client, _):
        assert client.get(METRICS).status_code == 401
        assert client.get(METRICS, headers={"Authorization": "Bearer wrong-token"}).status_code == 401
        scraped = client.get(METRICS, headers={"Authorization": f"Bearer {token}"})
        assert scraped.status_code == 200
        assert scraped.text.startswith("# HELP aeza_customers_total")
        sign_in(client)
        assert client.get(METRICS).status_code == 200


def test_metrics_agree_with_the_summary(open_app):
    with open_app() as (client, _):
        sign_in(client)
        summary = client.get(SUMMARY).json()
        text = client.get(METRICS).text
        levels = {
            line.split('"')[1]: float(line.split()[-1])
            for line in text.splitlines()
            if line.startswith("aeza_customers_total{")
        }
        assert sum(levels.values()) == summary["customers_total"]
        assert levels["high"] == summary["risk_counts"]["high"]
        loss = next(float(line.split()[-1]) for line in text.splitlines() if line.startswith("aeza_potential_loss_eur "))
        assert loss == pytest.approx(summary["potential_loss_minor"] / 100, abs=0.01)
        near_term = next(float(line.split()[-1]) for line in text.splitlines() if line.startswith("aeza_near_term_loss_eur "))
        assert near_term == pytest.approx(summary["near_term_loss_minor"] / 100, abs=0.01)


def test_settings_and_snapshot_survive_a_restart(open_app):
    with open_app() as (client, _):
        sign_in(client)
        client.patch(SETTINGS, json={"weights": {"renewal_urgency": 33}, "prediction_horizon_days": 45})
        client.put(SNAPSHOT, json={"customers": [{"id": "7", "email": "kept@example.test", "balance": 0,
                                                  "services": [], "transactions": []}]})
    with open_app() as (client, _):
        sign_in(client)
        settings = client.get(SETTINGS).json()
        assert settings["weights"]["renewal_urgency"] == 33
        assert settings["prediction_horizon_days"] == 45
        assert settings["revision"] == 2
        summary = client.get(SUMMARY).json()
        assert summary["source_kind"] == "uploaded"
        assert summary["customers_total"] == 1
