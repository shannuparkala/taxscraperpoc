"""SQLAlchemy ORM models.

Sensitivity annotations
-----------------------
Every column that can hold client data is marked in a comment as one of:

* ``PII``        — holds a real taxpayer value. Encrypted at rest where noted.
* ``TOKENIZED``  — holds mask tokens only; safe to display and to send outbound.
* ``DERIVED``    — hashes, counts, confidences; no recoverable client data.

The only table storing recoverable PII in bulk is ``masking_maps`` (the vault),
and its value column is Fernet-encrypted with a dedicated key.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.models.enums import (
    AuthorityLevel,
    DocumentType,
    FileStatus,
    FilingStatus,
    FilingType,
    Jurisdiction,
    RagDocumentStatus,
    ReviewReason,
    ReviewStatus,
    SourceType,
    StageStatus,
    TemplateStatus,
    WorkflowStage,
    WorkflowStatus,
)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base with a JSON type map suited to SQLite and Postgres."""

    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


# ===========================================================================
# Users & access
# ===========================================================================


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))          # PII (staff)
    full_name: Mapped[str | None] = mapped_column(String(255))      # PII (staff)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # DERIVED
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="preparer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Filing links to users twice (preparer_id, reviewer_id), so the join
    # column has to be named explicitly on both sides.
    filings: Mapped[list[Filing]] = relationship(
        back_populates="preparer", foreign_keys="Filing.preparer_id"
    )


# ===========================================================================
# Filings
# ===========================================================================


class Filing(Base, TimestampMixin):
    """A tax return engagement. The dashboard aggregates over this table."""

    __tablename__ = "filings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # TOKENIZED: a stable pseudonymous label such as "CLIENT_014", never a name.
    client_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    # DERIVED: keyed blind index so the same client can be recognised without
    # storing their name. See core.security.blind_index.
    client_blind_index: Mapped[str | None] = mapped_column(String(64), index=True)

    tax_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    filing_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FilingType.INDIVIDUAL.value, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FilingStatus.DRAFT.value, index=True
    )
    jurisdiction: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Jurisdiction.FEDERAL.value
    )
    state_code: Mapped[str | None] = mapped_column(String(2))

    preparer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )

    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    amended_from_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("filings.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)          # TOKENIZED

    preparer: Mapped[User | None] = relationship(
        back_populates="filings", foreign_keys=[preparer_id]
    )
    files: Mapped[list[UploadedFile]] = relationship(
        back_populates="filing", cascade="all, delete-orphan"
    )
    workflows: Mapped[list[Workflow]] = relationship(back_populates="filing")

    __table_args__ = (
        Index("ix_filings_year_status", "tax_year", "status"),
        Index("ix_filings_type_status", "filing_type", "status"),
    )


# ===========================================================================
# Files & documents
# ===========================================================================


class UploadedFile(Base, TimestampMixin):
    """One uploaded artifact. Bytes live encrypted in the raw zone on disk."""

    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filing_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("filings.id", ondelete="CASCADE"), index=True
    )

    # PII: a client filename can contain a taxpayer name ("Smith W-2.pdf").
    # Displayed to authenticated staff only; never sent to an LLM.
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # DERIVED: opaque on-disk name; what the storage layer actually uses.
    stored_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # DERIVED: SHA-256 of plaintext bytes. Dedupe + chain-of-custody.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FileStatus.UPLOADED.value, index=True
    )
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # DERIVED: sanitised metadata (page count, producer). Author/creator fields
    # are stripped by the ingestion service before this is written.
    file_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    validation_notes: Mapped[str | None] = mapped_column(Text)

    uploaded_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    filing: Mapped[Filing | None] = relationship(back_populates="files")
    documents: Mapped[list[Document]] = relationship(
        back_populates="uploaded_file", cascade="all, delete-orphan"
    )
    workflows: Mapped[list[Workflow]] = relationship(back_populates="uploaded_file")


class Document(Base, TimestampMixin):
    """A logically distinct document detected inside an uploaded file.

    One 40-page workpaper PDF typically splits into many documents: an
    organizer, several W-2s, a brokerage statement, and so on.
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    uploaded_file_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("uploaded_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    document_type: Mapped[str] = mapped_column(
        String(48), nullable=False, default=DocumentType.UNKNOWN_WORKPAPER.value
    )
    classification_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    classification_method: Mapped[str] = mapped_column(String(32), default="rules")

    page_start: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    tax_year: Mapped[int | None] = mapped_column(Integer)
    is_handwritten: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_performed: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_engine: Mapped[str | None] = mapped_column(String(64))
    ocr_mean_confidence: Mapped[float | None] = mapped_column(Float)

    # TOKENIZED: masked text only. The raw OCR text is never persisted to the
    # database — it lives in the masked zone after tokenization, and the raw
    # form exists only in memory during the masking stage.
    masked_text_path: Mapped[str | None] = mapped_column(String(512))
    # DERIVED: hash of the pre-masking text, so re-runs can detect drift.
    source_text_hash: Mapped[str | None] = mapped_column(String(64))
    # TOKENIZED: layout structures (tables, key-values, checkboxes) post-mask.
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    uploaded_file: Mapped[UploadedFile] = relationship(back_populates="documents")
    extractions: Mapped[list[ExtractionResult]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    pii_entities: Mapped[list[PiiEntity]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


# ===========================================================================
# Privacy: detected entities and the token vault
# ===========================================================================


class PiiEntity(Base, TimestampMixin):
    """A detected sensitive span.

    SECURITY: this table records *where* PII was found and *what token* replaced
    it. It deliberately does not store the value. The value lives only in
    ``MaskingMap.encrypted_value``.
    """

    __tablename__ = "pii_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    pii_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    # TOKENIZED
    token: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detector: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    page_number: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    # DERIVED: [x0, y0, x1, y1] in PDF points, for the review-UI highlight box.
    bbox: Mapped[list[Any] | None] = mapped_column(JSON)
    # DERIVED: length of the original span; useful for layout without the value.
    original_length: Mapped[int | None] = mapped_column(Integer)

    document: Mapped[Document] = relationship(back_populates="pii_entities")


class MaskingMap(Base, TimestampMixin):
    """The token vault: token -> encrypted original, plus a fake surrogate.

    SECURITY — the most sensitive table in the system:
      * ``encrypted_value`` is Fernet ciphertext under VAULT_ENCRYPTION_KEY,
        a different key from the one protecting uploaded files.
      * ``value_blind_index`` is a keyed HMAC allowing "seen this before?"
        lookups without plaintext.
      * No API endpoint returns ``encrypted_value``. Only
        ``rehydration_service`` decrypts it, and only when writing the final
        output package.
      * This table must never be serialized into an LLM prompt. There is no
        code path that joins it to an outbound payload.
    """

    __tablename__ = "masking_maps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    filing_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("filings.id", ondelete="CASCADE"), index=True
    )

    token: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    pii_type: Mapped[str] = mapped_column(String(48), nullable=False)
    # PII (encrypted at rest, dedicated key)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    # TOKENIZED: the realistic fake shown to the LLM, e.g. "Robert Miller".
    surrogate_value: Mapped[str] = mapped_column(String(512), nullable=False)
    # DERIVED: HMAC(original) for dedupe within a scope.
    value_blind_index: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        # A token means exactly one value within a workflow.
        UniqueConstraint("workflow_id", "token", name="uq_vault_workflow_token"),
        # The same value always maps to the same token within a workflow, so
        # "Smith" on page 2 and page 30 stay consistent for the model.
        UniqueConstraint(
            "workflow_id", "value_blind_index", name="uq_vault_workflow_value"
        ),
    )


# ===========================================================================
# Workflows
# ===========================================================================


class Workflow(Base, TimestampMixin):
    """One end-to-end run of the nine-stage pipeline over one file."""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    uploaded_file_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("uploaded_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filing_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("filings.id", ondelete="SET NULL"), index=True
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkflowStatus.PENDING.value, index=True
    )
    current_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkflowStage.UPLOAD.value
    )
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # TOKENIZED: user-facing failure summary, PII-free by construction.
    error_summary: Mapped[str | None] = mapped_column(Text)

    documents_detected: Mapped[int] = mapped_column(Integer, default=0)
    pii_entities_masked: Mapped[int] = mapped_column(Integer, default=0)
    review_items_open: Mapped[int] = mapped_column(Integer, default=0)
    overall_confidence: Mapped[float | None] = mapped_column(Float)

    # DERIVED: model tier actually used, token counts, latency. No content.
    llm_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    triggered_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )

    uploaded_file: Mapped[UploadedFile] = relationship(back_populates="workflows")
    filing: Mapped[Filing | None] = relationship(back_populates="workflows")
    stages: Mapped[list[WorkflowStageRun]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStageRun.stage_index",
    )
    review_items: Mapped[list[ReviewItem]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    output_packages: Mapped[list[OutputPackage]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )


class WorkflowStageRun(Base, TimestampMixin):
    """Execution record for a single pipeline stage. Powers the UI timeline."""

    __tablename__ = "workflow_stage_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=StageStatus.PENDING.value
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # TOKENIZED / DERIVED: counters and token references only.
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)

    workflow: Mapped[Workflow] = relationship(back_populates="stages")

    __table_args__ = (
        UniqueConstraint("workflow_id", "stage", name="uq_stage_per_workflow"),
    )


class ExtractionResult(Base, TimestampMixin):
    """One extracted tax fact.

    SECURITY: ``masked_value`` is what the LLM saw and what the UI displays.
    The real value is recoverable only by rehydrating tokens through the vault
    at output time.
    """

    __tablename__ = "extraction_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )

    field_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    field_label: Mapped[str | None] = mapped_column(String(255))
    # TOKENIZED
    masked_value: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(String(255))
    value_type: Mapped[str] = mapped_column(String(32), default="string")

    confidence: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    extraction_method: Mapped[str] = mapped_column(String(48), default="llm")
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_bbox: Mapped[list[Any] | None] = mapped_column(JSON)
    # TOKENIZED: the masked snippet the value came from, for reviewer context.
    source_snippet: Mapped[str | None] = mapped_column(Text)

    # Target mapping produced by template learning.
    target_form: Mapped[str | None] = mapped_column(String(64))
    target_line: Mapped[str | None] = mapped_column(String(64))

    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_status: Mapped[str | None] = mapped_column(String(32))
    validation_message: Mapped[str | None] = mapped_column(Text)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    document: Mapped[Document] = relationship(back_populates="extractions")


# ===========================================================================
# Human review
# ===========================================================================


class ReviewItem(Base, TimestampMixin):
    __tablename__ = "review_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE")
    )
    extraction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("extraction_results.id", ondelete="CASCADE")
    )
    learned_template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("learned_templates.id", ondelete="CASCADE")
    )

    reason: Mapped[str] = mapped_column(
        String(48), nullable=False, default=ReviewReason.LOW_CONFIDENCE.value, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ReviewStatus.PENDING.value, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 highest

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)      # TOKENIZED
    field_name: Mapped[str | None] = mapped_column(String(160))
    # TOKENIZED: all three of the below carry masked content only.
    masked_source_snippet: Mapped[str | None] = mapped_column(Text)
    proposed_value: Mapped[str | None] = mapped_column(Text)
    corrected_value: Mapped[str | None] = mapped_column(Text)

    confidence: Mapped[float | None] = mapped_column(Float)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_bbox: Mapped[list[Any] | None] = mapped_column(JSON)

    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_notes: Mapped[str | None] = mapped_column(Text)

    workflow: Mapped[Workflow | None] = relationship(back_populates="review_items")


# ===========================================================================
# Chatbot
# ===========================================================================


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation")

    # Default research context; individual messages may override.
    jurisdiction: Mapped[str] = mapped_column(
        String(16), default=Jurisdiction.FEDERAL.value
    )
    state_code: Mapped[str | None] = mapped_column(String(2))
    tax_year: Mapped[int | None] = mapped_column(Integer)
    taxpayer_type: Mapped[str | None] = mapped_column(String(32))

    message_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # TOKENIZED: user questions are masked before storage and before retrieval,
    # so a preparer pasting a client's SSN into the chat does not persist it.
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured assistant answer (see schemas.chat.TaxAnswer).
    short_answer: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    tax_rule: Mapped[str | None] = mapped_column(Text)
    clarifying_questions: Mapped[list[Any] | None] = mapped_column(JSON)
    escalation_note: Mapped[str | None] = mapped_column(Text)

    confidence_level: Mapped[str | None] = mapped_column(String(16))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    jurisdiction: Mapped[str | None] = mapped_column(String(16))
    state_code: Mapped[str | None] = mapped_column(String(2))
    tax_year: Mapped[int | None] = mapped_column(Integer)

    model_tier: Mapped[str | None] = mapped_column(String(16))
    model_name: Mapped[str | None] = mapped_column(String(96))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    retrieval_hit_count: Mapped[int | None] = mapped_column(Integer)
    # DERIVED: true when the user's text contained PII that we masked.
    was_masked: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
    citations: Mapped[list[Citation]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


# ===========================================================================
# RAG knowledge base
# ===========================================================================


class RagDocument(Base, TimestampMixin):
    """An indexed knowledge source. Public tax authority — contains no client PII."""

    __tablename__ = "rag_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_url: Mapped[str | None] = mapped_column(String(1024), index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(48), nullable=False, default=SourceType.WEB_PAGE.value
    )
    authority_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AuthorityLevel.SECONDARY.value, index=True
    )
    jurisdiction: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Jurisdiction.FEDERAL.value, index=True
    )
    state_code: Mapped[str | None] = mapped_column(String(2), index=True)
    tax_year: Mapped[int | None] = mapped_column(Integer, index=True)
    document_type: Mapped[str | None] = mapped_column(String(64))

    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieval_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=RagDocumentStatus.PENDING.value, index=True
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    # Free-form provenance: publication number, IRC section, docket number.
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    chunks: Mapped[list[RagChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_rag_docs_jurisdiction_year", "jurisdiction", "tax_year"),
    )


class RagChunk(Base, TimestampMixin):
    __tablename__ = "rag_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rag_document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("rag_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    # Anchor for citation display: section heading, page, or paragraph.
    section_path: Mapped[str | None] = mapped_column(String(512))
    page_number: Mapped[int | None] = mapped_column(Integer)
    # Vector lives in the vector store, keyed by this chunk's id.
    embedding_id: Mapped[str | None] = mapped_column(String(64), index=True)
    has_embedding: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped[RagDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("rag_document_id", "chunk_index", name="uq_chunk_index"),
    )


class Citation(Base, TimestampMixin):
    """A source passage actually used to ground an assistant answer."""

    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    rag_chunk_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rag_chunks.id", ondelete="SET NULL")
    )
    rag_document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rag_documents.id", ondelete="SET NULL")
    )

    display_index: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    authority_level: Mapped[str | None] = mapped_column(String(32))
    section_path: Mapped[str | None] = mapped_column(String(512))
    quoted_text: Mapped[str | None] = mapped_column(Text)
    relevance_score: Mapped[float | None] = mapped_column(Float)

    message: Mapped[ChatMessage | None] = relationship(back_populates="citations")


class AssistantAnswerRecord(Base, TimestampMixin):
    """The full structured answer behind one assistant ``ChatMessage``.

    A separate table rather than new columns on ``chat_messages``: the schema
    is created with ``create_all``, which adds tables but never columns, so a
    new column would break every existing database.

    TOKENIZED: ``payload`` is stored exactly as generated - masked. It is
    un-masked only per request, for display, and never written back.
    """

    __tablename__ = "assistant_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str | None] = mapped_column(String(48))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    #: Issue codes from each attempt, e.g. [["wrong_state"], []]. No content.
    validation: Mapped[list[Any] | None] = mapped_column(JSON)


# ===========================================================================
# Template learning
# ===========================================================================


class LearnedTemplate(Base, TimestampMixin):
    """A transformation pattern inferred from an input/output document pair.

    SECURITY: templates describe *structure* — "organizer field X maps to 1040
    line Y" — and must never embed observed client values. ``sample_evidence``
    stores masked snippets only.
    """

    __tablename__ = "learned_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_document_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    output_document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    filing_type: Mapped[str] = mapped_column(
        String(32), default=FilingType.INDIVIDUAL.value, index=True
    )
    tax_year: Mapped[int | None] = mapped_column(Integer, index=True)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=TemplateStatus.PROPOSED.value, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)

    # The learned mapping rules: field -> target form/line, normalisation,
    # rounding, aggregation. See schemas.templates.TemplateRule.
    rules: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # TOKENIZED: masked before/after fragments justifying each rule.
    sample_evidence: Mapped[list[Any] | None] = mapped_column(JSON)

    pair_count: Mapped[int] = mapped_column(Integer, default=1)
    support: Mapped[float] = mapped_column(Float, default=0.0)     # 0-1 coverage
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # DERIVED: hashes of the source files, so provenance is auditable without
    # storing filenames that may contain client names.
    source_pair_hashes: Mapped[list[Any] | None] = mapped_column(JSON)

    approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    times_applied: Mapped[int] = mapped_column(Integer, default=0)


# ===========================================================================
# Output
# ===========================================================================


class OutputPackage(Base, TimestampMixin):
    """A generated deliverable in the output zone."""

    __tablename__ = "output_packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(48), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64))

    # True once vault tokens were substituted back to real values. Such files
    # contain PII and are access-controlled + audit-logged on download.
    is_rehydrated: Mapped[bool] = mapped_column(Boolean, default=False)
    tokens_rehydrated: Mapped[int] = mapped_column(Integer, default=0)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workflow: Mapped[Workflow] = relationship(back_populates="output_packages")


# ===========================================================================
# Audit
# ===========================================================================


class AuditEvent(Base):
    """Append-only, hash-chained audit record. See core.audit."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info", index=True)

    actor_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    entity_type: Mapped[str | None] = mapped_column(String(48), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)

    # TOKENIZED: enforced by core.audit._assert_clean before insert.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, index=True
    )
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (Index("ix_audit_action_time", "action", "occurred_at"),)


# ===========================================================================
# Usage quotas
# ===========================================================================


class UsageCounter(Base):
    """One day's request count for one scope and route group.

    DERIVED: a count and an opaque scope key. Carries no client data.

    Persisted rather than held in memory because the in-process limiter in
    ``core.rate_limit`` resets whenever the process does, and a free-tier host
    that sleeps an idle service restarts it several times a day. A daily cap
    that forgets itself on every cold start is not a cap. The row survives a
    restart; only a redeploy that replaces the database clears it.
    """

    __tablename__ = "usage_counters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    #: "global" for the whole deployment, or "client:<user id or address>".
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Route group being counted: "upload", "chat", or "default".
    route_group: Mapped[str] = mapped_column(String(32), nullable=False)
    #: UTC calendar day, "YYYY-MM-DD". A fixed window, not a rolling one:
    #: a quota a tester can reason about beats one that is strictly fairer.
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("scope", "route_group", "day", name="uq_usage_window"),
        Index("ix_usage_day", "day"),
    )



# ===========================================================================
# LLM cost ledger
# ===========================================================================


class LlmCall(Base):
    """One model call: which return and stage it served, and what it cost.

    DERIVED: token counts, model names and opaque ids. SECURITY: never the
    prompt or the reply - a cost ledger is read by people who have no reason to
    see client content, and it is kept longer than the content it describes.

    Not foreign keys: a call made for a workflow that is later deleted is still
    money that was spent, and the ledger should still add up.
    """

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False, index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(String(36), index=True)
    chat_session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    #: Pipeline stage, "calculation_report", "chat" - or the task when the
    #: caller declared no scope, so an unattributed call is still visible.
    stage: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task: Mapped[str] = mapped_column(String(48), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    #: As the API's usage fields report them. ``input_tokens`` includes
    #: ``cached_tokens``; ``thinking_tokens`` is billed as output.
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    thinking_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    stub: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Decimal as text, fixed at call time. None means the price file had no
    #: rate for this model - "unpriced", never an estimate.
    cost_usd: Mapped[str | None] = mapped_column(String(32))
    #: The price file's date, so a figure can always say what rates made it.
    prices_as_of: Mapped[str] = mapped_column(String(32), nullable=False, default="")

# ===========================================================================
# Associate workspace: clients, custom deadlines, bookmarks
# ===========================================================================


class WorkspaceClient(Base, TimestampMixin):
    """A client on an associate's calendar.

    SECURITY: the name and notes are encrypted at rest (``encrypt_text``) and
    are never logged or sent to a model. There is deliberately no field for an
    SSN, EIN, account number or address: the calendar needs none of them, and a
    field that does not exist cannot leak. Rows are scoped to ``owner_id``.
    """

    __tablename__ = "workspace_clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name_encrypted: Mapped[str] = mapped_column(Text, nullable=False)        # PII (encrypted)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Month the tax year ends (12 = calendar year). The year ends on that
    #: month's last day; 52-53 week years are not modelled.
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    states: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    #: "not_extended" or "extended" - for the return currently being prepared.
    extension_status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_extended")
    notes_encrypted: Mapped[str | None] = mapped_column(Text)               # PII (encrypted)


class CustomDeadline(Base, TimestampMixin):
    """A deadline or task an associate added by hand."""

    __tablename__ = "custom_deadlines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workspace_clients.id", ondelete="CASCADE"), index=True
    )
    due_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    title_encrypted: Mapped[str] = mapped_column(Text, nullable=False)       # may name a client
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="deadline")  # deadline | task
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class NewsBookmark(Base, TimestampMixin):
    """An Industry Updates item an associate saved. Public metadata only."""

    __tablename__ = "news_bookmarks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    published: Mapped[str] = mapped_column(String(10), nullable=False, default="")


#: Import-time convenience for tests and tooling.
ALL_TABLES = (
    User, Filing, UploadedFile, Document, PiiEntity, MaskingMap, Workflow,
    WorkflowStageRun, ExtractionResult, ReviewItem, ChatSession, ChatMessage,
    RagDocument, RagChunk, Citation, LearnedTemplate, OutputPackage, AuditEvent,
    UsageCounter, LlmCall, WorkspaceClient, CustomDeadline, NewsBookmark,
)
