"""File upload and listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import (
    AuditDep,
    DbSession,
    rate_limit,
    role_required,
)
from app.core.config import Role
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.security import Principal
from app.models.database_models import UploadedFile
from app.schemas.api import FileListResponse, UploadedFileOut
from app.services.ingestion_service import IngestionService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post(
    "/upload",
    response_model=UploadedFileOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("upload")],
)
def upload_file(
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.PREPARER),
    file: UploadFile = File(...),
    filing_id: str | None = Form(default=None),
) -> UploadedFileOut:
    """Upload a workpaper.

    The file is validated (extension, magic bytes, size), hashed, stripped of
    identifying metadata, encrypted, and stored in the raw zone.
    """
    ingestion = IngestionService(session, audit=audit)
    record = ingestion.store(
        filename=file.filename or "unnamed",
        stream=file.file,
        content_type=file.content_type or "application/octet-stream",
        filing_id=filing_id,
        uploaded_by=principal.user_id,
    )
    return UploadedFileOut.model_validate(record)


@router.get("", response_model=FileListResponse)
def list_files(
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
    filing_id: str | None = Query(default=None),
    file_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> FileListResponse:
    stmt = select(UploadedFile)
    count_stmt = select(func.count()).select_from(UploadedFile)

    if filing_id:
        stmt = stmt.where(UploadedFile.filing_id == filing_id)
        count_stmt = count_stmt.where(UploadedFile.filing_id == filing_id)
    if file_status:
        stmt = stmt.where(UploadedFile.status == file_status)
        count_stmt = count_stmt.where(UploadedFile.status == file_status)

    total = session.execute(count_stmt).scalar_one()
    rows = session.execute(
        stmt.order_by(UploadedFile.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars()

    return FileListResponse(
        items=[UploadedFileOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{file_id}", response_model=UploadedFileOut)
def get_file(
    file_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> UploadedFileOut:
    record = session.get(UploadedFile, file_id)
    if record is None:
        raise NotFoundError("No such file.")
    return UploadedFileOut.model_validate(record)
