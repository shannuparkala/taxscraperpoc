"""Application error hierarchy and FastAPI exception handlers.

Every error surfaced to a client is shaped the same way::

    {"error": {"code": "...", "message": "...", "details": {...}}}

SECURITY: error messages are written for a client audience and must never
interpolate document content, extracted field values, or vault entries. When an
error concerns a specific value, reference its *token* (``SSN_001``) instead.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for expected, client-reportable failures."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


# --- 4xx -------------------------------------------------------------------


class ValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"
    message = "The request could not be validated."


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "The requested resource does not exist."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "The request conflicts with the current state."


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"
    message = "Authentication is required."


class AuthorizationError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "Your role does not permit this action."


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests. Please retry shortly."


class UnsupportedFileError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_file"
    message = "This file type is not accepted."


class FileTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "file_too_large"
    message = "The uploaded file exceeds the configured size limit."


# --- 5xx / pipeline --------------------------------------------------------


class PipelineError(AppError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "pipeline_error"
    message = "The processing pipeline failed."


class OcrUnavailableError(PipelineError):
    code = "ocr_unavailable"
    message = (
        "No local OCR engine is available and the document has no text layer. "
        "Install Tesseract and set TESSERACT_CMD, or review the document "
        "manually."
    )


class MaskingError(PipelineError):
    code = "masking_error"
    message = "Sensitive-data masking failed; processing was halted."


class UnreadableFileError(PipelineError):
    """The stored original cannot be decrypted with the current key."""

    status_code = status.HTTP_409_CONFLICT
    code = "file_unreadable"
    message = (
        "This file was encrypted with a different key and can no longer be "
        "read. Re-upload it to process it."
    )


class LlmError(PipelineError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "llm_error"
    message = "The language model request failed."


class ExportMapError(PipelineError):
    """An export map is malformed or out of step with the fact vocabulary.

    Raised at map load, never mid-render. A map that names a fact key the
    engine does not produce would write a blank into a return someone files,
    so the map is rejected rather than partially honoured.
    """

    code = "export_map_error"
    message = "A tax software export map could not be loaded."


class EgressBlockedError(AppError):
    """Raised when the outbound guard finds unmasked PII in an LLM payload.

    SECURITY: this is a hard stop, never a warning to be retried around. It
    means the masking stage failed to catch something and real client data was
    about to leave the host.
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "egress_blocked"
    message = (
        "Outbound request blocked: the payload still contains unmasked "
        "sensitive data. No data was transmitted."
    )


class VectorStoreError(AppError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "vector_store_error"
    message = "The vector store operation failed."


class DatabaseBusyError(AppError):
    """Another writer holds the SQLite write lock.

    WAL lets readers run during a write, but writers still serialise, and a
    pipeline run holds its transaction for the whole run — minutes on a scanned
    workpaper. An upload arriving in that window waits out the busy timeout and
    then fails. Retrying is the right response; a 500 with a traceback is not.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "database_busy"
    message = (
        "Another document is being processed and currently holds the database "
        "write lock. Nothing was saved. Retry once it finishes."
    )


#: SQLite reports both of these as OperationalError with no distinguishing code.
_SQLITE_BUSY_MARKERS = ("database is locked", "database is busy")


def is_database_busy(exc: BaseException) -> bool:
    """Whether an OperationalError is lock contention rather than a real fault.

    SECURITY: the message is matched but never logged or returned — a failed
    statement carries its bound parameters, which are client data.
    """
    text = str(exc).lower()
    return any(marker in text for marker in _SQLITE_BUSY_MARKERS)


# --- handlers --------------------------------------------------------------


def _mark_file_quarantined(uploaded_file_id: str) -> None:
    """Record that a stored file can no longer be decrypted.

    Best effort: bookkeeping must never replace the error the client is being
    told about, so any failure here is logged and swallowed.
    """
    try:
        from app.core.db import session_scope
        from app.models.database_models import UploadedFile

        with session_scope() as session:
            record = session.get(UploadedFile, uploaded_file_id)
            if record is None:
                return
            record.status = "quarantined"
            record.validation_notes = (
                "Encrypted under a previous key, so the original cannot be "
                "recovered. Re-upload the file to process it."
            )
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning(
            "Could not mark file %s as unreadable (%s)",
            uploaded_file_id,
            type(exc).__name__,
        )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach uniform JSON error handling to the app."""

    @app.exception_handler(UnreadableFileError)
    async def _unreadable_file(_: Request, exc: UnreadableFileError) -> JSONResponse:
        """Mark the file unreadable, then report the conflict.

        The write happens here rather than in the pipeline because by this point
        the request's database session has been rolled back and released. Doing
        it inside the failing transaction would either be discarded by that
        rollback or block on SQLite's writer lock.
        """
        file_id = exc.details.get("uploaded_file_id")
        if file_id:
            _mark_file_quarantined(str(file_id))
        logger.info("%s: %s", exc.code, exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        # Egress blocks are a security event: log loudly, but the message is
        # already PII-free by construction.
        if isinstance(exc, EgressBlockedError):
            logger.error("SECURITY: outbound LLM payload blocked by egress guard")
        elif exc.status_code >= 500:
            logger.error("%s: %s", exc.code, exc.message)
        else:
            logger.info("%s: %s", exc.code, exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _request_validation(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # SECURITY: FastAPI's default handler echoes the offending input back to
        # the caller. For a tax API that input may be an SSN, so we return only
        # the field location and the rule that failed.
        safe = [
            {"location": list(err.get("loc", ())), "problem": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": {"fields": safe},
                }
            },
        )

    @app.exception_handler(OperationalError)
    async def _operational(_: Request, exc: OperationalError) -> JSONResponse:
        if not is_database_busy(exc):
            # SECURITY: logger.exception renders the statement's bound
            # parameters. A real database fault gets the class name only.
            logger.error("Unhandled OperationalError")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": {
                        "code": "internal_error",
                        "message": "An unexpected error occurred.",
                        "details": {},
                    }
                },
            )
        busy = DatabaseBusyError()
        logger.warning("%s: another writer holds the lock", busy.code)
        return JSONResponse(
            status_code=busy.status_code,
            content=busy.to_payload(),
            headers={"Retry-After": "30"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # SECURITY: never leak a traceback or exception text to the client — an
        # unhandled exception from the document pipeline can carry file content.
        logger.exception("Unhandled %s", type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": {},
                }
            },
        )
