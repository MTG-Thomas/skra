"""Step-up verification for security-sensitive MFA mutations."""

import pyotp
from fastapi import HTTPException, status

from src.core.security import decrypt_secret


def require_totp_step_up(encrypted_secret: str | None, code: str | None) -> None:
    """Require a valid current TOTP code before replacing an active factor."""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current MFA verification code is required",
        )

    if encrypted_secret is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current MFA verification failed",
        )

    secret = decrypt_secret(encrypted_secret)
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current MFA verification failed",
        )
