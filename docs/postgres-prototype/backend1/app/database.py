"""PostgreSQL-реализация Database."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json, os
from typing import Any, Iterator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from .risk import DEFAULT_MODEL_SETTINGS, demo_snapshot

def _utcnow() -> datetime: return datetime.now(timezone.utc)
def _iso(value: datetime | None) -> str | None: return value.astimezone(timezone.utc).isoformat() if value else None

class Database:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ["DATABASE_URL"]
        self.engine = create_engine(self.url, pool_pre_ping=True, future=True)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    @contextmanager
    def connection(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def initialize(self) -> None:
        with self.connection() as s:
            s.execute(text("INSERT INTO app_state(key, value) VALUES ('model_settings', :v) ON CONFLICT (key) DO NOTHING"), {"v": json.dumps(DEFAULT_MODEL_SETTINGS, ensure_ascii=False)})
            s.execute(text("INSERT INTO app_state(key, value) VALUES ('source_updated_at', :v) ON CONFLICT (key) DO NOTHING"), {"v": _utcnow().isoformat()})
            row = s.execute(text("SELECT value FROM app_state WHERE key = 'source_kind'")).first()
            if row is None:
                count = s.execute(text("SELECT COUNT(*) FROM customers")).scalar_one()
                if count == 0:
                    self._replace_snapshot(s, demo_snapshot())
                s.execute(text("INSERT INTO app_state(key, value) VALUES ('source_kind', :v)"), {"v": "demo" if count == 0 else "uploaded"})
                s.execute(text("INSERT INTO app_state(key, value) VALUES ('source_updated_at', :v) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"), {"v": _utcnow().isoformat()})

    def model_settings(self) -> dict[str, Any]:
        with self.connection() as s:
            row = s.execute(text("SELECT value FROM app_state WHERE key = 'model_settings'")).first()
            return json.loads(row[0]) if row else DEFAULT_MODEL_SETTINGS.copy()

    def save_model_settings(self, settings: dict[str, Any]) -> None:
        with self.connection() as s:
            s.execute(text("INSERT INTO app_state(key, value) VALUES ('model_settings', :v) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"), {"v": json.dumps(settings, ensure_ascii=False)})

    def source_info(self) -> dict[str, str]:
        with self.connection() as s:
            rows = s.execute(text("SELECT key, value FROM app_state WHERE key IN ('source_kind','source_updated_at')")).all()
            return {r[0]: r[1] for r in rows}

    def replace_snapshot(self, customers: list[dict[str, Any]]) -> None:
        with self.connection() as s:
            self._replace_snapshot(s, customers)
            s.execute(text("INSERT INTO app_state(key, value) VALUES ('source_kind', 'uploaded') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"))
            s.execute(text("INSERT INTO app_state(key, value) VALUES ('source_updated_at', :v) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"), {"v": _utcnow().isoformat()})

    @staticmethod
    def _replace_snapshot(s: Session, customers: list[dict[str, Any]]) -> None:
        s.execute(text("DELETE FROM transactions")); s.execute(text("DELETE FROM services")); s.execute(text("DELETE FROM customers"))
        for c in customers:
            cid = str(c["id"])
            s.execute(text("INSERT INTO customers (id, email, balance_minor, withdraw_balance_minor, bonus_balance_minor, bonus_spend_enabled, total_replenished_minor) VALUES (:id, :email, :bal, :wb, :bb, :bse, :tr)"), {"id": cid, "email": c["email"], "bal": c["balance_minor"], "wb": c["withdraw_balance_minor"], "bb": c["bonus_balance_minor"], "bse": bool(c["bonus_spend_enabled"]), "tr": c["total_replenished_minor"]})
            for idx, svc in enumerate(c["services"], start=1):
                sid = str(svc["id"] or f"{cid}-service-{idx}")
                s.execute(text("INSERT INTO services (id, customer_id, name, price_minor, auto_prolong, payment_term, status, expires_at) VALUES (:id, :cid, :n, :p, :a, :pt, :st, :ea)"), {"id": sid, "cid": cid, "n": svc["name"], "p": svc["price_minor"], "a": bool(svc["auto_prolong"]), "pt": svc["payment_term"], "st": svc["status"], "ea": svc["expires_at"]})
            for idx, tx in enumerate(c["transactions"], start=1):
                tid = str(tx["id"] or f"{cid}-transaction-{idx}")
                s.execute(text("INSERT INTO transactions (id, customer_id, service_id, status, type, amount_minor, created_at) VALUES (:id, :cid, :sid, :st, :t, :am, :ca)"), {"id": tid, "cid": cid, "sid": tx["service_id"], "st": tx["status"], "t": tx["type"], "am": tx["amount_minor"], "ca": tx["created_at"]})

    def customer_rows(self) -> list[dict[str, Any]]:
        with self.connection() as s:
            customers = s.execute(text("SELECT * FROM customers ORDER BY id")).mappings().all()
            services = s.execute(text("SELECT * FROM services ORDER BY customer_id, id")).mappings().all()
            txs = s.execute(text("SELECT * FROM transactions ORDER BY customer_id, id")).mappings().all()
        svc_by = {}; tx_by = {}
        for r in services: svc_by.setdefault(r["customer_id"], []).append({"id": r["id"], "name": r["name"], "price_minor": r["price_minor"], "auto_prolong": bool(r["auto_prolong"]), "payment_term": r["payment_term"], "status": r["status"], "expires_at": _iso(r["expires_at"])})
        for r in txs: tx_by.setdefault(r["customer_id"], []).append({"id": r["id"], "service_id": r["service_id"], "status": r["status"], "type": r["type"], "amount_minor": r["amount_minor"], "created_at": _iso(r["created_at"])})
        return [{"id": r["id"], "email": r["email"], "balance_minor": r["balance_minor"], "withdraw_balance_minor": r["withdraw_balance_minor"], "bonus_balance_minor": r["bonus_balance_minor"], "bonus_spend_enabled": bool(r["bonus_spend_enabled"]), "total_replenished_minor": r["total_replenished_minor"], "services": svc_by.get(r["id"], []), "transactions": tx_by.get(r["id"], [])} for r in customers]

    def create_session(self, token_hash: str, username: str, expires_at: str) -> None:
        with self.connection() as s:
            s.execute(text("DELETE FROM sessions WHERE expires_at <= :now"), {"now": _utcnow()})
            s.execute(text("INSERT INTO sessions(token_hash, username, expires_at, created_at) VALUES (:th, :u, :ea, :ca)"), {"th": token_hash, "u": username, "ea": expires_at, "ca": _utcnow()})

    def session_username(self, token_hash: str) -> str | None:
        with self.connection() as s:
            row = s.execute(text("SELECT username FROM sessions WHERE token_hash = :th AND expires_at > :now"), {"th": token_hash, "now": _utcnow()}).first()
            return row[0] if row else None

    def delete_session(self, token_hash: str) -> None:
        with self.connection() as s: s.execute(text("DELETE FROM sessions WHERE token_hash = :th"), {"th": token_hash})

    def begin_login_attempt(self, client_key: str, max_attempts: int = 5, window_seconds: int = 900) -> int:
        now = _utcnow(); cutoff = now - timedelta(seconds=window_seconds)
        with self.connection() as s:
            s.execute(text("DELETE FROM login_attempts WHERE window_started_at <= :c"), {"c": cutoff})
            row = s.execute(text("SELECT window_started_at, failures FROM login_attempts WHERE client_key = :k FOR UPDATE"), {"k": client_key}).first()
            if row:
                started_at, failures = row
                if started_at.tzinfo is None: started_at = started_at.replace(tzinfo=timezone.utc)
                if failures >= max_attempts: return max(1, int((started_at + timedelta(seconds=window_seconds) - now).total_seconds() + 0.999))
                s.execute(text("UPDATE login_attempts SET failures = failures + 1 WHERE client_key = :k"), {"k": client_key})
            else:
                s.execute(text("INSERT INTO login_attempts(client_key, window_started_at, failures) VALUES (:k, :w, 1)"), {"k": client_key, "w": now})
        return 0

    def clear_login_attempts(self, client_key: str) -> None:
        with self.connection() as s: s.execute(text("DELETE FROM login_attempts WHERE client_key = :k"), {"k": client_key})