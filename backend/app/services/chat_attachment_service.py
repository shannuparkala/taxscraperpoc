"""Documents a user attaches to a conversation.

Somebody pastes a notice into the chat because they want it explained. That
document is a tax assessment addressed to a real person, and it is the most
sensitive thing this application handles: it carries a name, an address, a
taxpayer identification number and an amount, all on page one.

So an attachment goes through the same four zones as a workpaper, in the same
order, with no shortcut for being "just a chat upload":

1. **Raw.** Stored through ``IngestionService``, Fernet-encrypted at rest.
   Nothing outside the ingestion, OCR and rehydration services reads it.
2. **Extraction.** ``OcrService`` produces text — the PDF text layer where
   there is one, Tesseract where the page is an image, native readers for
   Office and delimited files.
3. **Masked.** ``MaskingService`` tokenizes the extracted text. Tokenized, not
   redacted: the values stay recoverable locally, so a later answer can be
   rehydrated for the person it belongs to.
4. **Stored masked.** Only the masked text is written to ``RagDocument`` /
   ``RagChunk``, page by page, and only that is ever put into a prompt.

Two properties the rest of the application depends on:

**An attachment is scoped to one conversation.** The document carries the
session id in ``extra``, and ``masked_text_for`` reads only documents whose
recorded session matches the conversation the assistant is answering in. The
session id comes from the stored conversation, never from a request naming
document ids - "whose document is this" must never be got wrong.

**An attachment is evidence, not authority.** It is stored at
``FIRM_INTERNAL`` and the assistant's prompt presents it as the user's own
document - data about their situation, never instructions and never law.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditLogger
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.database_models import ChatSession, RagChunk, RagDocument, UploadedFile
from app.models.enums import AuthorityLevel, Jurisdiction, RagDocumentStatus, SourceType
from app.services.ingestion_service import IngestionService
from app.services.masking_service import MaskingService, MaskStyle
from app.services.ocr_service import OcrService
from app.services.pii_detection_service import DetectionConfig, PiiDetectionService

logger = get_logger(__name__)

#: Formats a person will actually paste into a tax conversation.
#:
#: Narrower than the pipeline's list on purpose: the pipeline accepts loose
#: page images because a scanned workpaper arrives that way, while a chat
#: attachment is a document somebody chose to send and naming the accepted
#: types is clearer than silently failing on the fifth one.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".docx", ".txt", ".xlsx", ".xls", ".csv"}
)

#: Attachments allowed on one conversation. A ceiling exists because every one
#: of them is retrieved against every subsequent question in the thread.
MAX_ATTACHMENTS_PER_SESSION = 10

#: ``RagDocument.document_type`` for a chat attachment.
ATTACHMENT_DOCUMENT_TYPE = "chat_attachment"

#: Below this, extraction did not really work — a scanned notice with no text
#: layer and no OCR available comes back nearly empty, and indexing that
#: produces a document the model will be shown and cannot read.
_MIN_USABLE_CHARS = 40


@dataclass(slots=True)
class AttachmentSummary:
    """What the UI shows for one attached document."""

    document_id: str
    file_id: str
    filename: str
    size_bytes: int
    page_count: int
    chunk_count: int
    masked_value_count: int
    #: Mean OCR/extraction confidence, 0..1. Low means the text is unreliable
    #: and the answer should say so.
    extraction_confidence: float
    #: Share of pages that produced usable text.
    coverage: float
    #: True when extraction was thin enough that answers should be hedged.
    needs_review: bool
    note: str = ""


class ChatAttachmentService:
    """Takes an uploaded file and makes it answerable, without leaking it."""

    def __init__(
        self,
        session: Session,
        *,
        audit: AuditLogger | None = None,
        settings: Settings | None = None,
        ocr: OcrService | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = audit
        self._ocr = ocr or OcrService(self._settings)
        self._ingestion = IngestionService(session, settings=self._settings, audit=audit)

    # -- public -----------------------------------------------------------

    def attach(
        self,
        *,
        session_id: str,
        filename: str,
        stream: BinaryIO,
        content_type: str = "application/octet-stream",
        actor_id: str | None = None,
    ) -> AttachmentSummary:
        """Store, read, mask and index one attachment."""
        chat_session = self._session.get(ChatSession, session_id)
        if chat_session is None:
            raise NotFoundError("No such conversation.")

        extension = _extension(filename)
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValidationError(
                f"{extension or 'That file type'} cannot be read here. "
                "Attach a PDF, Word document, spreadsheet, CSV or text file."
            )

        if len(self.list_for(session_id)) >= MAX_ATTACHMENTS_PER_SESSION:
            raise ValidationError(
                f"A conversation can hold {MAX_ATTACHMENTS_PER_SESSION} "
                "documents. Start a new chat, or remove one first."
            )

        # --- 1. Raw zone: encrypted at rest ------------------------------
        record = self._ingestion.store(
            filename=filename,
            stream=stream,
            content_type=content_type or "application/octet-stream",
            uploaded_by=actor_id,
        )

        # --- 2. Extraction ------------------------------------------------
        path = self._ingestion.materialize(record, actor_id=actor_id)
        try:
            extraction = self._ocr.extract(path)
        finally:
            # The decrypted copy is a plaintext taxpayer document on disk.
            # It exists for the length of one extraction and no longer,
            # whether or not the extraction succeeded.
            _discard(path)

        pages = [text for text in extraction.page_texts]
        joined = "\n\n".join(pages).strip()
        if len(joined) < _MIN_USABLE_CHARS:
            raise ValidationError(
                "I could not read any text out of that file. If it is a scan, "
                "it needs OCR — check that Tesseract is installed — and if it "
                "is a photo, a clearer one will read better."
            )

        # --- 3. Masked zone ------------------------------------------------
        masked_pages, masked_count = self._mask_pages(pages)

        # --- 4. Stored, masked ---------------------------------------------
        document = RagDocument(
            title=record.original_filename,
            source_url=None,
            source_type=_source_type(extension).value,
            # An attachment is evidence about the taxpayer's situation, never
            # authority about the law. Lowest level there is.
            authority_level=AuthorityLevel.FIRM_INTERNAL.value,
            jurisdiction=_as_jurisdiction(chat_session.jurisdiction).value,
            state_code=chat_session.state_code,
            tax_year=chat_session.tax_year,
            document_type=ATTACHMENT_DOCUMENT_TYPE,
            status=RagDocumentStatus.INDEXED.value,
            extra={
                "chat_session_id": chat_session.id,
                "uploaded_file_id": record.id,
                "masked_value_count": masked_count,
                "extraction_method": extraction.summary().get("method", ""),
            },
        )
        self._session.add(document)
        self._session.flush()
        chunk_count = 0
        for page_number, text in enumerate(masked_pages, start=1):
            if not text.strip():
                continue
            self._session.add(
                RagChunk(
                    rag_document_id=document.id,
                    chunk_index=chunk_count,
                    content=text,
                    token_estimate=len(text) // 4,
                    page_number=page_number,
                    section_path=f"page {page_number}",
                )
            )
            chunk_count += 1
        document.chunk_count = chunk_count
        self._session.flush()
        document_id = document.id

        if self._audit is not None:
            # SECURITY: counts and identifiers only. The filename is the
            # user's own and is retained; no extracted content is recorded.
            self._audit.record(
                AuditAction.FILE_UPLOADED,
                entity_type="chat_attachment",
                entity_id=document_id,
                actor_id=actor_id,
                payload={
                    "chat_session_id": chat_session.id,
                    "uploaded_file_id": record.id,
                    "pages": len(pages),
                    "chunks": chunk_count,
                    "masked_values": masked_count,
                    "coverage": round(extraction.coverage, 3),
                    "mean_confidence": round(extraction.mean_confidence, 3),
                },
            )

        return AttachmentSummary(
            document_id=document_id,
            file_id=record.id,
            filename=record.original_filename,
            size_bytes=int(record.size_bytes or 0),
            page_count=len(pages),
            chunk_count=chunk_count,
            masked_value_count=masked_count,
            extraction_confidence=round(extraction.mean_confidence, 3),
            coverage=round(extraction.coverage, 3),
            needs_review=_needs_review(extraction),
            note=_extraction_note(extraction, masked_count),
        )

    def list_for(self, session_id: str) -> list[AttachmentSummary]:
        """Every document attached to one conversation."""
        rows = self._session.execute(
            select(RagDocument)
            .where(RagDocument.document_type == ATTACHMENT_DOCUMENT_TYPE)
            .order_by(RagDocument.created_at.asc())
        ).scalars()

        summaries: list[AttachmentSummary] = []
        for document in rows:
            extra = document.extra or {}
            if extra.get("chat_session_id") != session_id:
                continue
            upload = (
                self._session.get(UploadedFile, extra.get("uploaded_file_id"))
                if extra.get("uploaded_file_id")
                else None
            )
            summaries.append(
                AttachmentSummary(
                    document_id=document.id,
                    file_id=str(extra.get("uploaded_file_id") or ""),
                    filename=document.title,
                    size_bytes=int(upload.size_bytes or 0) if upload else 0,
                    page_count=_max_page(document),
                    chunk_count=int(document.chunk_count or 0),
                    masked_value_count=int(extra.get("masked_value_count") or 0),
                    extraction_confidence=1.0,
                    coverage=1.0,
                    needs_review=False,
                )
            )
        return summaries

    def remove(self, *, session_id: str, document_id: str) -> bool:
        """Detach a document from a conversation.

        SECURITY: the session id is checked against the document's own record
        before anything is deleted, so a caller cannot remove an attachment
        belonging to a conversation they do not hold.
        """
        document = self._session.get(RagDocument, document_id)
        if document is None or document.document_type != ATTACHMENT_DOCUMENT_TYPE:
            return False
        if (document.extra or {}).get("chat_session_id") != session_id:
            return False

        self._session.delete(document)
        self._session.flush()
        return True

    def masked_text_for(self, session_id: str, *, max_chars: int) -> str:
        """The masked text of this conversation's attachments, for a prompt.

        SECURITY: reads stored masked pages only - nothing here touches the raw
        zone - and only documents whose recorded session is ``session_id``.
        Truncated to ``max_chars`` so one long document cannot crowd the
        question out of the prompt.
        """
        parts: list[str] = []
        used = 0
        for summary in self.list_for(session_id):
            chunks = self._session.execute(
                select(RagChunk)
                .where(RagChunk.rag_document_id == summary.document_id)
                .order_by(RagChunk.chunk_index.asc())
            ).scalars()
            header = f"--- Attached document: {summary.filename} ---"
            body = "\n\n".join(
                f"[page {chunk.page_number}]\n{chunk.content}" for chunk in chunks
            )
            block = f"{header}\n{body}"
            remaining = max_chars - used
            if remaining <= len(header):
                break
            if len(block) > remaining:
                block = block[:remaining] + "\n[... truncated ...]"
            parts.append(block)
            used += len(block)
        return "\n\n".join(parts)

    # -- internals --------------------------------------------------------

    def _mask_pages(self, pages: list[str]) -> tuple[list[str], int]:
        """Tokenize every page. A failure here stops the attachment entirely.

        SECURITY: there is no partial-success path. If masking raises on page
        four, pages one to three are not indexed either — an index holding
        three masked pages and one unmasked one is exactly the state that sends
        a taxpayer's name to a model, and it would look like a working feature.
        """
        masker = MaskingService(
            self._session,
            workflow_id=None,
            filing_id=None,
            style=MaskStyle.SURROGATE,
            audit=self._audit,
        )
        detector = PiiDetectionService(DetectionConfig())

        masked: list[str] = []
        total = 0
        try:
            for page in pages:
                if not page.strip():
                    masked.append("")
                    continue
                spans = detector.detect(page)
                if not spans:
                    masked.append(page)
                    continue
                result = masker.mask_text(page, spans)
                masked.append(result.masked_text)
                total += result.masked_count
        except Exception:
            logger.exception(
                "Masking an attachment failed; it will not be indexed"
            )
            raise ValidationError(
                "I could not safely hide the personal details in that "
                "document, so I have not stored it for questions."
            ) from None

        return masked, total


def _needs_review(extraction: object) -> bool:
    confidence = float(getattr(extraction, "mean_confidence", 0.0))
    coverage = float(getattr(extraction, "coverage", 0.0))
    return confidence < 0.70 or coverage < 0.80


def _extraction_note(extraction: object, masked_count: int) -> str:
    parts: list[str] = []
    coverage = float(getattr(extraction, "coverage", 1.0))
    confidence = float(getattr(extraction, "mean_confidence", 1.0))

    if coverage < 0.999:
        parts.append(
            f"I could only read {coverage * 100:.0f}% of the pages, so I may "
            "be missing something."
        )
    if confidence < 0.70:
        parts.append(
            "The scan is hard to read, so treat anything I quote from it as "
            "worth checking against the original."
        )
    if masked_count:
        parts.append(
            f"{masked_count} personal detail{'s' if masked_count != 1 else ''} "
            "were replaced with placeholders before anything was sent."
        )
    return " ".join(parts)


def _max_page(document: RagDocument) -> int:
    return max(
        (int(chunk.page_number or 0) for chunk in document.chunks),
        default=0,
    )


def _extension(filename: str) -> str:
    _, _, tail = str(filename or "").rpartition(".")
    return f".{tail.lower()}" if tail else ""


def _source_type(extension: str) -> SourceType:
    return SourceType.PDF if extension == ".pdf" else SourceType.FIRM_MEMO


def _as_jurisdiction(value: str | None) -> Jurisdiction:
    try:
        return Jurisdiction(value or Jurisdiction.FEDERAL.value)
    except ValueError:
        return Jurisdiction.FEDERAL


def _discard(path: object) -> None:
    from pathlib import Path

    try:
        Path(str(path)).unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove the temporary decrypted attachment")
