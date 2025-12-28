from pydantic import BaseModel


class PlanOut(BaseModel):
    id: str
    name: str
    price: int
    currency: str
    monthly_limit: int



