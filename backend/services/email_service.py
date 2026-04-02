"""
LDVELH - Email Service (Resend)

Handles sending transactional emails: verification, password reset, etc.
"""

import logging
import secrets

import resend

from config import get_settings

logger = logging.getLogger(__name__)


def generate_verification_token() -> str:
    """Generate a cryptographically secure 32-byte hex token."""
    return secrets.token_hex(32)


async def send_verification_email(email: str, token: str) -> bool:
    """Send a verification email via Resend. Returns True on success."""
    settings = get_settings()

    if not settings.resend_api_key:
        logger.warning("[EMAIL] No RESEND_API_KEY configured, skipping email send")
        return False

    resend.api_key = settings.resend_api_key
    verify_url = f"{settings.frontend_url}/verify?token={token}"

    try:
        resend.Emails.send({
            "from": settings.email_from,
            "to": [email],
            "subject": "LDVELH - Vérifiez votre email",
            "html": _verification_html(verify_url),
        })
        logger.info(f"[EMAIL] Verification email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"[EMAIL] Failed to send verification email to {email}: {e}")
        return False


def _verification_html(verify_url: str) -> str:
    """Build the HTML body for the verification email."""
    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                max-width: 480px; margin: 0 auto; padding: 40px 20px;">
        <h1 style="color: #8B5CF6; font-size: 24px; margin-bottom: 24px;">
            LDVELH
        </h1>
        <p style="color: #E5E7EB; font-size: 16px; line-height: 1.6;">
            Bienvenue ! Cliquez sur le lien ci-dessous pour confirmer votre adresse email :
        </p>
        <a href="{verify_url}"
           style="display: inline-block; margin: 24px 0; padding: 12px 32px;
                  background-color: #8B5CF6; color: #FFFFFF; text-decoration: none;
                  border-radius: 8px; font-weight: 600; font-size: 14px;">
            Vérifier mon email
        </a>
        <p style="color: #9CA3AF; font-size: 13px; line-height: 1.5;">
            Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :<br/>
            <a href="{verify_url}" style="color: #8B5CF6; word-break: break-all;">
                {verify_url}
            </a>
        </p>
        <p style="color: #6B7280; font-size: 12px; margin-top: 32px;">
            Ce lien expire dans 24 heures. Si vous n'avez pas créé de compte, ignorez cet email.
        </p>
    </div>
    """
