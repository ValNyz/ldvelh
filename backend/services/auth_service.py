"""
LDVELH - Auth Service
JWT token management and user authentication.
"""

import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

import bcrypt
import jwt

from config import get_settings
from services.email_service import generate_verification_token, send_verification_email

logger = logging.getLogger(__name__)

# Verification token valid for 24 hours
VERIFICATION_TOKEN_EXPIRY_HOURS = 24


def hash_password(plain: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_token(user_id: UUID, email: str) -> str:
    """Create a JWT token for the given user."""
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises jwt.PyJWTError on failure."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


async def register(conn, email: str, password: str, display_name: str | None = None) -> dict:
    """
    Register a new user. Returns {id, email, display_name, token, email_verified}.
    Sends a verification email if Resend is configured.
    Raises ValueError if email already exists or password too short.
    """
    email = email.lower().strip()
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")

    pw_hash = hash_password(password)
    verification_token = generate_verification_token()

    try:
        row = await conn.fetchrow(
            """INSERT INTO users (email, password_hash, display_name,
                                  email_verification_token, email_verification_sent_at)
               VALUES ($1, $2, $3, $4, now())
               RETURNING id, email, display_name, email_verified""",
            email, pw_hash, display_name, verification_token,
        )
    except Exception as e:
        err = str(e).lower()
        if "unique" in err or "duplicate" in err:
            if "display_name" in err:
                raise ValueError("Display name already taken")
            raise ValueError("Email already registered")
        raise

    # Send verification email (non-blocking, don't fail registration if email fails)
    await send_verification_email(email, verification_token)

    user = {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "email_verified": row["email_verified"],
    }
    user["token"] = create_token(row["id"], row["email"])
    logger.info(f"[AUTH] User registered: {email}")
    return user


async def authenticate(conn, identifier: str, password: str) -> dict | None:
    """
    Authenticate a user by email or display_name.
    Returns {id, email, display_name, email_verified, token} or None.
    """
    identifier = identifier.strip()

    # Try email first, then display_name
    if "@" in identifier:
        row = await conn.fetchrow(
            "SELECT id, email, password_hash, display_name, email_verified FROM users WHERE email = $1",
            identifier.lower(),
        )
    else:
        row = await conn.fetchrow(
            "SELECT id, email, password_hash, display_name, email_verified FROM users WHERE display_name = $1",
            identifier,
        )
    if not row:
        return None

    if not verify_password(password, row["password_hash"]):
        return None

    user = {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "email_verified": row["email_verified"],
    }
    user["token"] = create_token(row["id"], row["email"])
    logger.info(f"[AUTH] User authenticated: {row['email']}")
    return user


async def verify_email(conn, token: str) -> dict | None:
    """
    Verify an email using the verification token.
    Returns user dict on success, None if token invalid/expired.
    """
    row = await conn.fetchrow(
        """SELECT id, email, display_name, email_verified,
                  email_verification_sent_at
           FROM users
           WHERE email_verification_token = $1""",
        token,
    )
    if not row:
        return None

    if row["email_verified"]:
        return {"id": row["id"], "email": row["email"], "already_verified": True}

    # Check expiry (24 hours)
    sent_at = row["email_verification_sent_at"]
    if sent_at:
        expiry = sent_at + timedelta(hours=VERIFICATION_TOKEN_EXPIRY_HOURS)
        if datetime.now(timezone.utc) > expiry:
            return None

    await conn.execute(
        "UPDATE users SET email_verified = true WHERE id = $1",
        row["id"],
    )
    logger.info(f"[AUTH] Email verified: {row['email']}")
    return {"id": row["id"], "email": row["email"], "already_verified": False}


async def resend_verification(conn, user_id: UUID) -> bool:
    """Regenerate token and resend verification email. Returns True on success."""
    row = await conn.fetchrow(
        "SELECT email, email_verified FROM users WHERE id = $1", user_id
    )
    if not row or row["email_verified"]:
        return False

    new_token = generate_verification_token()
    await conn.execute(
        """UPDATE users
           SET email_verification_token = $1, email_verification_sent_at = now()
           WHERE id = $2""",
        new_token, user_id,
    )
    return await send_verification_email(row["email"], new_token)
