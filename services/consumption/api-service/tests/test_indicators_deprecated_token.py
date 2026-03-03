from __future__ import annotations

from src.utils.errors import ErrorCode


def test_indicators_requires_token_and_is_deprecated(client, monkeypatch):
    from src.routers import query_v1 as qv1

    monkeypatch.setenv("QUERY_SERVICE_TOKEN", "secret")
    monkeypatch.setattr(qv1, "fetch_indicator_rows", lambda **kwargs: ([], None))

    resp = client.get("/api/v1/indicators/基础数据同步器.py?interval=15m&mode=raw&limit=1")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is False
    assert payload["code"] == ErrorCode.PARAM_ERROR.value

    resp2 = client.get(
        "/api/v1/indicators/基础数据同步器.py?interval=15m&mode=raw&limit=1",
        headers={"X-Internal-Token": "secret"},
    )
    assert resp2.status_code == 200
    payload2 = resp2.json()
    assert payload2["success"] is True
    assert payload2["data"]["deprecated"] is True
    assert "deprecated_hint" in payload2["data"]

