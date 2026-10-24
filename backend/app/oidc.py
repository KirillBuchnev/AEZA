"""OpenID Connect login with authorization code flow, PKCE and signed id_tokens.

The client keeps no session state of its own: the pending login (state, nonce and
PKCE verifier) lives in the oidc_transactions table for ten minutes and is consumed
once. The HTTP client is injectable, so tests can play the identity provider.
"""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from .database import Database
from .security import new_token


# Asymmetric algorithms only. "none" and shared-secret HMAC are never accepted.
ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
TRANSACTION_MINUTES = 10
DISCOVERY_TTL_SECONDS = 3600
JWKS_TTL_SECONDS = 600


class OidcError(Exception):
    """A login could not be completed. The message is for logs and never shown to the user."""


def state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OidcClient:
    def __init__(
        self,
        *,
        database: Database,
        issuer: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: str,
        http: httpx.Client | None = None,
    ) -> None:
        self._database = database
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._scopes = scopes
        self._http = http or httpx.Client(timeout=5.0)
        self._metadata: dict[str, Any] | None = None
        self._metadata_at = 0.0
        self._jwks: dict[str, Any] | None = None
        self._jwks_at = 0.0

    @property
    def issuer(self) -> str:
        return self._issuer

    def start_login(self) -> str:
        """Create a pending login and return the identity provider URL to redirect to."""
        state = new_token()
        nonce = new_token()
        verifier = secrets.token_urlsafe(48)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=TRANSACTION_MINUTES)
        metadata = self._discover()
        self._database.create_oidc_transaction(state_hash(state), nonce, verifier, expires_at.isoformat())
        query = urlencode({
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": self._scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": _code_challenge(verifier),
            "code_challenge_method": "S256",
        })
        return f"{metadata['authorization_endpoint']}?{query}"

    def complete_login(self, *, state: str, code: str) -> dict[str, Any]:
        """Exchange the code and return the verified id_token claims."""
        stored = self._database.consume_oidc_transaction(state_hash(state))
        if stored is None:
            raise OidcError("unknown, expired or reused state")
        metadata = self._discover()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "code_verifier": stored["code_verifier"],
        }
        if self._client_secret:
            form["client_secret"] = self._client_secret
        token_response = self._post_json(metadata["token_endpoint"], form)
        id_token = token_response.get("id_token")
        if not isinstance(id_token, str):
            raise OidcError("token response has no id_token")
        return self._validate_id_token(id_token, nonce=stored["nonce"])

    def _validate_id_token(self, id_token: str, *, nonce: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as error:
            raise OidcError("malformed id_token") from error
        key = self._signing_key(header.get("kid"))
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=ALGORITHMS,
                audience=self._client_id,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as error:
            raise OidcError(f"id_token rejected: {error}") from error
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OidcError("nonce mismatch")
        return claims

    def _signing_key(self, kid: str | None) -> Any:
        for refresh in (False, True):
            jwks = self._jwks_document(refresh=refresh)
            candidates = [
                key for key in jwks.get("keys", [])
                if key.get("use", "sig") == "sig" and (kid is None or key.get("kid") == kid)
            ]
            if candidates:
                try:
                    return jwt.PyJWK(candidates[0]).key
                except jwt.PyJWTError as error:
                    raise OidcError("unsupported signing key") from error
        raise OidcError("no published key matches the id_token")

    def _jwks_document(self, *, refresh: bool) -> dict[str, Any]:
        fresh = self._jwks is not None and time.monotonic() - self._jwks_at < JWKS_TTL_SECONDS
        if refresh or not fresh:
            metadata = self._discover()
            self._jwks = self._get_json(metadata["jwks_uri"])
            self._jwks_at = time.monotonic()
        return self._jwks

    def _discover(self) -> dict[str, Any]:
        fresh = self._metadata is not None and time.monotonic() - self._metadata_at < DISCOVERY_TTL_SECONDS
        if fresh:
            return self._metadata
        metadata = self._get_json(f"{self._issuer}/.well-known/openid-configuration")
        if metadata.get("issuer") != self._issuer:
            raise OidcError("discovery document issuer does not match AEZA_OIDC_ISSUER")
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not isinstance(metadata.get(field), str):
                raise OidcError(f"discovery document lacks {field}")
        self._metadata = metadata
        self._metadata_at = time.monotonic()
        return metadata

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = self._http.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise OidcError(f"request to identity provider failed: {url}") from error
        if not isinstance(payload, dict):
            raise OidcError(f"unexpected response from {url}")
        return payload

    def _post_json(self, url: str, form: dict[str, str]) -> dict[str, Any]:
        try:
            response = self._http.post(url, data=form, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise OidcError("token exchange failed") from error
        if not isinstance(payload, dict):
            raise OidcError("unexpected token response")
        return payload
