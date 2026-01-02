# db/utils.py
from contextlib import contextmanager
from sqlalchemy.orm import Session
from db.session import SessionLocal
from typing import Generator
import logging

logger = logging.getLogger(__name__)

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    Ensures proper cleanup and error handling.
    
    Usage:
        with get_db_session() as db:
            result = db.query(Model).all()
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        logger.error(f"Database error, rolling back: {e}")
        raise
    finally:
        db.close()