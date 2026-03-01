def test_health_endpoint(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["code"] == "0"
    assert payload["success"] is True
    assert payload["data"]["status"] == "healthy"
