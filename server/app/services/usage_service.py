import asyncio
import datetime as dt
import logging
import uuid
from typing import Optional, Tuple

from sqlalchemy import Select, and_, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.plan import Plan
from ..models.reservation import Reservation
from ..models.subscription import Subscription
from ..models.usage import Usage


def _current_month_key(now: Optional[dt.datetime] = None) -> str:
    now = now or dt.datetime.utcnow()
    return now.strftime("%Y-%m")


def _month_reset_at(now: Optional[dt.datetime] = None) -> dt.datetime:
    now = now or dt.datetime.utcnow()
    return dt.datetime(year=now.year, month=now.month, day=1, tzinfo=dt.timezone.utc)


def _get_user_plan_and_limit(db: Session, user_id: uuid.UUID) -> Tuple[str, int]:
    sub: Subscription | None = (
        db.query(Subscription).filter(Subscription.user_id == user_id, Subscription.status == "active").first()
    )
    if not sub:
        # Fallback to Free plan by name
        plan: Plan | None = db.query(Plan).filter(Plan.name == "Free").first()
    else:
        plan = db.query(Plan).get(sub.plan_id)
    if not plan:
        # default free 50
        return "Free", 50
    return plan.name, plan.monthly_limit


def get_usage_snapshot(db: Session, user_id: uuid.UUID) -> tuple[int, int, dt.datetime, str]:
    month_key = _current_month_key()
    usage: Usage | None = db.query(Usage).filter(Usage.user_id == user_id, Usage.month_key == month_key).first()
    used = usage.used if usage else 0
    plan_name, monthly_limit = _get_user_plan_and_limit(db, user_id)
    remaining = max(0, monthly_limit - used)
    reset_at = _month_reset_at()
    return used, remaining, reset_at, plan_name


def reserve_messages(db: Session, *, user_id: uuid.UUID, messages: int, correlation_id: uuid.UUID) -> tuple[uuid.UUID, int, int]:
    settings = get_settings()
    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    month_key = _current_month_key(now)

    try:
        with db.begin():
            # Lock/create usage row for current month
            usage: Usage | None = (
                db.query(Usage).filter(Usage.user_id == user_id, Usage.month_key == month_key).with_for_update().first()
            )
            if not usage:
                usage = Usage(user_id=user_id, month_key=month_key, used=0)
                db.add(usage)
                db.flush()

            # Compute active holds
            active_holds: int = (
                db.query(func.coalesce(func.sum(Reservation.messages), 0))
                .filter(
                    Reservation.user_id == user_id,
                    Reservation.committed.is_(False),
                    Reservation.rolled_back.is_(False),
                    Reservation.expires_at > now,
                )
                .scalar()
            )

            # Get plan limit
            _, monthly_limit_name = None, None
            plan_name, monthly_limit = _get_user_plan_and_limit(db, user_id)

            # Enforce quota including holds
            if usage.used + active_holds + messages > monthly_limit:
                raise PermissionError("quota_exceeded")

            # Create reservation with TTL
            expires_at = now + dt.timedelta(minutes=settings.RESERVATION_TTL_MINUTES)
            reservation = Reservation(
                user_id=user_id, messages=messages, correlation_id=correlation_id, expires_at=expires_at
            )
            db.add(reservation)
            db.flush()

        # Transaction committed
        _, remaining, _, _ = get_usage_snapshot(db, user_id)
        return reservation.id, messages, remaining
    except IntegrityError as e:
        # Idempotency conflict (unique user_id+correlation_id)
        db.rollback()
        raise FileExistsError("idempotency_conflict") from e


def commit_reservation(db: Session, *, reservation_id: uuid.UUID, used: int) -> None:
    reservation: Reservation | None = db.get(Reservation, reservation_id)
    if not reservation:
        raise LookupError("reservation_not_found")
    if reservation.committed or reservation.rolled_back:
        raise FileExistsError("already_closed")
    if used < 0 or used > reservation.messages:
        raise ValueError("invalid_used")
    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if reservation.expires_at < now:
        raise TimeoutError("reservation_expired")

    # Update usage atomically
    month_key = _current_month_key(now)
    usage: Usage | None = db.query(Usage).filter(Usage.user_id == reservation.user_id, Usage.month_key == month_key).first()
    if not usage:
        usage = Usage(user_id=reservation.user_id, month_key=month_key, used=0)
        db.add(usage)
        db.flush()
    # Check limit at commit time
    _, remaining, _, _ = get_usage_snapshot(db, reservation.user_id)
    if used > remaining:
        raise PermissionError("quota_exceeded")

    usage.used = usage.used + used
    reservation.committed = True
    reservation.committed_at = now
    reservation.closed_at = now
    db.add_all([usage, reservation])
    db.commit()


def rollback_reservation(db: Session, *, reservation_id: uuid.UUID) -> None:
    reservation: Reservation | None = db.get(Reservation, reservation_id)
    if not reservation:
        raise LookupError("reservation_not_found")
    if reservation.committed or reservation.rolled_back:
        raise FileExistsError("already_closed")
    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    reservation.rolled_back = True
    reservation.closed_at = now
    db.add(reservation)
    db.commit()


async def cleanup_expired_reservations() -> None:
    from ..db import SessionLocal

    settings = get_settings()
    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    with SessionLocal() as db:
        # Find expired and not closed
        expired = (
            db.query(Reservation)
            .filter(Reservation.expires_at < now, Reservation.committed.is_(False), Reservation.rolled_back.is_(False))
            .all()
        )
        count = 0
        for r in expired:
            r.rolled_back = True
            r.closed_at = now
            db.add(r)
            count += 1
        if count:
            db.commit()
            logging.info("Cleanup closed %s reservations", count)


