"""Restoring real values into the final output package.

Rehydration is the inverse of masking and the last stage before a deliverable
exists. It runs **only here**, in a deterministic local service.

SECURITY — the invariants that make this safe:

* Rehydration happens strictly *after* all model interaction is complete. There
  is no code path where a rehydrated artifact is sent anywhere outbound.
* Only ``rehydration_service`` and ``ingestion_service`` decrypt anything. No
  API route returns a decrypted vault value.
* Every rehydration is audit-logged with a count of tokens restored, so the
  volume of PII exposure per deliverable is on the record.
* Rehydrated files are written to the output zone and marked
  ``is_rehydrated=True``; downloading one is itself an audited, role-gated event.

Both directions are supported, because the model may echo back either form:

    token     ``PERSON_001``    -> original
    surrogate ``Robert Miller`` -> original

Surrogate replacement is longest-first, so ``Robert Miller Jr`` is not corrupted
by an earlier match on ``Robert Miller``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditLogger
from app.core.logging import get_logger
from app.core.pii_patterns import TOKEN_RE
from app.core.security import decrypt_text
from app.models.database_models import MaskingMap

logger = get_logger(__name__)


@dataclass(slots=True)
class RehydrationResult:
    text: str
    tokens_restored: int = 0
    tokens_unresolved: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Audit-safe. SECURITY: counts and token names only."""
        return {
            "tokens_restored": self.tokens_restored,
            "unresolved": self.tokens_unresolved[:10],
            "unresolved_count": len(self.tokens_unresolved),
        }


class RehydrationService:
    """Substitutes real values back into finished artifacts."""

    def __init__(
        self,
        session: Session,
        *,
        workflow_id: str,
        audit: AuditLogger | None = None,
    ) -> None:
        self._session = session
        self._workflow_id = workflow_id
        self._audit = audit
        self._token_to_value: dict[str, str] | None = None
        self._surrogate_to_value: dict[str, str] | None = None

    # --------------------------------------------------------------- vault

    def _load(self) -> None:
        """Decrypt this workflow's vault once, into memory.

        SECURITY: the decrypted map is held only for the lifetime of this
        service instance, which the orchestrator scopes to the rehydration and
        output stages. It is never returned by an API, never logged, and never
        serialized into a prompt.
        """
        if self._token_to_value is not None:
            return

        entries = list(
            self._session.execute(
                select(MaskingMap).where(MaskingMap.workflow_id == self._workflow_id)
            ).scalars()
        )

        token_map: dict[str, str] = {}
        surrogate_map: dict[str, str] = {}
        for entry in entries:
            try:
                original = decrypt_text(entry.encrypted_value, vault=True)
            except RuntimeError:
                # A single undecryptable entry must not abort the package; the
                # token stays visible in the output and the reviewer sees it.
                logger.error(
                    "Vault entry %s could not be decrypted; its token will "
                    "remain in the output.",
                    entry.token,
                )
                continue
            token_map[entry.token] = original
            if entry.surrogate_value:
                surrogate_map[entry.surrogate_value] = original

            entry.access_count = (entry.access_count or 0) + 1

        self._token_to_value = token_map
        self._surrogate_to_value = surrogate_map
        logger.info(
            "Loaded %d vault entries for rehydration of workflow %s",
            len(token_map),
            self._workflow_id,
        )

    # ----------------------------------------------------------- rehydrate

    def rehydrate_text(self, text: str) -> RehydrationResult:
        """Replace tokens and surrogates in ``text`` with real values."""
        self._load()
        assert self._token_to_value is not None
        assert self._surrogate_to_value is not None

        if not text:
            return RehydrationResult(text=text)

        restored = 0
        unresolved: list[str] = []

        # --- tokens -------------------------------------------------------
        def replace_token(match: re.Match[str]) -> str:
            nonlocal restored
            token = match.group()
            value = self._token_to_value.get(token)
            if value is None:
                if token not in unresolved:
                    unresolved.append(token)
                return token
            restored += 1
            return value

        output = TOKEN_RE.sub(replace_token, text)

        # --- surrogates ---------------------------------------------------
        # Longest first so a longer surrogate is not clipped by a shorter one
        # that happens to be a prefix.
        for surrogate in sorted(self._surrogate_to_value, key=len, reverse=True):
            if not surrogate or len(surrogate) < 3:
                continue
            if surrogate in output:
                occurrences = output.count(surrogate)
                output = output.replace(surrogate, self._surrogate_to_value[surrogate])
                restored += occurrences

        result = RehydrationResult(
            text=output, tokens_restored=restored, tokens_unresolved=unresolved
        )

        if unresolved:
            logger.warning(
                "%d token(s) had no vault entry and remain in the output",
                len(unresolved),
            )
        return result

    def rehydrate_structure(self, data: Any) -> tuple[Any, RehydrationResult]:
        """Recursively rehydrate strings inside a nested structure."""
        total_restored = 0
        all_unresolved: list[str] = []

        def walk(node: Any) -> Any:
            nonlocal total_restored
            if isinstance(node, str):
                result = self.rehydrate_text(node)
                total_restored += result.tokens_restored
                for token in result.tokens_unresolved:
                    if token not in all_unresolved:
                        all_unresolved.append(token)
                return result.text
            if isinstance(node, dict):
                return {walk(k): walk(v) for k, v in node.items()}
            if isinstance(node, list):
                return [walk(v) for v in node]
            if isinstance(node, tuple):
                return tuple(walk(v) for v in node)
            return node

        rehydrated = walk(data)
        summary = RehydrationResult(
            text="",
            tokens_restored=total_restored,
            tokens_unresolved=all_unresolved,
        )
        return (rehydrated, summary)

    def finalize(self, *, artifact_count: int = 1) -> None:
        """Record that rehydration occurred for this workflow."""
        if self._audit is None:
            return
        self._audit.record(
            AuditAction.REHYDRATION_PERFORMED,
            entity_type="workflow",
            entity_id=self._workflow_id,
            payload={
                "vault_entries": len(self._token_to_value or {}),
                "artifacts": artifact_count,
            },
        )

    @property
    def vault_size(self) -> int:
        self._load()
        return len(self._token_to_value or {})

    def verify_no_tokens_remain(self, text: str) -> list[str]:
        """Return any mask tokens still present.

        Used as a post-condition on generated deliverables: a token surviving
        into a client-facing document means a vault entry was lost, and the
        package must not be shipped as-is.
        """
        return sorted(set(TOKEN_RE.findall(text)))
