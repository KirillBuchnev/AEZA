import importlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

ADMIN_USERNAME = "demo"
ADMIN_PASSWORD = "local-demo-change-this-password"
ADMIN_CODEWORD = "demo-codeword"
PASSWORD = "Quartz-7421"
NEW_PASSWORD = "Harbor-9083"
VERIFY = "/api/v1/auth/password/verify-codeword"
RESET = "/api/v1/auth/password/reset"
CHANGE = "/api/v1/auth/password/change"


def register(client, **overrides):
    payload = {
        "username": "ivan",
        "first_name": "Иван",
        "last_name": "Петров",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "codeword": "my-word",
    }
    payload.update(overrides)
    return client.post("/api/v1/auth/register", json=payload)


def login(client, username, password):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def verify(client, username, codeword):
    return client.post(VERIFY, json={"username": username, "codeword": codeword})


def reset(client, token, new_password, confirm=None):
    return client.post(
        RESET,
        json={
            "reset_token": token,
            "new_password": new_password,
            "new_password_confirm": new_password if confirm is None else confirm,
        },
    )


def change(client, current, new_password, confirm=None):
    return client.post(
        CHANGE,
        json={
            "current_password": current,
            "new_password": new_password,
            "new_password_confirm": new_password if confirm is None else confirm,
        },
    )


def test_bootstrap_admin_logs_in_and_secrets_are_hashed(open_app, tmp_path):
    with open_app() as (client, _):
        assert login(client, ADMIN_USERNAME, ADMIN_PASSWORD).status_code == 200
        assert client.get("/api/v1/auth/me").json()["username"] == ADMIN_USERNAME

    database_file = (tmp_path / "aeza.db").read_bytes()
    assert ADMIN_PASSWORD.encode() not in database_file
    assert ADMIN_CODEWORD.encode() not in database_file

    db = sqlite3.connect(tmp_path / "aeza.db")
    try:
        password_hash, codeword_hash = db.execute(
            "SELECT password_hash, codeword_hash FROM users WHERE username = ?",
            (ADMIN_USERNAME,),
        ).fetchone()
    finally:
        db.close()
    assert password_hash.startswith("scrypt$")
    assert codeword_hash.startswith("scrypt$")


def test_register_creates_profile_and_signs_in(open_app):
    with open_app() as (client, _):
        response = register(client, username="  Ivan.P  ")
        assert response.status_code == 201
        assert client.get("/api/v1/auth/me").json() == {
            "username": "ivan.p",
            "first_name": "Иван",
            "last_name": "Петров",
            "role": "analyst",
        }


def test_register_rejects_taken_username_in_any_case(open_app):
    with open_app() as (client, _):
        assert register(client, username="ivan").status_code == 201
        client.post("/api/v1/auth/logout")
        assert register(client, username="IVAN").status_code == 409


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"password": "Short-1", "password_confirm": "Short-1"}, "от 10 до 128"),
        ({"password": "lettersonly", "password_confirm": "lettersonly"}, "буквы и цифры"),
        ({"password_confirm": "Other-1234"}, "не совпадают"),
        (
            {"username": "quartz-7421", "password": "Quartz-7421", "password_confirm": "Quartz-7421"},
            "не должен совпадать с логином",
        ),
        ({"codeword": "ab"}, "от 6 до 64"),
        ({"codeword": "123456"}, "слишком простое"),
        ({"codeword": PASSWORD}, "не должно совпадать с паролем"),
        ({"username": "ab"}, "Логин должен быть от 3 до 40"),
        ({"first_name": "   "}, "Укажите имя и фамилию"),
    ],
)
def test_register_validates_input(open_app, overrides, message):
    with open_app() as (client, _):
        response = register(client, **overrides)
        assert response.status_code == 422
        assert message in response.json()["detail"]


def test_registration_can_be_disabled(open_app):
    with open_app(AEZA_REGISTRATION_ENABLED="false") as (client, _):
        assert register(client).status_code == 403


def test_login_error_does_not_reveal_whether_user_exists(open_app):
    with open_app() as (client, _):
        register(client)
        client.post("/api/v1/auth/logout")
        wrong_password = login(client, "ivan", "Wrong-99999")
        unknown_user = login(client, "nobody", "Wrong-99999")
        assert wrong_password.status_code == unknown_user.status_code == 401
        assert wrong_password.json() == unknown_user.json()


def test_forgot_password_resets_with_codeword(open_app):
    with open_app() as (client, _):
        register(client, codeword="my-word")
        assert verify(client, "ivan", "wrong-word").status_code == 401

        token = verify(client, "ivan", "MY-word").json()["reset_token"]
        assert reset(client, token, NEW_PASSWORD, confirm="Other-1234").status_code == 422
        assert reset(client, token, NEW_PASSWORD).status_code == 204

        assert client.get("/api/v1/auth/me").status_code == 401
        assert login(client, "ivan", PASSWORD).status_code == 401
        assert login(client, "ivan", NEW_PASSWORD).status_code == 200


def test_reset_keeps_token_when_new_password_is_weak(open_app):
    with open_app() as (client, _):
        register(client, codeword="my-word")
        token = verify(client, "ivan", "my-word").json()["reset_token"]
        weak = reset(client, token, "onlyletters")
        assert weak.status_code == 422
        assert reset(client, token, NEW_PASSWORD).status_code == 204


def test_reset_token_is_single_use(open_app):
    with open_app() as (client, _):
        register(client, codeword="my-word")
        token = verify(client, "ivan", "my-word").json()["reset_token"]
        assert reset(client, token, NEW_PASSWORD).status_code == 204
        assert reset(client, token, "Third-55555").status_code == 400


def test_reset_token_expires(open_app, tmp_path):
    with open_app() as (client, _):
        register(client, codeword="my-word")
        token = verify(client, "ivan", "my-word").json()["reset_token"]

        db = sqlite3.connect(tmp_path / "aeza.db")
        try:
            db.execute("UPDATE password_resets SET expires_at = '2000-01-01T00:00:00+00:00'")
            db.commit()
        finally:
            db.close()

        response = reset(client, token, NEW_PASSWORD)
        assert response.status_code == 400
        assert "Ссылка для сброса устарела" in response.json()["detail"]


def test_verify_codeword_does_not_reveal_unknown_users(open_app):
    with open_app() as (client, _):
        register(client)
        client.post("/api/v1/auth/logout")
        wrong = verify(client, "ivan", "wrong-word")
        unknown = verify(client, "nobody", "wrong-word")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()


def test_codeword_guessing_is_throttled_per_user(open_app):
    with open_app() as (client, _):
        register(client, codeword="my-word")
        client.post("/api/v1/auth/logout")
        statuses = [verify(client, "ivan", f"guess-{i}").status_code for i in range(5)]
        assert statuses == [401] * 5
        locked = verify(client, "ivan", "my-word")
        assert locked.status_code == 429
        assert locked.headers["Retry-After"].isdigit()


def test_change_password_requires_session(open_app):
    with open_app() as (client, _):
        assert change(client, PASSWORD, NEW_PASSWORD).status_code == 401


def test_change_password_keeps_current_session_and_revokes_others(open_app):
    with open_app() as (client, main):
        register(client)
        other = TestClient(main.app)
        assert login(other, "ivan", PASSWORD).status_code == 200

        assert change(client, PASSWORD, NEW_PASSWORD).status_code == 204

        assert client.get("/api/v1/auth/me").status_code == 200
        assert other.get("/api/v1/auth/me").status_code == 401
        assert login(TestClient(main.app), "ivan", PASSWORD).status_code == 401
        assert login(TestClient(main.app), "ivan", NEW_PASSWORD).status_code == 200


def test_change_password_checks_current_password_and_policy(open_app):
    with open_app() as (client, _):
        register(client)

        wrong_current = change(client, "Wrong-99999", NEW_PASSWORD)
        assert wrong_current.status_code == 400
        assert "Текущий пароль указан неверно" in wrong_current.json()["detail"]

        same = change(client, PASSWORD, PASSWORD)
        assert same.status_code == 422
        assert "должен отличаться" in same.json()["detail"]

        assert change(client, PASSWORD, NEW_PASSWORD, confirm="Other-1234").status_code == 422
        assert change(client, PASSWORD, "onlyletters").status_code == 422


def test_session_cookie_is_http_only_and_lax(open_app):
    with open_app() as (client, _):
        set_cookie = login(client, ADMIN_USERNAME, ADMIN_PASSWORD).headers["set-cookie"].lower()
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie


def test_auth_writes_reject_foreign_origin(open_app):
    with open_app() as (client, _):
        response = client.post(
            VERIFY,
            json={"username": "ivan", "codeword": "my-word"},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403


def test_login_is_throttled_per_account_across_addresses(open_app):
    with open_app() as (client, main):
        register(client)
        client.post("/api/v1/auth/logout")
        for index in range(10):
            attacker = TestClient(main.app, client=(f"203.0.113.{index + 10}", 50000))
            assert login(attacker, "ivan", "Wrong-99999").status_code == 401
        other_address = TestClient(main.app, client=("203.0.113.200", 50000))
        assert login(other_address, "ivan", "Wrong-99999").status_code == 429


def test_reset_requests_are_throttled_per_address(open_app):
    with open_app() as (client, _):
        register(client, codeword="my-word")
        client.post("/api/v1/auth/logout")
        for index in range(30):
            assert verify(client, f"nobody-{index}", "wrong-word").status_code == 401
        assert verify(client, "ivan", "my-word").status_code == 429


def test_change_password_guesses_are_throttled(open_app):
    with open_app() as (client, _):
        register(client)
        for _ in range(5):
            assert change(client, "Wrong-99999", NEW_PASSWORD).status_code == 400
        assert change(client, "Wrong-99999", NEW_PASSWORD).status_code == 429


def test_production_requires_admin_codeword(monkeypatch):
    from app.config import load_config

    monkeypatch.delenv("AEZA_ADMIN_CODEWORD", raising=False)
    for key, value in {
        "AEZA_ENVIRONMENT": "production",
        "AEZA_ADMIN_USERNAME": "ops-analyst",
        "AEZA_ADMIN_PASSWORD": "Strong-passphrase-2026",
        "AEZA_COOKIE_SECURE": "true",
        "AEZA_RATE_LIMIT_SECRET": "r" * 40,
        "AEZA_ALLOWED_ORIGINS": "https://analytics.example",
        "AEZA_METRICS_TOKEN": "m" * 40,
    }.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(ValueError, match="AEZA_ADMIN_CODEWORD"):
        load_config()

    monkeypatch.setenv("AEZA_ADMIN_CODEWORD", "ops-word-2026")
    config = load_config()
    assert config.registration_enabled is False


def test_production_refuses_database_with_published_demo_password(open_app):
    with open_app():
        pass
    production = {
        "AEZA_ENVIRONMENT": "production",
        "AEZA_ADMIN_USERNAME": "ops-analyst",
        "AEZA_ADMIN_PASSWORD": "Strong-passphrase-2026",
        "AEZA_ADMIN_CODEWORD": "ops-word-2026",
        "AEZA_COOKIE_SECURE": "true",
        "AEZA_RATE_LIMIT_SECRET": "r" * 40,
        "AEZA_ALLOWED_ORIGINS": "https://analytics.example",
        "AEZA_METRICS_TOKEN": "m" * 40,
    }
    with pytest.raises(RuntimeError, match="published demo password"):
        with open_app(**production):
            pass
