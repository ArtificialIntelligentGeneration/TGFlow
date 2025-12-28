import datetime as dt
import os
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from ..db import get_db
from ..models.user import User
from sqlalchemy.orm import Session


_bearer_scheme = HTTPBearer(auto_error=False)


def _read_key(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def create_access_token(*, user_id: str, email: str, device_fingerprint: Optional[str]) -> str:
    settings = get_settings()
    private_key = _read_key(settings.JWT_PRIVATE_KEY_PATH)
    if not private_key:
        raise RuntimeError("JWT private key is not configured")
    now = dt.datetime.utcnow()
    payload: Dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "dfp": device_fingerprint,
        "iss": settings.JWT_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp()),
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token


def decode_token(token: str) -> Dict[str, Any]:
    settings = get_settings()
    public_key = _read_key(settings.JWT_PUBLIC_KEY_PATH)
    if not public_key:
        raise RuntimeError("JWT public key is not configured")
    try:
        return jwt.decode(token, public_key, algorithms=["RS256"], options={"require": ["exp", "iat", "sub"]})
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


