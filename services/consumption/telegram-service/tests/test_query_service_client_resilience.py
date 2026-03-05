from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_data_provider_module():
    path = Path(__file__).resolve().parents[1] / "src" / "cards" / "data_provider.py"
    spec = importlib.util.spec_from_file_location("_data_provider", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_query_service_client_stale_if_error(monkeypatch):
    import httpx

    QueryServiceClient = _load_data_provider_module().QueryServiceClient

    monkeypatch.setenv("QUERY_SERVICE_BASE_URL", "http://example.invalid")
    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")
    monkeypatch.setenv("QUERY_SERVICE_CACHE_TTL_SECONDS", "0")  # 立即过期，强制走 stale 分支
    monkeypatch.setenv("QUERY_SERVICE_STALE_TTL_SECONDS", "60")
    monkeypatch.setenv("QUERY_SERVICE_NET_MAX_RETRIES", "0")
    monkeypatch.setenv("QUERY_SERVICE_NET_RETRY_BASE_SECONDS", "0")

    client = QueryServiceClient()

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "data": {"ok": 1}}

    calls = {"n": 0}

    def _fake_get(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp()
        raise httpx.TimeoutException("timeout")

    client._client.get = _fake_get  # type: ignore[method-assign]

    v1 = client.get_card(card_id="atr_ranking", interval="15m", limit=1)
    v2 = client.get_card(card_id="atr_ranking", interval="15m", limit=1)
    assert v1 == v2 == {"ok": 1}


def test_query_service_client_retries_then_succeeds(monkeypatch):
    import httpx

    QueryServiceClient = _load_data_provider_module().QueryServiceClient

    monkeypatch.setenv("QUERY_SERVICE_BASE_URL", "http://example.invalid")
    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")
    monkeypatch.setenv("QUERY_SERVICE_CACHE_TTL_SECONDS", "0")
    monkeypatch.setenv("QUERY_SERVICE_STALE_TTL_SECONDS", "0")
    monkeypatch.setenv("QUERY_SERVICE_NET_MAX_RETRIES", "2")
    monkeypatch.setenv("QUERY_SERVICE_NET_RETRY_BASE_SECONDS", "0")  # 测试中避免 sleep

    client = QueryServiceClient()

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "data": {"ok": 1}}

    calls = {"n": 0}

    def _fake_get(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.TimeoutException("timeout")
        return _Resp()

    client._client.get = _fake_get  # type: ignore[method-assign]

    out = client.get_card(card_id="atr_ranking", interval="15m", limit=1)
    assert out == {"ok": 1}
    assert calls["n"] == 2
