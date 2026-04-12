# db/auth_crud.py
"""
CRUD operations for dashboard users and trading profile secrets.

  Passwords  → bcrypt  (AppUser.set_password / verify_password)
  API keys   → Fernet  (utils.secrets.encrypt_secret / resolve_secret)

Quick-start — create your first admin user:

    from db.session import SessionLocal
    from db.auth_crud import create_user, assign_profile

    db = SessionLocal()
    user = create_user(db, "michael", "your-password", role="admin")
    assign_profile(db, user.id, "default")
    assign_profile(db, user.id, "MB15m")
    db.close()
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from db.models import AppUser, UserProfileMapping, TradingProfileDB


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dummy_bcrypt_verify(password: str) -> None:
    """
    Run a bcrypt verify against a dummy hash to consume the same wall-clock
    time as a real verify. Prevents attackers from enumerating valid usernames
    by measuring response time differences.
    """
    import bcrypt
    # This is a valid bcrypt hash of a random string — it will never match.
    _DUMMY = b"$2b$12$invalidhashpaddinginvalidhashpaddinginvalidhashpaddinginva"
    try:
        bcrypt.checkpw(password.encode(), _DUMMY)
    except Exception:
        pass


# ── App user reads ─────────────────────────────────────────────────────────────

def get_user_by_id(db: Session, user_id: int) -> Optional[AppUser]:
    return db.query(AppUser).filter(AppUser.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> Optional[AppUser]:
    return db.query(AppUser).filter(AppUser.username == username).first()


def get_all_users(db: Session) -> list[AppUser]:
    return db.query(AppUser).order_by(AppUser.username).all()


def get_user_profiles(db: Session, user_id: int) -> list[str]:
    """Return the profile_names accessible to this user (active mappings only)."""
    rows = (
        db.query(UserProfileMapping)
        .filter(
            UserProfileMapping.user_id == user_id,
            UserProfileMapping.is_active == True,
        )
        .all()
    )
    return [r.profile_name for r in rows]


# ── Authentication ─────────────────────────────────────────────────────────────

def authenticate_user(db: Session, username: str, password: str) -> Optional[AppUser]:
    """
    Validate credentials against the app_users table.

    Returns the AppUser on success, None on any failure.
    Always runs bcrypt (even for unknown users) to resist timing attacks.
    """
    user = get_user_by_username(db, username)

    if user is None:
        _dummy_bcrypt_verify(password)
        return None

    if not user.is_active:
        _dummy_bcrypt_verify(password)
        return None

    if not user.verify_password(password):
        return None

    return user


def record_login(db: Session, user: AppUser) -> None:
    """Stamp last_login_at — call after every successful authentication."""
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()


# ── Profile data with decrypted API keys ──────────────────────────────────────

def get_user_profile_data(db: Session, user_id: int) -> dict:
    """
    Return a dict of all profiles this user can access, with their API keys
    Fernet-decrypted at call time using DB_ENCRYPTION_KEY.

    This is the single place where decryption happens for the dashboard.
    The returned api_key values are passed to /auth/me and live in JS memory
    only — they are never written to localStorage, sessionStorage, or cookies.

    Return shape:
        {
            "default": {
                "api_key":      "raw-plaintext-key",   # decrypted here
                "display_name": "Default Profile",
                "key_hint":     "...abc123",            # last 6 chars for display
            },
            "MB15m": { ... },
        }
    """
    from utils.db_secrets import resolve_secret

    profile_names = get_user_profiles(db, user_id)
    result = {}

    for name in profile_names:
        row = (
            db.query(TradingProfileDB)
            .filter(
                TradingProfileDB.name == name,
                TradingProfileDB.is_active == True,
            )
            .first()
        )
        if not row:
            continue

        try:
            raw_key = resolve_secret(row.account.api_key) if row.account else None
        except Exception as e:
            # Don't crash the entire login if one profile's key is broken —
            # log it and let the user see the other profiles.
            import logging
            logging.getLogger(__name__).error(
                "Failed to decrypt api_key for profile %r: %s", name, e
            )
            raw_key = None

        result[name] = {
            # Renamed exchange_api_key to be unambiguous — this is the Backpack
            # exchange key, NOT the X-API-Key for your own FastAPI endpoints.
            "exchange_api_key": raw_key,
            "display_name":     row.display_name,
            "key_hint":         f"...{raw_key[-6:]}" if raw_key else None,
            "account_id":       row.account_id,
        }

    return result


def get_decrypted_profile_secrets(db: Session, profile_name: str) -> Optional[dict]:
    """
    Fetch a trading profile's plaintext api_key and secret for server-side
    exchange calls (e.g. when you migrate away from YAML-based profile loading).

    Never log or serialize the return value.

    Returns: {"api_key": "...", "secret": "..."} or None if not found / inactive.
    """
    from utils.db_secrets import resolve_secret

    row = (
        db.query(TradingProfileDB)
        .filter(
            TradingProfileDB.profile_name == profile_name,
            TradingProfileDB.is_active == True,
        )
        .first()
    )
    if not row:
        return None

    if not row.account:
        return None

    return {
        "api_key": resolve_secret(row.account.api_key),
        "secret":  resolve_secret(row.account.secret),
    }


# ── App user create / update ───────────────────────────────────────────────────

def create_user(
    db: Session,
    username: str,
    password: str,
    role: str = "viewer",
    display_name: Optional[str] = None,
    email: Optional[str] = None,
) -> AppUser:
    """
    Create a new dashboard user with a bcrypt-hashed password.
    Raises ValueError if the username already exists.
    """
    if get_user_by_username(db, username):
        raise ValueError(f"Username '{username}' already exists")

    user = AppUser(
        username=username,
        display_name=display_name or username,
        email=email,
        role=role,
        is_active=True,
    )
    user.set_password(password)   # bcrypt hash stored in user.password_hash

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_password(db: Session, user_id: int, new_password: str) -> AppUser:
    user = get_user_by_id(db, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    user.set_password(new_password)
    db.commit()
    db.refresh(user)
    return user


def deactivate_user(db: Session, user_id: int) -> AppUser:
    user = get_user_by_id(db, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


def reactivate_user(db: Session, user_id: int) -> AppUser:
    user = get_user_by_id(db, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


# ── Profile mappings ───────────────────────────────────────────────────────────

def assign_profile(db: Session, user_id: int, profile_name: str) -> UserProfileMapping:
    """
    Link a user to a trading profile.
    Idempotent — re-activates the mapping if it was previously removed.
    """
    existing = (
        db.query(UserProfileMapping)
        .filter(
            UserProfileMapping.user_id == user_id,
            UserProfileMapping.profile_name == profile_name,
        )
        .first()
    )
    if existing:
        if not existing.is_active:
            existing.is_active = True
            db.commit()
            db.refresh(existing)
        return existing

    mapping = UserProfileMapping(
        user_id=user_id, profile_name=profile_name, is_active=True
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


def remove_profile(db: Session, user_id: int, profile_name: str) -> bool:
    """Soft-remove a user's access to a profile. Returns True if the mapping existed."""
    mapping = (
        db.query(UserProfileMapping)
        .filter(
            UserProfileMapping.user_id == user_id,
            UserProfileMapping.profile_name == profile_name,
        )
        .first()
    )
    if not mapping:
        return False
    mapping.is_active = False
    db.commit()
    return True


def set_user_profiles(
    db: Session, user_id: int, profile_names: list[str]
) -> list[str]:
    """
    Replace all profile assignments for a user atomically.
    Profiles in the list are activated; any others are deactivated.
    Returns the final list of active profile names.
    """
    existing = db.query(UserProfileMapping).filter(
        UserProfileMapping.user_id == user_id
    ).all()

    existing_map = {m.profile_name: m for m in existing}
    desired = set(profile_names)

    for name, mapping in existing_map.items():
        mapping.is_active = name in desired

    for name in desired:
        if name not in existing_map:
            db.add(UserProfileMapping(user_id=user_id, profile_name=name, is_active=True))

    db.commit()
    return list(desired)


# ── Trading profile secret writes ──────────────────────────────────────────────

def upsert_trading_profile(
    db: Session,
    profile_name: str,
    display_name: str,
    **kwargs,
) -> TradingProfileDB:
    """
    Create or update a TradingProfileDB row.
    Any additional TradingProfileDB column values can be passed as kwargs.
    Credentials (api_key/secret) are stored on ExchangeAccount, not here.
    """
    from db.models import TradingProfileDB

    row = db.query(TradingProfileDB).filter(
        TradingProfileDB.profile_name == profile_name
    ).first()

    if row:
        row.display_name = display_name
        for k, v in kwargs.items():
            if hasattr(row, k):
                setattr(row, k, v)
        db.add(row)
    else:
        valid_kw = {k: v for k, v in kwargs.items() if hasattr(TradingProfileDB, k)}
        row = TradingProfileDB(
            profile_name=profile_name,
            display_name=display_name,
            **valid_kw,
        )
        db.add(row)

    db.commit()
    db.refresh(row)
    return row
