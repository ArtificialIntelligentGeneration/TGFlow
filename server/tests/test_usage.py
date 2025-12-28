import uuid
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def login_token() -> str:
    r = client.post("/auth/login", json={"email": "test@example.com", "password": "password123", "device_fingerprint": "dev-1"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_reserve_commit_flow():
    token = login_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Reserve
    corr = str(uuid.uuid4())
    r = client.post("/usage/reserve", json={"messages": 3, "correlation_id": corr}, headers=headers)
    assert r.status_code == 200, r.text
    res = r.json()
    reservation_id = res["reservation_id"]

    # Commit
    r2 = client.post("/usage/commit", json={"reservation_id": reservation_id, "used": 2}, headers=headers)
    assert r2.status_code == 200, r2.text


def test_reserve_rollback_flow():
    token = login_token()
    headers = {"Authorization": f"Bearer {token}"}

    corr = str(uuid.uuid4())
    r = client.post("/usage/reserve", json={"messages": 2, "correlation_id": corr}, headers=headers)
    assert r.status_code == 200, r.text
    reservation_id = r.json()["reservation_id"]

    r2 = client.post("/usage/rollback", json={"reservation_id": reservation_id}, headers=headers)
    assert r2.status_code == 200, r2.text


def test_idempotency_conflict():
    token = login_token()
    headers = {"Authorization": f"Bearer {token}"}

    corr = str(uuid.uuid4())
    r1 = client.post("/usage/reserve", json={"messages": 1, "correlation_id": corr}, headers=headers)
    assert r1.status_code == 200
    r2 = client.post("/usage/reserve", json={"messages": 1, "correlation_id": corr}, headers=headers)
    assert r2.status_code == 409



