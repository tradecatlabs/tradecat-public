from __future__ import annotations

from src.utils.errors import ErrorCode


def test_futures_metrics_missing_table_returns_table_not_found(client, monkeypatch):
    from src.routers import futures_metrics as fm

    # 避免测试环境依赖真实数据库
    monkeypatch.setattr(fm.market_dao, "table_exists", lambda schema, table: False)

    resp = client.get("/api/futures/metrics?symbol=BTC&interval=15m&limit=1")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["success"] is False
    assert payload["code"] == ErrorCode.TABLE_NOT_FOUND.value
    assert "表不存在" in payload["msg"]
    assert payload["missing_table"] == {"schema": "market_data", "table": "binance_futures_metrics_15m_last"}


def test_open_interest_missing_table_returns_table_not_found(client, monkeypatch):
    from src.routers import open_interest as oi

    monkeypatch.setattr(oi.market_dao, "table_exists", lambda schema, table: False)

    resp = client.get("/api/futures/open-interest/history?symbol=BTC&interval=15m&limit=1")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["success"] is False
    assert payload["code"] == ErrorCode.TABLE_NOT_FOUND.value
    assert "表不存在" in payload["msg"]
    assert payload["missing_table"] == {"schema": "market_data", "table": "binance_futures_metrics_15m_last"}


def test_funding_rate_missing_table_returns_table_not_found(client, monkeypatch):
    resp = client.get("/api/futures/funding-rate/history?symbol=BTC&interval=15m&limit=1")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["success"] is False
    assert payload["code"] == ErrorCode.TABLE_NOT_FOUND.value
    assert payload["msg"] == "funding_rate_not_supported"


def test_ohlc_missing_table_returns_table_not_found(client, monkeypatch):
    from src.routers import ohlc as ohlc_router

    monkeypatch.setattr(ohlc_router.market_dao, "table_exists", lambda schema, table: False)

    resp = client.get("/api/futures/ohlc/history?symbol=BTC&interval=6h&limit=1")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["success"] is False
    assert payload["code"] == ErrorCode.TABLE_NOT_FOUND.value
    assert "表不存在" in payload["msg"]
    assert payload["missing_table"] == {"schema": "market_data", "table": "candles_6h"}
