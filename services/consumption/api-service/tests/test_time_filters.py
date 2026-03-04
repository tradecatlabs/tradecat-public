from __future__ import annotations


class _DummyCursor:
    def __init__(self):
        self.last_params: list[object] | None = None

    def execute(self, query, params):
        # 只验证参数拼接行为即可；不需要真实 DB。
        self.last_params = list(params)

    def fetchall(self):
        return []

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


def test_ohlc_end_time_zero_is_applied(client, monkeypatch):
    from src.query import market_dao

    cursor = _DummyCursor()
    monkeypatch.setattr(market_dao, "table_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(market_dao, "get_market_pool", lambda: _DummyPool(cursor))

    resp = client.get("/api/futures/ohlc/history?symbol=BTC&interval=1h&limit=10&endTime=0")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True

    assert cursor.last_params is not None
    assert 0 in cursor.last_params


def test_open_interest_end_time_zero_is_applied(client, monkeypatch):
    from src.query import market_dao

    cursor = _DummyCursor()
    monkeypatch.setattr(market_dao, "table_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(market_dao, "get_market_pool", lambda: _DummyPool(cursor))

    resp = client.get("/api/futures/open-interest/history?symbol=BTC&interval=5m&limit=10&endTime=0")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True

    assert cursor.last_params is not None
    assert 0 in cursor.last_params
