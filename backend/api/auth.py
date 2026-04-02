"""
LDVELH - Auth API Routes
Registration, login, user info, and preferences endpoints.
"""

import json
import logging
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.dependencies import get_pool, get_current_user
from services import auth_service
from utils.crypto import encrypt_value, decrypt_value, mask_api_key
from utils.rate_limit import auth_limiter

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_PROVIDERS = {"anthropic", "mistral", "wandb", "nebius", "nous"}


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================


class RegisterRequest(BaseModel):
    email: str
    password: str
    password_confirm: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    identifier: str  # email or display_name
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str | None


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    new_password_confirm: str


class UpdateProfileRequest(BaseModel):
    display_name: str | None = None


class PreferencesUpdate(BaseModel):
    preferences: dict


# =============================================================================
# HELPERS
# =============================================================================


def _mask_preferences(prefs: dict) -> dict:
    """Return preferences with API keys masked."""
    if not prefs:
        return {}
    result = dict(prefs)
    api_keys = result.get("api_keys", {})
    if api_keys:
        masked = {}
        for provider, encrypted_key in api_keys.items():
            if encrypted_key:
                try:
                    plain = decrypt_value(encrypted_key)
                    masked[provider] = mask_api_key(plain)
                except Exception:
                    masked[provider] = "****"
            else:
                masked[provider] = None
        result["api_keys"] = masked
    return result


async def _get_user_preferences(conn, user_id: UUID) -> dict:
    """Load raw preferences from DB."""
    row = await conn.fetchval(
        "SELECT preferences FROM users WHERE id = $1", user_id
    )
    if row and isinstance(row, str):
        return json.loads(row)
    return row or {}


def _build_user_response(user: dict, preferences: dict | None = None) -> dict:
    """Build user response dict with optional masked preferences."""
    resp = {
        "id": str(user["id"]),
        "email": user["email"],
        "display_name": user.get("display_name"),
        "email_verified": user.get("email_verified", False),
    }
    if preferences is not None:
        resp["preferences"] = _mask_preferences(preferences)
    return resp


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.post("/register")
async def register(
    request: RegisterRequest,
    raw_request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Register a new user account."""
    auth_limiter.check(raw_request)
    if request.password != request.password_confirm:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    try:
        async with pool.acquire() as conn:
            result = await auth_service.register(
                conn, request.email, request.password, request.display_name
            )
        return {
            "token": result["token"],
            "user": _build_user_response(result, {}),
        }
    except ValueError as e:
        msg = str(e)
        status = 409 if "already" in msg else 400
        raise HTTPException(status_code=status, detail=msg)


@router.post("/login")
async def login(
    request: LoginRequest,
    raw_request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Authenticate and get a JWT token."""
    auth_limiter.check(raw_request)
    async with pool.acquire() as conn:
        result = await auth_service.authenticate(conn, request.identifier, request.password)

    if not result:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    async with pool.acquire() as conn:
        prefs = await _get_user_preferences(conn, result["id"])

    return {
        "token": result["token"],
        "user": _build_user_response(result, prefs),
    }


@router.get("/me")
async def me(
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Get current user info with preferences."""
    async with pool.acquire() as conn:
        prefs = await _get_user_preferences(conn, user["id"])

    return {"user": _build_user_response(user, prefs)}


@router.post("/refresh")
async def refresh_token(user: dict = Depends(get_current_user)):
    """Issue a fresh JWT if the current token is still valid."""
    token = auth_service.create_token(str(user["id"]), user["email"])
    return {"token": token}


@router.patch("/profile")
async def update_profile(
    request: UpdateProfileRequest,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Update current user's profile (display name)."""
    if request.display_name is not None:
        name = request.display_name.strip()
        if len(name) > 100:
            raise HTTPException(status_code=400, detail="Display name too long (max 100)")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET display_name = $1 WHERE id = $2",
                name or None, user["id"],
            )

    # Return updated user
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, display_name, email_verified FROM users WHERE id = $1",
            user["id"],
        )
    return {"user": _build_user_response(dict(row))}


# =============================================================================
# EMAIL VERIFICATION
# =============================================================================


@router.get("/verify")
async def verify_email(
    token: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Verify email using the token from the verification link."""
    if not token or len(token) < 10:
        raise HTTPException(status_code=400, detail="Invalid verification token")

    async with pool.acquire() as conn:
        result = await auth_service.verify_email(conn, token)

    if not result:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired verification token. Request a new one.",
        )

    return {
        "success": True,
        "email": result["email"],
        "already_verified": result.get("already_verified", False),
    }


@router.post("/resend-verification")
async def resend_verification(
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Resend the verification email for the current user."""
    async with pool.acquire() as conn:
        sent = await auth_service.resend_verification(conn, user["id"])

    if not sent:
        raise HTTPException(
            status_code=400,
            detail="Email already verified or sending failed",
        )

    return {"success": True, "message": "Verification email sent"}


# =============================================================================
# PASSWORD CHANGE
# =============================================================================


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Change the current user's password."""
    if request.new_password != request.new_password_confirm:
        raise HTTPException(status_code=400, detail="New passwords do not match")
    if len(request.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT password_hash FROM users WHERE id = $1", user["id"]
        )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    if not auth_service.verify_password(request.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    new_hash = auth_service.hash_password(request.new_password)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET password_hash = $1 WHERE id = $2",
            new_hash, user["id"],
        )

    return {"success": True}


# =============================================================================
# PREFERENCES ENDPOINTS
# =============================================================================


@router.get("/preferences")
async def get_preferences(
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Get user preferences with masked API keys."""
    async with pool.acquire() as conn:
        prefs = await _get_user_preferences(conn, user["id"])
    return {"preferences": _mask_preferences(prefs)}


@router.patch("/preferences")
async def update_preferences(
    request: PreferencesUpdate,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Update user preferences. API keys are encrypted before storage."""
    async with pool.acquire() as conn:
        current = await _get_user_preferences(conn, user["id"])

    updates = request.preferences

    # Handle api_keys separately — encrypt them
    if "api_keys" in updates:
        current_keys = current.get("api_keys", {})
        for provider, key_value in updates["api_keys"].items():
            if provider not in ALLOWED_PROVIDERS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown provider: {provider}. Allowed: {', '.join(ALLOWED_PROVIDERS)}"
                )
            if key_value is None or key_value == "":
                # Remove the key
                current_keys.pop(provider, None)
            else:
                # Encrypt and store
                current_keys[provider] = encrypt_value(key_value)
        current["api_keys"] = current_keys
        del updates["api_keys"]

    # Merge remaining preferences
    for key, value in updates.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value

    # Save to DB
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET preferences = $1 WHERE id = $2",
            json.dumps(current),
            user["id"],
        )

    return {"preferences": _mask_preferences(current)}
