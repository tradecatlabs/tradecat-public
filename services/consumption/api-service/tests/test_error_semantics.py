from __future__ import annotations


def test_validation_error_returns_http_200(client, monkeypatch):
    monkeypatch.setenv("QUERY_SERVICE_AUTH_MODE", "required")
    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")

    resp = client.get("/api/v1/cards/atr_ranking?limit=abc", headers={"X-Internal-Token": "secret"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is False
    assert payload["code"] == "40001"


def test_unhandled_exception_returns_http_200_and_trace_id(client):
    from src.app import app
    from fastapi.testclient import TestClient

    path = "/__test__/boom"
    if not any(getattr(r, "path", "") == path for r in app.router.routes):

        @app.get(path)  # type: ignore[misc]
        def _boom():
            raise RuntimeError("boom")

    # TestClient 默认会把服务端异常 re-raise（raise_server_exceptions=True）。
    # 这里要验证“异常 → 统一错误响应”的语义，需关闭该行为。
    with TestClient(app, raise_server_exceptions=False) as unsafe_client:
        resp = unsafe_client.get(path)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is False
    assert payload["code"] == "50002"
    assert payload.get("trace_id")
