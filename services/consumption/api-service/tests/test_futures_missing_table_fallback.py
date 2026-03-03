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

