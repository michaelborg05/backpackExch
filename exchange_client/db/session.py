from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from utils.config import Config

config = Config()

# Get database URL from config
DATABASE_URL = config.database_url  # e.g., "postgresql://user:pass@host/dbname"


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # Verify connections at checkout (catches dead idle conns)
    pool_recycle=300,     # Retire connections after 5 min so Neon doesn't drop them mid-query
    pool_size=5,
    max_overflow=10
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """Dependency for FastAPI routes"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()