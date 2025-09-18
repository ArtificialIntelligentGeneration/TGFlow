import uuid
from sqlalchemy import Column, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from ..db import Base


class Plan(Base):
    __tablename__ = "plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(64), nullable=False, unique=True, index=True)
    monthly_limit = Column(Integer, nullable=False)
    price = Column(Integer, nullable=False, default=0)  # minor units
    currency = Column(String(8), nullable=False, default="RUB")



