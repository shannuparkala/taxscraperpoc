"""Masking a question on request, and un-masking only what is displayed.

**Masking is opt-in.** A question is masked only when the user starts it with
``/mask`` (owner's decision, 2026-10-09). Masking every question by default
replaced title-case phrases and case names with invented people - "Progress
in Preventing Fraud" reached the model as "Progress in Joseph Bennett", and
*Moore v. United States* lost its taxpayer - so the model answered a question
nobody asked, while display restore hid the damage from the user.

Without ``/mask`` the question is sent as typed. The egress guard in
``GeminiService`` still runs on every call, so a question carrying an SSN,
EIN, card or account number or an email is blocked rather than sent, and the
service tells the user to remove it or resend with ``/mask``. Names, phone
numbers and street addresses are not blocked by the guard; ``/mask`` is how a
user keeps those out.

With ``/mask`` the masking is tuned for prose rather than scanned forms:

* Structured identifiers (SSN, EIN/ITIN, account and routing numbers, card,
  phone, email, dates of birth, street addresses) are masked as before.
* The form-layout detectors are off: column pairing and the ALL-CAPS recasing
  pass find nothing real in a typed sentence, only false matches.
* Person names come from spaCy plus explicit person signals the model misses
  ("my wife Maria", "Mr. Patel"), and every later mention of a found name is
  masked too. Names inside quoted titles, URLs, case captions ("Moore v.
  United States", "In re ...") and title-shaped phrases ("Taxpayer Bill of
  Rights") are left alone - they name public things, not the user's people.

The reverse map (surrogate -> what the user typed) is built from the masking
spans, whose offsets index the original text, so it needs no vault access and
cannot reach beyond this one request. It is applied to what is shown, never to
what is stored or sent: stored turns are replayed to the model as history and
must stay masked. (CLAUDE.md trap 27.)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import AuditLogger
from app.core.logging import get_logger
from app.core.pii_patterns import PiiType
from app.services.masking_service import MaskingService, MaskStyle
from app.services.pii_detection_service import (
    DetectedSpan,
    DetectionConfig,
    PiiDetectionService,
)

logger = get_logger(__name__)

#: ``/mask`` at the very start of the message, as a command.
_MASK_COMMAND = re.compile(r"^\s*/mask(?![\w-])[ \t:,-]*", re.IGNORECASE)

#: Shapes that should never be typed into a chat: SSN/ITIN, and long digit
#: runs that look like bank or card numbers. Used only to tell the user so -
#: masking has already replaced them.
_SENSITIVE_SHAPES = re.compile(
    r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)|(?<!\d)\d{9}(?!\d)|(?<!\d)\d{12,19}(?!\d)"
)

_CAP = r"[A-Z][A-Za-z'’.-]*"
_NAME = r"[A-Z][a-z'’-]+(?:[ \t]+[A-Z][a-z'’-]+){0,2}"

#: Ranges that name public things and are never masked as a person.
_PROTECTED = (
    # Quoted titles: "Understanding Your CP2000 Notice".
    re.compile(r"\"[^\"\n]{2,200}\"|“[^”\n]{2,200}”"),
    # URLs and bare domains.
    re.compile(r"\bhttps?://\S+|\bwww\.\S+"),
    # Case captions: Moore v. United States, Smith vs. Commissioner.
    re.compile(rf"\b{_CAP}(?:[ \t]+{_CAP}){{0,4}}[ \t]+vs?\.?[ \t]+{_CAP}(?:[ \t]+{_CAP}){{0,4}}"),
    # In re Estate of Holmes, In re Smith.
    re.compile(rf"\bIn[ \t]+re[ \t]+(?:[A-Z][a-z]+[ \t]+of[ \t]+)?{_CAP}(?:[ \t]+{_CAP}){{0,3}}"),
    # Title-shaped phrases: capitalised words joined by a lowercase
    # connective - "Progress in Preventing Fraud", "Taxpayer Bill of Rights".
    # "and" is deliberately not a connective: "Maria and John" are people.
    re.compile(
        rf"\b{_CAP}(?:[ \t]+(?:of|in|for|on|to|the|by|with|from|at|under)"
        rf"(?:[ \t]+(?:the|a|an))?[ \t]+{_CAP})+(?:[ \t]+{_CAP})*"
    ),
)

#: A person signal spaCy does not need: a relation or an honorific right
#: before a capitalised name.
_RELATION = re.compile(
    r"\b(?:my|our|his|her|their)[ \t]+(?:client|clients|wife|husband|spouse|ex-wife|"
    r"ex-husband|ex|partner|fianc[eé]e?|son|daughter|child|kid|mother|mom|father|dad|"
    r"parent|brother|sister|grandmother|grandfather|grandson|granddaughter|aunt|uncle|"
    r"cousin|nephew|niece|friend|boss|employee|employer|tenant|landlord|dependent)"
    rf",?[ \t]+({_NAME})"
)
_HONORIFIC = re.compile(rf"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr)\.?[ \t]+({_NAME})")
_NAMED = re.compile(rf"\b(?:named|called)[ \t]+({_NAME})")

#: Words that can follow a relation but are not names ("my client Form 1040").
_NOT_A_NAME = frozenset(
    {"Form", "Schedule", "The", "This", "That", "Who", "And", "But", "IRS", "Social",
     "Section", "Notice", "Publication", "Pub"}
)

_NAME_TYPES = frozenset({PiiType.PERSON_NAME})


def parse_mask_command(question: str) -> tuple[bool, str]:
    """``(requested, question without the command)``."""
    match = _MASK_COMMAND.match(question)
    if not match:
        return False, question
    return True, question[match.end():]


@dataclass(slots=True)
class MaskedQuestion:
    text: str
    was_masked: bool
    restore: dict[str, str] = field(default_factory=dict)
    #: True when the user typed something shaped like an SSN or account number.
    sensitive_identifier: bool = False

    @classmethod
    def unmasked(cls, question: str) -> MaskedQuestion:
        """A question sent as typed. The egress guard still checks it."""
        return cls(question, False, {}, False)


class QuestionMasker:
    def __init__(self, session: Session, *, audit: AuditLogger | None = None) -> None:
        self._session = session
        self._audit = audit
        # Organisation masking is off: questions legitimately name public
        # bodies ("the IRS", "the Texas Comptroller"), and tokenizing those
        # destroys the question. The form-layout detectors are off: a typed
        # question has no columns and no block-capital name fields.
        self._detector = PiiDetectionService(
            DetectionConfig(mask_organizations=False, enable_columnar=False, recase_all_caps=False)
        )

    def mask(self, question: str) -> MaskedQuestion:
        sensitive = bool(_SENSITIVE_SHAPES.search(question))
        try:
            spans, decisions = chat_spans(question, self._detector.detect(question))
            # Counts and reasons only. SECURITY: never the values.
            logger.info("assistant.mask %s", dict(sorted(decisions.items())))
            if not spans:
                return MaskedQuestion(question, False, {}, sensitive)
            masker = MaskingService(
                self._session,
                workflow_id=None,
                filing_id=None,
                style=MaskStyle.SURROGATE,
                audit=self._audit,
            )
            result = masker.mask_text(question, spans)
        except Exception:
            logger.exception("Masking the question failed; refusing to send it")
            raise

        restore: dict[str, str] = {}
        for span in result.spans:
            original = question[span.start : span.end]
            replacement = span.replacement
            if not replacement or replacement == original:
                continue
            restore[replacement] = original
            # A model given "Joseph Bennett" writes "Joseph", so each part of
            # a multi-word surrogate maps back too. Whole entries win because
            # restore_text replaces longest first.
            parts = replacement.split()
            if len(parts) < 2:
                continue
            originals = original.split()
            for index, part in enumerate(parts):
                if len(part) < 3 or not part.isalpha():
                    continue
                restore.setdefault(
                    part, originals[index] if len(originals) == len(parts) else original
                )
        return MaskedQuestion(
            result.masked_text, result.masked_count > 0, restore, sensitive
        )


def chat_spans(
    text: str, detected: list[DetectedSpan]
) -> tuple[list[DetectedSpan], Counter[str]]:
    """The spans ``/mask`` replaces in a typed question, and why each was kept or dropped.

    Structured identifiers pass through untouched. Person names are dropped
    inside protected ranges, added where a relation or honorific marks a
    person spaCy missed, and every later whole-word mention of a found name
    is added too.
    """
    decisions: Counter[str] = Counter()
    protected = [(m.start(), m.end()) for p in _PROTECTED for m in p.finditer(text)]

    def is_protected(start: int, end: int) -> bool:
        return any(s <= start and end <= e for s, e in protected)

    kept: list[DetectedSpan] = []
    for span in detected:
        if span.pii_type in _NAME_TYPES and span.detector.startswith("ner") and is_protected(
            span.start, span.end
        ):
            decisions["name_kept_public_title"] += 1
            continue
        decisions[f"mask_{span.pii_type.value}"] += 1
        kept.append(span)

    for pattern, detector in ((_RELATION, "relation"), (_HONORIFIC, "honorific"), (_NAMED, "named")):
        for match in pattern.finditer(text):
            words = match.group(1).split()
            while words and words[-1] in _NOT_A_NAME:
                words.pop()
            if not words or words[0] in _NOT_A_NAME:
                continue
            value = " ".join(words)
            start = match.start(1)
            end = start + len(value)
            if any(s.start < end and start < s.end for s in kept):
                continue
            decisions[f"mask_person_name_{detector}"] += 1
            kept.append(_person(value, start, end, detector))

    # Every later mention of a name already found: "Maria ... can Maria".
    tokens = {
        word
        for span in kept
        if span.pii_type in _NAME_TYPES
        for word in text[span.start : span.end].split()
        if len(word) >= 3 and word[0].isupper() and word not in _NOT_A_NAME
    }
    for word in sorted(tokens):
        for match in re.finditer(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text):
            if any(s.start < match.end() and match.start() < s.end for s in kept):
                continue
            if is_protected(match.start(), match.end()):
                continue
            decisions["mask_person_name_repeat"] += 1
            kept.append(_person(word, match.start(), match.end(), "repeat"))

    return sorted(kept, key=lambda s: s.start), decisions


def _person(value: str, start: int, end: int, detector: str) -> DetectedSpan:
    return DetectedSpan(
        pii_type=PiiType.PERSON_NAME,
        text=value,
        start=start,
        end=end,
        confidence=0.9,
        detector=f"chat:{detector}",
    )


def restore_text(text: str, restore: dict[str, str]) -> str:
    """Put the user's own words back into text that is about to be displayed.

    Longest surrogate first, on word boundaries and case-sensitively: a
    surrogate part can be an ordinary word ("Field"), and a plain substring
    replace would rewrite "field examination" into somebody's name.
    """
    if not text or not restore:
        return text
    keys = sorted((key for key in restore if key), key=len, reverse=True)
    if not keys:
        return text

    pattern = re.compile("|".join(_boundary(key) for key in keys))
    return pattern.sub(lambda match: restore[match.group()], text)


class StreamRestorer:
    """``restore_text`` over a stream, without cutting inside a surrogate.

    A surrogate arrives split across chunks ("Jos" + "eph Bennett"). Cutting
    mid-surrogate once showed "John Bennett" - half the user's name and half
    invented, worse than either (CLAUDE.md trap 27). So the tail that could
    still grow into a surrogate is held back, and a cut never lands inside a
    match. Matching runs over the whole text so far, so the word-boundary
    checks see the real neighbouring characters.
    """

    def __init__(self, restore: dict[str, str]) -> None:
        self._restore = restore
        keys = sorted((key for key in restore if key), key=len, reverse=True)
        self._hold = max((len(key) for key in keys), default=1) - 1
        self._pattern = (
            re.compile("|".join(_boundary(key) for key in keys)) if keys else None
        )
        self._text = ""
        self._emitted = 0

    def feed(self, piece: str) -> str:
        if self._pattern is None:
            return piece
        self._text += piece
        return self._emit(max(self._emitted, len(self._text) - self._hold))

    def flush(self) -> str:
        if self._pattern is None:
            return ""
        return self._emit(len(self._text))

    def _emit(self, cut: int) -> str:
        assert self._pattern is not None
        matches = list(self._pattern.finditer(self._text))
        for match in matches:
            if match.start() < cut < match.end():
                cut = match.start()
        if cut <= self._emitted:
            return ""
        out: list[str] = []
        cursor = self._emitted
        for match in matches:
            if match.start() < self._emitted or match.end() > cut:
                continue
            out.append(self._text[cursor : match.start()])
            out.append(self._restore[match.group()])
            cursor = match.end()
        out.append(self._text[cursor:cut])
        self._emitted = cut
        return "".join(out)


def _boundary(key: str) -> str:
    left = r"(?<![0-9A-Za-z_])" if key[0].isalnum() or key[0] == "_" else ""
    right = r"(?![0-9A-Za-z_])" if key[-1].isalnum() or key[-1] == "_" else ""
    return f"{left}{re.escape(key)}{right}"


def restore_deep(value: Any, restore: dict[str, str], *, skip: frozenset[str] = frozenset()) -> Any:
    """``restore_text`` over every string in a nested payload, except ``skip`` keys."""
    if not restore:
        return value
    if isinstance(value, str):
        return restore_text(value, restore)
    if isinstance(value, list):
        return [restore_deep(item, restore, skip=skip) for item in value]
    if isinstance(value, dict):
        return {
            key: item if key in skip else restore_deep(item, restore, skip=skip)
            for key, item in value.items()
        }
    return value
