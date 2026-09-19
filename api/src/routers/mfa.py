"""
MFA Router

Provides endpoints for Multi-Factor Authentication:
- MFA status check
- TOTP setup and verification (stubbed)
- MFA removal (stubbed)

Login-time MFA enforcement is handled separately; this router manages enrollment.
"""

import base64
import io
import logging
import secrets
from datetime import UTC, datetime

import pyotp
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from src.core.auth import CurrentActiveUser
from src.core.database import DbSession
from src.core.rate_limiting import RateLimits, limiter
from src.core.security import decrypt_secret, encrypt_secret, get_password_hash
from src.models.enums import MFAMethodStatus, MFAMethodType
from src.models.orm.mfa import MFARecoveryCode, UserMFAMethod
from src.models.orm.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])

MFA_ISSUER = "Skra"
RECOVERY_CODE_COUNT = 10


# =============================================================================
# Request/Response Models
# =============================================================================


class MFAStatusResponse(BaseModel):
    """MFA status response."""

    mfa_enabled: bool
    enabled: bool
    backup_codes_remaining: int


class MFASetupResponse(BaseModel):
    """MFA setup response with secret."""

    secret: str
    qr_code: str
    qr_code_uri: str
    provisioning_uri: str
    issuer: str
    account_name: str
    backup_codes: list[str]


class MFAVerifyRequest(BaseModel):
    """Request to verify MFA code."""

    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class MFAVerifyResponse(BaseModel):
    """MFA verification response."""

    success: bool
    recovery_codes: list[str] | None = None


class MFARemoveRequest(BaseModel):
    """Request to remove MFA method."""

    password: str | None = None
    mfa_code: str | None = None
    code: str | None = None


# =============================================================================
# MFA Status
# =============================================================================


@router.get("/status", response_model=MFAStatusResponse)
async def get_mfa_status(
    current_user: CurrentActiveUser,
    db: DbSession,
) -> MFAStatusResponse:
    """
    Get MFA status for current user.

    Returns:
        MFA status including enabled state and backup code count
    """
    logger.debug(f"MFA status requested for user: {current_user.email}")

    remaining = await _count_unused_recovery_codes(db, current_user.user_id)
    enabled = await _has_active_totp_method(db, current_user.user_id)

    return MFAStatusResponse(
        mfa_enabled=enabled,
        enabled=enabled,
        backup_codes_remaining=remaining,
    )


# =============================================================================
# MFA Setup and Verification
# =============================================================================


@router.post("/totp/setup", response_model=MFASetupResponse)
@router.post("/setup", response_model=MFASetupResponse)
@limiter.limit(RateLimits.MFA)
async def setup_mfa(
    request: Request,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> MFASetupResponse:
    """
    Initialize MFA enrollment for an authenticated user.

    Generates a new TOTP secret and returns the provisioning URI for QR code generation.

    Returns:
        MFA setup data including secret and QR code URI

    Raises:
        HTTPException: User not found
    """
    logger.info(f"MFA setup requested for user: {current_user.email}")

    user = await db.get(User, current_user.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await _delete_existing_totp_state(db, current_user.user_id)

    secret = pyotp.random_base32()
    account_name = user.email
    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
        name=account_name,
        issuer_name=MFA_ISSUER,
    )
    backup_codes = _generate_recovery_codes()

    db.add(
        UserMFAMethod(
            user_id=current_user.user_id,
            method_type=MFAMethodType.TOTP,
            status=MFAMethodStatus.PENDING,
            encrypted_secret=encrypt_secret(secret),
            mfa_metadata={
                "issuer": MFA_ISSUER,
                "account_name": account_name,
            },
        )
    )
    _add_recovery_codes(db, current_user.user_id, backup_codes)
    await db.flush()

    qr_code = _build_qr_code_data_url(provisioning_uri)

    return MFASetupResponse(
        secret=secret,
        qr_code=qr_code,
        qr_code_uri=qr_code,
        provisioning_uri=provisioning_uri,
        issuer=MFA_ISSUER,
        account_name=account_name,
        backup_codes=backup_codes,
    )


@router.post("/totp/verify", response_model=MFAVerifyResponse)
@router.post("/enable", response_model=MFAVerifyResponse)
@limiter.limit(RateLimits.MFA)
async def verify_mfa(
    request: Request,
    verify_request: MFAVerifyRequest,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> MFAVerifyResponse:
    """
    Verify MFA code to complete enrollment.

    On success:
    - Activates the MFA method
    - Generates recovery codes (shown only once!)

    Args:
        verify_request: MFA verification request with 6-digit code

    Returns:
        Success status and recovery codes

    Raises:
        HTTPException: No pending setup or invalid code
    """
    logger.info(f"MFA verification requested for user: {current_user.email}")

    method = await _get_totp_method(db, current_user.user_id, MFAMethodStatus.PENDING)
    if method is None or method.encrypted_secret is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending MFA setup found",
        )

    secret = decrypt_secret(method.encrypted_secret)
    if not pyotp.TOTP(secret).verify(verify_request.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    user = await db.get(User, current_user.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    method.status = MFAMethodStatus.ACTIVE
    method.verified_at = datetime.now(UTC)
    user.mfa_enabled = True
    await db.flush()

    return MFAVerifyResponse(success=True, recovery_codes=None)


@router.delete("", status_code=status.HTTP_200_OK)
@router.post("/disable", status_code=status.HTTP_200_OK)
@limiter.limit(RateLimits.MFA)
async def remove_mfa(
    request: Request,
    remove_request: MFARemoveRequest,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> dict:
    """
    Remove MFA enrollment.

    Requires either current password or MFA code for verification.

    Args:
        remove_request: Removal request with password or MFA code

    Returns:
        Success message

    Raises:
        HTTPException: MFA not configured or invalid code
    """
    logger.info(f"MFA removal requested for user: {current_user.email}")

    method = await _get_totp_method(db, current_user.user_id, MFAMethodStatus.ACTIVE)
    if method is None or method.encrypted_secret is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled",
        )

    code = remove_request.mfa_code or remove_request.code
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code is required",
        )

    secret = decrypt_secret(method.encrypted_secret)
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    user = await db.get(User, current_user.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    method.status = MFAMethodStatus.DISABLED
    user.mfa_enabled = False
    await db.execute(delete(MFARecoveryCode).where(MFARecoveryCode.user_id == current_user.user_id))
    await db.flush()

    return {"success": True, "message": "MFA disabled"}


@router.post("/backup-codes", status_code=status.HTTP_200_OK)
@limiter.limit(RateLimits.MFA)
async def regenerate_backup_codes(
    request: Request,
    current_user: CurrentActiveUser,
    db: DbSession,
) -> dict:
    """Regenerate recovery codes for a user with active MFA."""
    method = await _get_totp_method(db, current_user.user_id, MFAMethodStatus.ACTIVE)
    if method is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled",
        )

    backup_codes = _generate_recovery_codes()
    await db.execute(delete(MFARecoveryCode).where(MFARecoveryCode.user_id == current_user.user_id))
    _add_recovery_codes(db, current_user.user_id, backup_codes)
    await db.flush()

    return {"backup_codes": backup_codes}


async def _get_totp_method(
    db: DbSession,
    user_id,
    method_status: MFAMethodStatus,
) -> UserMFAMethod | None:
    result = await db.execute(
        select(UserMFAMethod)
        .where(
            UserMFAMethod.user_id == user_id,
            UserMFAMethod.method_type == MFAMethodType.TOTP,
            UserMFAMethod.status == method_status,
        )
        .order_by(UserMFAMethod.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _has_active_totp_method(db: DbSession, user_id) -> bool:
    return await _get_totp_method(db, user_id, MFAMethodStatus.ACTIVE) is not None


async def _count_unused_recovery_codes(db: DbSession, user_id) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(MFARecoveryCode)
        .where(
            MFARecoveryCode.user_id == user_id,
            MFARecoveryCode.is_used.is_(False),
        )
    )
    return int(result.scalar_one())


async def _delete_existing_totp_state(db: DbSession, user_id) -> None:
    await db.execute(
        delete(UserMFAMethod).where(
            UserMFAMethod.user_id == user_id,
            UserMFAMethod.method_type == MFAMethodType.TOTP,
        )
    )
    await db.execute(delete(MFARecoveryCode).where(MFARecoveryCode.user_id == user_id))


def _generate_recovery_codes() -> list[str]:
    return [
        f"{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
        for _ in range(RECOVERY_CODE_COUNT)
    ]


def _add_recovery_codes(db: DbSession, user_id, recovery_codes: list[str]) -> None:
    for code in recovery_codes:
        db.add(
            MFARecoveryCode(
                user_id=user_id,
                code_hash=get_password_hash(code),
            )
        )


def _build_qr_code_data_url(provisioning_uri: str) -> str:
    image = qrcode.make(provisioning_uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/svg+xml;base64,{encoded}"
