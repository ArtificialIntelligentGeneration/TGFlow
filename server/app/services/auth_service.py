from typing import Optional

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from ..core.security import create_access_token
from ..models.user import User


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def login_user(db: Session, *, email: str, password: str, device_fingerprint: Optional[str]) -> tuple[str, User]:
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise ValueError("Invalid credentials")
    token = create_access_token(user_id=str(user.id), email=user.email, device_fingerprint=device_fingerprint)
    if device_fingerprint:
        user.device_fingerprint = device_fingerprint
        db.add(user)
        db.commit()
    return token, user



