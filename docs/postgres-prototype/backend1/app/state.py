"""Общее состояние приложения."""
from __future__ import annotations
import hashlib, hmac, ipaddress
from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyCookie
from .config import AppConfig, load_config
from .database import Database

config: AppConfig = load_config()
database: Database = Database(config.database_url)
SESSION_COOKIE = "aeza_session"
session_cookie = APIKeyCookie(name=SESSION_COOKIE, scheme_name="sessionCookie", auto_error=False)

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def client_key(request: Request) -> str:
    forwarded_address = request.headers.get("x-real-ip", "")
    socket_address = request.client.host if request.client else "unknown"
    try:
        address = ipaddress.ip_address(forwarded_address or socket_address).compressed
    except ValueError:
        address = socket_address
    return hmac.new(config.rate_limit_secret, address.encode("utf-8"), hashlib.sha256).hexdigest()

def unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Войдите, чтобы продолжить.")

def require_session(token: str | None = Depends(session_cookie)) -> str:
    if not token:
        raise unauthorized()
    username = database.session_username(token_hash(token))
    if not username:
        raise unauthorized()
    return username