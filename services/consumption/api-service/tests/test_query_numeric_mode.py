from __future__ import annotations

from decimal import Decimal


def test_numeric_mode_default_is_float(monkeypatch):
    from src.query.dao import normalize_numeric_value

    monkeypatch.delenv("QUERY_NUMERIC_MODE", raising=False)
    out = normalize_numeric_value(Decimal("123.4567890123456789"))
    assert isinstance(out, float)


def test_numeric_mode_string_preserves_decimal(monkeypatch):
    from src.query.dao import normalize_numeric_value

    monkeypatch.setenv("QUERY_NUMERIC_MODE", "string")
    assert normalize_numeric_value(Decimal("0E-8")) == "0"
    assert normalize_numeric_value(Decimal("123.4567890123456789")) == "123.4567890123456789"
