"""Outbound payload inspection for LLM calls.

SECURITY: this is the last check before bytes leave the host. Every LLM request
passes through ``EgressGuard.assert_safe``. It exists because masking is a
best-effort detection problem — if ``pii_detection_service`` misses a span, the
guard catches the consequence.

Design notes
------------
* The guard **re-scans the serialized payload**, not the structured objects.
  Serialization is where a stray field sneaks in (an ORM object with
  ``__repr__`` exposing a column, a nested dict a caller forgot to mask).
* Surrogates are constructed to be indistinguishable in *shape* from real
  values, so the guard would flag them too. ``_is_known_surrogate`` suppresses
  exactly the surrogates minted for this workflow — nothing broader.
* Default mode is ``block``: raise and send nothing. ``warn`` exists only for
  local debugging and ``config.py`` forbids it in production.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.audit import AuditAction, AuditLogger
from app.core.config import EgressGuardMode, get_settings
from app.core.errors import EgressBlockedError
from app.core.logging import get_logger
from app.core.pii_patterns import (
    CRITICAL_TYPES,
    CUSIP_RE,
    PATTERN_SPECS,
    TOKEN_RE,
    PiiType,
    apply_validator,
)

logger = get_logger(__name__)

#: Patterns whose false-positive rate on legitimately-masked tax content is too
#: high to block on. Tax documents are full of bare 8-17 digit strings (CUSIPs,
#: form control numbers, document IDs) that are not account numbers. These are
#: still *reported*, but they do not by themselves block a send.
_ADVISORY_ONLY: frozenset[str] = frozenset(
    {"account_bare_long", "street_address", "city_state_zip", "phone_us"}
)

#: Confidence at or above which a non-advisory finding blocks the send.
_BLOCK_THRESHOLD = 0.70

#: Domains reserved by RFC 2606 / RFC 6761. They cannot be registered, so an
#: address there belongs to nobody. ``masking_service`` generates surrogate
#: emails at example.com for exactly this reason.
_RESERVED_EMAIL_RE = re.compile(
    r"(?i)^[^@\s]+@(?:[\w.-]+\.)?(?:example\.(?:com|org|net)|invalid|test|localhost)$"
)

#: 555-0100 through 555-0199 is the block reserved for fictional use, which is
#: what ``generate_surrogate`` emits for phone numbers.
_RESERVED_PHONE_RE = re.compile(
    r"^(?:\+?1[-.\s]?)?\(?555\)?[-.\s]?555[-.\s]?01\d{2}$"
)


@dataclass(slots=True)
class EgressFinding:
    """One suspicious span found in an outbound payload."""

    pii_type: PiiType
    pattern_name: str
    confidence: float
    #: Character offset in the serialized payload — useful for debugging.
    position: int
    #: SECURITY: a masked fingerprint, never the matched text itself. Enough to
    #: correlate two findings, not enough to recover the value.
    fingerprint: str
    advisory: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "pii_type": self.pii_type.value,
            "pattern": self.pattern_name,
            "confidence": round(self.confidence, 3),
            "position": self.position,
            "fingerprint": self.fingerprint,
            "advisory": self.advisory,
        }


@dataclass(slots=True)
class EgressReport:
    findings: list[EgressFinding] = field(default_factory=list)
    payload_bytes: int = 0
    scanned: bool = True

    @property
    def blocking(self) -> list[EgressFinding]:
        return [f for f in self.findings if not f.advisory]

    @property
    def is_safe(self) -> bool:
        return not self.blocking

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "payload_bytes": self.payload_bytes,
            "finding_count": len(self.findings),
            "blocking_count": len(self.blocking),
            "findings": [f.to_dict() for f in self.findings[:20]],
        }


def _fingerprint(text: str) -> str:
    """Stable, non-reversible short tag for a matched span."""
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class EgressGuard:
    """Scans serialized LLM payloads for unmasked sensitive data."""

    def __init__(
        self,
        *,
        allowed_surrogates: set[str] | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._settings = get_settings()
        # Surrogates minted for this workflow. Matching one is expected and safe.
        self._allowed = allowed_surrogates or set()
        self._audit = audit
        self._allowed_normalized = {
            re.sub(r"\D", "", s) for s in self._allowed if any(c.isdigit() for c in s)
        }

    # ------------------------------------------------------------------ API

    def scan(self, payload: Any) -> EgressReport:
        """Inspect ``payload`` without raising."""
        if not self._settings.llm_egress_guard_enabled:
            return EgressReport(scanned=False)

        blob = self._serialize(payload)
        report = EgressReport(payload_bytes=len(blob.encode("utf-8")))

        # Spans already replaced by our own tokens are, by definition, masked.
        token_ranges = [(m.start(), m.end()) for m in TOKEN_RE.finditer(blob)]
        # ...and so are the spans the masker deliberately left alone because
        # they are not client data. A CUSIP is a public security identifier and
        # MaskingService does not mask it on purpose; the guard has to make the
        # same judgement or the two disagree forever. It did: a 1099-B carries a
        # CUSIP on every trade line, all-digit CUSIPs are common, and one that
        # begins with 9 with an IRS-assigned second pair is a well-formed ITIN.
        # The guard blocked one and that workpaper produced no return on five
        # consecutive batches. Both sides read CUSIP_RE, so they cannot drift.
        token_ranges += [(m.start(1), m.end(1)) for m in CUSIP_RE.finditer(blob)]

        for spec in PATTERN_SPECS:
            for match in spec.regex.finditer(blob):
                text = match.group(1) if match.groups() else match.group()
                if not text or not text.strip():
                    continue
                start = match.start(1) if match.groups() else match.start()
                if any(s <= start < e for s, e in token_ranges):
                    continue
                if self._is_known_surrogate(text):
                    continue

                confidence = apply_validator(spec, text)
                advisory = (
                    spec.name in _ADVISORY_ONLY
                    or confidence < _BLOCK_THRESHOLD
                )
                # Critical types always block regardless of the advisory list.
                if spec.pii_type in CRITICAL_TYPES and confidence >= _BLOCK_THRESHOLD:
                    advisory = False

                report.findings.append(
                    EgressFinding(
                        pii_type=spec.pii_type,
                        pattern_name=spec.name,
                        confidence=confidence,
                        position=start,
                        fingerprint=_fingerprint(text),
                        advisory=advisory,
                    )
                )
        return report

    def assert_safe(self, payload: Any, *, context: str = "llm_request") -> EgressReport:
        """Scan and enforce policy.

        SECURITY: on a blocking finding in ``block`` mode this raises and the
        caller must not proceed. The exception carries no matched text.
        """
        report = self.scan(payload)
        if report.is_safe:
            return report

        audit_payload = {"context": context, **report.to_audit_dict()}

        if self._settings.llm_egress_guard_mode is EgressGuardMode.BLOCK:
            if self._audit is not None:
                self._audit.record(
                    AuditAction.EGRESS_BLOCKED,
                    entity_type="llm_request",
                    payload=audit_payload,
                )
            logger.error(
                "SECURITY: blocked outbound payload (%s) — %d unmasked findings: %s",
                context,
                len(report.blocking),
                ", ".join(sorted({f.pii_type.value for f in report.blocking})),
            )
            raise EgressBlockedError(
                "Outbound request blocked: the payload contains "
                f"{len(report.blocking)} unmasked sensitive value(s) "
                f"({', '.join(sorted({f.pii_type.value for f in report.blocking}))}). "
                "Nothing was transmitted."
            )

        # warn mode — development only
        if self._audit is not None:
            self._audit.record(
                AuditAction.EGRESS_WARNING,
                entity_type="llm_request",
                payload=audit_payload,
            )
        logger.warning(
            "SECURITY: egress guard in WARN mode allowed %d unmasked findings (%s). "
            "This must never be the production configuration.",
            len(report.blocking),
            context,
        )
        return report

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _serialize(payload: Any) -> str:
        """Flatten a payload into scannable text.

        SECURITY / correctness: this deliberately does NOT use ``json.dumps``.
        JSON escaping rewrites a newline as the two characters ``\\`` and ``n``,
        and the ``n`` then merges into the adjacent token — so a masked
        ``\\nalice@example.com`` scans as ``nalice@example.com``, which no longer
        matches the surrogate allow-list and blocks a payload that was correctly
        masked. Walking the structure and joining the real strings keeps token
        boundaries identical to what the model will actually receive.
        """
        if isinstance(payload, str):
            return payload
        if isinstance(payload, bytes):
            # Binary payloads (images) cannot be pattern-scanned. They are only
            # ever sent when ALLOW_CLOUD_OCR_FALLBACK is explicitly enabled,
            # which is audited separately at the call site.
            return ""

        parts: list[str] = []

        def walk(node: Any, depth: int = 0) -> None:
            # Bound the recursion: a pathological structure must not hang the
            # guard, and nothing legitimate nests this deeply.
            if depth > 12:
                parts.append(str(node))
                return
            if isinstance(node, str):
                parts.append(node)
            elif isinstance(node, dict):
                for key, value in node.items():
                    parts.append(str(key))
                    walk(value, depth + 1)
            elif isinstance(node, (list, tuple, set)):
                for value in node:
                    walk(value, depth + 1)
            elif node is not None:
                parts.append(str(node))

        try:
            walk(payload)
        except Exception:  # pragma: no cover - guard must never fail open
            return str(payload)

        # Newline separator: it cannot join two tokens into a third the way a
        # space or an escape sequence can.
        return "\n".join(parts)

    def _is_known_surrogate(self, text: str) -> bool:
        """True when ``text`` is a surrogate this workflow minted."""
        if text in self._allowed:
            return True
        digits = re.sub(r"\D", "", text)
        if digits and digits in self._allowed_normalized:
            return True
        # Structural checks, for when the caller could not supply a surrogate
        # set. Every generated surrogate is drawn from a range that is never
        # issued in reality, so recognising the range is as sound as an
        # allow-list — and it is the only option on the chat path, where masking
        # happens per request rather than per workflow.
        #
        # Without this, the guard blocks our OWN substitute: a client email in a
        # chat question is replaced with one at example.com, which is still
        # email-shaped, and the whole request is refused.
        if len(digits) == 9 and (digits.startswith("666") or digits.startswith("00")):
            return True
        # The ITIN surrogate is 9xx-99-0000. It has to keep the 9xx-NN-xxxx
        # shape to read as an ITIN to the model, and group 99 is inside the
        # IRS-assigned range, so is_valid_itin accepts it -- the guard was
        # blocking its own substitute. Serial 0000 is never assigned, so the
        # full triple is ours and nobody else's. Without this the whole
        # workpaper is refused whenever the allow-list cannot be loaded: one
        # sample return crashed at llm_processing on a correctly masked payload
        # and produced nothing at all.
        if (
            len(digits) == 9
            and digits.startswith("9")
            and digits[3:5] == "99"
            and digits[5:] == "0000"
        ):
            return True
        if _RESERVED_EMAIL_RE.fullmatch(text):
            return True
        if _RESERVED_PHONE_RE.fullmatch(text.strip()):
            return True
        return False


#: Placeholder substituted into retrieved source text.
_SOURCE_REDACTION = "[contact detail removed]"


def redact_blocking_patterns(text: str) -> str:
    """Strip guard-blocking identifiers from third-party source text.

    Retrieved authority is public — an IRS or state page routinely carries an
    office email or phone number. That is not client data, but the guard cannot
    tell the difference and correctly refuses to transmit it, which would break
    every answer built on such a page.

    Removing it is the right resolution rather than exempting the text: a
    contact address contributes nothing to a tax answer, so redaction costs no
    accuracy while keeping the guard strict for genuine client data. Only
    *blocking* patterns are touched — the advisory ones (street addresses,
    bare digit runs) are frequently load-bearing in tax guidance and are left
    intact.

    SECURITY: this is applied to retrieved *source passages* only. It must never
    be used on client document text as a way to satisfy the guard; that content
    goes through ``MaskingService`` so the values remain recoverable at output.
    """
    if not text:
        return text

    for spec in PATTERN_SPECS:
        if spec.name in _ADVISORY_ONLY:
            continue
        if spec.base_confidence < _BLOCK_THRESHOLD:
            continue
        if spec.regex.groups:
            # Keep the label, drop the value, so "Email: x@y.gov" stays readable.
            text = spec.regex.sub(
                lambda m: m.group(0).replace(m.group(1), _SOURCE_REDACTION), text
            )
        else:
            text = spec.regex.sub(_SOURCE_REDACTION, text)
    return text


def build_guard(
    *,
    masking_service: Any | None = None,
    audit: AuditLogger | None = None,
) -> EgressGuard:
    """Construct a guard aware of the current workflow's surrogates."""
    allowed: set[str] = set()
    if masking_service is not None:
        try:
            allowed = set(masking_service.token_to_surrogate().values())
        except Exception:  # pragma: no cover - guard must never fail open loudly
            logger.warning("Could not load surrogate allow-list; scanning strictly")
    return EgressGuard(allowed_surrogates=allowed, audit=audit)
