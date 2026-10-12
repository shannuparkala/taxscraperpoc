"""Audit log inspection and chain verification."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import AuditDep, DbSession, role_required
from app.core.config import Role
from app.core.logging import get_logger
from app.core.security import Principal
from app.models.database_models import AuditEvent
from app.schemas.api import AuditEventOut, AuditListResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/events", response_model=AuditListResponse)
def list_events(
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.READONLY),
    action: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    verify: bool = Query(
        default=False,
        description="Recompute the hash chain. Slower on large logs.",
    ),
) -> AuditListResponse:
    """List audit events, newest first.

    SECURITY: audit payloads are token-only by construction — ``core.audit``
    rejects any payload containing patterned PII before it is written — so this
    endpoint is safe for any authenticated role to read.
    """
    stmt = select(AuditEvent)
    count_stmt = select(func.count()).select_from(AuditEvent)

    for column, value in (
        (AuditEvent.action, action),
        (AuditEvent.severity, severity),
        (AuditEvent.entity_type, entity_type),
        (AuditEvent.entity_id, entity_id),
    ):
        if value:
            stmt = stmt.where(column == value)
            count_stmt = count_stmt.where(column == value)

    total = int(session.execute(count_stmt).scalar_one())
    rows = session.execute(
        stmt.order_by(AuditEvent.sequence.desc()).offset(offset).limit(limit)
    ).scalars()

    chain_valid, broken = (True, [])
    if verify:
        chain_valid, broken = audit.verify_chain()

    return AuditListResponse(
        items=[AuditEventOut.model_validate(r) for r in rows],
        total=total,
        chain_valid=chain_valid,
        broken_sequences=broken,
    )


@router.get("/verify")
def verify_chain(
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.REVIEWER),
) -> dict[str, object]:
    """Recompute the full hash chain and report tampering.

    A broken sequence means an event was altered or deleted after it was
    written. That is a security incident, not a data-quality issue.
    """
    valid, broken = audit.verify_chain()
    total = int(
        session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
    )
    return {
        "chain_valid": valid,
        "events_checked": total,
        "broken_sequences": broken,
        "message": (
            "Audit chain intact; no events were altered or removed."
            if valid
            else (
                f"TAMPERING DETECTED at sequence(s) {broken}. "
                "Investigate immediately — an audit event was modified or "
                "deleted after it was recorded."
            )
        ),
    }


@router.get("/actions")
def list_actions(
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> dict[str, int]:
    """Counts by action, for the audit page's filter chips."""
    rows = session.execute(
        select(AuditEvent.action, func.count())
        .group_by(AuditEvent.action)
        .order_by(func.count().desc())
    ).all()
    return {action: int(count) for action, count in rows}
