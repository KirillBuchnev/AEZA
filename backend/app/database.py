from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Iterator
import uuid

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine, make_url

from .risk import DEFAULT_MODEL_SETTINGS, MODEL_VERSION, as_utc, demo_snapshot, merge_model_settings


# One schema bootstrap at a time, also when several API processes start together.
SCHEMA_LOCK_KEY = 745_101

SET_STATE = text(
    "INSERT INTO app_state (key, value) VALUES (:key, :value) "
    "ON CONFLICT (key) DO UPDATE SET value = excluded.value"
)
ADD_STATE = text("INSERT INTO app_state (key, value) VALUES (:key, :value) ON CONFLICT (key) DO NOTHING")
INSERT_CUSTOMER = text(
    """
    INSERT INTO customers (
        id, email, balance_minor, withdraw_balance_minor,
        bonus_balance_minor, bonus_spend_enabled, total_replenished_minor
    ) VALUES (
        :id, :email, :balance_minor, :withdraw_balance_minor,
        :bonus_balance_minor, :bonus_spend_enabled, :total_replenished_minor
    )
    """
)
INSERT_SERVICE = text(
    """
    INSERT INTO services (
        id, customer_id, name, price_minor, auto_prolong,
        payment_term, status, expires_at
    ) VALUES (
        :id, :customer_id, :name, :price_minor, :auto_prolong,
        :payment_term, :status, :expires_at
    )
    """
)
INSERT_TRANSACTION = text(
    """
    INSERT INTO transactions (
        id, customer_id, service_id, status, type, amount_minor, created_at
    ) VALUES (
        :id, :customer_id, :service_id, :status, :type, :amount_minor, :created_at
    )
    """
)
INSERT_EVENT = text(
    """
    INSERT INTO snapshot_events (
        observed_at, snapshot_id, customer_id, service_id,
        event_type, from_status, to_status, price_minor
    ) VALUES (
        :observed_at, :snapshot_id, :customer_id, :service_id,
        :event_type, :from_status, :to_status, :price_minor
    )
    """
)
UPSERT_ATTEMPT = text(
    """
    INSERT INTO login_attempts (client_key, window_started_at, failures)
    VALUES (:client_key, :window_started_at, :failures)
    ON CONFLICT (client_key) DO UPDATE SET
        window_started_at = excluded.window_started_at,
        failures = excluded.failures
    """
)


def create_database_engine(url: str) -> Engine:
    if make_url(url).get_backend_name() == "sqlite":
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 10})

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys = ON")

        return engine
    return create_engine(url, pool_pre_ping=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(connection: Connection, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(text(sql), params or {}).mappings().all()]


def _row(connection: Connection, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    row = connection.execute(text(sql), params or {}).mappings().first()
    return dict(row) if row else None


def _scalar(connection: Connection, sql: str, params: dict[str, Any] | None = None) -> Any:
    return connection.execute(text(sql), params or {}).scalar()


def _schema_statements(dialect: str) -> list[str]:
    """Idempotent DDL. Money is BIGINT and flags are BOOLEAN on both databases. Dates from a
    snapshot stay ISO text: the robust snapshot accepts messy rows and reports them as data issues."""
    journal_id = "INTEGER PRIMARY KEY AUTOINCREMENT" if dialect == "sqlite" else "BIGSERIAL PRIMARY KEY"
    return [
        """CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS customers (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            balance_minor BIGINT NOT NULL,
            withdraw_balance_minor BIGINT NOT NULL DEFAULT 0,
            bonus_balance_minor BIGINT NOT NULL DEFAULT 0,
            bonus_spend_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            total_replenished_minor BIGINT NOT NULL DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            price_minor BIGINT NOT NULL,
            auto_prolong BOOLEAN NOT NULL,
            payment_term TEXT,
            status TEXT NOT NULL,
            expires_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            service_id TEXT,
            status TEXT NOT NULL,
            type TEXT NOT NULL,
            amount_minor BIGINT NOT NULL,
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS login_attempts (
            client_key TEXT PRIMARY KEY,
            window_started_at TEXT NOT NULL,
            failures INTEGER NOT NULL CHECK (failures >= 1)
        )""",
        """CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            middle_name TEXT,
            password_hash TEXT NOT NULL,
            codeword_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'analyst',
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS password_resets (
            token_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS snapshot_events (
            id {journal_id},
            observed_at TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            service_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            price_minor BIGINT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS oidc_identities (
            issuer TEXT NOT NULL,
            subject TEXT NOT NULL,
            username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
            PRIMARY KEY (issuer, subject)
        )""",
        """CREATE TABLE IF NOT EXISTS oidc_transactions (
            state_hash TEXT PRIMARY KEY,
            nonce TEXT NOT NULL,
            code_verifier TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_snapshot_events_observed ON snapshot_events(observed_at)",
        "CREATE INDEX IF NOT EXISTS idx_services_customer ON services(customer_id)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_customer ON transactions(customer_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at)",
    ]


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = create_database_engine(url)
        self.dialect = self.engine.dialect.name

    def dispose(self) -> None:
        self.engine.dispose()

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        """One transaction: committed on success, rolled back on any exception."""
        with self.engine.begin() as connection:
            yield connection

    def initialize(
        self,
        admin_profile: dict[str, str] | None = None,
        seed_customers: list[dict[str, Any]] | None = None,
        seed_name: str = "empty",
    ) -> None:
        self._prepare_storage()
        with self.connection() as connection:
            self._lock_schema(connection)
            for statement in _schema_statements(self.dialect):
                connection.execute(text(statement))
            self._migrate_users(connection)
            settings = _scalar(connection, "SELECT value FROM app_state WHERE key = 'model_settings'")
            if settings is None:
                connection.execute(SET_STATE, {
                    "key": "model_settings",
                    "value": json.dumps(DEFAULT_MODEL_SETTINGS, ensure_ascii=False),
                })
            else:
                stored_settings = json.loads(settings)
                if stored_settings.get("version", 1) < MODEL_VERSION:
                    # Keep the custom weights and thresholds of the previous version.
                    migrated = merge_model_settings(stored_settings)
                    connection.execute(SET_STATE, {
                        "key": "model_settings",
                        "value": json.dumps(migrated, ensure_ascii=False),
                    })
            connection.execute(ADD_STATE, {"key": "source_updated_at", "value": _now()})
            connection.execute(ADD_STATE, {"key": "snapshot_id", "value": str(uuid.uuid4())})
            source_kind = _scalar(connection, "SELECT value FROM app_state WHERE key = 'source_kind'")
            if source_kind is None:
                customer_count = _scalar(connection, "SELECT COUNT(*) FROM customers")
                if customer_count == 0 and seed_customers is not None:
                    self._replace_snapshot(connection, seed_customers)
                    source_name = seed_name
                else:
                    source_name = "empty" if customer_count == 0 else "uploaded"
                connection.execute(SET_STATE, {"key": "source_kind", "value": source_name})
                connection.execute(SET_STATE, {"key": "source_updated_at", "value": _now()})
            elif source_kind == "demo":
                # Demo dates are relative to the current day. Refresh only the
                # synthetic source; an uploaded snapshot remains untouched.
                self._replace_snapshot(connection, demo_snapshot())
                connection.execute(SET_STATE, {"key": "source_updated_at", "value": _now()})
            elif source_kind == "showcase" and seed_name == "showcase" and seed_customers is not None:
                # Scenario dates are relative to the current time: rebuild them on every start.
                self._replace_snapshot(connection, seed_customers)
                connection.execute(SET_STATE, {"key": "source_updated_at", "value": _now()})
            if admin_profile is not None:
                exists = _scalar(
                    connection,
                    "SELECT 1 FROM users WHERE username = :username",
                    {"username": admin_profile["username"]},
                )
                if exists is None:
                    connection.execute(
                        text(
                            """
                            INSERT INTO users (
                                username, first_name, last_name, password_hash,
                                codeword_hash, role, created_at
                            ) VALUES (
                                :username, :first_name, :last_name, :password_hash,
                                :codeword_hash, 'analyst', :created_at
                            )
                            """
                        ),
                        {**admin_profile, "created_at": _now()},
                    )

    def _prepare_storage(self) -> None:
        if self.dialect == "sqlite":
            database = self.engine.url.database
            if database and database != ":memory:":
                Path(database).parent.mkdir(parents=True, exist_ok=True)

    def _lock_schema(self, connection: Connection) -> None:
        if self.dialect == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK_KEY})

    @staticmethod
    def _migrate_users(connection: Connection) -> None:
        # Databases created before the middle name existed get the column in place.
        columns = {column["name"] for column in inspect(connection).get_columns("users")}
        if "middle_name" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN middle_name TEXT"))

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            return _row(
                connection,
                """
                SELECT username, first_name, last_name, middle_name, password_hash, codeword_hash, role
                FROM users WHERE username = :username
                """,
                {"username": username},
            )

    def list_users(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return _rows(connection, "SELECT username, password_hash FROM users")

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
                text(
                    """
                    INSERT INTO users (
                        username, first_name, last_name, middle_name, password_hash,
                        codeword_hash, role, created_at
                    ) VALUES (
                        :username, :first_name, :last_name, :middle_name, :password_hash,
                        :codeword_hash, 'analyst', :created_at
                    )
                    """
                ),
                {
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "middle_name": middle_name,
                    "password_hash": password_hash,
                    "codeword_hash": codeword_hash,
                    "created_at": _now(),
                },
            )

    def set_password(self, username: str, password_hash: str) -> None:
        with self.connection() as connection:
            connection.execute(
                text("UPDATE users SET password_hash = :password_hash WHERE username = :username"),
                {"password_hash": password_hash, "username": username},
            )

    def delete_user_sessions(self, username: str, keep_token_hash: str | None = None) -> None:
        with self.connection() as connection:
            if keep_token_hash is None:
                connection.execute(text("DELETE FROM sessions WHERE username = :username"), {"username": username})
            else:
                connection.execute(
                    text("DELETE FROM sessions WHERE username = :username AND token_hash != :keep"),
                    {"username": username, "keep": keep_token_hash},
                )

    def create_password_reset(self, token_hash: str, username: str, expires_at: str) -> None:
        with self.connection() as connection:
            connection.execute(text("DELETE FROM password_resets WHERE username = :username"), {"username": username})
            connection.execute(
                text(
                    """
                    INSERT INTO password_resets(token_hash, username, expires_at, created_at)
                    VALUES (:token_hash, :username, :expires_at, :created_at)
                    """
                ),
                {"token_hash": token_hash, "username": username, "expires_at": expires_at, "created_at": _now()},
            )

    def peek_password_reset(self, token_hash: str) -> str | None:
        with self.connection() as connection:
            return _scalar(
                connection,
                "SELECT username FROM password_resets WHERE token_hash = :token_hash AND expires_at > :now",
                {"token_hash": token_hash, "now": _now()},
            )

    def consume_password_reset(self, token_hash: str) -> str | None:
        with self.connection() as connection:
            return _scalar(
                connection,
                "DELETE FROM password_resets WHERE token_hash = :token_hash AND expires_at > :now RETURNING username",
                {"token_hash": token_hash, "now": _now()},
            )

    def replace_password(self, username: str, password_hash: str, keep_token_hash: str | None = None) -> None:
        """Set the password and revoke sessions in one transaction."""
        with self.connection() as connection:
            connection.execute(
                text("UPDATE users SET password_hash = :password_hash WHERE username = :username"),
                {"password_hash": password_hash, "username": username},
            )
            if keep_token_hash is None:
                connection.execute(text("DELETE FROM sessions WHERE username = :username"), {"username": username})
            else:
                connection.execute(
                    text("DELETE FROM sessions WHERE username = :username AND token_hash != :keep"),
                    {"username": username, "keep": keep_token_hash},
                )

    def model_settings(self) -> dict[str, Any]:
        with self.connection() as connection:
            value = _scalar(connection, "SELECT value FROM app_state WHERE key = 'model_settings'")
        if value is None:
            return merge_model_settings(DEFAULT_MODEL_SETTINGS)
        return merge_model_settings(json.loads(value))

    def save_model_settings(self, settings: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(SET_STATE, {
                "key": "model_settings",
                "value": json.dumps(merge_model_settings(settings), ensure_ascii=False),
            })

    def source_info(self) -> dict[str, str]:
        with self.connection() as connection:
            rows = _rows(
                connection,
                "SELECT key, value FROM app_state WHERE key IN ('source_kind', 'source_updated_at')",
            )
        return {row["key"]: row["value"] for row in rows}

    def snapshot_meta(self) -> dict[str, str | None]:
        with self.connection() as connection:
            rows = _rows(
                connection,
                "SELECT key, value FROM app_state WHERE key IN ('source_kind', 'source_updated_at', 'snapshot_id')",
            )
        values = {row["key"]: row["value"] for row in rows}
        return {
            "snapshot_id": values.get("snapshot_id"),
            "source_kind": values.get("source_kind", "demo"),
            "source_updated_at": values.get("source_updated_at"),
        }

    def replace_snapshot(self, customers: list[dict[str, Any]]) -> dict[str, Any]:
        observed_at = _now()
        snapshot_id = str(uuid.uuid4())
        with self.connection() as connection:
            previous_kind = _scalar(connection, "SELECT value FROM app_state WHERE key = 'source_kind'")
            events: list[dict[str, Any]] = []
            # The demo source is not a real history: the first uploaded snapshot starts the journal.
            if previous_kind == "uploaded":
                events = self._transition_events(connection, customers, observed_at, snapshot_id)
            self._replace_snapshot(connection, customers)
            if events:
                connection.execute(INSERT_EVENT, events)
            connection.execute(SET_STATE, {"key": "source_kind", "value": "uploaded"})
            connection.execute(SET_STATE, {"key": "source_updated_at", "value": observed_at})
            connection.execute(SET_STATE, {"key": "snapshot_id", "value": snapshot_id})
        return {"snapshot_id": snapshot_id, "observed_at": observed_at, "events_recorded": len(events)}

    @staticmethod
    def _transition_events(
        connection: Connection,
        customers: list[dict[str, Any]],
        observed_at: str,
        snapshot_id: str,
    ) -> list[dict[str, Any]]:
        """Compare the stored services with the incoming snapshot and record facts that happened."""
        previous = {
            row["id"]: row
            for row in _rows(connection, "SELECT id, customer_id, status, expires_at, price_minor FROM services")
        }
        incoming: dict[str, dict[str, Any]] = {}
        for customer in customers:
            customer_id = str(customer["id"])
            for index, service in enumerate(customer["services"], start=1):
                service_id = str(service["id"] or f"{customer_id}-service-{index}")
                incoming[service_id] = service

        events: list[dict[str, Any]] = []
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
            events.append({
                "observed_at": observed_at,
                "snapshot_id": snapshot_id,
                "customer_id": old["customer_id"],
                "service_id": service_id,
                "event_type": event,
                "from_status": old["status"],
                "to_status": to_status,
                "price_minor": old["price_minor"],
            })
        return events

    def journal_rows(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return _rows(
                connection,
                """
                SELECT observed_at, snapshot_id, customer_id, service_id, event_type,
                       from_status, to_status, price_minor
                FROM snapshot_events ORDER BY id
                """,
            )

    def outflow_facts(self, since: str) -> dict[str, Any]:
        with self.connection() as connection:
            rows = _rows(
                connection,
                """
                SELECT substr(observed_at, 1, 10) AS day, event_type,
                       COUNT(*) AS services,
                       CAST(COALESCE(SUM(price_minor), 0) AS BIGINT) AS amount_minor
                FROM snapshot_events
                WHERE observed_at >= :since
                GROUP BY day, event_type
                ORDER BY day
                """,
                {"since": since},
            )
            snapshots = _scalar(
                connection,
                "SELECT COUNT(DISTINCT snapshot_id) FROM snapshot_events WHERE observed_at >= :since",
                {"since": since},
            )
        return {"rows": rows, "snapshots": snapshots}

    def oidc_identity(self, issuer: str, subject: str) -> str | None:
        with self.connection() as connection:
            return _scalar(
                connection,
                "SELECT username FROM oidc_identities WHERE issuer = :issuer AND subject = :subject",
                {"issuer": issuer, "subject": subject},
            )

    def link_oidc_identity(self, issuer: str, subject: str, username: str) -> None:
        with self.connection() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO oidc_identities (issuer, subject, username)
                    VALUES (:issuer, :subject, :username)
                    ON CONFLICT (issuer, subject) DO UPDATE SET username = excluded.username
                    """
                ),
                {"issuer": issuer, "subject": subject, "username": username},
            )

    def create_oidc_transaction(self, state_hash: str, nonce: str, code_verifier: str, expires_at: str) -> None:
        with self.connection() as connection:
            connection.execute(text("DELETE FROM oidc_transactions WHERE expires_at <= :now"), {"now": _now()})
            connection.execute(
                text(
                    """
                    INSERT INTO oidc_transactions(state_hash, nonce, code_verifier, expires_at)
                    VALUES (:state_hash, :nonce, :code_verifier, :expires_at)
                    """
                ),
                {"state_hash": state_hash, "nonce": nonce, "code_verifier": code_verifier, "expires_at": expires_at},
            )

    def consume_oidc_transaction(self, state_hash: str) -> dict[str, str] | None:
        with self.connection() as connection:
            return _row(
                connection,
                """
                DELETE FROM oidc_transactions
                WHERE state_hash = :state_hash AND expires_at > :now
                RETURNING nonce, code_verifier
                """,
                {"state_hash": state_hash, "now": _now()},
            )

    @staticmethod
    def _replace_snapshot(connection: Connection, customers: list[dict[str, Any]]) -> None:
        connection.execute(text("DELETE FROM transactions"))
        connection.execute(text("DELETE FROM services"))
        connection.execute(text("DELETE FROM customers"))
        customer_rows: list[dict[str, Any]] = []
        service_rows: list[dict[str, Any]] = []
        transaction_rows: list[dict[str, Any]] = []
        for customer in customers:
            customer_id = str(customer["id"])
            customer_rows.append({
                "id": customer_id,
                "email": customer["email"],
                "balance_minor": customer["balance_minor"],
                "withdraw_balance_minor": customer["withdraw_balance_minor"],
                "bonus_balance_minor": customer["bonus_balance_minor"],
                "bonus_spend_enabled": bool(customer["bonus_spend_enabled"]),
                "total_replenished_minor": customer["total_replenished_minor"],
            })
            for index, service in enumerate(customer["services"], start=1):
                service_rows.append({
                    "id": str(service["id"] or f"{customer_id}-service-{index}"),
                    "customer_id": customer_id,
                    "name": service["name"],
                    "price_minor": service["price_minor"],
                    "auto_prolong": bool(service["auto_prolong"]),
                    "payment_term": service["payment_term"],
                    "status": service["status"],
                    "expires_at": service["expires_at"],
                })
            for index, transaction in enumerate(customer["transactions"], start=1):
                transaction_rows.append({
                    "id": str(transaction["id"] or f"{customer_id}-transaction-{index}"),
                    "customer_id": customer_id,
                    "service_id": transaction["service_id"],
                    "status": transaction["status"],
                    "type": transaction["type"],
                    "amount_minor": transaction["amount_minor"],
                    "created_at": transaction["created_at"],
                })
        # Parents before children: customers, then their services and transactions.
        if customer_rows:
            connection.execute(INSERT_CUSTOMER, customer_rows)
        if service_rows:
            connection.execute(INSERT_SERVICE, service_rows)
        if transaction_rows:
            connection.execute(INSERT_TRANSACTION, transaction_rows)

    def customer_rows(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            customers = _rows(connection, "SELECT * FROM customers ORDER BY id")
            services = _rows(connection, "SELECT * FROM services ORDER BY customer_id, id")
            transactions = _rows(connection, "SELECT * FROM transactions ORDER BY customer_id, id")

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
            connection.execute(text("DELETE FROM sessions WHERE expires_at <= :now"), {"now": _now()})
            connection.execute(
                text(
                    """
                    INSERT INTO sessions(token_hash, username, expires_at, created_at)
                    VALUES (:token_hash, :username, :expires_at, :created_at)
                    """
                ),
                {"token_hash": token_hash, "username": username, "expires_at": expires_at, "created_at": _now()},
            )

    def session_username(self, token_hash: str) -> str | None:
        with self.connection() as connection:
            return _scalar(
                connection,
                "SELECT username FROM sessions WHERE token_hash = :token_hash AND expires_at > :now",
                {"token_hash": token_hash, "now": _now()},
            )

    def delete_session(self, token_hash: str) -> None:
        with self.connection() as connection:
            connection.execute(text("DELETE FROM sessions WHERE token_hash = :token_hash"), {"token_hash": token_hash})

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
            self._lock_client(connection, client_key)
            connection.execute(
                text("DELETE FROM login_attempts WHERE window_started_at <= :cutoff"),
                {"cutoff": cutoff},
            )
            row = _row(
                connection,
                "SELECT window_started_at, failures FROM login_attempts WHERE client_key = :client_key",
                {"client_key": client_key},
            )

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

            connection.execute(UPSERT_ATTEMPT, {
                "client_key": client_key,
                "window_started_at": window_started_at,
                "failures": failures,
            })
        return 0

    def _lock_client(self, connection: Connection, client_key: str) -> None:
        if self.dialect == "sqlite":
            # SQLite has no row locks: BEGIN IMMEDIATE takes the write lock before the count is read.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:client_key, 0))"),
                {"client_key": client_key},
            )

    def clear_login_attempts(self, client_key: str) -> None:
        with self.connection() as connection:
            connection.execute(text("DELETE FROM login_attempts WHERE client_key = :client_key"), {"client_key": client_key})
