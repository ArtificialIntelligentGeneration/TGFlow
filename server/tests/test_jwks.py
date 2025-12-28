from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_jwks_available():
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    data = r.json()
    assert "keys" in data and isinstance(data["keys"], list) and data["keys"]
    key = data["keys"][0]
    assert key["kty"] == "RSA" and key["alg"] == "RS256" and key["use"] == "sig"
    assert "pem" in key and key["pem"].startswith("-----BEGIN PUBLIC KEY-----")



