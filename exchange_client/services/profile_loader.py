from typing import Optional
from decimal import Decimal
from db.session import SessionLocal
from db.crud import get_profile_by_name, db_profile_to_pydantic
from models.trading_profile import TradingProfile
from utils.logging import log_manager
from utils.config import Config

logger = log_manager.get_logger("ProfileLoader")

def load_profile(profile_name: str) -> Optional[TradingProfile]:
    """Load a trading profile from database"""
    db = SessionLocal()
    try:
        db_profile = get_profile_by_name(db, profile_name)
        if db_profile:
            logger.info(f"Loaded profile: {profile_name}")
            return db_profile_to_pydantic(db_profile)
        else:
            logger.warning(f"Profile '{profile_name}' not found")
            return None
    except Exception as e:
        logger.error(f"Error loading profile '{profile_name}': {e}")
        return None
    finally:
        db.close()

def load_profile_or_default(profile_name: Optional[str] = None) -> TradingProfile:
    """Load profile by name, or return default profile"""
    if profile_name:
        profile = load_profile(profile_name)
        if profile:
            return profile
    
    # Return default profile from environment
    config = Config()
    logger.info("Using default profile from environment")
    return TradingProfile(
        name="default",
        api_key=config.api_key,
        secret=config.secret,
        max_risk_pct=Decimal("0.25"),
        default_order_size_pct=Decimal("5")
    )