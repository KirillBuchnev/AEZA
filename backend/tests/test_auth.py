import importlib

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.security import hash_secret, normalize_codeword

# The emergency account: the only one that signs in with a password (conftest seeds it).
ADMIN_USERNAME = "demo"
ADMIN_PASSWORD = "local-demo-change-this-password"
ADMIN_CODEWORD = "demo-codeword"
PASSWORD = "Quartz-7421"
NEW_PASSWORD = "Harbor-9083"
VERIFY = "/api/v1/auth/password/verify-codeword"
RESET = "/api/v1/auth/password/reset"
CHANGE = "/api/v1/auth/password/change"
ADMIN_USERS = "/api/v1/admin/users"
ISSUER = "https://sso.example"
SESSION_COOKIE = "aeza_session"


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


def legacy_password_user(main, username="ivan", password=PASSWORD, codeword="my-word"):
    """A password account that is not the emergency one, as an older database may hold it."""
    main.database.create_user(
        username,
        "Иван",
        "Петров",
        hash_secret(password),
        hash_secret(normalize_codeword(codeword)),
    )


def sso_session(client, main, username):
    """Open a session for an SSO employee the way a successful SSO callback does."""
    response = Response()
    main._start_session(response, main.database.get_user(username))
    token = response.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    client.cookies.set(SESSION_COOKIE, token)


def admin_session(main):
    admin = TestClient(main.app)
    assert login(admin, ADMIN_USERNAME, ADMIN_PASSWORD).status_code == 200
    return admin


def test_bootstrap_admin_logs_in_and_secrets_are_hashed(open_app, database_url, tmp_path):
    with open_app() as (client, main):
        assert login(client, ADMIN_USERNAME, ADMIN_PASSWORD).status_code == 200
        me = client.get("/api/v1/auth/me").json()
        assert me["role"] == "admin"
        assert me["has_password"] is True
        admin = main.database.get_user(ADMIN_USERNAME)

    assert admin["password_hash"].startswith("scrypt$")
    assert admin["codeword_hash"].startswith("scrypt$")
    if database_url.startswith("sqlite"):
        # Файл можно искать на открытый текст; данные PostgreSQL живут вне процесса тестов.
        database_file = (tmp_path / "aeza.db").read_bytes()
        assert ADMIN_PASSWORD.encode() not in database_file
        assert ADMIN_CODEWORD.encode() not in database_file


def test_public_registration_is_gone(open_app):
    with open_app() as (client, _):
        assert client.post("/api/v1/auth/register", json={"username": "ivan"}).status_code == 404
        assert "registration" not in client.get("/api/v1/auth/methods").json()


def test_admin_registers_employee_for_sso_without_password(open_app):
    with open_app() as (client, _):
        assert login(client, ADMIN_USERNAME, ADMIN_PASSWORD).status_code == 200
        created = client.post(
            ADMIN_USERS,
            json={"username": "  Ivan.P  ", "first_name": "Иван", "last_name": "Петров", "middle_name": "Сергеевич"},
        )
        assert created.status_code == 201
        assert created.json() == {
            "username": "ivan.p",
            "first_name": "Иван",
            "last_name": "Петров",
            "middle_name": "Сергеевич",
            "full_name": "Петров Иван Сергеевич",
            "role": "analyst",
            "active": True,
            "has_password": False,
            "created_at": created.json()["created_at"],
        }
        client.post("/api/v1/auth/logout")
        assert login(client, "ivan.p", PASSWORD).status_code == 401


def test_admin_create_rejects_taken_username_in_any_case(open_app):
    with open_app() as (client, _):
        login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        body = {"username": "ivan", "first_name": "Иван", "last_name": "Петров"}
        assert client.post(ADMIN_USERS, json=body).status_code == 201
        assert client.post(ADMIN_USERS, json={**body, "username": "IVAN"}).status_code == 409


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"username": "ab"}, "Логин должен быть от 3 до 64"),
        ({"first_name": "   "}, "Укажите имя и фамилию"),
    ],
)
def test_admin_create_validates_input(open_app, overrides, message):
    with open_app() as (client, _):
        login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        body = {"username": "ivan", "first_name": "Иван", "last_name": "Петров", **overrides}
        response = client.post(ADMIN_USERS, json=body)
        assert response.status_code == 422
        assert message in response.json()["detail"]


def test_only_admins_reach_the_user_panel(open_app):
    with open_app() as (_, main):
        admin = admin_session(main)
        admin.post(ADMIN_USERS, json={"username": "ivan", "first_name": "Иван", "last_name": "Петров"})

        analyst = TestClient(main.app)
        sso_session(analyst, main, "ivan")
        assert analyst.get(ADMIN_USERS).status_code == 403
        assert TestClient(main.app).get(ADMIN_USERS).status_code == 401


def test_admin_cannot_block_or_demote_themselves(open_app):
    with open_app() as (client, _):
        login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        assert client.patch(f"{ADMIN_USERS}/{ADMIN_USERNAME}", json={"active": False}).status_code == 409
        assert client.patch(f"{ADMIN_USERS}/{ADMIN_USERNAME}", json={"role": "analyst"}).status_code == 409
        assert client.get("/api/v1/auth/me").status_code == 200


def test_blocked_employee_loses_session_and_cannot_sign_in_again(open_app):
    with open_app() as (_, main):
        admin = admin_session(main)
        admin.post(ADMIN_USERS, json={"username": "ivan", "first_name": "Иван", "last_name": "Петров"})
        employee = TestClient(main.app)
        sso_session(employee, main, "ivan")
        assert employee.get("/api/v1/auth/me").status_code == 200

        blocked = admin.patch(f"{ADMIN_USERS}/ivan", json={"active": False})
        assert blocked.status_code == 200
        assert blocked.json()["active"] is False

        assert employee.get("/api/v1/auth/me").status_code == 401
        assert main._oidc_user(ISSUER, {"sub": "x", "preferred_username": "ivan"}) is None


def test_admin_can_promote_an_employee(open_app):
    with open_app() as (client, _):
        login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        client.post(ADMIN_USERS, json={"username": "ivan", "first_name": "Иван", "last_name": "Петров"})
        promoted = client.patch(f"{ADMIN_USERS}/ivan", json={"role": "admin"})
        assert promoted.status_code == 200
        assert promoted.json()["role"] == "admin"

        listing = client.get(ADMIN_USERS).json()["items"]
        assert [item["username"] for item in listing] == ["demo", "ivan"]


def test_last_active_admin_cannot_be_removed(open_app):
    with open_app() as (_, main):
        with pytest.raises(ValueError, match="без активного администратора"):
            main.database.update_user(ADMIN_USERNAME, active=False)


def test_bootstrap_admin_is_restored_when_no_active_admin_is_left(open_app):
    with open_app() as (_, main):
        with main.database.connection() as connection:
            connection.execute(
                text("UPDATE users SET active = :active WHERE username = :username"),
                {"active": False, "username": ADMIN_USERNAME},
            )
    with open_app() as (client, _):
        assert login(client, ADMIN_USERNAME, ADMIN_PASSWORD).status_code == 200


def test_sso_links_only_employees_the_admin_registered(open_app):
    with open_app() as (client, main):
        login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        client.post(ADMIN_USERS, json={"username": "ivan.sso", "first_name": "Иван", "last_name": "Петров"})
        employee = {"sub": "subject-1", "preferred_username": "ivan.sso"}

        assert main._oidc_user(ISSUER, employee)["username"] == "ivan.sso"
        assert main._oidc_user(ISSUER, employee)["username"] == "ivan.sso"
        assert main._oidc_user(ISSUER, {"sub": "subject-2", "preferred_username": "stranger"}) is None
        # A local password account is never taken over through SSO.
        assert main._oidc_user(ISSUER, {"sub": "subject-3", "preferred_username": ADMIN_USERNAME}) is None

        client.patch(f"{ADMIN_USERS}/ivan.sso", json={"active": False})
        assert main._oidc_user(ISSUER, employee) is None


def test_password_sign_in_is_closed_for_everyone_but_the_emergency_account(open_app):
    with open_app() as (client, main):
        legacy_password_user(main)
        admin_session(main).post(ADMIN_USERS, json={"username": "ivan.sso", "first_name": "Иван", "last_name": "Петров"})

        assert login(client, "ivan", PASSWORD).status_code == 401
        assert login(client, "ivan.sso", PASSWORD).status_code == 401
        assert login(client, "ivan.sso", "Anything-Long-1").status_code == 401
        # A legacy password account cannot reset through its codeword either.
        assert verify(client, "ivan", "my-word").status_code == 401


def test_login_error_does_not_reveal_whether_user_exists(open_app):
    with open_app() as (client, _):
        wrong_password = login(client, ADMIN_USERNAME, "Wrong-99999")
        unknown_user = login(client, "nobody", "Wrong-99999")
        assert wrong_password.status_code == unknown_user.status_code == 401
        assert wrong_password.json() == unknown_user.json()


def test_forgot_password_resets_with_codeword(open_app):
    with open_app() as (client, _):
        assert verify(client, ADMIN_USERNAME, "wrong-word").status_code == 401

        token = verify(client, ADMIN_USERNAME, ADMIN_CODEWORD.upper()).json()["reset_token"]
        assert reset(client, token, NEW_PASSWORD, confirm="Other-1234").status_code == 422
        assert reset(client, token, NEW_PASSWORD).status_code == 204

        assert client.get("/api/v1/auth/me").status_code == 401
        assert login(client, ADMIN_USERNAME, ADMIN_PASSWORD).status_code == 401
        assert login(client, ADMIN_USERNAME, NEW_PASSWORD).status_code == 200


def test_reset_keeps_token_when_new_password_is_weak(open_app):
    with open_app() as (client, _):
        token = verify(client, ADMIN_USERNAME, ADMIN_CODEWORD).json()["reset_token"]
        weak = reset(client, token, "onlyletters")
        assert weak.status_code == 422
        assert reset(client, token, NEW_PASSWORD).status_code == 204


def test_reset_token_is_single_use(open_app):
    with open_app() as (client, _):
        token = verify(client, ADMIN_USERNAME, ADMIN_CODEWORD).json()["reset_token"]
        assert reset(client, token, NEW_PASSWORD).status_code == 204
        assert reset(client, token, "Third-55555").status_code == 400


def test_reset_token_expires(open_app):
    with open_app() as (client, main):
        token = verify(client, ADMIN_USERNAME, ADMIN_CODEWORD).json()["reset_token"]

        with main.database.connection() as connection:
            connection.execute(text("UPDATE password_resets SET expires_at = '2000-01-01T00:00:00+00:00'"))

        response = reset(client, token, NEW_PASSWORD)
        assert response.status_code == 400
        assert "Ссылка для сброса устарела" in response.json()["detail"]


def test_verify_codeword_does_not_reveal_unknown_users(open_app):
    with open_app() as (client, _):
        wrong = verify(client, ADMIN_USERNAME, "wrong-word")
        unknown = verify(client, "nobody", "wrong-word")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()


def test_codeword_guessing_is_throttled_per_user(open_app):
    with open_app() as (client, _):
        statuses = [verify(client, ADMIN_USERNAME, f"guess-{i}").status_code for i in range(5)]
        assert statuses == [401] * 5
        locked = verify(client, ADMIN_USERNAME, ADMIN_CODEWORD)
        assert locked.status_code == 429
        assert locked.headers["Retry-After"].isdigit()


def test_change_password_requires_session(open_app):
    with open_app() as (client, _):
        assert change(client, ADMIN_PASSWORD, NEW_PASSWORD).status_code == 401


def test_change_password_keeps_current_session_and_revokes_others(open_app):
    with open_app() as (client, main):
        login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        other = TestClient(main.app)
        assert login(other, ADMIN_USERNAME, ADMIN_PASSWORD).status_code == 200

        assert change(client, ADMIN_PASSWORD, NEW_PASSWORD).status_code == 204

        assert client.get("/api/v1/auth/me").status_code == 200
        assert other.get("/api/v1/auth/me").status_code == 401
        assert login(TestClient(main.app), ADMIN_USERNAME, ADMIN_PASSWORD).status_code == 401
        assert login(TestClient(main.app), ADMIN_USERNAME, NEW_PASSWORD).status_code == 200


def test_change_password_checks_current_password_and_policy(open_app):
    with open_app() as (client, _):
        login(client, ADMIN_USERNAME, ADMIN_PASSWORD)

        wrong_current = change(client, "Wrong-99999", NEW_PASSWORD)
        assert wrong_current.status_code == 400
        assert "Текущий пароль указан неверно" in wrong_current.json()["detail"]

        same = change(client, ADMIN_PASSWORD, ADMIN_PASSWORD)
        assert same.status_code == 422
        assert "должен отличаться" in same.json()["detail"]

        assert change(client, ADMIN_PASSWORD, NEW_PASSWORD, confirm="Other-1234").status_code == 422
        assert change(client, ADMIN_PASSWORD, "onlyletters").status_code == 422


def test_change_password_is_closed_for_sso_employees(open_app):
    with open_app() as (_, main):
        admin_session(main).post(ADMIN_USERS, json={"username": "ivan", "first_name": "Иван", "last_name": "Петров"})
        employee = TestClient(main.app)
        sso_session(employee, main, "ivan")
        assert employee.get("/api/v1/auth/me").json()["has_password"] is False

        assert change(employee, PASSWORD, NEW_PASSWORD).status_code == 403


def test_session_cookie_is_http_only_and_lax(open_app):
    with open_app() as (client, _):
        set_cookie = login(client, ADMIN_USERNAME, ADMIN_PASSWORD).headers["set-cookie"].lower()
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie


def test_auth_writes_reject_foreign_origin(open_app):
    with open_app() as (client, _):
        response = client.post(
            VERIFY,
            json={"username": ADMIN_USERNAME, "codeword": ADMIN_CODEWORD},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403


def test_login_is_throttled_per_account_across_addresses(open_app):
    with open_app() as (_, main):
        for index in range(10):
            attacker = TestClient(main.app, client=(f"203.0.113.{index + 10}", 50000))
            assert login(attacker, ADMIN_USERNAME, "Wrong-99999").status_code == 401
        other_address = TestClient(main.app, client=("203.0.113.200", 50000))
        assert login(other_address, ADMIN_USERNAME, "Wrong-99999").status_code == 429


def test_reset_requests_are_throttled_per_address(open_app):
    with open_app() as (client, _):
        for index in range(30):
            assert verify(client, f"nobody-{index}", "wrong-word").status_code == 401
        assert verify(client, ADMIN_USERNAME, ADMIN_CODEWORD).status_code == 429


def test_change_password_guesses_are_throttled(open_app):
    with open_app() as (client, _):
        login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
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
    assert load_config().admin_username == "ops-analyst"


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
