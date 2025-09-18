import uuid as uuidlib
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.security import get_current_user
from ...db import get_db
from ...models.user import User
from ...schemas.usage import CommitRequest, ReserveRequest, ReserveResponse, RollbackRequest
from ...services.usage_service import commit_reservation, reserve_messages, rollback_reservation
from ..deps import rate_limit_ip, rate_limit_token
from ...metrics import USAGE_RESERVE_TOTAL, USAGE_COMMIT_TOTAL, USAGE_ROLLBACK_TOTAL


router = APIRouter()


@router.post("/reserve", response_model=ReserveResponse, dependencies=[Depends(rate_limit_ip), Depends(rate_limit_token)])
def reserve(payload: ReserveRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        reservation_id, reserved, remaining = reserve_messages(
            db,
            user_id=user.id,
            messages=payload.messages,
            correlation_id=uuidlib.UUID(payload.correlation_id),
        )
        logging.info(
            "reserve_success",
            extra={
                "event": "reserve",
                "status": "success",
                "user_id": str(user.id),
                "reservation_id": str(reservation_id),
                "messages": payload.messages,
                "correlation_id": payload.correlation_id,
            },
        )
        USAGE_RESERVE_TOTAL.labels("success", "").inc()
        return ReserveResponse(reservation_id=str(reservation_id), reserved=reserved, remaining=remaining)
    except PermissionError:
        logging.warning(
            "reserve_failure",
            extra={
                "event": "reserve",
                "status": "failure",
                "reason": "quota_exceeded",
                "user_id": str(user.id),
                "messages": payload.messages,
                "correlation_id": payload.correlation_id,
            },
        )
        USAGE_RESERVE_TOTAL.labels("failure", "quota_exceeded").inc()
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient quota")
    except FileExistsError:
        logging.warning(
            "reserve_failure",
            extra={
                "event": "reserve",
                "status": "failure",
                "reason": "idempotency_conflict",
                "user_id": str(user.id),
                "messages": payload.messages,
                "correlation_id": payload.correlation_id,
            },
        )
        USAGE_RESERVE_TOTAL.labels("failure", "idempotency_conflict").inc()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency conflict")


@router.post("/commit", dependencies=[Depends(rate_limit_ip), Depends(rate_limit_token)])
def commit(payload: CommitRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        commit_reservation(db, reservation_id=uuidlib.UUID(payload.reservation_id), used=payload.used)
        logging.info(
            "commit_success",
            extra={
                "event": "commit",
                "status": "success",
                "user_id": str(user.id),
                "reservation_id": payload.reservation_id,
                "used": payload.used,
            },
        )
        USAGE_COMMIT_TOTAL.labels("success", "").inc()
        return {"ok": True}
    except LookupError:
        logging.warning(
            "commit_failure",
            extra={
                "event": "commit",
                "status": "failure",
                "reason": "not_found",
                "user_id": str(user.id),
                "reservation_id": payload.reservation_id,
                "used": payload.used,
            },
        )
        USAGE_COMMIT_TOTAL.labels("failure", "not_found").inc()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Reservation not found")
    except FileExistsError:
        logging.warning(
            "commit_failure",
            extra={
                "event": "commit",
                "status": "failure",
                "reason": "already_closed",
                "user_id": str(user.id),
                "reservation_id": payload.reservation_id,
                "used": payload.used,
            },
        )
        USAGE_COMMIT_TOTAL.labels("failure", "already_closed").inc()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already closed")
    except ValueError:
        logging.warning(
            "commit_failure",
            extra={
                "event": "commit",
                "status": "failure",
                "reason": "invalid_used",
                "user_id": str(user.id),
                "reservation_id": payload.reservation_id,
                "used": payload.used,
            },
        )
        USAGE_COMMIT_TOTAL.labels("failure", "invalid_used").inc()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid used value")
    except TimeoutError:
        logging.warning(
            "commit_failure",
            extra={
                "event": "commit",
                "status": "failure",
                "reason": "expired",
                "user_id": str(user.id),
                "reservation_id": payload.reservation_id,
                "used": payload.used,
            },
        )
        USAGE_COMMIT_TOTAL.labels("failure", "expired").inc()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Reservation expired")
    except PermissionError:
        logging.warning(
            "commit_failure",
            extra={
                "event": "commit",
                "status": "failure",
                "reason": "quota_exceeded",
                "user_id": str(user.id),
                "reservation_id": payload.reservation_id,
                "used": payload.used,
            },
        )
        USAGE_COMMIT_TOTAL.labels("failure", "quota_exceeded").inc()
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient quota at commit")


@router.post("/rollback", dependencies=[Depends(rate_limit_ip), Depends(rate_limit_token)])
def rollback(payload: RollbackRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        rollback_reservation(db, reservation_id=uuidlib.UUID(payload.reservation_id))
        logging.info(
            "rollback_success",
            extra={
                "event": "rollback",
                "status": "success",
                "user_id": str(user.id),
                "reservation_id": payload.reservation_id,
            },
        )
        USAGE_ROLLBACK_TOTAL.labels("success", "").inc()
        return {"ok": True}
    except LookupError:
        logging.warning(
            "rollback_failure",
            extra={
                "event": "rollback",
                "status": "failure",
                "reason": "not_found",
                "user_id": str(user.id),
                "reservation_id": payload.reservation_id,
            },
        )
        USAGE_ROLLBACK_TOTAL.labels("failure", "not_found").inc()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Reservation not found")
    except FileExistsError:
        logging.warning(
            "rollback_failure",
            extra={
                "event": "rollback",
                "status": "failure",
                "reason": "already_closed",
                "user_id": str(user.id),
                "reservation_id": payload.reservation_id,
            },
        )
        USAGE_ROLLBACK_TOTAL.labels("failure", "already_closed").inc()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already closed")


