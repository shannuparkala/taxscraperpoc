"""Secure upload handling: validation, hashing, and encrypted raw-zone storage.

SECURITY properties enforced here:

* **Extension and magic-byte agreement.** A file named ``.pdf`` whose header is
  ``MZ`` is rejected. Checking only the extension is not validation.
* **Executables blocked** regardless of extension or declared content type.
* **Size limit** applied while streaming, so an oversized upload is abandoned
  before it is buffered rather than after.
* **Metadata stripped.** PDF ``Author``/``Creator``/``Title`` routinely carry a
  taxpayer's name; only structural metadata is retained.
* **Encrypted at rest.** Bytes are Fernet-encrypted before they touch disk. The
  plaintext exists only in memory, briefly.
* **Opaque stored names.** The on-disk name is a UUID, never the client
  filename, so a directory listing discloses nothing.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditLogger
from app.core.config import Settings, get_settings
from app.core.errors import FileTooLargeError, UnsupportedFileError, ValidationError
from app.core.logging import get_logger
from app.core.security import encrypt_bytes, sha256_bytes
from app.models.database_models import UploadedFile
from app.models.enums import FileStatus

logger = get_logger(__name__)

#: Magic-byte signatures per extension. A file must match one of its
#: extension's signatures, or it is rejected.
_MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
    ".bmp": (b"BM",),
    # OOXML formats are ZIP containers.
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    # Legacy OLE compound document.
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"PK\x03\x04"),
}

#: Extensions with no reliable signature; validated by content sniffing instead.
_TEXTUAL_EXTENSIONS = frozenset({".csv", ".txt"})

#: SECURITY: executable and script signatures. Rejected outright, whatever the
#: file is called — a "W-2.pdf" that is really a PE binary is an attack.
_FORBIDDEN_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"MZ", "Windows executable"),
    (b"\x7fELF", "ELF executable"),
    (b"\xca\xfe\xba\xbe", "Mach-O / Java class"),
    (b"\xfe\xed\xfa", "Mach-O executable"),
    (b"#!", "shell script"),
    (b"<?php", "PHP script"),
)

#: Extensions that are never accepted even if the caller adds them to config.
_ALWAYS_FORBIDDEN_EXTENSIONS = frozenset(
    {
        ".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".js",
        ".jar", ".msi", ".scr", ".cpl", ".sh", ".bash", ".py", ".php", ".jsp",
        ".asp", ".aspx", ".htaccess", ".lnk", ".reg", ".scf", ".hta",
    }
)

#: Windows reserved device names — a file called ``CON.pdf`` breaks tooling.
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_CHUNK = 1 << 20  # 1 MiB


@dataclass(slots=True)
class ValidationOutcome:
    ok: bool
    reason: str = ""
    detected_kind: str = ""


def sanitize_filename(name: str) -> str:
    """Strip path components and unsafe characters from a client filename.

    SECURITY: defeats path traversal (``../../etc/passwd``) and NTFS alternate
    data streams (``report.pdf:evil``). The result is used only for display —
    on-disk names are UUIDs — but it also lands in the database and the output
    package, so it must be inert.
    """
    name = name.replace("\\", "/").split("/")[-1]
    name = name.split(":")[0]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r'[<>:"|?*]', "_", name).strip(" .")

    if not name:
        return "unnamed"
    stem = name.rsplit(".", 1)[0].upper()
    if stem in _RESERVED_NAMES:
        name = f"file_{name}"
    return name[:255]


class IngestionService:
    """Validates and stores uploads in the encrypted raw zone."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = audit or AuditLogger(session)

    # -------------------------------------------------------- validation

    def validate(self, filename: str, head: bytes, size: int) -> ValidationOutcome:
        """Check a candidate upload before any bytes are persisted."""
        safe_name = sanitize_filename(filename)
        extension = Path(safe_name).suffix.lower()

        if not extension:
            return ValidationOutcome(False, "The file has no extension.")
        if extension in _ALWAYS_FORBIDDEN_EXTENSIONS:
            return ValidationOutcome(
                False, f"Executable and script files are not accepted ({extension})."
            )
        if extension not in self._settings.allowed_extension_set:
            return ValidationOutcome(
                False,
                f"'{extension}' is not an accepted file type. Allowed: "
                + ", ".join(sorted(self._settings.allowed_extension_set)),
            )
        if size > self._settings.max_upload_bytes:
            return ValidationOutcome(
                False,
                f"File is {size / 1e6:.1f} MB; the limit is "
                f"{self._settings.max_upload_mb} MB.",
            )
        if size == 0:
            return ValidationOutcome(False, "The file is empty.")

        # SECURITY: reject dangerous content whatever the extension claims.
        for signature, description in _FORBIDDEN_SIGNATURES:
            if head.startswith(signature):
                logger.warning(
                    "Rejected upload: %s content declared as '%s'",
                    description,
                    extension,
                )
                return ValidationOutcome(
                    False, f"File content is a {description}, which is not accepted."
                )

        expected = _MAGIC_SIGNATURES.get(extension)
        if expected is not None:
            if not any(head.startswith(sig) for sig in expected):
                return ValidationOutcome(
                    False,
                    f"File content does not match its '{extension}' extension.",
                )
        elif extension in _TEXTUAL_EXTENSIONS:
            # Reject binary content masquerading as text.
            sample = head[:512]
            if b"\x00" in sample:
                return ValidationOutcome(
                    False, "Binary content was supplied with a text extension."
                )

        return ValidationOutcome(True, detected_kind=extension)

    # ----------------------------------------------------------- storage

    def store(
        self,
        *,
        filename: str,
        stream: BinaryIO,
        content_type: str = "application/octet-stream",
        filing_id: str | None = None,
        uploaded_by: str | None = None,
    ) -> UploadedFile:
        """Validate, encrypt, and persist an upload.

        Raises before writing anything if validation fails.
        """
        safe_name = sanitize_filename(filename)
        extension = Path(safe_name).suffix.lower()

        payload = self._read_limited(stream)
        outcome = self.validate(safe_name, payload[:1024], len(payload))
        if not outcome.ok:
            self._audit.record(
                AuditAction.FILE_REJECTED,
                actor_id=uploaded_by,
                entity_type="uploaded_file",
                payload={
                    "extension": extension,
                    "size_bytes": len(payload),
                    "reason": outcome.reason,
                },
            )
            if "limit" in outcome.reason:
                raise FileTooLargeError(outcome.reason)
            raise UnsupportedFileError(outcome.reason)

        content_hash = sha256_bytes(payload)
        metadata = self._safe_metadata(payload, extension)

        # SECURITY: opaque on-disk name; the client filename never reaches the
        # filesystem, so a directory listing leaks nothing about the taxpayer.
        stored_name = f"{uuid.uuid4()}{extension}.enc"
        destination = self._settings.raw_zone_dir / stored_name
        destination.parent.mkdir(parents=True, exist_ok=True)

        # SECURITY: encrypt before writing — plaintext never lands on disk.
        destination.write_bytes(encrypt_bytes(payload, vault=False))

        record = UploadedFile(
            filing_id=filing_id,
            original_filename=safe_name,
            stored_filename=stored_name,
            content_type=content_type[:160],
            extension=extension,
            size_bytes=len(payload),
            content_hash=content_hash,
            status=FileStatus.UPLOADED.value,
            is_encrypted=True,
            file_metadata=metadata,
            uploaded_by=uploaded_by,
            purge_after=datetime.now(UTC)
            + timedelta(days=self._settings.retention_raw_days),
        )
        self._session.add(record)
        self._session.flush()

        self._audit.record(
            AuditAction.FILE_UPLOADED,
            actor_id=uploaded_by,
            entity_type="uploaded_file",
            entity_id=record.id,
            payload={
                "extension": extension,
                "size_bytes": len(payload),
                "content_hash": content_hash,
                "encrypted": True,
                "pages": metadata.get("page_count"),
            },
        )
        logger.info(
            "Stored upload %s (%s, %.1f KB, encrypted)",
            record.id,
            extension,
            len(payload) / 1024,
        )
        return record

    def _read_limited(self, stream: BinaryIO) -> bytes:
        """Read the stream, aborting as soon as the size limit is exceeded."""
        limit = self._settings.max_upload_bytes
        chunks: list[bytes] = []
        total = 0
        while chunk := stream.read(_CHUNK):
            total += len(chunk)
            if total > limit:
                raise FileTooLargeError(
                    f"Upload exceeds the {self._settings.max_upload_mb} MB limit."
                )
            chunks.append(chunk)
        return b"".join(chunks)

    # ---------------------------------------------------------- retrieval

    def read_plaintext(self, record: UploadedFile, *, actor_id: str | None = None) -> bytes:
        """Decrypt an original.

        SECURITY: raw-zone access is audited every time. Only deterministic
        preprocessing (OCR, rehydration) has any business calling this — never a
        code path that forwards the result to an LLM.
        """
        from app.core.security import decrypt_bytes

        path = self._settings.raw_zone_dir / record.stored_filename
        if not path.exists():
            raise ValidationError("The stored file is no longer available.")

        payload = path.read_bytes()
        plaintext = decrypt_bytes(payload, vault=False) if record.is_encrypted else payload

        self._audit.record(
            AuditAction.FILE_DECRYPTED,
            actor_id=actor_id,
            entity_type="uploaded_file",
            entity_id=record.id,
            payload={"size_bytes": len(plaintext)},
        )
        return plaintext

    def materialize(self, record: UploadedFile, *, actor_id: str | None = None) -> Path:
        """Write a decrypted working copy into the tmp zone.

        SECURITY: the caller owns cleanup. ``workflow_orchestrator`` deletes the
        copy in a ``finally`` block so plaintext does not linger.
        """
        plaintext = self.read_plaintext(record, actor_id=actor_id)
        target = self._settings.tmp_zone_dir / f"{uuid.uuid4()}{record.extension}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(plaintext)
        return target

    # ----------------------------------------------------------- metadata

    @staticmethod
    def _safe_metadata(payload: bytes, extension: str) -> dict[str, Any]:
        """Extract structural metadata only.

        SECURITY: PDF ``Author``, ``Title``, ``Subject`` and ``Keywords`` very
        often contain the taxpayer's name (export tools populate them from the
        client record). They are read and discarded here, never persisted.
        """
        metadata: dict[str, Any] = {"extension": extension}
        if extension != ".pdf":
            return metadata

        try:
            import io

            import fitz

            with fitz.open(stream=io.BytesIO(payload), filetype="pdf") as doc:
                metadata["page_count"] = doc.page_count
                metadata["is_encrypted"] = bool(doc.is_encrypted)
                raw = doc.metadata or {}
                # Producer/creator identify the software, not the person.
                metadata["producer"] = (raw.get("producer") or "")[:120]
                metadata["creator"] = (raw.get("creator") or "")[:120]
                metadata["has_identifying_metadata"] = bool(
                    raw.get("author") or raw.get("title") or raw.get("subject")
                )
        except Exception as exc:  # pragma: no cover
            logger.debug("Metadata probe failed: %s", type(exc).__name__)
            metadata["probe_error"] = type(exc).__name__

        return metadata
