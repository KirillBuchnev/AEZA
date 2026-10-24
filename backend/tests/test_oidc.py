from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import load_config
from app.oidc import OidcClient


ISSUER = "https://idp.example.test"
CLIENT_ID = "aeza-panel"
REDIRECT_URI = "http://localhost:5173/api/v1/auth/oidc/callback"
CALLBACK = "/api/v1/auth/oidc/callback"
LOGIN = "/api/v1/auth/oidc/login"
ME = "/api/v1/auth/me"
PASSWORD_LOGIN = "/api/v1/auth/login"
OIDC_ENV = {
    "AEZA_OIDC_ISSUER": ISSUER,
    "AEZA_OIDC_CLIENT_ID": CLIENT_ID,
    "AEZA_OIDC_CLIENT_SECRET": "client-secret-for-tests",
    "AEZA_OIDC_REDIRECT_URI": REDIRECT_URI,
}


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class FakeIdentityProvider:
    """Serves discovery, JWKS and the token endpoint, and signs real RS256 id_tokens."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "test-key-1"
        self.codes: dict[str, dict[str, str]] = {}
        self.claim_overrides: dict[str, object] = {}

    def jwk(self) -> dict:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
            })
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [self.jwk()]})
        if request.url.path == "/token":
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            issued = self.codes.pop(form.get("code", ""), None)
            if issued is None or _challenge(form.get("code_verifier", "")) != issued["challenge"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            now = datetime.now(timezone.utc)
            claims = {
                "iss": ISSUER,
                "aud": CLIENT_ID,
                "sub": "subject-42",
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=5)).timestamp()),
                "nonce": issued["nonce"],
                "preferred_username": "ivan_p",
                "given_name": "Иван",
                "family_name": "Петров",
            }
            claims.update(self.claim_overrides)
            token = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})
            return httpx.Response(200, json={"id_token": token, "token_type": "Bearer"})
        return httpx.Response(404)


@pytest.fixture
def idp() -> FakeIdentityProvider:
    return FakeIdentityProvider()


def install(main, idp: FakeIdentityProvider) -> None:
    main.oidc_client = OidcClient(
        database=main.database,
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret="client-secret-for-tests",
        redirect_uri=REDIRECT_URI,
        scopes="openid profile",
        http=httpx.Client(transport=httpx.MockTransport(idp.handler)),
    )


def start_login(client, idp: FakeIdentityProvider, code: str = "code-1") -> str:
    """Begin a login as the browser would and let the fake provider remember the authorization request."""
    response = client.get(LOGIN, follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["response_type"] == ["code"]
    idp.codes[code] = {"nonce": query["nonce"][0], "challenge": query["code_challenge"][0]}
    return query["state"][0]


def complete(client, state: str, code: str = "code-1"):
    return client.get(CALLBACK, params={"state": state, "code": code}, follow_redirects=False)


def test_sso_is_off_without_configuration(open_app):
    with open_app() as (client, _):
        assert client.get("/api/v1/auth/methods").json()["sso"]["enabled"] is False
        assert client.get(LOGIN, follow_redirects=False).status_code == 404


def test_sso_is_advertised_when_configured(open_app, idp):
    with open_app(**OIDC_ENV) as (client, main):
        install(main, idp)
        assert client.get("/api/v1/auth/methods").json()["sso"]["enabled"] is True


def test_login_redirects_with_pkce_state_and_nonce(open_app, idp):
    with open_app(**OIDC_ENV) as (client, main):
        install(main, idp)
        response = client.get(LOGIN, follow_redirects=False)
        query = parse_qs(urlsplit(response.headers["location"]).query)
        assert response.headers["location"].startswith(f"{ISSUER}/authorize?")
        assert query["client_id"] == [CLIENT_ID]
        assert query["redirect_uri"] == [REDIRECT_URI]
        assert len(query["state"][0]) > 30
        assert len(query["nonce"][0]) > 30
        assert len(query["code_challenge"][0]) == 43


def test_unknown_user_is_denied_without_provisioning(open_app, idp):
    with open_app(**OIDC_ENV) as (client, main):
        install(main, idp)
        state = start_login(client, idp)
        response = complete(client, state)
        assert response.status_code == 303
        assert response.headers["location"] == "/?sso=denied"
        assert "aeza_session" not in response.cookies
        assert client.get(ME).status_code == 401


def test_provisioned_user_signs_in_and_password_login_stays_closed(open_app, idp):
    with open_app(**OIDC_ENV, AEZA_OIDC_AUTO_PROVISION="true") as (client, main):
        install(main, idp)
        state = start_login(client, idp)
        response = complete(client, state)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "aeza_session" in response.cookies

        me = client.get(ME).json()
        assert me["username"] == "ivan_p"
        assert me["first_name"] == "Иван"
        assert main.database.oidc_identity(ISSUER, "subject-42") == "ivan_p"

        # SSO-only accounts have no local password; the password form must refuse them.
        client.cookies.clear()
        refused = client.post(PASSWORD_LOGIN, json={"username": "ivan_p", "password": "Quartz-7421"})
        assert refused.status_code == 401


def test_provisioning_never_links_to_an_existing_local_account(open_app, idp):
    with open_app(**OIDC_ENV, AEZA_OIDC_AUTO_PROVISION="true") as (client, main):
        install(main, idp)
        existing = client.post("/api/v1/auth/register", json={
            "username": "ivan_p",
            "first_name": "Local",
            "last_name": "User",
            "password": "Quartz-7421",
            "password_confirm": "Quartz-7421",
            "codeword": "my-word",
        })
        assert existing.status_code == 201
        client.cookies.clear()
        state = start_login(client, idp)
        response = complete(client, state)
        assert response.headers["location"] == "/?sso=denied"
        assert main.database.oidc_identity(ISSUER, "subject-42") is None


@pytest.mark.parametrize(
    "claims",
    [
        {"nonce": "not-the-issued-nonce"},
        {"aud": "another-application"},
        {"iss": "https://evil.example.test"},
        {"exp": int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())},
    ],
)
def test_rejects_forged_or_stale_id_tokens(open_app, idp, claims):
    with open_app(**OIDC_ENV, AEZA_OIDC_AUTO_PROVISION="true") as (client, main):
        install(main, idp)
        idp.claim_overrides = claims
        state = start_login(client, idp)
        response = complete(client, state)
        assert response.headers["location"] == "/?sso=failed"
        assert "aeza_session" not in response.cookies


def test_rejects_wrong_pkce_verifier(open_app, idp):
    with open_app(**OIDC_ENV, AEZA_OIDC_AUTO_PROVISION="true") as (client, main):
        install(main, idp)
        state = start_login(client, idp)
        idp.codes["code-1"]["challenge"] = "a-different-challenge-value-0000000000000"
        response = complete(client, state)
        assert response.headers["location"] == "/?sso=failed"


def test_state_is_single_use_and_unknown_state_is_refused(open_app, idp):
    with open_app(**OIDC_ENV, AEZA_OIDC_AUTO_PROVISION="true") as (client, main):
        install(main, idp)
        state = start_login(client, idp)
        assert complete(client, "forged-state").headers["location"] == "/?sso=failed"
        first = complete(client, state)
        assert first.headers["location"] == "/"
        idp.codes["code-2"] = {"nonce": "unused", "challenge": "unused"}
        replay = complete(client, state, code="code-2")
        assert replay.headers["location"] == "/?sso=failed"


def test_provider_error_parameter_is_reported_as_failure(open_app, idp):
    with open_app(**OIDC_ENV) as (client, main):
        install(main, idp)
        response = client.get(CALLBACK, params={"error": "access_denied"}, follow_redirects=False)
        assert response.headers["location"] == "/?sso=failed"


def test_partial_oidc_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("AEZA_OIDC_ISSUER", ISSUER)
    monkeypatch.delenv("AEZA_OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("AEZA_OIDC_REDIRECT_URI", raising=False)
    with pytest.raises(ValueError, match="must be set together"):
        load_config()


def test_production_requires_https_identity_provider(monkeypatch):
    monkeypatch.setenv("AEZA_ENVIRONMENT", "production")
    monkeypatch.setenv("AEZA_OIDC_ISSUER", "http://idp.internal")
    monkeypatch.setenv("AEZA_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("AEZA_OIDC_REDIRECT_URI", REDIRECT_URI)
    with pytest.raises(ValueError, match="HTTPS"):
        load_config()
