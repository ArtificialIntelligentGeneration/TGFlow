import uuid
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from ..db import Base


class Usage(Base):
    __tablename__ = "usages"
    __table_args__ = (
        UniqueConstraint("user_id", "month_key", name="uq_usage_user_month"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    month_key = Column(String(7), nullable=False, index=True)  # YYYY-MM
    used = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())



