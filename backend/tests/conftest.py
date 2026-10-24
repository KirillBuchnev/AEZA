import importlib
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

ADMIN_USERNAME = "demo"
ADMIN_PASSWORD = "local-demo-change-this-password"
ADMIN_CODEWORD = "demo-codeword"


@pytest.fixture
def open_app(tmp_path, monkeypatch):
    """Start the app against a fresh SQLite file; reuse the same file to simulate a restart."""

    @contextmanager
    def opener(**overrides):
        env = {
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
        with TestClient(main.app) as client:
            yield client, main

    return opener
