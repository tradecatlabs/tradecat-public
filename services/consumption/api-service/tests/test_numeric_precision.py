from __future__ import annotations

from datetime import datetime
from decimal import Decimal


class _DummyCursor:
    def execute(self, _query, _params):
        return None

    def fetchall(self):
        return [
            (
                "BTC",
                datetime(2026, 1, 1, 0, 0, 0),
                Decimal("123.4567890123456789"),
            )
        ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyConn:
    def __init__(self, cursor: _DummyCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyPool:
    def __init__(self, cursor: _DummyCursor):
        self._cursor = cursor

    def connection(self):
        return _DummyConn(self._cursor)


def test_open_interest_decimal_is_not_downgraded_to_float(client, monkeypatch):
    from src.query import market_dao

    cursor = _DummyCursor()
    monkeypatch.setattr(market_dao, "table_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(market_dao, "get_market_pool", lambda: _DummyPool(cursor))

    resp = client.get("/api/futures/open-interest/history?symbol=BTC&interval=5m&limit=1")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["data"][0]["open"] == "123.4567890123456789"
