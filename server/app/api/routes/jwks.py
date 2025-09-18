import json
import uuid
import base64
import hashlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter

from ...core.config import get_settings


router = APIRouter()


def _load_public_key_pem() -> str:
    path = get_settings().JWT_PUBLIC_KEY_PATH
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_public_key_rsa() -> rsa.RSAPublicKey:
    """Load RSA public key for JWK format"""
    pem_data = _load_public_key_pem()
    return serialization.load_pem_public_key(pem_data.encode())


def _generate_stable_kid(public_key: rsa.RSAPublicKey) -> str:
    """Generate stable kid based on public key modulus"""
    # Use SHA256 of the modulus as kid for stability
    modulus = public_key.public_numbers().n
    modulus_bytes = modulus.to_bytes((modulus.bit_length() + 7) // 8, 'big')
    kid = hashlib.sha256(modulus_bytes).hexdigest()[:16]  # First 16 chars for readability
    return kid


def _rsa_to_jwk(public_key: rsa.RSAPublicKey) -> dict:
    """Convert RSA public key to JWK format with n and e parameters"""
    public_numbers = public_key.public_numbers()

    # Convert modulus (n) to base64url
    n_bytes = public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, 'big')
    n_b64 = base64.urlsafe_b64encode(n_bytes).decode('utf-8').rstrip('=')

    # Convert exponent (e) to base64url
    e_bytes = public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, 'big')
    e_b64 = base64.urlsafe_b64encode(e_bytes).decode('utf-8').rstrip('=')

    kid = _generate_stable_kid(public_key)

    return {
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "kid": kid,
        "n": n_b64,
        "e": e_b64,
    }


@router.get("/.well-known/jwks.json")
def jwks():
    settings = get_settings()

    if settings.ENV == "dev":
        # For dev environment, return PEM format for easier debugging
        pem = _load_public_key_pem()
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "alg": "RS256",
                    "use": "sig",
                    "kid": "dev-key",
                    "pem": pem,
                }
            ]
        }
    else:
        # For stage/prod, return JWK format with n/e parameters
        public_key = _load_public_key_rsa()
        jwk = _rsa_to_jwk(public_key)
        return {
            "keys": [jwk]
        }



