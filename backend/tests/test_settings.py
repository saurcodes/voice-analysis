from vocal_coach.settings import Settings, get_settings


def test_default_database_url_is_postgres(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")


def test_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    assert get_settings().database_url == "sqlite+pysqlite:///:memory:"


def test_new_settings_defaults_and_derived(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(_env_file=None)
    assert s.keycloak_issuer == "http://localhost:8080/realms/vocal-coach"
    assert s.keycloak_audience == "vocal-coach-web"
    assert s.jwks_url == "http://localhost:8080/realms/vocal-coach/protocol/openid-connect/certs"
    assert s.job_workers == 1 and s.max_upload_mb == 500 and s.require_ffmpeg is True
    assert s.max_upload_bytes == 500 * 1024 * 1024
    assert str(s.data_dir) == "data"


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_ISSUER", "https://kc.example/realms/x")
    monkeypatch.setenv("JOB_WORKERS", "3")
    monkeypatch.setenv("DATA_DIR", "/srv/data")
    s = get_settings()
    assert s.jwks_url == "https://kc.example/realms/x/protocol/openid-connect/certs"
    assert s.job_workers == 3 and str(s.data_dir) == "/srv/data"
    monkeypatch.setenv("KEYCLOAK_JWKS_URL_OVERRIDE", "http://keycloak:8080/realms/x/protocol/openid-connect/certs")
    assert get_settings().jwks_url == "http://keycloak:8080/realms/x/protocol/openid-connect/certs"
