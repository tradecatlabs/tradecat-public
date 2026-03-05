from __future__ import annotations

from collections import OrderedDict


def test_dashboard_cache_coalesces_identical_requests(monkeypatch):
    from src.query import service as qs

    monkeypatch.setenv("QUERY_DASHBOARD_CACHE_TTL_SEC", "60")
    monkeypatch.setattr(qs, "_DASHBOARD_CACHE", OrderedDict())
    monkeypatch.setattr(qs, "_INFLIGHT_LOCKS", {})

    calls = {"n": 0}

    def _fake_build_card_payload(*, card_id: str, interval: str, symbols, limit: int):
        calls["n"] += 1
        return {"card_id": card_id, "interval": interval, "rows": []}

    monkeypatch.setattr(qs, "build_card_payload", _fake_build_card_payload)

    qs.dashboard_payload(cards=["atr_ranking"], intervals=["15m"], symbols=None, shape="wide", limit=1)
    qs.dashboard_payload(cards=["atr_ranking"], intervals=["15m"], symbols=None, shape="wide", limit=1)
    assert calls["n"] == 1


def test_dashboard_cache_is_not_mutated_by_ignored_cards(client, monkeypatch):
    from src.query import service as qs

    monkeypatch.setenv("QUERY_SERVICE_AUTH_MODE", "required")
    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")
    monkeypatch.setenv("QUERY_DASHBOARD_CACHE_TTL_SEC", "60")

    monkeypatch.setattr(qs, "_DASHBOARD_CACHE", OrderedDict())
    monkeypatch.setattr(qs, "_INFLIGHT_LOCKS", {})

    def _fake_build_card_payload(*, card_id: str, interval: str, symbols, limit: int):
        return {
            "card_id": card_id,
            "interval": interval,
            "rows": [{"symbol": "BTCUSDT", "fields": {"price": 1.0}}],
        }

    monkeypatch.setattr(qs, "build_card_payload", _fake_build_card_payload)

    resp1 = client.get("/api/v1/dashboard?cards=atr_ranking,unknown&intervals=15m&shape=wide&limit=1", headers={"X-Internal-Token": "secret"})
    assert resp1.status_code == 200
    payload1 = resp1.json()
    assert payload1["success"] is True
    assert "ignored_cards" in payload1["data"]

    resp2 = client.get("/api/v1/dashboard?cards=atr_ranking&intervals=15m&shape=wide&limit=1", headers={"X-Internal-Token": "secret"})
    assert resp2.status_code == 200
    payload2 = resp2.json()
    assert payload2["success"] is True
    assert "ignored_cards" not in payload2["data"]
