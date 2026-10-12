"""Sign-in.

The JWT machinery, the ``users`` table and the role checks all existed before
this module did; what was missing was a way to obtain a token. That gap was
invisible in development, where ``AUTH_DISABLED=true`` hands every caller the
dev principal, and fatal anywhere else: ``validate_production_posture`` refuses
to start with auth disabled, so a deployed instance had no route in at all.

SECURITY: a failed sign-in says only that the credentials were wrong. It never
distinguishes an unknown username from a bad password, and never says whether
an account exists but is disabled — each of those answers turns the endpoint
into a way to enumerate staff. Attempts are rate limited on the default group
and every outcome is audited.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import (
    AuditDep,
    CurrentPrincipal,
    DbSession,
    rate_limit_anonymous,
)
from app.core.audit import AuditAction
from app.core.config import Role, get_settings
from app.core.errors import AuthenticationError
from app.core.logging import get_logger
from app.core.security import (
    DEV_PRINCIPAL_ID,
    Principal,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.database_models import User
from app.schemas.api import LoginRequest, PrincipalOut, TokenOut

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: A well-formed hash of a value nobody knows. Verifying against it keeps the
#: cost of a failed sign-in the same whether or not the account exists, so the
#: endpoint cannot be used to enumerate staff with a stopwatch. Built once at
#: import, because the KDF is deliberately slow.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


@router.post(
    "/login",
    response_model=TokenOut,
    dependencies=[rate_limit_anonymous("default")],
)
def login(
    payload: LoginRequest,
    session: DbSession,
    audit: AuditDep,
) -> TokenOut:
    """Exchange a username and password for a bearer token."""
    settings = get_settings()

    # Case-insensitive, because a username is an identifier a person types.
    user = session.execute(
        select(User).where(func.lower(User.username) == payload.username.strip().lower())
    ).scalar_one_or_none()

    # SECURITY: verify the password even when the user is missing or has no
    # hash, so the endpoint takes the same time either way. Skipping the KDF on
    # an unknown username makes the two cases distinguishable by a stopwatch.
    stored = (user.password_hash if user else None) or _DUMMY_HASH
    password_ok = verify_password(payload.password, stored)

    if user is None or not user.password_hash or not password_ok or not user.is_active:
        logger.info("Sign-in refused")
        audit.record(
            AuditAction.AUTH_FAILED,
            entity_type="user",
            entity_id=user.id if user else None,
            payload={"outcome": "refused"},
        )
        raise AuthenticationError("Incorrect username or password.")

    principal = Principal(
        user_id=user.id, username=user.username, role=Role(user.role)
    )
    token = create_access_token(principal)

    audit.record(
        AuditAction.AUTH_SUCCEEDED,
        actor_id=user.id,
        actor_role=user.role,
        entity_type="user",
        entity_id=user.id,
        payload={"outcome": "granted"},
    )
    logger.info("Sign-in granted with role '%s'", user.role)

    return TokenOut(
        access_token=token,
        token_type="bearer",
        expires_in_minutes=settings.jwt_expire_minutes,
        username=user.username,
        role=user.role,
    )


@router.get("/me", response_model=PrincipalOut)
def me(principal: CurrentPrincipal, session: DbSession) -> PrincipalOut:
    """Who the bearer token says you are. Used by the UI to restore a session."""
    user = session.get(User, principal.user_id)
    full_name = (user.full_name or "").strip() if user else ""
    if principal.user_id == DEV_PRINCIPAL_ID:
        # The development login is seeded as "Development User"; greet it by
        # the configured name instead (DEV_DISPLAY_NAME), on new databases
        # and ones seeded before the setting existed alike.
        full_name = get_settings().dev_display_name.strip() or full_name
    return PrincipalOut(
        user_id=principal.user_id,
        username=principal.username,
        role=principal.role.value,
        first_name=full_name.split()[0] if full_name else principal.username,
    )
