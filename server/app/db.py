from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session

from .core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = create_engine(get_settings().DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



