from datetime import datetime, timedelta, timezone

import pytest

from app.database import Database
from app.migration import migrate_sqlite
from app.risk import demo_snapshot


FUTURE = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def admin_profile() -> dict[str, str]:
    return {
        "username": "demo",
        "first_name": "Демо",
        "last_name": "Аналитик",
        "password_hash": "scrypt$source",
        "codeword_hash": "scrypt$source",
    }


def test_migration_refuses_a_sqlite_target(tmp_path):
    source_path = tmp_path / "source.db"
    Database(f"sqlite:///{source_path}").initialize(admin_profile=admin_profile())
    with pytest.raises(ValueError):
        migrate_sqlite(str(source_path), f"sqlite:///{tmp_path / 'target.db'}")


def test_sqlite_data_and_journal_reach_postgres(database_url, tmp_path):
    if database_url.startswith("sqlite"):
        pytest.skip("Set AEZA_TEST_DATABASE_URL to a PostgreSQL test database to run the migration test.")

    source_path = tmp_path / "source.db"
    source = Database(f"sqlite:///{source_path}")
    source.initialize(admin_profile=admin_profile(), seed_customers=demo_snapshot(), seed_name="demo")
    source.replace_snapshot(demo_snapshot())  # the first upload starts the journal
    changed = demo_snapshot()
    changed[0]["services"][0]["status"] = "prolong_wait"
    source.replace_snapshot(changed)  # one service enters waiting for payment
    source.create_session("session-hash", "demo", FUTURE)
    source.begin_login_attempt("client-key")
    source.dispose()

    target = Database(database_url)
    target.initialize()
    target.create_user("demo", "Старое", "Имя", "scrypt$old", "scrypt$old")  # created by the app first
    target.dispose()

    counts = migrate_sqlite(str(source_path), database_url)

    source = Database(f"sqlite:///{source_path}")
    target = Database(database_url)
    try:
        assert target.customer_rows() == source.customer_rows()
        assert target.journal_rows() == source.journal_rows()
        assert [row["event_type"] for row in target.journal_rows()] == ["entered_wait"]
        assert target.snapshot_meta() == source.snapshot_meta()
        assert target.model_settings() == source.model_settings()
        assert target.get_user("demo")["password_hash"] == "scrypt$source"
        assert target.session_username("session-hash") == "demo"
        assert counts["snapshot_events"] == 1

        # The copied journal ids are explicit: the next recorded event must not collide with them.
        renewed = demo_snapshot()
        renewed[0]["services"][0]["status"] = "active"
        target.replace_snapshot(renewed)
        assert [row["event_type"] for row in target.journal_rows()] == ["entered_wait", "renewed"]
    finally:
        source.dispose()
        target.dispose()
