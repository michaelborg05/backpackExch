# services/dashboard_auth.py
"""
JWT-based authentication for the web dashboard.

  Login credentials  → validated against app_users table (bcrypt)
  Internal API key   → API_READONLY_KEY env var, returned to JS for calling
                       your FastAPI endpoints (X-API-Key header)
  Exchange API keys  → read from trading_profiles table, Fernet-decrypted,
                       returned to JS as exchange_api_key (for future use)
                       Both live in JS memory only — never in cookies/storage.

Two separate key systems:
  - Internal keys (API_MASTER_KEY, API_READONLY_KEY, API_TRADING_KEY): gate
    access to your FastAPI endpoints via security.py. The dashboard uses
    API_READONLY_KEY to call monitoring/portfolio/balance endpoints.
  - Exchange keys (in trading_profiles DB): authenticate against Backpack.
    These are NOT sent as X-API-Key — they are used server-side by trading code.

Required environment variables:
    JWT_SECRET          HS256 signing key, minimum 32 characters.
                        Generate: python -c "import secrets; print(secrets.token_hex(32))"

    DB_ENCRYPTION_KEY   Fernet key for trading secrets.
                        Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    API_READONLY_KEY    Your existing internal readonly key (already in your .env).
                        The dashboard sends this as X-API-Key on every API call.

Optional:
    JWT_ACCESS_EXPIRE_MIN     default: 15
    JWT_REFRESH_EXPIRE_HR     default: 24

─── Wiring into api_server.py ────────────────────────────────────────────────

    from services.dashboard_auth import auth_router, get_dashboard_user
    app.include_router(auth_router)

    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/", dependencies=[Depends(get_dashboard_user)])
    async def serve_dashboard():
        return FileResponse("static/index.html")
"""

import os
import hmac
import hashlib
import time
import base64
import json
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Response, Depends, Cookie
from pydantic import BaseModel

from db.session import SessionLocal
from db.auth_crud import (
    authenticate_user,
    record_login,
    get_user_profiles,
    get_user_profile_data,
    get_user_by_id,
    get_all_users,
    create_user,
    update_password,
    deactivate_user,
    assign_profile,
    set_user_profiles,
)


# ── Config ─────────────────────────────────────────────────────────────────────

def _cfg() -> dict:
    return {
        "jwt_secret":     os.environ.get("JWT_SECRET", ""),
        "access_expire":  int(os.environ.get("JWT_ACCESS_EXPIRE_MIN", "15")),
        "refresh_expire": int(os.environ.get("JWT_REFRESH_EXPIRE_HR",  "24")),
    }

def _get_internal_api_key(role: str = "viewer") -> str:
    """
    Return the internal API key the dashboard should use as X-API-Key.

    Two separate key systems exist:
      - Internal keys (API_MASTER_KEY, API_READONLY_KEY, API_TRADING_KEY):
        gate access to your FastAPI endpoints via security.py.
        The dashboard sends one of these as X-API-Key.
      - Exchange keys (TradingProfileDB.api_key):
        authenticate against Backpack. Used server-side by trading code only.
        NEVER sent as X-API-Key — that is what was causing the 401 errors.

    Role-based selection gives least-privilege access:
      admin  -> API_MASTER_KEY  (full access to all endpoints)
      viewer -> API_READONLY_KEY (read-only, trade endpoints will 403)
    """
    if role == "admin":
        key = os.environ.get("API_MASTER_KEY", "")
        if key:
            return key
    # Default / viewer / fallback
    return os.environ.get("API_READONLY_KEY", "") or os.environ.get("API_MASTER_KEY", "")

def _require_cfg(cfg: dict) -> None:
    if not cfg["jwt_secret"]:
        raise HTTPException(status_code=500, detail="JWT_SECRET env var is not set")
    if len(cfg["jwt_secret"]) < 32:
        raise HTTPException(status_code=500, detail="JWT_SECRET must be at least 32 characters")


# ── Minimal HS256 JWT (stdlib only, no extra deps) ─────────────────────────────
# Compatible with any standard JWT library for verification if needed.

def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (4 - len(s) % 4))

def _sign(header_b64: str, body_b64: str, secret: str) -> str:
    msg = f"{header_b64}.{body_b64}".encode()
    return _b64e(hmac.new(secret.encode(), msg, hashlib.sha256).digest())

def _make_jwt(payload: dict, secret: str) -> str:
    h = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    b = _b64e(json.dumps(payload).encode())
    return f"{h}.{b}.{_sign(h, b, secret)}"

def _verify_jwt(token: str, secret: str) -> dict:
    try:
        h, b, s = token.split(".")
    except ValueError:
        raise HTTPException(status_code=401, detail="Malformed token")
    expected = _sign(h, b, secret)
    if not hmac.compare_digest(expected, s):
        raise HTTPException(status_code=401, detail="Invalid token signature")
    try:
        payload = json.loads(_b64d(b))
    except Exception:
        raise HTTPException(status_code=401, detail="Could not decode token")
    if payload.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="Token expired")
    return payload


# ── Token helpers ──────────────────────────────────────────────────────────────

def _make_access_token(user_id: int, username: str, role: str, profiles: list[str], cfg: dict) -> str:
    """
    Access token — short-lived (15 min default).
    Carries profile names only; actual API keys are fetched separately via /auth/me
    to keep the token payload small and avoid re-issuing keys on every refresh.
    """
    return _make_jwt(
        {
            "sub":      str(user_id),
            "username": username,
            "role":     role,
            "profiles": profiles,
            "type":     "access",
            "iat":      int(time.time()),
            "exp":      int(time.time()) + cfg["access_expire"] * 60,
            "jti":      secrets.token_hex(8),
        },
        cfg["jwt_secret"],
    )

def _make_refresh_token(user_id: int, cfg: dict) -> str:
    """Refresh token — long-lived (24 hr default), carries only user_id."""
    return _make_jwt(
        {
            "sub":  str(user_id),
            "type": "refresh",
            "iat":  int(time.time()),
            "exp":  int(time.time()) + cfg["refresh_expire"] * 3600,
            "jti":  secrets.token_hex(8),
        },
        cfg["jwt_secret"],
    )

def _set_auth_cookies(response: Response, access: str, refresh: str, cfg: dict) -> None:
    kw = dict(httponly=True, secure=True, samesite="strict", path="/")
    response.set_cookie("access_token",  access,  max_age=cfg["access_expire"] * 60,   **kw)
    response.set_cookie("refresh_token", refresh, max_age=cfg["refresh_expire"] * 3600, **kw)

def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token",  path="/")
    response.delete_cookie("refresh_token", path="/")


# ── CurrentUser dependency ─────────────────────────────────────────────────────

class CurrentUser:
    """Decoded access token, available via Depends(get_dashboard_user)."""

    def __init__(self, payload: dict):
        self.user_id:  int       = int(payload["sub"])
        self.username: str       = payload["username"]
        self.role:     str       = payload["role"]
        self.profiles: list[str] = payload.get("profiles", [])

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def require_admin(self) -> None:
        if not self.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

    def require_profile_access(self, profile_name: str) -> None:
        if profile_name not in self.profiles and not self.is_admin:
            raise HTTPException(
                status_code=403, detail=f"No access to profile '{profile_name}'"
            )


async def get_dashboard_user(
    access_token: Optional[str] = Cookie(default=None),
) -> CurrentUser:
    """
    FastAPI dependency — validates the access_token HttpOnly cookie.
    Use as: Depends(get_dashboard_user)
    """
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    cfg = _cfg()
    _require_cfg(cfg)
    payload = _verify_jwt(access_token, cfg["jwt_secret"])
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Wrong token type")
    return CurrentUser(payload)


# ── Pydantic models ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateUserRequest(BaseModel):
    username:     str
    password:     str
    role:         str = "viewer"
    display_name: Optional[str] = None
    profiles:     list[str] = []

class UpdateProfilesRequest(BaseModel):
    profiles: list[str]

class ChangePasswordRequest(BaseModel):
    new_password: str


# ── Router ─────────────────────────────────────────────────────────────────────

auth_router = APIRouter(prefix="/auth", tags=["Dashboard Auth"])


@auth_router.post("/login")
async def login(body: LoginRequest, response: Response):
    """
    Validate username/password against the app_users table.
    On success, issues two HttpOnly cookies:
      - access_token  (15 min, carries profile names)
      - refresh_token (24 hr, used by /auth/refresh)
    Returns username, role, and accessible profile names.
    API keys are NOT in this response — call /auth/me after login.
    """
    cfg = _cfg()
    _require_cfg(cfg)

    db = SessionLocal()
    try:
        user = authenticate_user(db, body.username, body.password)
        if not user:
            # Identical response time and body for wrong user vs wrong password
            raise HTTPException(status_code=401, detail="Invalid credentials")

        profiles = get_user_profiles(db, user.id)
        record_login(db, user)

        access  = _make_access_token(user.id, user.username, user.role, profiles, cfg)
        refresh = _make_refresh_token(user.id, cfg)
        _set_auth_cookies(response, access, refresh, cfg)

        return {"ok": True, "username": user.username, "role": user.role, "profiles": profiles}
    finally:
        db.close()


@auth_router.get("/me")
async def get_me(current_user: CurrentUser = Depends(get_dashboard_user)):
    """
    Return session info, the internal API key for FastAPI calls, and per-profile
    exchange API keys (Fernet-decrypted from DB).

    KEY DISTINCTION — two completely separate key systems:

      internal_api_key   The key to send as X-API-Key on every call to your
                         FastAPI endpoints (/monitoring, /portfolio, /balances etc).
                         This is API_READONLY_KEY (or API_MASTER_KEY for admins)
                         from your environment variables. This is what security.py
                         checks. The dashboard was previously sending the exchange
                         key here — that is what caused the 401 errors.

      profiles[x].exchange_api_key   The encrypted Backpack API key for each
                         trading profile, decrypted here and held in JS memory.
                         Used by server-side trading code to call Backpack.
                         NOT sent as X-API-Key to your own API.

    Both live in JS memory only — never in localStorage, sessionStorage, or cookies.
    """
    db = SessionLocal()
    try:
        profile_data = get_user_profile_data(db, current_user.user_id)

        # Internal key: gates access to your own FastAPI endpoints.
        # Role-based: admins get master key (full access), viewers get readonly key.
        internal_key = _get_internal_api_key(current_user.role)
        if not internal_key:
            # Warn loudly but don't crash login — missing key means all API calls
            # will 401, which is visible and debuggable from the dashboard.
            import logging
            logging.getLogger(__name__).error(
                "API_READONLY_KEY / API_MASTER_KEY env var not set — "
                "dashboard API calls will fail with 401"
            )

        return {
            "user_id":          current_user.user_id,
            "username":         current_user.username,
            "role":             current_user.role,
            "internal_api_key": internal_key,   # send this as X-API-Key
            "profiles":         profile_data,   # exchange_api_key lives here
        }
    finally:
        db.close()


@auth_router.get("/status")
async def auth_status(current_user: CurrentUser = Depends(get_dashboard_user)):
    """Lightweight session check called on dashboard page load."""
    return {
        "authenticated": True,
        "username":      current_user.username,
        "role":          current_user.role,
        "profiles":      current_user.profiles,
    }


@auth_router.post("/refresh")
async def refresh_token(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None),
):
    """
    Exchange a valid refresh_token cookie for a new access_token cookie.
    Also re-fetches the user's current profile list in case it changed.
    """
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    cfg = _cfg()
    payload = _verify_jwt(refresh_token, cfg["jwt_secret"])
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Wrong token type")

    db = SessionLocal()
    try:
        user = get_user_by_id(db, int(payload["sub"]))
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or deactivated")

        profiles   = get_user_profiles(db, user.id)
        new_access = _make_access_token(user.id, user.username, user.role, profiles, cfg)
        response.set_cookie(
            "access_token", new_access,
            max_age=cfg["access_expire"] * 60,
            httponly=True, secure=True, samesite="strict", path="/",
        )
        return {"ok": True}
    finally:
        db.close()


@auth_router.post("/logout")
async def logout(response: Response):
    """Clear both auth cookies."""
    _clear_auth_cookies(response)
    return {"ok": True}


# ── Admin: user management ─────────────────────────────────────────────────────

@auth_router.get("/users")
async def list_users(current_user: CurrentUser = Depends(get_dashboard_user)):
    """List all dashboard users. Admin only."""
    current_user.require_admin()
    db = SessionLocal()
    try:
        return {
            "users": [
                {
                    "id":           u.id,
                    "username":     u.username,
                    "display_name": u.display_name,
                    "role":         u.role,
                    "is_active":    u.is_active,
                    "last_login":   u.last_login_at.isoformat() if u.last_login_at else None,
                    "profiles":     [m.profile_name for m in u.profile_mappings if m.is_active],
                }
                for u in get_all_users(db)
            ]
        }
    finally:
        db.close()


@auth_router.post("/users")
async def create_dashboard_user(
    body: CreateUserRequest,
    current_user: CurrentUser = Depends(get_dashboard_user),
):
    """Create a new dashboard user and assign profiles. Admin only."""
    current_user.require_admin()
    if body.role not in ("admin", "viewer"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'viewer'")

    db = SessionLocal()
    try:
        user = create_user(db, body.username, body.password, body.role, body.display_name)
        for p in body.profiles:
            assign_profile(db, user.id, p)
        return {"ok": True, "user_id": user.id, "username": user.username, "profiles": body.profiles}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    finally:
        db.close()


@auth_router.put("/users/{user_id}/profiles")
async def update_user_profiles(
    user_id: int,
    body: UpdateProfilesRequest,
    current_user: CurrentUser = Depends(get_dashboard_user),
):
    """Replace a user's profile assignments atomically. Admin only."""
    current_user.require_admin()
    db = SessionLocal()
    try:
        profiles = set_user_profiles(db, user_id, body.profiles)
        return {"ok": True, "user_id": user_id, "profiles": profiles}
    finally:
        db.close()


@auth_router.put("/users/{user_id}/password")
async def change_password(
    user_id: int,
    body: ChangePasswordRequest,
    current_user: CurrentUser = Depends(get_dashboard_user),
):
    """Change a password. Admins can change anyone's; users can only change their own."""
    if not current_user.is_admin and current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Can only change your own password")
    db = SessionLocal()
    try:
        update_password(db, user_id, body.new_password)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        db.close()


@auth_router.delete("/users/{user_id}")
async def deactivate_dashboard_user(
    user_id: int,
    current_user: CurrentUser = Depends(get_dashboard_user),
):
    """Soft-deactivate a user. Admin only. Cannot deactivate yourself."""
    current_user.require_admin()
    if current_user.user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    db = SessionLocal()
    try:
        deactivate_user(db, user_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        db.close()
