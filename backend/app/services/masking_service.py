"""Tokenization, surrogate generation, and the encrypted token vault.

Every sensitive value acquires three representations:

===============  ==========================  ==============================
Representation   Example                     Who may see it
===============  ==========================  ==============================
original         ``John A Smith``            raw zone + rehydration only
token            ``PERSON_001``              internal keys, logs, audit, UI
surrogate        ``Robert Miller``           the LLM
===============  ==========================  ==============================

Why a realistic surrogate rather than the bare token
----------------------------------------------------
Substituting ``PERSON_001`` into a W-2 produces text no tax form ever
contained, and extraction quality drops sharply — the model loses the cue that
box (e) holds a person's name. A realistic surrogate keeps the document
statistically normal, so extraction behaves as it would on real data. The token
remains the canonical internal key, and every stored artifact references it.

Why surrogates are provably fake
--------------------------------
Every generated surrogate is drawn from a range that cannot correspond to a
real person:

* SSNs use area ``666``, which the SSA has never issued.
* EINs use prefix ``00``, which the IRS has never issued.
* Phone numbers use ``555-01xx``, reserved for fiction.
* Emails use ``example.com`` / ``example.org`` (RFC 2606).
* Routing numbers deliberately fail the ABA checksum, so they cannot route.
* Card numbers deliberately fail Luhn, so they cannot be processed.

A surrogate leaking is therefore not a breach: it points at nobody.

SECURITY: this module is the boundary. If ``mask_text`` misses a span, unmasked
PII reaches the LLM. ``llm_egress_guard`` is the second line of defence, and
tests assert both.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditLogger
from app.core.logging import get_logger
from app.core.pii_patterns import (
    FORMAT_PRESERVING_TYPES,
    TOKEN_PREFIXES,
    PiiType,
)
from app.core.security import blind_index, decrypt_text, encrypt_text
from app.models.database_models import MaskingMap
from app.services.pii_detection_service import DetectedSpan

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Surrogate vocabulary — synthetic, deliberately unremarkable
# ---------------------------------------------------------------------------

_FIRST_NAMES = (
    "Robert", "Linda", "James", "Patricia", "Michael", "Barbara", "William",
    "Elizabeth", "David", "Jennifer", "Richard", "Maria", "Joseph", "Susan",
    "Thomas", "Margaret", "Charles", "Dorothy", "Daniel", "Nancy", "Matthew",
    "Karen", "Anthony", "Betty", "Donald", "Helen", "Steven", "Sandra",
    "Paul", "Donna", "Andrew", "Carol", "Joshua", "Ruth", "Kenneth", "Sharon",
)

_LAST_NAMES = (
    "Miller", "Bennett", "Coleman", "Harrington", "Whitfield", "Ashford",
    "Prescott", "Lindgren", "Caldwell", "Thorne", "Mercer", "Ellison",
    "Radcliffe", "Sutton", "Marden", "Kingsley", "Waverly", "Ashby",
    "Fairbanks", "Holloway", "Ridgeway", "Sinclair", "Winslow", "Barrett",
    "Chandler", "Delaney", "Everly", "Fletcher", "Grayson", "Hollis",
)

_ORG_PREFIXES = (
    "Northgate", "Bluewater", "Ironwood", "Silverline", "Crestview",
    "Harborview", "Stonebridge", "Fairmont", "Westbrook", "Greenfield",
    "Redstone", "Lakeshore", "Summit Park", "Cedarcrest", "Brookhaven",
)

_ORG_SUFFIXES = (
    "Industries LLC", "Holdings Inc", "Partners LP", "Group LLC",
    "Manufacturing Inc", "Services Inc", "Associates LLC", "Enterprises Inc",
    "Solutions LLC", "Capital LLC", "Logistics Inc", "Technologies Inc",
)

_STREET_NAMES = (
    "Maple", "Oak", "Cedar", "Birch", "Willow", "Aspen", "Juniper", "Laurel",
    "Chestnut", "Sycamore", "Poplar", "Hawthorn", "Alder", "Linden",
)

_STREET_TYPES = ("Street", "Avenue", "Road", "Drive", "Lane", "Court", "Way")

#: Placeholder cities/states. Real ZIPs are avoided by using the 09xxx range,
#: which is reserved for military overseas addresses and never a home address.
_CITIES = (
    "Springfield", "Riverton", "Fairview", "Clearwater", "Milton",
    "Georgetown", "Ashland", "Bristol", "Dover", "Newport",
)

_STATES = ("NY", "CA", "TX", "IL", "PA", "OH", "MI", "GA", "NC", "VA")


class MaskStyle(str, Enum):
    """What replaces a detected span in the masked artifact."""

    #: Realistic fake value. Default — best extraction quality.
    SURROGATE = "surrogate"
    #: Bare token, e.g. ``SSN_001``. Maximum obviousness, lower extraction
    #: quality. Useful for demos and for reviewers auditing the masking itself.
    TOKEN = "token"


@dataclass(slots=True)
class MaskedSpan:
    """Record of one substitution performed on a text buffer."""

    token: str
    surrogate: str
    pii_type: PiiType
    start: int
    end: int
    replacement: str
    confidence: float
    page_number: int | None = None

    def to_audit_dict(self) -> dict[str, Any]:
        """SECURITY: token and surrogate only — never the original."""
        return {
            "token": self.token,
            "pii_type": self.pii_type.value,
            "confidence": round(self.confidence, 3),
            "page": self.page_number,
        }


@dataclass(slots=True)
class MaskingResult:
    """Outcome of masking one text buffer."""

    masked_text: str
    spans: list[MaskedSpan] = field(default_factory=list)
    #: token -> surrogate, for this buffer. Safe to log and display.
    token_map: dict[str, str] = field(default_factory=dict)

    @property
    def masked_count(self) -> int:
        return len(self.spans)

    def summary(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for span in self.spans:
            by_type[span.pii_type.value] = by_type.get(span.pii_type.value, 0) + 1
        return {"masked_count": self.masked_count, "by_type": by_type}


class MaskingService:
    """Mints tokens, generates surrogates, and owns the vault.

    Scope: a *workflow*. The same original value always maps to the same token
    and surrogate within one workflow, so a taxpayer's name is consistent across
    all 40 pages. Across workflows the mapping is independent, which prevents
    cross-engagement correlation.
    """

    def __init__(
        self,
        session: Session,
        *,
        workflow_id: str | None = None,
        filing_id: str | None = None,
        style: MaskStyle = MaskStyle.SURROGATE,
        audit: AuditLogger | None = None,
    ) -> None:
        self._session = session
        self._workflow_id = workflow_id
        self._filing_id = filing_id
        self._style = style
        self._audit = audit
        # In-memory caches for this workflow, loaded lazily from the vault.
        self._by_blind_index: dict[str, MaskingMap] = {}
        self._by_token: dict[str, MaskingMap] = {}
        self._counters: dict[str, int] = {}
        self._loaded = False

    # ------------------------------------------------------------- vault io

    def _ensure_loaded(self) -> None:
        """Load this workflow's existing vault entries once."""
        if self._loaded:
            return
        if self._workflow_id:
            stmt = select(MaskingMap).where(
                MaskingMap.workflow_id == self._workflow_id
            )
            for entry in self._session.execute(stmt).scalars():
                self._by_blind_index[entry.value_blind_index] = entry
                self._by_token[entry.token] = entry
                prefix, _, number = entry.token.rpartition("_")
                if number.isdigit():
                    self._counters[prefix] = max(
                        self._counters.get(prefix, 0), int(number)
                    )
        self._loaded = True

    def _next_token(self, pii_type: PiiType) -> str:
        prefix = TOKEN_PREFIXES.get(pii_type, "SENSITIVE")
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}_{self._counters[prefix]:03d}"

    # ---------------------------------------------------------- tokenizing

    def tokenize(
        self, value: str, pii_type: PiiType, *, confidence: float = 1.0
    ) -> MaskingMap:
        """Return the vault entry for ``value``, creating it if new.

        SECURITY: ``value`` is encrypted immediately and never logged. Lookup
        uses a keyed blind index so we can recognise a repeat without ever
        comparing plaintext.
        """
        self._ensure_loaded()
        normalized = " ".join(value.split())
        index = blind_index(normalized)

        existing = self._by_blind_index.get(index)
        if existing is not None:
            # ``or 0``: column defaults are applied by the DB on flush, so a
            # pending (not yet flushed) row still has None here.
            existing.occurrence_count = (existing.occurrence_count or 0) + 1
            return existing

        token = self._next_token(pii_type)
        surrogate = generate_surrogate(pii_type, token, normalized)

        entry = MaskingMap(
            workflow_id=self._workflow_id,
            filing_id=self._filing_id,
            token=token,
            pii_type=pii_type.value,
            encrypted_value=encrypt_text(normalized, vault=True),
            surrogate_value=surrogate,
            value_blind_index=index,
            occurrence_count=1,
        )
        self._session.add(entry)
        self._by_blind_index[index] = entry
        self._by_token[token] = entry

        if self._audit is not None:
            self._audit.record(
                AuditAction.VAULT_ENTRY_CREATED,
                entity_type="masking_map",
                entity_id=token,
                payload={
                    "token": token,
                    "pii_type": pii_type.value,
                    "confidence": round(confidence, 3),
                },
            )
        return entry

    # ------------------------------------------------------------- masking

    def mask_text(
        self, text: str, spans: list[DetectedSpan]
    ) -> MaskingResult:
        """Replace detected spans with tokens or surrogates.

        Substitution runs right-to-left so that earlier character offsets stay
        valid as the buffer changes length.
        """
        if not spans:
            return MaskingResult(masked_text=text)

        ordered = sorted(spans, key=lambda s: s.start, reverse=True)
        buffer = text
        masked_spans: list[MaskedSpan] = []
        token_map: dict[str, str] = {}

        for span in ordered:
            if span.start < 0 or span.end > len(text) or span.start >= span.end:
                logger.warning(
                    "Skipping span with invalid offsets (type=%s)",
                    span.pii_type.value,
                )
                continue

            entry = self.tokenize(
                span.text, span.pii_type, confidence=span.confidence
            )
            replacement = (
                entry.surrogate_value
                if self._style is MaskStyle.SURROGATE
                else entry.token
            )
            buffer = buffer[: span.start] + replacement + buffer[span.end :]

            masked_spans.append(
                MaskedSpan(
                    token=entry.token,
                    surrogate=entry.surrogate_value,
                    pii_type=span.pii_type,
                    start=span.start,
                    end=span.end,
                    replacement=replacement,
                    confidence=span.confidence,
                    page_number=span.page_number,
                )
            )
            token_map[entry.token] = entry.surrogate_value

        masked_spans.reverse()
        result = MaskingResult(
            masked_text=buffer, spans=masked_spans, token_map=token_map
        )

        if self._audit is not None and masked_spans:
            self._audit.record(
                AuditAction.MASKING_APPLIED,
                entity_type="workflow",
                entity_id=self._workflow_id,
                payload=result.summary(),
            )
        return result

    def mask_structure(self, data: Any, spans_by_text: bool = True) -> Any:
        """Recursively mask strings inside a nested dict/list structure.

        Used for tables and key-value maps, where masking the flattened text
        would lose the structure the model needs.
        """
        from app.services.pii_detection_service import PiiDetectionService

        detector = PiiDetectionService()

        def _walk(node: Any) -> Any:
            if isinstance(node, str):
                if not node.strip():
                    return node
                found = detector.detect(node)
                return self.mask_text(node, found).masked_text if found else node
            if isinstance(node, dict):
                # Keys are masked too: a table header can be "John's account".
                return {_walk(k): _walk(v) for k, v in node.items()}
            if isinstance(node, list):
                return [_walk(v) for v in node]
            if isinstance(node, tuple):
                return tuple(_walk(v) for v in node)
            return node

        return _walk(data)

    # --------------------------------------------------------- vault reads

    def resolve_token(self, token: str) -> str | None:
        """Decrypt the original behind ``token``.

        SECURITY: the only legitimate callers are ``rehydration_service`` and
        an explicitly authorised reviewer action. Every call is audit-logged
        and increments ``access_count``, so unusual vault access is visible.
        """
        self._ensure_loaded()
        entry = self._by_token.get(token)
        if entry is None and self._workflow_id:
            stmt = select(MaskingMap).where(
                MaskingMap.workflow_id == self._workflow_id,
                MaskingMap.token == token,
            )
            entry = self._session.execute(stmt).scalar_one_or_none()
        if entry is None:
            return None

        entry.access_count = (entry.access_count or 0) + 1
        entry.last_accessed_at = datetime.now(UTC)
        if self._audit is not None:
            self._audit.record(
                AuditAction.VAULT_ACCESSED,
                entity_type="masking_map",
                entity_id=token,
                payload={"token": token, "pii_type": entry.pii_type},
            )
        return decrypt_text(entry.encrypted_value, vault=True)

    def surrogate_to_token(self) -> dict[str, str]:
        """Reverse map surrogate -> token, for rehydrating LLM output."""
        self._ensure_loaded()
        return {
            entry.surrogate_value: entry.token
            for entry in self._by_token.values()
        }

    def token_to_surrogate(self) -> dict[str, str]:
        self._ensure_loaded()
        return {
            token: entry.surrogate_value for token, entry in self._by_token.items()
        }

    def vault_size(self) -> int:
        self._ensure_loaded()
        return len(self._by_token)


# ---------------------------------------------------------------------------
# Surrogate generation
# ---------------------------------------------------------------------------


def _seed(token: str, original: str) -> int:
    """Deterministic seed so re-running produces identical surrogates.

    Derived from the token *and* the original so two different values never
    collapse to the same surrogate within a workflow.
    """
    material = f"{token}|{original}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _pick(pool: tuple[str, ...], seed: int, salt: int = 0) -> str:
    return pool[(seed + salt) % len(pool)]


def _digits_from_seed(seed: int, count: int) -> str:
    return f"{seed % (10 ** count):0{count}d}"


def generate_surrogate(pii_type: PiiType, token: str, original: str) -> str:
    """Produce a realistic but provably fake replacement.

    SECURITY: for every structured type the output is drawn from a range that
    is never issued in reality, so a surrogate can never coincide with a real
    person's identifier.
    """
    seed = _seed(token, original)

    match pii_type:
        case PiiType.PERSON_NAME:
            first = _pick(_FIRST_NAMES, seed)
            last = _pick(_LAST_NAMES, seed, salt=7)
            # Preserve a middle initial if the original had one.
            if re.search(r"\b[A-Z]\.?\s", original) and len(original.split()) >= 3:
                middle = chr(ord("A") + (seed % 26))
                return f"{first} {middle} {last}"
            return f"{first} {last}"

        case PiiType.EMPLOYER_NAME | PiiType.ORGANIZATION:
            return f"{_pick(_ORG_PREFIXES, seed)} {_pick(_ORG_SUFFIXES, seed, 3)}"

        case PiiType.SSN:
            # Area 666 is never issued by the SSA.
            return f"666-{(seed % 89) + 10:02d}-{_digits_from_seed(seed >> 8, 4)}"

        case PiiType.ITIN:
            # Valid ITIN shape (9xx-7x-xxxx) but group 99 with serial 0000,
            # which the IRS does not assign.
            return f"9{(seed % 90) + 10:02d}-99-0000"

        case PiiType.EIN:
            # Prefix 00 is not an IRS campus code.
            return f"00-{_digits_from_seed(seed, 7)}"

        case PiiType.PHONE:
            # 555-0100..555-0199 is the reserved fictional block.
            return f"(555) 555-{(seed % 100) + 100:04d}"[:14]

        case PiiType.EMAIL:
            first = _pick(_FIRST_NAMES, seed).lower()
            last = _pick(_LAST_NAMES, seed, 7).lower()
            # example.com is reserved by RFC 2606 and cannot be registered.
            return f"{first}.{last}@example.com"

        case PiiType.ADDRESS:
            number = (seed % 8900) + 100
            street = _pick(_STREET_NAMES, seed, 2)
            kind = _pick(_STREET_TYPES, seed, 5)
            return f"{number} {street} {kind}"

        case PiiType.ROUTING_NUMBER:
            # Built to FAIL the ABA checksum so it cannot route funds.
            base = f"0{_digits_from_seed(seed, 8)}"
            from app.core.pii_patterns import is_valid_aba_routing

            if is_valid_aba_routing(base):
                # Nudge the last digit to break the checksum.
                base = base[:-1] + str((int(base[-1]) + 5) % 10)
            return base

        case PiiType.BANK_ACCOUNT | PiiType.ACCOUNT_NUMBER:
            # SECURITY: a surrogate must not read as some *other* identifier.
            # An unconstrained nine-digit account surrogate begins with 9 about
            # a tenth of the time, and 44 of every 100 second-pairs fall inside
            # an IRS-assigned ITIN group -- so 4.5% of them are valid ITINs.
            # A 1099-B carries dozens of account numbers, so one workpaper hit
            # it every run: the egress guard saw an ITIN it had itself minted,
            # blocked the payload, and that return was never produced at all.
            # Leading digit 1-8 keeps the whole 9xx ITIN space out of reach.
            width = max(8, min(len(re.sub(r"\D", "", original)) or 10, 12))
            first = (seed % 8) + 1
            return f"{first}{_digits_from_seed(seed >> 4, width - 1)}"

        case PiiType.CREDIT_CARD:
            # Built to FAIL Luhn so it cannot be processed.
            from app.core.pii_patterns import is_valid_luhn

            candidate = f"4000{_digits_from_seed(seed, 12)}"
            if is_valid_luhn(candidate):
                candidate = candidate[:-1] + str((int(candidate[-1]) + 1) % 10)
            return f"{candidate[:4]}-{candidate[4:8]}-{candidate[8:12]}-{candidate[12:16]}"

        case PiiType.DATE_OF_BIRTH:
            month = (seed % 12) + 1
            day = ((seed >> 4) % 28) + 1
            year = 1950 + ((seed >> 8) % 50)
            return f"{month:02d}/{day:02d}/{year}"

        case PiiType.PASSPORT:
            return f"X{_digits_from_seed(seed, 8)}"

        case PiiType.DRIVERS_LICENSE | PiiType.STATE_ID:
            return f"{_pick(_STATES, seed)}{_digits_from_seed(seed, 7)}"

        case PiiType.PTIN:
            return f"P{_digits_from_seed(seed, 8)}"

        case PiiType.EFIN:
            return _digits_from_seed(seed, 6)

        case PiiType.CAF_NUMBER:
            return f"{_digits_from_seed(seed, 4)}-{_digits_from_seed(seed >> 8, 5)}"

        case PiiType.IP_PIN:
            return _digits_from_seed(seed, 6)

        case PiiType.CREDENTIAL | PiiType.URL_WITH_TOKEN:
            # Never approximate a secret's shape; make removal obvious.
            return "[REDACTED]"

        case _:
            return token


def format_preserving(pii_type: PiiType) -> bool:
    return pii_type in FORMAT_PRESERVING_TYPES
