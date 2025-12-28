import datetime as dt
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.security import get_current_user
from ...db import get_db
from ...models.user import User
from ...schemas.license import DeviceBinding, LicenseOut, Quota
from ...services.usage_service import get_usage_snapshot
from ..deps import rate_limit_ip, rate_limit_token


router = APIRouter()


@router.get("/license", response_model=LicenseOut, dependencies=[Depends(rate_limit_ip), Depends(rate_limit_token)])
def get_license(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    used, remaining, reset_at, plan_name = get_usage_snapshot(db, user.id)
    quota = Quota(monthly_limit=used + remaining, used=used, remaining=remaining, reset_at=reset_at)
    device = DeviceBinding(device_fingerprint=user.device_fingerprint)
    return LicenseOut(plan=plan_name, status="active", quota=quota, device_binding=device)


