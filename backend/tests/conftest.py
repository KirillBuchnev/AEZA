import importlib
import os
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

ADMIN_USERNAME = "demo"
ADMIN_PASSWORD = "local-demo-change-this-password"
ADMIN_CODEWORD = "demo-codeword"


def reset_schema(url: str) -> None:
    """Drop every table of a PostgreSQL test database. Only databases whose name contains 'test' qualify."""
    engine = create_engine(url)
    try:
        if "test" not in (engine.url.database or ""):
            raise RuntimeError("AEZA_TEST_DATABASE_URL must name a database whose name contains 'test'.")
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


@pytest.fixture
def database_url(tmp_path):
    """A fresh database per test: a SQLite file, or the PostgreSQL test database from AEZA_TEST_DATABASE_URL."""
    configured = os.getenv("AEZA_TEST_DATABASE_URL", "").strip()
    if not configured:
        return f"sqlite:///{tmp_path / 'aeza.db'}"
    reset_schema(configured)
    return configured


@pytest.fixture
def open_app(tmp_path, monkeypatch, database_url):
    """Start the app against one database; open it again with the same URL to simulate a restart."""

    @contextmanager
    def opener(**overrides):
        env = {
            "AEZA_DATABASE_URL": database_url,
            "AEZA_DATABASE_PATH": str(tmp_path / "aeza.db"),
            "AEZA_ENVIRONMENT": "development",
            "AEZA_ADMIN_USERNAME": ADMIN_USERNAME,
            "AEZA_ADMIN_PASSWORD": ADMIN_PASSWORD,
            "AEZA_ADMIN_CODEWORD": ADMIN_CODEWORD,
            "AEZA_RATE_LIMIT_SECRET": "test-secret-" + "x" * 30,
        }
        env.update(overrides)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        import app.main as main

        importlib.reload(main)
        try:
            with TestClient(main.app) as client:
                yield client, main
        finally:
            main.database.dispose()

    return opener
