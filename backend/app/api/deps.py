"""Shared FastAPI dependencies: auth, services, rate limiting."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.audit import AuditLogger
from app.core.config import Role, Settings, get_settings
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.rate_limit import enforce
from app.core.security import (
    DEV_PRINCIPAL_ID,
    Principal,
    decode_access_token,
    require_role,
)
from app.services.gemini_service import GeminiService
from app.services.llm_egress_guard import EgressGuard
from app.services.quota_service import enforce_daily_quota

logger = get_logger(__name__)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Resolve the caller.

    SECURITY: ``AUTH_DISABLED`` is a development convenience that grants
    ``DEV_DEFAULT_ROLE`` to every caller. ``config.validate_production_posture``
    refuses to start the process if it is still true in production, so this
    branch cannot be reached in a production deployment.
    """
    settings = get_settings()

    if settings.auth_disabled:
        return Principal(
            user_id=DEV_PRINCIPAL_ID,
            username="dev",
            role=settings.dev_default_role,
        )

    from app.core.errors import AuthenticationError

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("A bearer token is required.")
    return decode_access_token(authorization.split(" ", 1)[1].strip())


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def _client_id(request: Request, principal: Principal) -> str:
    if principal.user_id and principal.user_id != DEV_PRINCIPAL_ID:
        return principal.user_id
    client = request.client
    return client.host if client else "unknown"


def client_scope_for(request: Request, principal: Principal) -> str:
    """The quota scope key this caller is charged against.

    Public so that the status endpoint reports the same bucket the limiter
    increments. Reading a different key than the one being charged is the
    obvious way for a usage display to be confidently wrong.
    """
    return f"client:{_client_id(request, principal)}"


def rate_limit_anonymous(group: str):
    """Rate limit a route that cannot require a principal.

    Sign-in is the one such route, and it is a bootstrap deadlock without this:
    the normal dependency resolves ``CurrentPrincipal`` to build the limiter
    key, which needs a bearer token, which is what the caller came to obtain.
    A token holder could never sign in and nobody else could either.

    Keyed on the client address alone. That is a weaker identity than a user
    id — a shared office NAT is one key — but it is the only one available
    before authentication, and the limit exists here to blunt credential
    stuffing rather than to apportion a budget fairly.
    """

    def dependency(request: Request) -> None:
        client = request.client
        client_id = client.host if client else "unknown"
        enforce(group, client_id)
        enforce_daily_quota(group, client_id)

    return Depends(dependency)


def rate_limit(group: str):
    """Build a dependency enforcing both limits for ``group``.

    Two ceilings, checked cheapest first: the in-memory per-minute burst
    limiter, then the durable daily quota. A client hammering the endpoint is
    turned away without a database round trip; only a request that clears the
    burst check costs a read of the day's counters.
    """

    def dependency(request: Request, principal: CurrentPrincipal) -> None:
        client_id = _client_id(request, principal)
        enforce(group, client_id)
        enforce_daily_quota(group, client_id)

    return Depends(dependency)


def role_required(minimum: Role):
    """Build a dependency requiring at least ``minimum`` privilege."""

    def dependency(
        principal: CurrentPrincipal, session: DbSession
    ) -> Principal:
        from app.core.audit import AuditAction
        from app.core.errors import AuthorizationError

        try:
            require_role(principal, minimum)
        except AuthorizationError:
            AuditLogger(session).record(
                AuditAction.ACCESS_DENIED,
                actor_id=principal.user_id,
                actor_role=principal.role.value,
                payload={"required_role": minimum.value},
            )
            raise
        return principal

    return Depends(dependency)


def get_audit(session: DbSession) -> AuditLogger:
    return AuditLogger(session)


AuditDep = Annotated[AuditLogger, Depends(get_audit)]


def get_settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]



def get_gemini_service(audit: AuditDep, session: DbSession) -> GeminiService:
    """Build a Gemini client with a strict egress guard.

    SECURITY: no surrogate allow-list is supplied here, because this instance
    serves the chatbot, where content is masked at the route before it arrives.
    A strict guard is the correct default; the workflow orchestrator constructs
    its own guard that knows that workflow's surrogates.
    """
    from app.services.llm_meter import DbLlmMeter

    return GeminiService(
        guard=EgressGuard(audit=audit), audit=audit, meter=DbLlmMeter(session)
    )


GeminiDep = Annotated[GeminiService, Depends(get_gemini_service)]
