"""Копирует файл SQLite из AEZA в PostgreSQL — однократно, после переключения рантайма на PostgreSQL.

    docker compose exec api python -m app.migration /data/aeza.db

Цель — AEZA_DATABASE_URL, если не задан --target. Снапшот источника заменяет снапшот цели;
аккаунты, сессии, троттлинг входа и журнал сливаются по первичному ключу, поэтому повторный
запуск команды не дублирует строки. Источник открывается только на чтение.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from sqlalchemy import text

from .config import normalize_database_url
from .database import Database


# Сначала родители: услуги и транзакции ссылаются на клиентов, OIDC-идентичности — на пользователей.
TABLES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("app_state", ("key",), ("key", "value")),
    ("users", ("username",), (
        "username", "first_name", "last_name", "middle_name", "password_hash",
        "codeword_hash", "role", "created_at",
    )),
    ("customers", ("id",), (
        "id", "email", "balance_minor", "withdraw_balance_minor", "bonus_balance_minor",
        "bonus_spend_enabled", "total_replenished_minor",
    )),
    ("services", ("id",), (
        "id", "customer_id", "name", "price_minor", "auto_prolong", "payment_term", "status", "expires_at",
    )),
    ("transactions", ("id",), (
        "id", "customer_id", "service_id", "status", "type", "amount_minor", "created_at",
    )),
    ("sessions", ("token_hash",), ("token_hash", "username", "expires_at", "created_at")),
    ("login_attempts", ("client_key",), ("client_key", "window_started_at", "failures")),
    ("password_resets", ("token_hash",), ("token_hash", "username", "expires_at", "created_at")),
    ("snapshot_events", ("id",), (
        "id", "observed_at", "snapshot_id", "customer_id", "service_id", "event_type",
        "from_status", "to_status", "price_minor",
    )),
    ("oidc_identities", ("issuer", "subject"), ("issuer", "subject", "username")),
    ("oidc_transactions", ("state_hash",), ("state_hash", "nonce", "code_verifier", "expires_at")),
)
SNAPSHOT_TABLES = ("transactions", "services", "customers")
# SQLite хранит флаги как 0 и 1; в PostgreSQL для них есть колонки BOOLEAN.
BOOLEAN_COLUMNS = {("customers", "bonus_spend_enabled"), ("services", "auto_prolong")}


def migrate_sqlite(source_path: str, target_url: str) -> dict[str, int]:
    """Копирует все таблицы AEZA из файла SQLite в PostgreSQL и возвращает количество строк."""
    target_url = normalize_database_url(target_url)
    if not target_url.startswith("postgresql+psycopg://"):
        raise ValueError("The migration target must be a PostgreSQL URL.")
    source_uri = f"{Path(source_path).resolve().as_uri()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    source.row_factory = sqlite3.Row
    target = Database(target_url)
    try:
        target.initialize()
        counts: dict[str, int] = {}
        with target.connection() as connection:
            for table in SNAPSHOT_TABLES:
                connection.execute(text(f"DELETE FROM {table}"))
            for table, primary_key, columns in TABLES:
                selected, rows = _read(source, table, columns)
                counts[table] = _write(connection, table, primary_key, selected, rows)
            # Скопированные id журнала заданы явно, поэтому последовательность PostgreSQL должна продолжиться после них.
            connection.execute(text(
                "SELECT setval(pg_get_serial_sequence('snapshot_events', 'id'), "
                "COALESCE((SELECT MAX(id) FROM snapshot_events), 1), "
                "(SELECT MAX(id) FROM snapshot_events) IS NOT NULL)"
            ))
        return counts
    finally:
        source.close()
        target.dispose()


def _read(
    source: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    # В старых файлах колонки может не быть (users.middle_name): копируем что есть, остальное оставляем NULL.
    available = {row["name"] for row in source.execute(f"PRAGMA table_info({table})")}
    selected = tuple(column for column in columns if column in available)
    if not selected:
        return selected, []
    rows = [dict(row) for row in source.execute(f"SELECT {', '.join(selected)} FROM {table}")]
    return selected, rows


def _write(
    connection: Any,
    table: str,
    primary_key: tuple[str, ...],
    columns: tuple[str, ...],
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    for row in rows:
        for column in columns:
            if (table, column) in BOOLEAN_COLUMNS and row[column] is not None:
                row[column] = bool(row[column])
    updates = [column for column in columns if column not in primary_key]
    action = (
        "DO UPDATE SET " + ", ".join(f"{column} = excluded.{column}" for column in updates)
        if updates
        else "DO NOTHING"
    )
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(f':{column}' for column in columns)}) "
        f"ON CONFLICT ({', '.join(primary_key)}) {action}"
    )
    connection.execute(text(sql), rows)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy an AEZA SQLite file into PostgreSQL.")
    parser.add_argument("source", help="SQLite file, for example /data/aeza.db")
    parser.add_argument(
        "--target",
        default=os.getenv("AEZA_DATABASE_URL", ""),
        help="PostgreSQL URL; defaults to AEZA_DATABASE_URL",
    )
    args = parser.parse_args(argv)
    if not Path(args.source).is_file():
        parser.error(f"{args.source} is not a file")
    try:
        counts = migrate_sqlite(args.source, args.target)
    except ValueError as error:
        parser.error(str(error))
    for table, count in counts.items():
        print(f"{table}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
