from __future__ import annotations


def test_capabilities_endpoint_contract(client, monkeypatch):
    # 避免测试环境依赖真实数据库
    from src.routers import query_v1 as qv1

    monkeypatch.setenv("QUERY_SERVICE_AUTH_MODE", "required")
    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(qv1, "check_sources", lambda: [{"id": "indicators", "ok": True, "dsn": "postgresql://x@y/db"}])

    resp = client.get("/api/v1/capabilities", headers={"X-Internal-Token": "secret"})
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["success"] is True
    data = payload["data"]
    assert "cards" in data
    assert isinstance(data["cards"], list)
    assert any(c.get("card_id") == "atr_ranking" for c in data["cards"])

def test_v1_requires_token_by_default(client, monkeypatch):
    from src.routers import query_v1 as qv1

    monkeypatch.setenv("QUERY_SERVICE_AUTH_MODE", "required")
    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(qv1, "check_sources", lambda: [])

    resp = client.get("/api/v1/capabilities")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is False
    assert payload["msg"] == "unauthorized"


def test_card_endpoint_does_not_leak_table_names(client, monkeypatch):
    from src.routers import query_v1 as qv1

    monkeypatch.setenv("QUERY_SERVICE_AUTH_MODE", "required")
    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")

    def _fake_build_card_payload(*, card_id: str, interval: str, symbols, limit: int):
        return {
            "card_id": card_id,
            "interval": interval,
            "rows": [
                {
                    "symbol": "BTCUSDT",
                    "base_symbol": "BTC",
                    "rank": 1,
                    "fields": {"price": 1.0, "quote_volume": 2.0, "updated_at": "2026-01-01T00:00:00Z"},
                }
            ],
        }

    monkeypatch.setattr(qv1, "build_card_payload", _fake_build_card_payload)

    resp = client.get("/api/v1/cards/atr_ranking?interval=15m&limit=5", headers={"X-Internal-Token": "secret"})
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["success"] is True
    raw = resp.text
    assert ".py" not in raw
    assert "tg_cards" not in raw
    assert "market_data" not in raw
    assert "交易对" not in raw
    assert "周期" not in raw


def test_dashboard_supports_cards_and_intervals(client, monkeypatch):
    from src.routers import query_v1 as qv1

    monkeypatch.setenv("QUERY_SERVICE_AUTH_MODE", "required")
    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")

    monkeypatch.setattr(
        qv1.query_service,
        "dashboard_payload",
        lambda **kwargs: {"rows": {"BTCUSDT": {"15m": {"symbol": "BTCUSDT", "fields": {"price": 1}}}}},
    )

    resp = client.get(
        "/api/v1/dashboard?cards=atr_ranking&intervals=15m&shape=wide",
        headers={"X-Internal-Token": "secret"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert "rows" in payload["data"]


def test_dashboard_rejects_too_many_items(client, monkeypatch):
    from src.routers import query_v1 as qv1

    monkeypatch.setenv("QUERY_SERVICE_AUTH_MODE", "required")
    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")

    def _should_not_be_called(**kwargs):
        raise AssertionError("dashboard_payload should not be called when parameters exceed limits")

    monkeypatch.setattr(qv1.query_service, "dashboard_payload", _should_not_be_called)

    too_many_cards = ",".join([f"c{i}" for i in range(21)])
    resp = client.get(
        f"/api/v1/dashboard?cards={too_many_cards}&intervals=15m&shape=wide",
        headers={"X-Internal-Token": "secret"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is False
    assert payload["msg"] == "too_many_items"


def test_snapshot_rejects_too_many_items(client, monkeypatch):
    from src.routers import query_v1 as qv1

    monkeypatch.setenv("QUERY_SERVICE_AUTH_MODE", "required")
    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")

    def _should_not_be_called(**kwargs):
        raise AssertionError("symbol_snapshot_payload should not be called when parameters exceed limits")

    monkeypatch.setattr(qv1.query_service, "symbol_snapshot_payload", _should_not_be_called)

    too_many_intervals = "5m,15m,1h,4h,1d,1w,2w,1M"
    resp = client.get(
        f"/api/v1/symbol/BTCUSDT/snapshot?intervals={too_many_intervals}",
        headers={"X-Internal-Token": "secret"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is False
    assert payload["msg"] == "too_many_items"
