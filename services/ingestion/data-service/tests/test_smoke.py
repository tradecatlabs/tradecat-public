import pytest


def test_normalize_interval_accepts_known_values():
    from src.config import normalize_interval

    assert normalize_interval("1m") == "1m"
    assert normalize_interval("5m") == "5m"
    assert normalize_interval("1h") == "1h"
    assert normalize_interval("1d") == "1d"
    assert normalize_interval("1w") == "1w"
    assert normalize_interval("1M") == "1M"


def test_normalize_interval_rejects_unknown_values():
    from src.config import normalize_interval

    with pytest.raises(ValueError):
        normalize_interval("bad")


def test_settings_database_url_from_env(monkeypatch):
    from src.config import Settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5433/market_data")
    s = Settings()
    assert s.database_url.startswith("postgresql://")

