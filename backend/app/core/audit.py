"""Tamper-evident audit trail.

Every sensitive action writes an ``AuditEvent``. Events are chained: each row
stores the hash of the previous row, so deleting or editing history breaks the
chain and ``verify_chain`` detects it.

SECURITY: audit payloads must contain *token references only*. ``_assert_clean``
scans every payload before it is persisted and raises if a raw SSN, EIN, email
or similar slips through — an audit log full of PII is worse than no audit log,
because it is retained for seven years and widely readable.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.pii_patterns import LOG_REDACTION_SPECS, TOKEN_RE

logger = get_logger(__name__)

GENESIS_HASH = "0" * 64

#: Hex runs of 32+ characters — SHA-256/MD5 digests and similar derived values.
_HASH_RE = re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE)

#: Canonical UUIDs. Machine-generated entity ids, present in nearly every audit
#: payload, and a frequent false positive against the phone rule.
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class AuditAction(str, Enum):
    """Auditable actions. Extend rather than reusing an approximate match."""

    # --- Files ---
    FILE_UPLOADED = "file.uploaded"
    FILE_REJECTED = "file.rejected"
    FILE_ENCRYPTED = "file.encrypted"
    FILE_DECRYPTED = "file.decrypted"
    FILE_DELETED = "file.deleted"
    FILE_DOWNLOADED = "file.downloaded"

    # --- Pipeline ---
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_STAGE_STARTED = "workflow.stage_started"
    WORKFLOW_STAGE_COMPLETED = "workflow.stage_completed"
    WORKFLOW_STAGE_FAILED = "workflow.stage_failed"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"

    DOCUMENT_CLASSIFIED = "document.classified"
    OCR_PERFORMED = "ocr.performed"
    OCR_UNAVAILABLE = "ocr.unavailable"
    OCR_CLOUD_FALLBACK_USED = "ocr.cloud_fallback_used"

    # --- Privacy ---
    PII_DETECTED = "pii.detected"
    MASKING_APPLIED = "masking.applied"
    VAULT_ENTRY_CREATED = "vault.entry_created"
    VAULT_ACCESSED = "vault.accessed"
    REHYDRATION_PERFORMED = "rehydration.performed"
    EGRESS_BLOCKED = "egress.blocked"
    EGRESS_WARNING = "egress.warning"

    # --- LLM ---
    LLM_REQUESTED = "llm.requested"
    LLM_COMPLETED = "llm.completed"
    LLM_FAILED = "llm.failed"
    LLM_ESCALATED = "llm.escalated"
    #: The assistant showed a safe fallback instead of an answer, because
    #: two generations in a row failed validation (no sources, no tax year,
    #: wrong state). Recorded with issue codes only, so how often this
    #: happens - and why - is measurable in production.
    CHAT_REFUSED = "chat.refused"

    # --- Validation / review ---
    VALIDATION_RUN = "validation.run"
    VALIDATION_MISMATCH = "validation.mismatch"
    REVIEW_ITEM_CREATED = "review.item_created"
    REVIEW_APPROVED = "review.approved"
    REVIEW_REJECTED = "review.rejected"
    REVIEW_EDITED = "review.edited"

    # --- RAG ---
    RAG_SOURCE_INGESTED = "rag.source_ingested"
    RAG_SOURCE_REFRESHED = "rag.source_refreshed"
    RAG_QUERY = "rag.query"
    RAG_NO_RESULTS = "rag.no_results"

    # --- Templates ---
    TEMPLATE_LEARNED = "template.learned"
    TEMPLATE_APPROVED = "template.approved"
    TEMPLATE_REJECTED = "template.rejected"

    # --- Output ---
    OUTPUT_GENERATED = "output.generated"

    # --- Access control ---
    AUTH_SUCCEEDED = "auth.succeeded"
    AUTH_FAILED = "auth.failed"
    ACCESS_DENIED = "access.denied"
    SETTINGS_CHANGED = "settings.changed"
    RETENTION_PURGE = "retention.purge"


class AuditSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


#: Actions that always warrant operator attention.
_CRITICAL_ACTIONS = frozenset(
    {
        AuditAction.EGRESS_BLOCKED,
        AuditAction.OCR_CLOUD_FALLBACK_USED,
        AuditAction.ACCESS_DENIED,
        AuditAction.AUTH_FAILED,
        AuditAction.WORKFLOW_FAILED,
    }
)


class AuditPayloadError(RuntimeError):
    """Raised when an audit payload would have persisted raw PII."""


def _assert_clean(payload: dict[str, Any]) -> None:
    """Reject audit payloads containing patterned sensitive data.

    SECURITY: fails closed. If this raises, the *caller* is wrong — fix the call
    site to pass a token instead of loosening this check.

    Mask tokens are removed before scanning. They are the very thing callers are
    supposed to pass, and leaving them in produces false positives: the JSON key
    ``"token": "SSN_001"`` otherwise trips the generic-secret rule.
    """
    blob = json.dumps(payload, default=str)
    blob = TOKEN_RE.sub("", blob)
    # Content hashes are long hex strings and will, by chance, contain digit
    # runs that look like a phone or account number. They are derived values
    # that cannot reveal anything, and audit payloads legitimately carry them.
    blob = _HASH_RE.sub("", blob)
    # UUIDs have exactly the same problem and it is not rare: 1.39% of random
    # UUID4s contain a substring matching the US phone rule — the id
    # fd8d60a0-d05e-494f-aef5-2128087569f8 reads as 212-808-7569. Almost every
    # audit payload carries an entity id, so leaving them in aborted roughly one
    # pipeline run in twenty, at random, with a PII error naming data that was
    # never there. A UUID is machine-generated and carries no taxpayer content.
    blob = _UUID_RE.sub("", blob)
    for spec in LOG_REDACTION_SPECS:
        if spec.regex.search(blob):
            raise AuditPayloadError(
                f"Audit payload contains unmasked {spec.pii_type.value}; "
                "pass a mask token instead of the raw value."
            )


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _canonical_timestamp(value: datetime) -> str:
    """Round-trip-stable UTC timestamp string for hashing.

    SQLite has no native timezone-aware type: a value written as tz-aware comes
    back naive, so ``isoformat()`` differs before and after persistence and
    every chain link would appear broken. Normalising to naive-UTC with fixed
    precision makes the hash independent of the backend's datetime handling.
    """
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")


def compute_event_hash(
    *,
    previous_hash: str,
    action: str,
    actor_id: str | None,
    entity_type: str | None,
    entity_id: str | None,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> str:
    """Hash of this event plus its predecessor — the chain link."""
    material = "|".join(
        [
            previous_hash,
            action,
            actor_id or "-",
            entity_type or "-",
            entity_id or "-",
            _canonical_timestamp(occurred_at),
            _canonical(payload),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditLogger:
    """Writes chained audit events within a request's DB session.

    Chain state (last sequence, last hash) is cached in memory, keyed to the
    **session** via ``Session.info``. Two things force this design:

    1. Reading the tail from the database per event does not work — events added
       during a request stay pending until commit, so each would read the same
       ``max(sequence)`` and the same tail hash, producing duplicate sequence
       numbers and a chain where every event points at genesis.
    2. The cache cannot live on the logger instance either, because several
       services in one request each construct their own ``AuditLogger`` over the
       same session. Per-instance counters would then hand out the same sequence
       twice and the transaction would fail on commit.

    Concurrency across processes: the unique constraint on ``sequence`` makes a
    race fail loudly rather than silently fork the chain. For multi-writer
    deployments, serialise audit writes (a dedicated writer process, or
    ``SELECT ... FOR UPDATE`` on a sequence row).
    """

    #: Key under which chain state is stashed in ``Session.info``.
    _STATE_KEY = "_taxscraper_audit_chain"

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def _state(self) -> dict[str, Any]:
        return self._session.info.setdefault(
            self._STATE_KEY, {"sequence": None, "previous_hash": None}
        )

    def _load_chain_tail(self) -> None:
        """Seed session-scoped chain state from the last committed event."""
        state = self._state
        if state["sequence"] is not None:
            return
        from app.models.database_models import AuditEvent

        row = self._session.execute(
            select(AuditEvent.sequence, AuditEvent.event_hash)
            .order_by(AuditEvent.sequence.desc())
            .limit(1)
        ).first()
        if row is None:
            state["sequence"] = 0
            state["previous_hash"] = GENESIS_HASH
        else:
            state["sequence"] = int(row[0])
            state["previous_hash"] = str(row[1])

    def record(
        self,
        action: AuditAction,
        *,
        actor_id: str | None = None,
        actor_role: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict[str, Any] | None = None,
        severity: AuditSeverity | None = None,
        ip_address: str | None = None,
    ) -> Any:
        """Append an event. Returns the persisted ``AuditEvent`` (unflushed)."""
        from app.models.database_models import AuditEvent

        safe_payload = payload or {}
        _assert_clean(safe_payload)

        self._load_chain_tail()
        state = self._state

        occurred_at = datetime.now(UTC)
        previous_hash = str(state["previous_hash"])
        sequence = int(state["sequence"]) + 1
        event_hash = compute_event_hash(
            previous_hash=previous_hash,
            action=action.value,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            occurred_at=occurred_at,
            payload=safe_payload,
        )

        if severity is None:
            severity = (
                AuditSeverity.CRITICAL
                if action in _CRITICAL_ACTIONS
                else AuditSeverity.INFO
            )

        event = AuditEvent(
            sequence=sequence,
            action=action.value,
            severity=severity.value,
            actor_id=actor_id,
            actor_role=actor_role,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=safe_payload,
            occurred_at=occurred_at,
            previous_hash=previous_hash,
            event_hash=event_hash,
            ip_address=ip_address,
        )
        self._session.add(event)
        # Advance session-scoped chain state so the next event — from this
        # logger or any other sharing the session — links to this one rather
        # than to the last committed row.
        state["sequence"] = sequence
        state["previous_hash"] = event_hash

        if severity is AuditSeverity.CRITICAL:
            logger.warning("AUDIT[%s] entity=%s", action.value, entity_id or "-")
        else:
            logger.debug("audit[%s] entity=%s", action.value, entity_id or "-")
        return event

    def verify_chain(self, *, limit: int | None = None) -> tuple[bool, list[int]]:
        """Recompute the chain. Returns ``(ok, [broken sequence numbers])``."""
        from app.models.database_models import AuditEvent

        stmt = select(AuditEvent).order_by(AuditEvent.sequence.asc())
        if limit is not None:
            stmt = stmt.limit(limit)

        broken: list[int] = []
        expected_previous = GENESIS_HASH
        for event in self._session.execute(stmt).scalars():
            recomputed = compute_event_hash(
                previous_hash=event.previous_hash,
                action=event.action,
                actor_id=event.actor_id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                occurred_at=event.occurred_at,
                payload=event.payload or {},
            )
            if recomputed != event.event_hash or event.previous_hash != expected_previous:
                broken.append(event.sequence)
            expected_previous = event.event_hash

        return (not broken, broken)
