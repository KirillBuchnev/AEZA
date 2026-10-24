from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from copy import deepcopy
from typing import Any, Iterator

from .risk import DEFAULT_MODEL_SETTINGS, demo_snapshot


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS customers (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    balance_minor INTEGER NOT NULL,
                    withdraw_balance_minor INTEGER NOT NULL DEFAULT 0,
                    bonus_balance_minor INTEGER NOT NULL DEFAULT 0,
                    bonus_spend_enabled INTEGER NOT NULL DEFAULT 0,
                    total_replenished_minor INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS services (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    price_minor INTEGER NOT NULL,
                    auto_prolong INTEGER NOT NULL,
                    payment_term TEXT,
                    status TEXT NOT NULL,
                    expires_at TEXT
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                    service_id TEXT,
                    status TEXT NOT NULL,
                    type TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    client_key TEXT PRIMARY KEY,
                    window_started_at TEXT NOT NULL,
                    failures INTEGER NOT NULL CHECK (failures >= 1)
                );
                CREATE INDEX IF NOT EXISTS idx_services_customer ON services(customer_id);
                CREATE INDEX IF NOT EXISTS idx_transactions_customer ON transactions(customer_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value) VALUES ('model_settings', ?)",
                (json.dumps(DEFAULT_MODEL_SETTINGS, ensure_ascii=False),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value) VALUES ('source_updated_at', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )
            source_kind = connection.execute(
                "SELECT value FROM app_state WHERE key = 'source_kind'"
            ).fetchone()
            if source_kind is None:
                customer_count = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
                if customer_count == 0:
                    self._replace_snapshot(connection, demo_snapshot())
                connection.execute(
                    "INSERT INTO app_state(key, value) VALUES ('source_kind', ?)",
                    ("demo" if customer_count == 0 else "uploaded",),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO app_state(key, value) VALUES ('source_updated_at', ?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )

    def model_settings(self) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT value FROM app_state WHERE key = 'model_settings'"
            ).fetchone()
            if row is None:
                return deepcopy(DEFAULT_MODEL_SETTINGS)
            stored = json.loads(row["value"])
            settings = {**DEFAULT_MODEL_SETTINGS, **stored}
            stored_weights = stored.get("weights", {}) if isinstance(stored, dict) else {}
            if set(stored_weights) != set(DEFAULT_MODEL_SETTINGS["weights"]):
                # The previous UI used unrelated binary flags; never reinterpret those
                # old weights as the new service-level expert factors.
                settings["weights"] = dict(DEFAULT_MODEL_SETTINGS["weights"])
                settings["high_risk_min"] = DEFAULT_MODEL_SETTINGS["high_risk_min"]
                settings["medium_risk_min"] = DEFAULT_MODEL_SETTINGS["medium_risk_min"]
            else:
                settings["weights"] = {**DEFAULT_MODEL_SETTINGS["weights"], **stored_weights}
            return settings

    def save_model_settings(self, settings: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO app_state(key, value) VALUES ('model_settings', ?)",
                (json.dumps(settings, ensure_ascii=False),),
            )

    def source_info(self) -> dict[str, str]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT key, value FROM app_state WHERE key IN ('source_kind', 'source_updated_at')"
            ).fetchall()
            return {row["key"]: row["value"] for row in rows}

    def replace_snapshot(self, customers: list[dict[str, Any]]) -> None:
        with self.connection() as connection:
            self._replace_snapshot(connection, customers)
            connection.execute(
                "INSERT OR REPLACE INTO app_state(key, value) VALUES ('source_kind', 'uploaded')"
            )
            connection.execute(
                "INSERT OR REPLACE INTO app_state(key, value) VALUES ('source_updated_at', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

    @staticmethod
    def _replace_snapshot(connection: sqlite3.Connection, customers: list[dict[str, Any]]) -> None:
        connection.execute("DELETE FROM transactions")
        connection.execute("DELETE FROM services")
        connection.execute("DELETE FROM customers")
        for customer in customers:
            customer_id = str(customer["id"])
            connection.execute(
                """
                INSERT INTO customers (
                    id, email, balance_minor, withdraw_balance_minor,
                    bonus_balance_minor, bonus_spend_enabled, total_replenished_minor
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_id,
                    customer["email"],
                    customer["balance_minor"],
                    customer["withdraw_balance_minor"],
                    customer["bonus_balance_minor"],
                    int(customer["bonus_spend_enabled"]),
                    customer["total_replenished_minor"],
                ),
            )
            for index, service in enumerate(customer["services"], start=1):
                service_id = str(service["id"] or f"{customer_id}-service-{index}")
                connection.execute(
                    """
                    INSERT INTO services (
                        id, customer_id, name, price_minor, auto_prolong,
                        payment_term, status, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        service_id,
                        customer_id,
                        service["name"],
                        service["price_minor"],
                        int(service["auto_prolong"]),
                        service["payment_term"],
                        service["status"],
                        service["expires_at"],
                    ),
                )
            for index, transaction in enumerate(customer["transactions"], start=1):
                transaction_id = str(transaction["id"] or f"{customer_id}-transaction-{index}")
                connection.execute(
                    """
                    INSERT INTO transactions (
                        id, customer_id, service_id, status, type,
                        amount_minor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        customer_id,
                        transaction["service_id"],
                        transaction["status"],
                        transaction["type"],
                        transaction["amount_minor"],
                        transaction["created_at"],
                    ),
                )

    def customer_rows(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            customers = connection.execute(
                "SELECT * FROM customers ORDER BY id"
            ).fetchall()
            services = connection.execute(
                "SELECT * FROM services ORDER BY customer_id, id"
            ).fetchall()
            transactions = connection.execute(
                "SELECT * FROM transactions ORDER BY customer_id, id"
            ).fetchall()

        services_by_customer: dict[str, list[dict[str, Any]]] = {}
        for row in services:
            services_by_customer.setdefault(row["customer_id"], []).append({
                "id": row["id"],
                "name": row["name"],
                "price_minor": row["price_minor"],
                "auto_prolong": bool(row["auto_prolong"]),
                "payment_term": row["payment_term"],
                "status": row["status"],
                "expires_at": row["expires_at"],
            })

        transactions_by_customer: dict[str, list[dict[str, Any]]] = {}
        for row in transactions:
            transactions_by_customer.setdefault(row["customer_id"], []).append({
                "id": row["id"],
                "service_id": row["service_id"],
                "status": row["status"],
                "type": row["type"],
                "amount_minor": row["amount_minor"],
                "created_at": row["created_at"],
            })

        return [
            {
                "id": row["id"],
                "email": row["email"],
                "balance_minor": row["balance_minor"],
                "withdraw_balance_minor": row["withdraw_balance_minor"],
                "bonus_balance_minor": row["bonus_balance_minor"],
                "bonus_spend_enabled": bool(row["bonus_spend_enabled"]),
                "total_replenished_minor": row["total_replenished_minor"],
                "services": services_by_customer.get(row["id"], []),
                "transactions": transactions_by_customer.get(row["id"], []),
            }
            for row in customers
        ]

    def create_session(self, token_hash: str, username: str, expires_at: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (datetime.now(timezone.utc).isoformat(),),
            )
            connection.execute(
                "INSERT INTO sessions(token_hash, username, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token_hash, username, expires_at, datetime.now(timezone.utc).isoformat()),
            )

    def session_username(self, token_hash: str) -> str | None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as connection:
            row = connection.execute(
                "SELECT username FROM sessions WHERE token_hash = ? AND expires_at > ?",
                (token_hash, now),
            ).fetchone()
            return row["username"] if row else None

    def delete_session(self, token_hash: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def begin_login_attempt(
        self,
        client_key: str,
        max_attempts: int = 5,
        window_seconds: int = 900,
    ) -> int:
        """Count an attempt atomically and return a lockout's remaining seconds."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        cutoff = (now - timedelta(seconds=window_seconds)).isoformat()

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM login_attempts WHERE window_started_at <= ?",
                (cutoff,),
            )
            row = connection.execute(
                "SELECT window_started_at, failures FROM login_attempts WHERE client_key = ?",
                (client_key,),
            ).fetchone()

            if row:
                started_at = datetime.fromisoformat(row["window_started_at"])
                if row["failures"] >= max_attempts:
                    remaining = int((started_at + timedelta(seconds=window_seconds) - now).total_seconds() + 0.999)
                    return max(1, remaining)
                failures = row["failures"] + 1
                window_started_at = row["window_started_at"]
            else:
                failures = 1
                window_started_at = now_iso

            connection.execute(
                "INSERT OR REPLACE INTO login_attempts(client_key, window_started_at, failures) VALUES (?, ?, ?)",
                (client_key, window_started_at, failures),
            )
        return 0

    def clear_login_attempts(self, client_key: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM login_attempts WHERE client_key = ?", (client_key,))
