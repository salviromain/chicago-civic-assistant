from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_query_requires_api_key():
    r = client.post("/query", json={"question": "How many potholes in Ward 1?"})
    assert r.status_code == 401


def test_query_validates_input():
    r = client.post("/query", json={"question": "x"}, headers={"X-API-Key": "change-me"})
    assert r.status_code == 422
