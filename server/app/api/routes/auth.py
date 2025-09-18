from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session

from ...schemas.auth import LoginRequest, LoginResponse, UserOut
from ...services.auth_service import login_user
from ...db import get_db
from ..deps import rate_limit_ip


router = APIRouter()


@router.post("/login", response_model=LoginResponse, dependencies=[Depends(rate_limit_ip)])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        token, user = login_user(db, email=payload.email, password=payload.password, device_fingerprint=payload.device_fingerprint)
        return LoginResponse(token=token, user=UserOut(id=str(user.id), email=user.email))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


