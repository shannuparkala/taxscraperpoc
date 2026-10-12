"""Human-in-the-loop review queue."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import AuditDep, DbSession, role_required
from app.core.audit import AuditAction
from app.core.config import Role
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.security import Principal
from app.models.database_models import ExtractionResult, ReviewItem, Workflow
from app.models.enums import ReviewStatus
from app.schemas.api import (
    ReviewDecisionRequest,
    ReviewEditRequest,
    ReviewItemOut,
    ReviewQueueResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/queue", response_model=ReviewQueueResponse)
def review_queue(
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
    item_status: str | None = Query(default=ReviewStatus.PENDING.value, alias="status"),
    workflow_id: str | None = Query(default=None),
    reason: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> ReviewQueueResponse:
    """List items awaiting a decision, highest priority first."""
    stmt = select(ReviewItem)
    if item_status:
        stmt = stmt.where(ReviewItem.status == item_status)
    if workflow_id:
        stmt = stmt.where(ReviewItem.workflow_id == workflow_id)
    if reason:
        stmt = stmt.where(ReviewItem.reason == reason)

    rows = list(
        session.execute(
            stmt.order_by(
                ReviewItem.priority.asc(), ReviewItem.created_at.asc()
            ).limit(limit)
        ).scalars()
    )
    total = session.execute(select(func.count()).select_from(ReviewItem)).scalar_one()
    pending = session.execute(
        select(func.count())
        .select_from(ReviewItem)
        .where(ReviewItem.status == ReviewStatus.PENDING.value)
    ).scalar_one()

    return ReviewQueueResponse(
        items=[ReviewItemOut.model_validate(r) for r in rows],
        total=total,
        pending=pending,
    )


@router.get("/{item_id}", response_model=ReviewItemOut)
def get_item(
    item_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> ReviewItemOut:
    item = session.get(ReviewItem, item_id)
    if item is None:
        raise NotFoundError("No such review item.")
    return ReviewItemOut.model_validate(item)


@router.post("/{item_id}/approve", response_model=ReviewItemOut)
def approve(
    item_id: str,
    payload: ReviewDecisionRequest,
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.REVIEWER),
) -> ReviewItemOut:
    """Accept the proposed value as correct."""
    item = _claim(session, item_id)
    item.status = ReviewStatus.APPROVED.value
    item.reviewed_by = principal.user_id
    item.reviewed_at = datetime.now(UTC)
    item.reviewer_notes = payload.notes

    if item.extraction_id:
        extraction = session.get(ExtractionResult, item.extraction_id)
        if extraction is not None:
            extraction.requires_review = False
            extraction.is_validated = True
            extraction.validation_status = "approved"

    _decrement_open_count(session, item)
    audit.record(
        AuditAction.REVIEW_APPROVED,
        actor_id=principal.user_id,
        actor_role=principal.role.value,
        entity_type="review_item",
        entity_id=item.id,
        payload={"reason": item.reason, "field": item.field_name},
    )
    return ReviewItemOut.model_validate(item)


@router.post("/{item_id}/reject", response_model=ReviewItemOut)
def reject(
    item_id: str,
    payload: ReviewDecisionRequest,
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.REVIEWER),
) -> ReviewItemOut:
    """Reject the proposed value. The extraction stays flagged."""
    item = _claim(session, item_id)
    item.status = ReviewStatus.REJECTED.value
    item.reviewed_by = principal.user_id
    item.reviewed_at = datetime.now(UTC)
    item.reviewer_notes = payload.notes

    if item.extraction_id:
        extraction = session.get(ExtractionResult, item.extraction_id)
        if extraction is not None:
            # Stays under review: a rejected value must not silently flow into
            # an output package.
            extraction.is_validated = False
            extraction.requires_review = True
            extraction.validation_status = "rejected"

    _decrement_open_count(session, item)
    audit.record(
        AuditAction.REVIEW_REJECTED,
        actor_id=principal.user_id,
        actor_role=principal.role.value,
        entity_type="review_item",
        entity_id=item.id,
        payload={"reason": item.reason, "field": item.field_name},
    )
    return ReviewItemOut.model_validate(item)


@router.post("/{item_id}/edit", response_model=ReviewItemOut)
def edit(
    item_id: str,
    payload: ReviewEditRequest,
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.REVIEWER),
) -> ReviewItemOut:
    """Replace the proposed value with a reviewer-supplied correction.

    SECURITY: the corrected value is stored as given. Reviewers work in the
    masked view, so a correction normally references surrogates or tokens and
    rehydration handles it. A reviewer who types a real value creates real PII
    in this column — acceptable, since it is their own authenticated decision,
    and the row is covered by the same retention policy.
    """
    item = _claim(session, item_id)
    item.status = ReviewStatus.EDITED.value
    item.corrected_value = payload.corrected_value
    item.reviewed_by = principal.user_id
    item.reviewed_at = datetime.now(UTC)
    item.reviewer_notes = payload.notes

    if item.extraction_id:
        extraction = session.get(ExtractionResult, item.extraction_id)
        if extraction is not None:
            extraction.masked_value = payload.corrected_value
            extraction.normalized_value = payload.corrected_value[:255]
            extraction.requires_review = False
            extraction.is_validated = True
            extraction.validation_status = "corrected"
            extraction.extraction_method = "human_corrected"
            # A human-supplied value is authoritative.
            extraction.confidence = 1.0

    _decrement_open_count(session, item)
    audit.record(
        AuditAction.REVIEW_EDITED,
        actor_id=principal.user_id,
        actor_role=principal.role.value,
        entity_type="review_item",
        entity_id=item.id,
        # SECURITY: record that a correction happened and its length, never the
        # corrected value itself.
        payload={
            "reason": item.reason,
            "field": item.field_name,
            "correction_length": len(payload.corrected_value),
        },
    )
    return ReviewItemOut.model_validate(item)


def _claim(session, item_id: str) -> ReviewItem:
    item = session.get(ReviewItem, item_id)
    if item is None:
        raise NotFoundError("No such review item.")
    if item.status != ReviewStatus.PENDING.value:
        raise ConflictError(
            f"This item was already {item.status}. Reopen it before deciding again."
        )
    return item


def _decrement_open_count(session, item: ReviewItem) -> None:
    if not item.workflow_id:
        return
    workflow = session.get(Workflow, item.workflow_id)
    if workflow is not None and workflow.review_items_open:
        workflow.review_items_open = max(0, workflow.review_items_open - 1)
