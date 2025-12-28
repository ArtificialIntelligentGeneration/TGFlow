from pydantic import BaseModel, EmailStr
from typing import Optional


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    device_fingerprint: Optional[str] = None


class UserOut(BaseModel):
    id: str
    email: EmailStr


class LoginResponse(BaseModel):
    token: str
    user: UserOut



