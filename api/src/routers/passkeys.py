"""
Passkey/WebAuthn Router

Provides endpoints for passkey-based passwordless authentication:
- Registration: Generate options and verify credential
- Authentication: Generate challenge and verify (returns JWT tokens)
- Management: List and delete passkeys

Passkeys provide two-factor authentication in one step:
- Something you have: Device with private key
- Something you are: Biometric (Face ID, Touch ID) or PIN
"""

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status

from src.core.auth import CurrentActiveUser, UserPrincipal
from src.core.database import DbSession
from src.core.log_sanitize import sanitize_log_value
from src.core.rate_limiting import RateLimits, limiter
from src.core.security import create_access_token, create_refresh_token
from src.models.contracts.auth import LoginResponse
from src.models.contracts.passkeys import (
    PasskeyAuthOptionsRequest,
    PasskeyAuthOptionsResponse,
    PasskeyAuthVerifyRequest,
    PasskeyDeleteResponse,
    PasskeyListResponse,
    PasskeyPublic,
    PasskeyRegistrationOptionsRequest,
    PasskeyRegistrationOptionsResponse,
    PasskeyRegistrationVerifyRequest,
    PasskeyRegistrationVerifyResponse,
)
from src.models.enums import AuditAction
from src.routers.auth import set_auth_cookies
from src.services.audit_service import get_audit_service
from src.services.passkey_service import PasskeyService, PasskeyValidationError, UserPasskey

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/passkeys", tags=["passkeys"])


def _to_public(passkey: UserPasskey) -> PasskeyPublic:
    """Convert UserPasskey ORM model to public response."""
    return PasskeyPublic.model_validate(passkey)


def _reject_api_key_passkey_enrollment(user: UserPrincipal) -> None:
    """Passkey enrollment is an interactive browser-user flow."""
    if user.api_key_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Passkey enrollment requires interactive user authentication",
        )


# =============================================================================
# Registration Endpoints (Authenticated users adding passkeys)
# =============================================================================


@router.post(
    "/register/options",
    response_model=PasskeyRegistrationOptionsResponse,
    summary="Get passkey registration options",
    description="Generate WebAuthn registration options for creating a new passkey. "
    "Returns a challenge and options that should be passed to navigator.credentials.create().",
)
@limiter.limit(RateLimits.PASSKEY)
async def get_registration_options(
    request: Request,
    registration_request: PasskeyRegistrationOptionsRequest,
    user: CurrentActiveUser,
    db: DbSession,
) -> PasskeyRegistrationOptionsResponse:
    """Generate WebAuthn registration options for the current user."""
    _reject_api_key_passkey_enrollment(user)
    service = PasskeyService(db)

    try:
        options = await service.generate_registration_options(user.user_id)
        return PasskeyRegistrationOptionsResponse(options=options)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(f"Failed to generate registration options for user {user.user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate registration options",
        ) from e


@router.post(
    "/register/verify",
    response_model=PasskeyRegistrationVerifyResponse,
    summary="Verify passkey registration",
    description="Verify the passkey registration response from the browser. "
    "This completes the passkey enrollment process.",
)
@limiter.limit(RateLimits.PASSKEY)
async def verify_registration(
    request: Request,
    registration_request: PasskeyRegistrationVerifyRequest,
    user: CurrentActiveUser,
    db: DbSession,
) -> PasskeyRegistrationVerifyResponse:
    """Verify and complete passkey registration."""
    _reject_api_key_passkey_enrollment(user)
    service = PasskeyService(db)

    try:
        # Convert credential dict to JSON string for the service
        credential_json = json.dumps(registration_request.credential)

        passkey = await service.verify_registration(
            user_id=user.user_id,
            credential_json=credential_json,
            device_name=registration_request.device_name,
        )

        await db.commit()

        logger.info(f"Passkey registered for user {user.user_id}: {passkey.id}")

        return PasskeyRegistrationVerifyResponse(
            verified=True,
            passkey_id=passkey.id,
            name=passkey.name,
        )
    except PasskeyValidationError as e:
        logger.warning(
            "Invalid passkey registration response for user %s",
            user.user_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid passkey registration response",
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(f"Failed to verify registration for user {user.user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify registration",
        ) from e


# =============================================================================
# Authentication Endpoints (Passwordless login)
# =============================================================================


@router.post(
    "/authenticate/options",
    response_model=PasskeyAuthOptionsResponse,
    summary="Get passkey authentication options",
    description="Generate WebAuthn authentication options for passwordless login. "
    "Returns a challenge that should be passed to navigator.credentials.get(). "
    "If email is provided, limits credentials to that user. "
    "If email is omitted, uses discoverable credentials (passkey autofill).",
)
@limiter.limit(RateLimits.PASSKEY)
async def get_authentication_options(
    request: Request,
    auth_request: PasskeyAuthOptionsRequest,
    db: DbSession,
) -> PasskeyAuthOptionsResponse:
    """Generate WebAuthn authentication options (public endpoint)."""
    service = PasskeyService(db)

    try:
        challenge_id, options = await service.generate_authentication_options(
            email=auth_request.email,
        )

        return PasskeyAuthOptionsResponse(
            challenge_id=challenge_id,
            options=options,
        )
    except Exception as e:
        logger.error(f"Failed to generate authentication options: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate authentication options",
        ) from e


@router.post(
    "/authenticate/verify",
    response_model=LoginResponse,
    summary="Verify passkey authentication",
    description="Verify the passkey authentication response and return JWT tokens. "
    "This is the passwordless login endpoint - no password required.",
)
@limiter.limit(RateLimits.PASSKEY)
async def verify_authentication(
    request: Request,
    auth_request: PasskeyAuthVerifyRequest,
    response: Response,
    db: DbSession,
) -> LoginResponse:
    """Verify passkey authentication and return login tokens (public endpoint)."""
    service = PasskeyService(db)

    try:
        # Convert credential dict to JSON string for the service
        credential_json = json.dumps(auth_request.credential)

        user = await service.verify_authentication(
            challenge_id=auth_request.challenge_id,
            credential_json=credential_json,
        )

        # Audit log - successful passkey login
        audit_service = get_audit_service(db)
        await audit_service.log(
            AuditAction.LOGIN,
            "user",
            user.id,
            actor=UserPrincipal(
                user_id=user.id,
                email=user.email,
                name=user.name or "",
                role=user.role,
            ),
            actor_label="passkey",
        )

        await db.commit()

        logger.info(f"Passkey authentication successful for user {user.id}")

        # Generate login tokens (same as password login)
        return await _generate_login_tokens(user, db, response)

    except PasskeyValidationError as e:
        logger.warning("Invalid passkey authentication response", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid passkey authentication response",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except Exception as e:
        logger.error(f"Failed to verify authentication: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify authentication",
        ) from e


# =============================================================================
# Management Endpoints (Authenticated users managing their passkeys)
# =============================================================================


@router.get(
    "",
    response_model=PasskeyListResponse,
    summary="List user's passkeys",
    description="Get a list of all passkeys registered for the current user.",
)
@limiter.limit(RateLimits.API_GENERAL)
async def list_passkeys(
    request: Request,
    user: CurrentActiveUser,
    db: DbSession,
) -> PasskeyListResponse:
    """List all passkeys for the current user."""
    service = PasskeyService(db)

    passkeys = await service.list_passkeys(user.user_id)

    return PasskeyListResponse(
        passkeys=[_to_public(p) for p in passkeys],
        count=len(passkeys),
    )


@router.delete(
    "/{passkey_id}",
    response_model=PasskeyDeleteResponse,
    summary="Delete a passkey",
    description="Delete a passkey by ID. Users can only delete their own passkeys.",
)
async def delete_passkey(
    passkey_id: UUID,
    user: CurrentActiveUser,
    db: DbSession,
) -> PasskeyDeleteResponse:
    """Delete a passkey owned by the current user."""
    service = PasskeyService(db)

    try:
        deleted = await service.delete_passkey(user.user_id, passkey_id)

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Passkey not found",
            )

        await db.commit()

        logger.info(sanitize_log_value(f"Passkey {passkey_id} deleted for user {user.user_id}"))

        return PasskeyDeleteResponse(
            deleted=True,
            passkey_id=passkey_id,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            sanitize_log_value(
                f"Failed to delete passkey {passkey_id} for user {user.user_id}: {e}"
            )
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete passkey",
        ) from e


# =============================================================================
# Helper Functions
# =============================================================================


async def _generate_login_tokens(user, db: DbSession, response: Response) -> LoginResponse:
    """Generate login tokens for authenticated user."""

    # Update last login
    user.last_login = datetime.now(UTC)
    await db.flush()

    # Build JWT claims
    from src.models.enums import UserRole

    is_admin = user.role in (UserRole.OWNER, UserRole.ADMINISTRATOR)
    roles = ["authenticated"]
    if is_admin:
        roles.append("PlatformAdmin")
    else:
        roles.append("OrgUser")

    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name or user.email.split("@")[0],
        "role": user.role.value,
        "roles": roles,
    }

    # Generate tokens
    access_token = create_access_token(data=token_data)
    refresh_token_str, _jti = create_refresh_token(data={"sub": str(user.id)})

    # Set cookies
    set_auth_cookies(response, access_token, refresh_token_str)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token_str,
    )
