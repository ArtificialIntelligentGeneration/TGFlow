from datetime import datetime
from pydantic import BaseModel


class Quota(BaseModel):
    monthly_limit: int
    used: int
    remaining: int
    reset_at: datetime


class DeviceBinding(BaseModel):
    device_fingerprint: str | None


class LicenseOut(BaseModel):
    plan: str
    status: str
    quota: Quota
    device_binding: DeviceBinding



