"""Dashboard aggregation endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession, role_required
from app.core.config import Role
from app.core.logging import get_logger
from app.core.security import Principal
from app.models.database_models import (
    AuditEvent,
    ChatMessage,
    Document,
    ExtractionResult,
    Filing,
    RagDocument,
    ReviewItem,
    UploadedFile,
    Workflow,
)
from app.models.enums import (
    ChatRole,
    FilingStatus,
    FilingType,
    RagDocumentStatus,
    ReviewStatus,
    WorkflowStatus,
)
from app.schemas.api import (
    AuditPreviewOut,
    ConfidenceBucket,
    DashboardSummaryOut,
    ExceptionOut,
    RecentChatOut,
    RecentUploadOut,
    StatusCount,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_STATUS_LABELS = {
    FilingStatus.DRAFT: "Draft",
    FilingStatus.IN_REVIEW: "In Review",
    FilingStatus.AWAITING_CLIENT_INFO: "Awaiting Client Info",
    FilingStatus.READY_TO_FILE: "Ready to File",
    FilingStatus.FILED: "Filed",
    FilingStatus.REJECTED: "Rejected",
    FilingStatus.AMENDED: "Amended",
}

_TYPE_LABELS = {
    FilingType.INDIVIDUAL: "Individual",
    FilingType.PARTNERSHIP: "Partnership",
    FilingType.S_CORP: "S-Corp",
    FilingType.C_CORP: "C-Corp",
    FilingType.TRUST_ESTATE: "Trust/Estate",
    FilingType.PAYROLL: "Payroll",
    FilingType.SALES_TAX: "Sales Tax",
    FilingType.STATE_LOCAL: "State/Local",
    FilingType.OTHER: "Other",
}

_CONFIDENCE_BUCKETS = (
    ("Very low (<50%)", 0.0, 0.5),
    ("Low (50-75%)", 0.5, 0.75),
    ("Medium (75-90%)", 0.75, 0.90),
    ("High (90-98%)", 0.90, 0.98),
    ("Very high (98%+)", 0.98, 1.01),
)


@router.get("/summary", response_model=DashboardSummaryOut)
def summary(
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> DashboardSummaryOut:
    """Aggregate counts for the dashboard.

    Every value is a count or an aggregate — no client data is returned beyond
    filenames, which authenticated staff are entitled to see.
    """
    # --- Filings ------------------------------------------------------------
    status_rows = dict(
        session.execute(
            select(Filing.status, func.count()).group_by(Filing.status)
        ).all()
    )
    by_status = [
        StatusCount(
            key=status.value,
            label=_STATUS_LABELS[status],
            count=int(status_rows.get(status.value, 0)),
        )
        for status in FilingStatus
    ]

    year_rows = session.execute(
        select(Filing.tax_year, func.count())
        .group_by(Filing.tax_year)
        .order_by(Filing.tax_year.desc())
    ).all()
    by_tax_year = [
        StatusCount(key=str(year), label=str(year), count=int(count))
        for year, count in year_rows
    ]

    type_rows = dict(
        session.execute(
            select(Filing.filing_type, func.count()).group_by(Filing.filing_type)
        ).all()
    )
    by_filing_type = [
        StatusCount(
            key=filing_type.value,
            label=_TYPE_LABELS[filing_type],
            count=int(type_rows.get(filing_type.value, 0)),
        )
        for filing_type in FilingType
    ]

    total_returns = int(
        session.execute(select(func.count()).select_from(Filing)).scalar_one()
    )
    total_filed = int(status_rows.get(FilingStatus.FILED.value, 0))

    # --- Workflows ----------------------------------------------------------
    workflows_running = int(
        session.execute(
            select(func.count())
            .select_from(Workflow)
            .where(Workflow.status == WorkflowStatus.RUNNING.value)
        ).scalar_one()
    )
    workflows_awaiting = int(
        session.execute(
            select(func.count())
            .select_from(Workflow)
            .where(Workflow.status == WorkflowStatus.AWAITING_REVIEW.value)
        ).scalar_one()
    )
    open_reviews = int(
        session.execute(
            select(func.count())
            .select_from(ReviewItem)
            .where(ReviewItem.status == ReviewStatus.PENDING.value)
        ).scalar_one()
    )
    documents_processed = int(
        session.execute(select(func.count()).select_from(Document)).scalar_one()
    )
    pii_masked = int(
        session.execute(
            select(func.coalesce(func.sum(Workflow.pii_entities_masked), 0))
        ).scalar_one()
    )

    # --- Confidence distribution -------------------------------------------
    confidences = list(
        session.execute(select(ExtractionResult.confidence)).scalars()
    )
    distribution = [
        ConfidenceBucket(
            label=label,
            lower=lower,
            upper=upper,
            count=sum(1 for c in confidences if c is not None and lower <= c < upper),
        )
        for label, lower, upper in _CONFIDENCE_BUCKETS
    ]

    # --- Recent activity ----------------------------------------------------
    recent_uploads = [
        RecentUploadOut.model_validate(row)
        for row in session.execute(
            select(UploadedFile).order_by(UploadedFile.created_at.desc()).limit(8)
        ).scalars()
    ]

    recent_chats = [
        RecentChatOut(
            id=message.id,
            session_id=message.session_id,
            question=message.content[:200],
            confidence_level=message.confidence_level,
            created_at=message.created_at,
        )
        for message in session.execute(
            select(ChatMessage)
            .where(ChatMessage.role == ChatRole.USER.value)
            .order_by(ChatMessage.created_at.desc())
            .limit(8)
        ).scalars()
    ]

    exceptions = [
        ExceptionOut.model_validate(item)
        for item in session.execute(
            select(ReviewItem)
            .where(ReviewItem.status == ReviewStatus.PENDING.value)
            .order_by(ReviewItem.priority.asc(), ReviewItem.created_at.desc())
            .limit(10)
        ).scalars()
    ]

    audit_preview = [
        AuditPreviewOut.model_validate(event)
        for event in session.execute(
            select(AuditEvent).order_by(AuditEvent.sequence.desc()).limit(10)
        ).scalars()
    ]

    knowledge_sources = int(
        session.execute(
            select(func.count())
            .select_from(RagDocument)
            .where(RagDocument.status == RagDocumentStatus.INDEXED.value)
        ).scalar_one()
    )

    return DashboardSummaryOut(
        total_returns=total_returns,
        total_filed=total_filed,
        by_status=by_status,
        by_tax_year=by_tax_year,
        by_filing_type=by_filing_type,
        workflows_running=workflows_running,
        workflows_awaiting_review=workflows_awaiting,
        open_review_items=open_reviews,
        documents_processed=documents_processed,
        pii_entities_masked=pii_masked,
        confidence_distribution=distribution,
        recent_uploads=recent_uploads,
        recent_chats=recent_chats,
        exceptions=exceptions,
        audit_preview=audit_preview,
        knowledge_sources=knowledge_sources,
        generated_at=datetime.now(UTC),
    )
