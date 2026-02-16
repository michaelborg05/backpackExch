"""
CRUD operations for settings management
"""
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from db.models import Settings


def get_setting(
    db: Session,
    setting_name: str,
    profile_name: str = '0'
) -> Optional[Settings]:
    """
    Get a specific setting for a profile or global
    
    Args:
        db: Database session
        setting_name: Name of the setting
        profile_name: Profile name ('0' for global, specific name for profile-specific)
    
    Returns:
        Settings object or None if not found
    """
    return db.query(Settings).filter(
        Settings.profile_name == profile_name,
        Settings.setting_name == setting_name
    ).first()


def get_all_settings(
    db: Session,
    profile_name: Optional[str] = None
) -> List[Settings]:
    """
    Get all settings, optionally filtered by profile
    
    Args:
        db: Database session
        profile_name: Optional profile name to filter by ('0' for global)
    
    Returns:
        List of Settings objects
    """
    query = db.query(Settings)
    
    if profile_name is not None:
        query = query.filter(Settings.profile_name == profile_name)
    
    return query.order_by(Settings.profile_name, Settings.setting_name).all()


def get_settings_for_profile(
    db: Session,
    profile_name: str
) -> Dict[str, str]:
    """
    Get all settings applicable to a profile (global + profile-specific)
    Profile-specific settings override global settings
    
    Args:
        db: Database session
        profile_name: Profile name
    
    Returns:
        Dictionary of setting_name -> value (profile-specific overrides global)
    """
    # Get global settings
    global_settings = db.query(Settings).filter(
        Settings.profile_name == '0'
    ).all()
    
    # Get profile-specific settings
    profile_settings = db.query(Settings).filter(
        Settings.profile_name == profile_name
    ).all()
    
    # Build dict with global first, then override with profile-specific
    result = {s.setting_name: s.value for s in global_settings}
    result.update({s.setting_name: s.value for s in profile_settings})
    
    return result


def create_setting(
    db: Session,
    setting_name: str,
    value: str,
    profile_name: str = '0'
) -> Settings:
    """
    Create a new setting
    
    Args:
        db: Database session
        setting_name: Name of the setting
        value: Value (stored as string)
        profile_name: Profile name ('0' for global)
    
    Returns:
        Created Settings object
    """
    setting = Settings(
        profile_name=profile_name,
        setting_name=setting_name,
        value=value,
        created_at=datetime.now(timezone.utc)
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def update_setting(
    db: Session,
    setting_name: str,
    value: str,
    profile_name: str = '0'
) -> Optional[Settings]:
    """
    Update an existing setting or create if doesn't exist
    
    Args:
        db: Database session
        setting_name: Name of the setting
        value: New value
        profile_name: Profile name ('0' for global)
    
    Returns:
        Updated Settings object or None if not found
    """
    setting = get_setting(db, setting_name, profile_name)
    
    if setting:
        setting.value = value
        setting.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(setting)
        return setting
    else:
        # Create if doesn't exist
        return create_setting(db, setting_name, value, profile_name)


def delete_setting(
    db: Session,
    setting_name: str,
    profile_name: str = '0'
) -> bool:
    """
    Delete a setting
    
    Args:
        db: Database session
        setting_name: Name of the setting
        profile_name: Profile name ('0' for global)
    
    Returns:
        True if deleted, False if not found
    """
    setting = get_setting(db, setting_name, profile_name)
    
    if setting:
        db.delete(setting)
        db.commit()
        return True
    
    return False


def bulk_upsert_settings(
    db: Session,
    settings_dict: Dict[str, str],
    profile_name: str = '0'
) -> List[Settings]:
    """
    Bulk upsert (update or insert) multiple settings
    
    Args:
        db: Database session
        settings_dict: Dictionary of setting_name -> value
        profile_name: Profile name ('0' for global)
    
    Returns:
        List of created/updated Settings objects
    """
    results = []
    
    for setting_name, value in settings_dict.items():
        setting = update_setting(db, setting_name, str(value), profile_name)
        results.append(setting)
    
    return results


def initialize_default_settings(db: Session, default_settings: dict[str,str]) -> List[Settings]:
    """
    Initialize default settings if not already present
    This should be called on first startup or during migrations
    
    Args:
        db: Database session
    
    Returns:
        List of created Settings objects
    """
    
    created = []
    for setting_name, value in default_settings.items():
        # Check if exists
        existing = get_setting(db, setting_name, '0')
        if not existing:
            setting = create_setting(db, setting_name, value, '0')
            created.append(setting)
    
    return created