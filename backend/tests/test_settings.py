from vocal_coach.settings import Settings, get_settings


def test_default_database_url_is_postgres():
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")


def test_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    assert get_settings().database_url == "sqlite+pysqlite:///:memory:"
