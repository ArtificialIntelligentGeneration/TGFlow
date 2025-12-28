from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from ...models.plan import Plan
from ...schemas.plans import PlanOut
from ..deps import rate_limit_ip


router = APIRouter()


@router.get("/plans", response_model=list[PlanOut], dependencies=[Depends(rate_limit_ip)])
def get_plans(db: Session = Depends(get_db)):
    plans = db.query(Plan).order_by(Plan.monthly_limit.asc()).all()
    return [
        PlanOut(id=str(p.id), name=p.name, monthly_limit=p.monthly_limit, price=p.price, currency=p.currency)
        for p in plans
    ]


