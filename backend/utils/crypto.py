"""
LDVELH - Encryption utilities for API key storage.
Uses Fernet (AES-128-CBC) symmetric encryption.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken

from config import get_settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """Get a Fernet instance from the configured encryption key."""
    key = get_settings().encryption_key
    if not key:
        raise ValueError("ENCRYPTION_KEY not configured")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns base64-encoded ciphertext."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Returns plaintext."""
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("[CRYPTO] Failed to decrypt value — invalid key or corrupted data")
        raise ValueError("Decryption failed")


def mask_api_key(key: str) -> str:
    """Mask an API key, showing first 4 and last 4 characters."""
    if not key or len(key) <= 8:
        return "****"
    return key[:4] + "*" * (len(key) - 8) + key[-4:]
