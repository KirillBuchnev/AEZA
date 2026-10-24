import pytest

from app.config import normalize_database_url


def test_common_postgres_spellings_use_the_psycopg_driver():
    assert normalize_database_url("postgresql://u:p@db:5432/aeza") == "postgresql+psycopg://u:p@db:5432/aeza"
    assert normalize_database_url("postgres://u:p@db/aeza") == "postgresql+psycopg://u:p@db/aeza"
    assert normalize_database_url("postgresql+psycopg://u:p@db/aeza") == "postgresql+psycopg://u:p@db/aeza"


def test_sqlite_file_urls_are_accepted_and_other_drivers_refused():
    assert normalize_database_url("sqlite:////data/aeza.db") == "sqlite:////data/aeza.db"
    with pytest.raises(ValueError):
        normalize_database_url("mysql://u:p@db/aeza")
