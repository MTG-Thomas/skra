"""Security regressions for replacing an existing MFA enrollment."""

from unittest.mock import patch

import pyotp
import pytest
from fastapi import HTTPException

from src.services.mfa_step_up import require_totp_step_up


def test_reset_requires_code_when_totp_is_active() -> None:
    with pytest.raises(HTTPException, match="verification code is required"):
        require_totp_step_up("encrypted", None)


def test_reset_rejects_invalid_current_totp() -> None:
    secret = pyotp.random_base32()
    invalid_code = "000000"
    if pyotp.TOTP(secret).verify(invalid_code, valid_window=1):
        invalid_code = "111111"

    with (
        patch("src.services.mfa_step_up.decrypt_secret", return_value=secret),
        pytest.raises(HTTPException, match="verification failed"),
    ):
        require_totp_step_up("encrypted", invalid_code)


def test_reset_accepts_valid_current_totp() -> None:
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()

    with (
        patch("src.services.mfa_step_up.decrypt_secret", return_value=secret),
    ):
        require_totp_step_up("encrypted", code)


def test_reset_fails_closed_when_active_secret_is_missing() -> None:
    with pytest.raises(HTTPException, match="verification failed"):
        require_totp_step_up(None, "123456")
