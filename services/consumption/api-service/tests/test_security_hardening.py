from __future__ import annotations


def test_redact_dsn_scrubs_password_in_url_form():
    from src.query.datasources import redact_dsn

    dsn = "postgresql://user:secret@localhost:5432/market_data?sslmode=require"
    redacted = redact_dsn(dsn)
    assert "secret" not in redacted
    assert "sslmode" not in redacted
    assert redacted.startswith("postgresql://user@localhost:5432/market_data")


def test_redact_dsn_scrubs_password_in_hostless_url_form():
    from src.query.datasources import redact_dsn

    dsn = "postgresql://user:secret@/market_data"
    redacted = redact_dsn(dsn)
    assert "secret" not in redacted
    assert redacted.startswith("postgresql://user@/market_data")


def test_redact_dsn_scrubs_password_in_libpq_kv_form():
    from src.query.datasources import redact_dsn

    dsn = "host=127.0.0.1 user=postgres password=secret dbname=market_data"
    redacted = redact_dsn(dsn)
    assert "secret" not in redacted
    assert "password=***" in redacted


def test_redact_dsn_scrubs_quoted_password_in_libpq_kv_form():
    from src.query.datasources import redact_dsn

    dsn = "host=127.0.0.1 user=postgres password='secret with space' dbname=market_data"
    redacted = redact_dsn(dsn)
    assert "secret with space" not in redacted
    assert "password=***" in redacted


def test_cors_default_does_not_allow_arbitrary_origin(client):
    # 默认不配置 API_CORS_ALLOW_ORIGINS 时，响应不应下发 CORS allow 头。
    resp = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers.keys()}

