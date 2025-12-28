import uuid
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _token() -> str:
    r = client.post("/auth/login", json={"email": "test@example.com", "password": "password123"})
    assert r.status_code == 200
    return r.json()["token"]


def test_commit_twice_conflict():
    token = _token()
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/usage/reserve", json={"messages": 1, "correlation_id": str(uuid.uuid4())}, headers=headers)
    assert r.status_code == 200
    rid = r.json()["reservation_id"]
    r1 = client.post("/usage/commit", json={"reservation_id": rid, "used": 1}, headers=headers)
    assert r1.status_code == 200
    r2 = client.post("/usage/commit", json={"reservation_id": rid, "used": 1}, headers=headers)
    assert r2.status_code == 409


def test_reserve_quota_exceeded():
    token = _token()
    headers = {"Authorization": f"Bearer {token}"}
    # Intentionally overshoot free quota
    r = client.post("/usage/reserve", json={"messages": 1000000, "correlation_id": str(uuid.uuid4())}, headers=headers)
    assert r.status_code == 402


