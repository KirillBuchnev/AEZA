from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
import uuid

from .risk import DEFAULT_MODEL_SETTINGS, MODEL_VERSION, as_utc, demo_snapshot, merge_model_settings


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

    def initialize(
        self,
        admin_profile: dict[str, str] | None = None,
        seed_customers: list[dict[str, Any]] | None = None,
        seed_name: str = "empty",
    ) -> None:
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
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    codeword_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'analyst',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS password_resets (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshot_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_at TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    price_minor INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oidc_identities (
                    issuer TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
                    PRIMARY KEY (issuer, subject)
                );
                CREATE TABLE IF NOT EXISTS oidc_transactions (
                    state_hash TEXT PRIMARY KEY,
                    nonce TEXT NOT NULL,
                    code_verifier TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_snapshot_events_observed ON snapshot_events(observed_at);
                CREATE INDEX IF NOT EXISTS idx_services_customer ON services(customer_id);
                CREATE INDEX IF NOT EXISTS idx_transactions_customer ON transactions(customer_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
                """
            )
            user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
            if "middle_name" not in user_columns:
                connection.execute("ALTER TABLE users ADD COLUMN middle_name TEXT")
            settings_row = connection.execute(
                "SELECT value FROM app_state WHERE key = 'model_settings'"
            ).fetchone()
            if settings_row is None:
                connection.execute(
                    "INSERT INTO app_state(key, value) VALUES ('model_settings', ?)",
                    (json.dumps(DEFAULT_MODEL_SETTINGS, ensure_ascii=False),),
                )
            else:
                stored_settings = json.loads(settings_row["value"])
                if stored_settings.get("version", 1) < MODEL_VERSION:
                    # Keep the custom weights and thresholds of the previous version.
                    migrated = merge_model_settings(stored_settings)
                    connection.execute(
                        "UPDATE app_state SET value = ? WHERE key = 'model_settings'",
                        (json.dumps(migrated, ensure_ascii=False),),
                    )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value) VALUES ('source_updated_at', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value) VALUES ('snapshot_id', ?)",
                (str(uuid.uuid4()),),
            )
            source_kind = connection.execute(
                "SELECT value FROM app_state WHERE key = 'source_kind'"
            ).fetchone()
            if source_kind is None:
                customer_count = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
                if customer_count == 0 and seed_customers is not None:
                    self._replace_snapshot(connection, seed_customers)
                    source_name = seed_name
                else:
                    source_name = "empty" if customer_count == 0 else "uploaded"
                connection.execute(
                    "INSERT INTO app_state(key, value) VALUES ('source_kind', ?)",
                    (source_name,),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO app_state(key, value) VALUES ('source_updated_at', ?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
            elif source_kind["value"] == "demo":
                # Demo dates are relative to the current day. Refresh only the
                # synthetic source; an uploaded snapshot remains untouched.
                self._replace_snapshot(connection, demo_snapshot())
                connection.execute(
                    "INSERT OR REPLACE INTO app_state(key, value) VALUES ('source_updated_at', ?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
            if admin_profile is not None:
                exists = connection.execute(
                    "SELECT 1 FROM users WHERE username = ?",
                    (admin_profile["username"],),
                ).fetchone()
                if exists is None:
                    connection.execute(
                        """
                        INSERT INTO users (
                            username, first_name, last_name, password_hash,
                            codeword_hash, role, created_at
                        ) VALUES (?, ?, ?, ?, ?, 'analyst', ?)
                        """,
                        (
                            admin_profile["username"],
                            admin_profile["first_name"],
                            admin_profile["last_name"],
                            admin_profile["password_hash"],
                            admin_profile["codeword_hash"],
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT username, first_name, last_name, middle_name, password_hash, codeword_hash, role
                FROM users WHERE username = ?
                """,
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute("SELECT username, password_hash FROM users").fetchall()
        return [dict(row) for row in rows]

    def create_user(
        self,
        username: str,
        first_name: str,
        last_name: str,
        password_hash: str,
        codeword_hash: str,
        middle_name: str | None = None,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    username, first_name, last_name, middle_name, password_hash,
                    codeword_hash, role, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'analyst', ?)
                """,
                (
                    username,
                    first_name,
                    last_name,
                    middle_name,
                    password_hash,
                    codeword_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def set_password(self, username: str, password_hash: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (password_hash, username),
            )

    def delete_user_sessions(self, username: str, keep_token_hash: str | None = None) -> None:
        with self.connection() as connection:
            if keep_token_hash is None:
                connection.execute("DELETE FROM sessions WHERE username = ?", (username,))
            else:
                connection.execute(
                    "DELETE FROM sessions WHERE username = ? AND token_hash != ?",
                    (username, keep_token_hash),
                )

    def create_password_reset(self, token_hash: str, username: str, expires_at: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM password_resets WHERE username = ?", (username,))
            connection.execute(
                "INSERT INTO password_resets(token_hash, username, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token_hash, username, expires_at, datetime.now(timezone.utc).isoformat()),
            )

    def peek_password_reset(self, token_hash: str) -> str | None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as connection:
            row = connection.execute(
                "SELECT username FROM password_resets WHERE token_hash = ? AND expires_at > ?",
                (token_hash, now),
            ).fetchone()
        return row["username"] if row else None

    def consume_password_reset(self, token_hash: str) -> str | None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as connection:
            row = connection.execute(
                "DELETE FROM password_resets WHERE token_hash = ? AND expires_at > ? RETURNING username",
                (token_hash, now),
            ).fetchone()
            return row["username"] if row else None

    def replace_password(self, username: str, password_hash: str, keep_token_hash: str | None = None) -> None:
        """Set the password and revoke sessions in one transaction."""
        with self.connection() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (password_hash, username),
            )
            if keep_token_hash is None:
                connection.execute("DELETE FROM sessions WHERE username = ?", (username,))
            else:
                connection.execute(
                    "DELETE FROM sessions WHERE username = ? AND token_hash != ?",
                    (username, keep_token_hash),
                )

    def model_settings(self) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT value FROM app_state WHERE key = 'model_settings'"
            ).fetchone()
            if row is None:
                return merge_model_settings(DEFAULT_MODEL_SETTINGS)
            return merge_model_settings(json.loads(row["value"]))

    def save_model_settings(self, settings: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO app_state(key, value) VALUES ('model_settings', ?)",
                (json.dumps(merge_model_settings(settings), ensure_ascii=False),),
            )

    def source_info(self) -> dict[str, str]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT key, value FROM app_state WHERE key IN ('source_kind', 'source_updated_at')"
            ).fetchall()
            return {row["key"]: row["value"] for row in rows}

    def snapshot_meta(self) -> dict[str, str | None]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT key, value FROM app_state WHERE key IN ('source_kind', 'source_updated_at', 'snapshot_id')"
            ).fetchall()
        values = {row["key"]: row["value"] for row in rows}
        return {
            "snapshot_id": values.get("snapshot_id"),
            "source_kind": values.get("source_kind", "demo"),
            "source_updated_at": values.get("source_updated_at"),
        }

    def replace_snapshot(self, customers: list[dict[str, Any]]) -> dict[str, Any]:
        observed_at = datetime.now(timezone.utc).isoformat()
        snapshot_id = str(uuid.uuid4())
        with self.connection() as connection:
            previous_kind = connection.execute(
                "SELECT value FROM app_state WHERE key = 'source_kind'"
            ).fetchone()
            events: list[tuple[Any, ...]] = []
            # The demo source is not a real history: the first uploaded snapshot starts the journal.
            if previous_kind is not None and previous_kind["value"] == "uploaded":
                events = self._transition_events(connection, customers, observed_at, snapshot_id)
            self._replace_snapshot(connection, customers)
            connection.executemany(
                """
                INSERT INTO snapshot_events (
                    observed_at, snapshot_id, customer_id, service_id,
                    event_type, from_status, to_status, price_minor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                events,
            )
            connection.execute(
                "INSERT OR REPLACE INTO app_state(key, value) VALUES ('source_kind', 'uploaded')"
            )
            connection.execute(
                "INSERT OR REPLACE INTO app_state(key, value) VALUES ('source_updated_at', ?)",
                (observed_at,),
            )
            connection.execute(
                "INSERT OR REPLACE INTO app_state(key, value) VALUES ('snapshot_id', ?)",
                (snapshot_id,),
            )
        return {"snapshot_id": snapshot_id, "observed_at": observed_at, "events_recorded": len(events)}

    @staticmethod
    def _transition_events(
        connection: sqlite3.Connection,
        customers: list[dict[str, Any]],
        observed_at: str,
        snapshot_id: str,
    ) -> list[tuple[Any, ...]]:
        """Compare the stored services with the incoming snapshot and record facts that happened."""
        previous = {
            row["id"]: row
            for row in connection.execute(
                "SELECT id, customer_id, status, expires_at, price_minor FROM services"
            ).fetchall()
        }
        incoming: dict[str, dict[str, Any]] = {}
        for customer in customers:
            customer_id = str(customer["id"])
            for index, service in enumerate(customer["services"], start=1):
                service_id = str(service["id"] or f"{customer_id}-service-{index}")
                incoming[service_id] = service

        events: list[tuple[Any, ...]] = []
        for service_id, old in previous.items():
            if old["status"] not in {"active", "suspended", "prolong_wait"}:
                continue
            new = incoming.get(service_id)
            if new is None:
                event, to_status = "removed", None
            else:
                to_status = new["status"]
                if to_status == "deleted":
                    event = "deleted"
                elif to_status == "blocked":
                    event = "blocked"
                elif old["status"] == "prolong_wait" and to_status in {"active", "suspended"}:
                    event = "renewed"
                elif old["status"] != "prolong_wait" and to_status == "prolong_wait":
                    event = "entered_wait"
                elif (
                    old["expires_at"]
                    and new["expires_at"]
                    and as_utc(new["expires_at"]) > as_utc(old["expires_at"])
                ):
                    event = "renewed"
                else:
                    continue
            events.append((
                observed_at,
                snapshot_id,
                old["customer_id"],
                service_id,
                event,
                old["status"],
                to_status,
                old["price_minor"],
            ))
        return events

    def journal_rows(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT observed_at, snapshot_id, customer_id, service_id, event_type,
                       from_status, to_status, price_minor
                FROM snapshot_events ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def outflow_facts(self, since: str) -> dict[str, Any]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT substr(observed_at, 1, 10) AS day, event_type,
                       COUNT(*) AS services, COALESCE(SUM(price_minor), 0) AS amount_minor
                FROM snapshot_events
                WHERE observed_at >= ?
                GROUP BY day, event_type
                ORDER BY day
                """,
                (since,),
            ).fetchall()
            snapshots = connection.execute(
                "SELECT COUNT(DISTINCT snapshot_id) FROM snapshot_events WHERE observed_at >= ?",
                (since,),
            ).fetchone()[0]
        return {"rows": [dict(row) for row in rows], "snapshots": snapshots}

    def oidc_identity(self, issuer: str, subject: str) -> str | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT username FROM oidc_identities WHERE issuer = ? AND subject = ?",
                (issuer, subject),
            ).fetchone()
        return row["username"] if row else None

    def link_oidc_identity(self, issuer: str, subject: str, username: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO oidc_identities(issuer, subject, username) VALUES (?, ?, ?)",
                (issuer, subject, username),
            )

    def create_oidc_transaction(self, state_hash: str, nonce: str, code_verifier: str, expires_at: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM oidc_transactions WHERE expires_at <= ?", (datetime.now(timezone.utc).isoformat(),))
            connection.execute(
                "INSERT INTO oidc_transactions(state_hash, nonce, code_verifier, expires_at) VALUES (?, ?, ?, ?)",
                (state_hash, nonce, code_verifier, expires_at),
            )

    def consume_oidc_transaction(self, state_hash: str) -> dict[str, str] | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                DELETE FROM oidc_transactions
                WHERE state_hash = ? AND expires_at > ?
                RETURNING nonce, code_verifier
                """,
                (state_hash, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
        return dict(row) if row else None

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
