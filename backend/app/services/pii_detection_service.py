"""Detection of sensitive spans in extracted document text.

Three detectors run and their results are merged:

1. **Pattern detector** — regexes from ``core.pii_patterns`` with structural
   validators (SSN issuance rules, ABA checksum, Luhn).
2. **NER detector** — spaCy ``en_core_web_sm`` for PERSON and ORG, which is how
   taxpayer, dependent, and employer names get caught. Names have no regex.
3. **Context detector** — tax-form-specific rules. Tax documents put sensitive
   values next to fixed labels ("Employer identification number", "Box a
   Employee's social security number"), so a label match promotes whatever
   follows it, even when the value itself looks unremarkable.

Overlap resolution keeps the highest-confidence, most-specific span.

SECURITY: this module decides what gets masked. Under-detection here is a data
breach downstream, so every ambiguous case resolves toward masking. The
``ACCOUNT_NUMBER`` bare-digit rule in particular is intentionally noisy; the
suppression list below removes only spans we can *prove* are not identifiers
(currency, tax years, form numbers, box labels).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.core.pii_patterns import (
    CUSIP_RE,
    PATTERN_SPECS,
    TOKEN_RE,
    PatternSpec,
    PiiType,
    apply_validator,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class DetectedSpan:
    """A sensitive span located in a text buffer."""

    pii_type: PiiType
    text: str
    start: int
    end: int
    confidence: float
    detector: str
    page_number: int | None = None
    bbox: list[float] | None = None
    context: str = ""

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: DetectedSpan) -> bool:
        return self.start < other.end and other.start < self.end

    def to_audit_dict(self) -> dict[str, Any]:
        """Audit-safe view. SECURITY: never includes ``text``."""
        return {
            "pii_type": self.pii_type.value,
            "detector": self.detector,
            "confidence": round(self.confidence, 3),
            "page": self.page_number,
            "length": self.length,
        }


# ---------------------------------------------------------------------------
# Suppression: things that look like identifiers but are not
# ---------------------------------------------------------------------------

#: Currency amounts, percentages, and quantities.
_MONEY_RE = re.compile(r"[\$€£]\s?[\d,]+(?:\.\d{2})?|\b[\d,]+\.\d{2}\b")
#: Four-digit years plausible for tax documents.
_YEAR_RE = re.compile(r"\b(?:19[5-9]\d|20[0-4]\d)\b")
#: IRS form/schedule/publication references, e.g. "Form W-2", "Schedule K-1".
#: [ \t] rather than \s: with \s the match runs past the end of the line and
#: swallows whatever follows on the next one — which on a W-2 is the employer's
#: name, silently exempting it from masking.
_FORM_REF_RE = re.compile(
    r"(?i)\b(?:form|schedule|pub(?:lication)?|instruction|line|box|part|"
    r"section|worksheet)[ \t]*[-#]?[ \t]*[A-Z0-9][A-Z0-9\-]{0,11}\b"
)
#: CUSIP (9 alphanumeric) and ticker symbols in brokerage statements — these
#: identify a *security*, not a person, and masking them destroys the tax data.
_CUSIP_RE = CUSIP_RE  # shared with the egress guard; see core.pii_patterns

#: Well-known non-client organisations. Masking the IRS or a state DOR adds
#: noise without protecting anyone.
_PUBLIC_ORGS = frozenset(
    {
        "irs", "internal revenue service", "department of the treasury",
        "treasury", "u.s. treasury", "us treasury", "social security administration",
        "ssa", "medicare", "medicaid", "state of maine", "maine revenue services",
        "franchise tax board", "department of revenue", "tax court",
        "united states", "u.s.", "usa", "federal", "state",
    }
)

#: spaCy frequently tags tax vocabulary as PERSON. Filtering these keeps the
#: token vocabulary meaningful for the model.
_NER_STOPWORDS = frozenset(
    {
        # Months / days
        "january", "february", "march", "april", "may", "june", "july",
        "august", "september", "october", "november", "december",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday",
        # Tax vocabulary
        "form", "schedule", "worksheet", "instruction", "publication",
        "taxpayer", "spouse", "dependent", "filer", "preparer", "payer",
        "payee", "employer", "employee", "recipient", "beneficiary",
        "federal", "state", "local", "total", "subtotal", "gross", "net",
        "adjusted", "taxable", "exempt", "standard", "itemized", "deduction",
        "credit", "refund", "balance", "due", "withholding", "estimated",
        "wages", "salaries", "tips", "interest", "dividends", "capital",
        "gain", "loss", "proceeds", "basis", "distribution", "contribution",
        "rollover", "roth", "traditional", "sep", "simple", "hsa", "fsa",
        "medicare", "social", "security", "unemployment", "self", "employment",
        "single", "married", "jointly", "separately", "household", "widow",
        "qualifying", "surviving", "head",
        "account", "routing", "bank", "checking", "savings", "direct",
        "deposit", "electronic", "signature", "date", "page", "box", "line",
        "part", "section", "column", "row", "amount", "value", "code",
        "various", "sale", "purchase", "short", "long", "term", "covered",
        "noncovered", "wash", "disallowed", "reported", "cost", "other",
        # Identifier acronyms — spaCy tags these as ORG on tax forms.
        "ein", "ssn", "itin", "tin", "ptin", "efin", "caf", "pin", "id",
        "dob", "aba", "rtn", "cusip", "naics", "sic",
        # Contact-field labels — spaCy tags "Daytime"/"Evening" as PERSON.
        "daytime", "evening", "nighttime", "cell", "mobile", "fax", "home",
        "work", "office", "primary", "secondary", "preferred", "contact",
        "street", "city", "zip", "postal", "county", "country", "province",
        "apt", "apartment", "unit", "suite", "floor", "building",
        "first", "last", "middle", "initial", "name", "title", "occupation",
        # Filing-software artefacts
        "prosystem", "lacerte", "ultratax", "drake", "proseries", "safesend",
    }
)

_MIN_NAME_LENGTH = 3


@dataclass(slots=True)
class DetectionConfig:
    """Tunables. Defaults bias toward recall."""

    enable_ner: bool = True
    enable_patterns: bool = True
    enable_context_rules: bool = True
    #: Spans below this are dropped entirely.
    min_confidence: float = 0.40
    #: Treat organisation names as sensitive (employers, vendors, clients).
    mask_organizations: bool = True
    #: Extra literal strings the caller knows are sensitive, e.g. a client name
    #: already known from the engagement record.
    known_sensitive_values: tuple[str, ...] = ()
    #: Pair column headers with the cells above and below them. Built for
    #: scanned form layouts; prose has no columns, only false matches.
    enable_columnar: bool = True
    #: Re-run NER over ALL-CAPS lines in title case (block-capital names on
    #: scanned forms). Prose in capitals is emphasis, not a name.
    recase_all_caps: bool = True


# ---------------------------------------------------------------------------
# Context rules: label -> the value that follows it
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContextRule:
    """A label whose following value is sensitive regardless of its shape."""

    pii_type: PiiType
    label: re.Pattern[str]
    #: What the value after the label may look like.
    value: re.Pattern[str]
    confidence: float


_CONTEXT_RULES: tuple[ContextRule, ...] = (
    ContextRule(
        PiiType.PERSON_NAME,
        re.compile(
            r"(?i)\b(?:taxpayer|spouse|dependent|employee|recipient|client)"
            r"'?s?\s*(?:first\s+)?name\b[\s:]*"
        ),
        re.compile(r"[A-Z][A-Za-z'\-.]+(?:\s+[A-Z][A-Za-z'\-.]+){0,3}"),
        0.88,
    ),
    ContextRule(
        # A bare role label and a colon. Correspondence writes "Taxpayer:
        # Jane Okafor" with no "name" anywhere on the line, so the rule above
        # — which requires the word "name" — misses every notice and
        # assessment letter. Those are precisely the documents somebody
        # attaches to a chat asking what it means, and the name is on line
        # one. spaCy does not reliably catch it either: in an all-caps notice
        # with label-colon layout, ``en_core_web_sm`` tagged no PERSON at all.
        #
        # SECURITY: the separator is ``[ \t]``, never ``\s``. A whitespace
        # class crosses the newline and swallows the next line's label, which
        # is how an address pattern once exempted an employer name from
        # masking entirely.
        PiiType.PERSON_NAME,
        re.compile(
            r"(?im)^[ \t]*(?:taxpayer|account\s+holder|addressee|recipient|"
            r"client|customer|member|primary\s+filer)[ \t]*:[ \t]*"
        ),
        re.compile(r"[A-Z][A-Za-z'\-.]+(?:[ \t]+[A-Z][A-Za-z'\-.]+){0,3}"),
        0.86,
    ),
    ContextRule(
        PiiType.EMPLOYER_NAME,
        re.compile(
            r"(?i)\b(?:employer|payer|payor|filer|company|business|firm|"
            r"corporation|partnership)'?s?\s*name\b[\s:]*"
        ),
        re.compile(r"[A-Z][A-Za-z0-9'&,.\- ]{2,60}"),
        0.85,
    ),
    ContextRule(
        PiiType.PERSON_NAME,
        re.compile(r"(?i)\bprepared\s+(?:for|by)\b[\s:]*"),
        re.compile(r"[A-Z][A-Za-z'\-.]+(?:\s+[A-Z][A-Za-z'\-.]+){0,3}"),
        0.86,
    ),
    ContextRule(
        PiiType.ADDRESS,
        re.compile(
            r"(?i)\b(?:street\s+address|mailing\s+address|home\s+address|"
            r"address(?:\s+line\s*\d)?)\b[\s:]*"
        ),
        re.compile(r"[0-9A-Z][^\n\r]{4,80}"),
        0.80,
    ),
    ContextRule(
        PiiType.SSN,
        re.compile(
            r"(?i)\b(?:employee'?s?\s+)?social\s+security\s+(?:no|number|#)\b[\s:]*"
        ),
        re.compile(r"[\dX*\-\s]{9,13}"),
        0.95,
    ),
    ContextRule(
        PiiType.EIN,
        re.compile(
            r"(?i)\b(?:employer\s+identification\s+(?:no|number)|"
            r"federal\s+(?:id|ein)\s*(?:no|number)?)\b[\s:]*"
        ),
        re.compile(r"[\d\-]{9,11}"),
        0.94,
    ),
)


# ---------------------------------------------------------------------------
# Columnar label rules
#
# Tax forms almost never put a label and its value on the same line. A W-2
# prints the header above the value; a CCH organizer prints it below:
#
#     e Employee's first name and initial      Last name
#       KYLE  A                                FIEBELKORN      <- W-2
#
#       MICHAEL              ANDERSON              ON FILE
#       First Name and Initial   Last Name   Social Security Number   <- organizer
#
# Same-line regexes miss both. These rules match a *label line*, then read the
# adjacent line and pair values to labels by column position.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ColumnLabel:
    """A column header that marks the adjacent column cell as sensitive."""

    pii_type: PiiType
    pattern: re.Pattern[str]
    confidence: float


_COLUMN_LABELS: tuple[ColumnLabel, ...] = (
    ColumnLabel(
        PiiType.PERSON_NAME,
        re.compile(
            r"(?i)^(?:[a-z]\s+)?(?:employee'?s?\s+|taxpayer'?s?\s+|spouse'?s?\s+"
            r"|recipient'?s?\s+|dependent'?s?\s+)?"
            r"(?:first\s+name(?:\s+and\s+initial)?|last\s+name|full\s+name"
            r"|name\s+and\s+initial|middle\s+initial)\s*$"
        ),
        0.90,
    ),
    ColumnLabel(
        PiiType.EMPLOYER_NAME,
        re.compile(
            r"(?i)^(?:[a-z]\s+)?(?:employer'?s?|payer'?s?|payor'?s?|filer'?s?|"
            r"company'?s?|business)\s+name"
            r"(?:\s*,?\s*address(?:\s*,?\s*and\s+zip\s+code)?)?\s*$"
        ),
        0.88,
    ),
    ColumnLabel(
        PiiType.SSN,
        re.compile(
            r"(?i)^(?:[a-z]\s+)?(?:employee'?s?\s+|recipient'?s?\s+)?"
            r"social\s+security\s+(?:no\.?|number|#)\s*$"
        ),
        0.94,
    ),
    ColumnLabel(
        PiiType.EIN,
        re.compile(
            r"(?i)^(?:[a-z]\s+)?(?:employer\s+identification\s+(?:no\.?|number)"
            r"|federal\s+id(?:entification)?\s*(?:no\.?|number)?)\s*$"
        ),
        0.92,
    ),
    ColumnLabel(
        PiiType.ADDRESS,
        re.compile(
            r"(?i)^(?:[a-z]\s+)?(?:street\s+address|mailing\s+address|"
            r"home\s+address|address(?:\s+and\s+zip\s+code)?|city|"
            r"apartment\s+number|zip(?:\s+or\s+postal)?\s+code)\s*$"
        ),
        0.80,
    ),
    ColumnLabel(
        PiiType.DATE_OF_BIRTH,
        re.compile(r"(?i)^date\s+of\s+birth(?:\s*\(mo/da/yr\))?\s*$"),
        0.92,
    ),
    ColumnLabel(
        PiiType.PHONE,
        re.compile(
            r"(?i)^(?:taxpayer\s+|spouse\s+)?(?:daytime|evening|home|work|cell|"
            r"mobile|foreign|fax)?\s*(?:phone|telephone|fax)(?:\s+number)?\s*$"
        ),
        0.85,
    ),
    ColumnLabel(
        PiiType.EMAIL,
        re.compile(r"(?i)^(?:taxpayer\s+|spouse\s+)?e-?mail(?:\s+address)?\s*$"),
        0.92,
    ),
    ColumnLabel(
        PiiType.DRIVERS_LICENSE,
        re.compile(
            r"(?i)^driver'?s?\s+licen[sc]e(?:\s+or\s+state-?issued\s+id)?"
            r"(?:\s+number)?\s*$"
        ),
        0.85,
    ),
    ColumnLabel(
        PiiType.PERSON_NAME,
        re.compile(r"(?i)^prepared\s+(?:for|by)\s*$"),
        0.86,
    ),
)

#: Column boundary = a run of two or more spaces.
_COLUMN_SPLIT_RE = re.compile(r"\s{2,}")
#: How far apart two column starts may be and still count as the same column.
_COLUMN_TOLERANCE = 14
#: Values longer than this are prose, not a form field.
_MAX_CELL_LENGTH = 80


@dataclass(frozen=True, slots=True)
class _Cell:
    text: str
    #: Absolute offset in the document buffer.
    start: int
    end: int
    #: Offset within its own line — this is what column alignment compares.
    column: int


def _split_cells(line: str, line_offset: int) -> list[_Cell]:
    """Split a line into column cells, keeping absolute and column offsets."""
    cells: list[_Cell] = []
    position = 0
    for part in _COLUMN_SPLIT_RE.split(line):
        if not part.strip():
            position += len(part)
            continue
        found = line.find(part, position)
        if found == -1:
            continue
        # Trim leading whitespace inside the cell so ``start`` points at text.
        lead = len(part) - len(part.lstrip())
        text = part.strip()
        cells.append(
            _Cell(
                text=text,
                start=line_offset + found + lead,
                end=line_offset + found + lead + len(text),
                column=found + lead,
            )
        )
        position = found + len(part)
    return cells


#: Memoised spaCy pipeline. Only a *successful* load is cached — see below.
_SPACY_MODEL: Any | None = None


def _load_spacy() -> Any | None:
    """Load spaCy lazily; degrade to pattern-only detection if unavailable.

    SECURITY: if the NER model is missing, person and organisation names cannot
    be detected. The service reports ``ner_available=False`` so the pipeline can
    force those documents into human review rather than silently under-masking.

    SECURITY: failures are deliberately NOT cached. This was an ``lru_cache``,
    which meant a single transient load failure — a cold import racing the
    model install, a momentary file lock — disabled name masking for the entire
    life of the process, with no retry and no further warning. The health probe
    then reported the model as "missing" when it was installed and loadable,
    so the one signal that masking had silently degraded was itself wrong.
    Caching only the success keeps the fast path free and lets a later call
    recover.
    """
    global _SPACY_MODEL
    if _SPACY_MODEL is not None:
        return _SPACY_MODEL

    try:
        import spacy

        _SPACY_MODEL = spacy.load("en_core_web_sm", disable=["lemmatizer", "textcat"])
        logger.info("spaCy NER loaded for PII detection")
        return _SPACY_MODEL
    except Exception as exc:  # pragma: no cover - depends on host install
        logger.error(
            "spaCy model unavailable (%s). Name detection is DISABLED; "
            "documents will be flagged for manual review. "
            "Fix with: python -m spacy download en_core_web_sm",
            type(exc).__name__,
        )
        return None


class PiiDetectionService:
    """Locates sensitive spans in text."""

    #: spaCy's default max_length is 1M chars; long PDFs exceed the memory
    #: budget, so text is processed in windows.
    _NER_WINDOW = 80_000

    def __init__(self, config: DetectionConfig | None = None) -> None:
        self.config = config or DetectionConfig()

    # ------------------------------------------------------------------ API

    @property
    def ner_available(self) -> bool:
        return _load_spacy() is not None if self.config.enable_ner else False

    def detect(
        self, text: str, *, page_number: int | None = None
    ) -> list[DetectedSpan]:
        """Return non-overlapping sensitive spans, ordered by position."""
        if not text or not text.strip():
            return []

        spans: list[DetectedSpan] = []
        suppressed = self._suppression_ranges(text)

        if self.config.enable_patterns:
            spans.extend(self._detect_patterns(text, suppressed, page_number))
        if self.config.enable_context_rules:
            spans.extend(self._detect_context(text, page_number))
            if self.config.enable_columnar:
                spans.extend(self._detect_columnar(text, page_number))
        if self.config.enable_ner:
            spans.extend(self._detect_names(text, page_number))
        if self.config.known_sensitive_values:
            spans.extend(self._detect_known_values(text, page_number))

        spans = [s for s in spans if s.confidence >= self.config.min_confidence]
        spans = self._drop_form_titles(spans, text)
        resolved = self._resolve_overlaps(spans)
        for span in resolved:
            span.context = self._context_window(text, span)
        return resolved

    def detect_pages(
        self, pages: list[str]
    ) -> dict[int, list[DetectedSpan]]:
        """Detect per page, 1-indexed."""
        return {
            index: self.detect(content, page_number=index)
            for index, content in enumerate(pages, start=1)
            if content.strip()
        }

    # --------------------------------------------------------- suppression

    def _suppression_ranges(self, text: str) -> list[tuple[int, int]]:
        """Character ranges that must not be treated as identifiers."""
        ranges: list[tuple[int, int]] = []
        for pattern in (_MONEY_RE, _YEAR_RE, _FORM_REF_RE):
            ranges.extend((m.start(), m.end()) for m in pattern.finditer(text))
        # A CUSIP identifies a security; keep the digits but never the label.
        ranges.extend((m.start(1), m.end(1)) for m in _CUSIP_RE.finditer(text))
        # Our own tokens are already masked.
        ranges.extend((m.start(), m.end()) for m in TOKEN_RE.finditer(text))
        return ranges

    @staticmethod
    def _is_suppressed(
        start: int, end: int, suppressed: list[tuple[int, int]]
    ) -> bool:
        return any(s <= start and end <= e for s, e in suppressed)

    @staticmethod
    def _drop_form_titles(
        spans: list[DetectedSpan], text: str
    ) -> list[DetectedSpan]:
        """Discard name/organisation spans that collide with a form title.

        spaCy reads "Form W-2 Wage and Tax Statement" as an organisation. Masking
        it replaces the document's own identity with a fake company name, and the
        extraction model then cannot tell what form it is reading. Form titles are
        published IRS strings — never client data — so dropping these spans
        removes noise without weakening protection.

        Only PERSON_NAME and ORGANIZATION are eligible: a structured identifier
        that happens to sit near a form reference is still masked.
        """
        form_ranges = [(m.start(), m.end()) for m in _FORM_REF_RE.finditer(text)]
        if not form_ranges:
            return spans

        eligible = {PiiType.PERSON_NAME, PiiType.ORGANIZATION, PiiType.EMPLOYER_NAME}
        kept: list[DetectedSpan] = []
        for span in spans:
            if span.pii_type in eligible and any(
                span.start < end and start < span.end for start, end in form_ranges
            ):
                continue
            kept.append(span)
        return kept

    # ------------------------------------------------------------ detectors

    def _detect_patterns(
        self,
        text: str,
        suppressed: list[tuple[int, int]],
        page_number: int | None,
    ) -> list[DetectedSpan]:
        found: list[DetectedSpan] = []
        for spec in PATTERN_SPECS:
            for match in spec.regex.finditer(text):
                # When a spec captures a group, the group is the value and the
                # label prefix is left unmasked (labels carry no PII and keep
                # the document readable for the model).
                if match.groups():
                    start, end = match.span(1)
                    value = match.group(1)
                else:
                    start, end = match.span()
                    value = match.group()

                if not value or not value.strip():
                    continue
                if self._is_suppressed(start, end, suppressed):
                    continue
                if self._is_low_value_numeric(spec, value, text, start):
                    continue

                found.append(
                    DetectedSpan(
                        pii_type=spec.pii_type,
                        text=value,
                        start=start,
                        end=end,
                        confidence=apply_validator(spec, value),
                        detector=f"pattern:{spec.name}",
                        page_number=page_number,
                    )
                )
        return found

    def _is_low_value_numeric(
        self, spec: PatternSpec, value: str, text: str, start: int
    ) -> bool:
        """Filter obvious false positives from the broad bare-digit rule."""
        if spec.pii_type is not PiiType.ACCOUNT_NUMBER:
            return False
        digits = re.sub(r"\D", "", value)
        # A run of identical digits is a form rule line or a placeholder.
        if len(set(digits)) <= 1:
            return True
        # Preceded by a currency symbol -> it is money, not an account.
        prefix = text[max(0, start - 2) : start]
        if "$" in prefix:
            return True
        return False

    def _detect_context(
        self, text: str, page_number: int | None
    ) -> list[DetectedSpan]:
        found: list[DetectedSpan] = []
        for rule in _CONTEXT_RULES:
            for label_match in rule.label.finditer(text):
                tail_start = label_match.end()
                # Only look at the remainder of the current line.
                line_end = text.find("\n", tail_start)
                if line_end == -1:
                    line_end = len(text)
                window = text[tail_start:line_end]
                value_match = rule.value.match(window.lstrip())
                if not value_match:
                    continue
                offset = tail_start + (len(window) - len(window.lstrip()))
                value = value_match.group().strip()
                if not self._is_plausible_cell_value(value, rule.pii_type):
                    continue
                found.append(
                    DetectedSpan(
                        pii_type=rule.pii_type,
                        text=value,
                        start=offset,
                        end=offset + len(value),
                        confidence=rule.confidence,
                        detector="context",
                        page_number=page_number,
                    )
                )
        return found

    #: Above this ratio of uppercase letters, a line is treated as ALL-CAPS and
    #: re-run through NER in title case.
    _CAPS_RATIO = 0.70

    @staticmethod
    def _titlecase_preserving_length(text: str) -> str:
        """Title-case ALL-CAPS lines, leaving character offsets unchanged.

        Scanned tax forms print names in block capitals ("FIEBELKORN"), and
        spaCy's model — trained on mixed-case text — misses them badly. Casing
        never changes string length, so spans found in the recased copy map back
        to the original buffer at identical offsets.
        """
        out: list[str] = []
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            letters = [c for c in stripped if c.isalpha()]
            if len(letters) >= 4:
                caps_ratio = sum(c.isupper() for c in letters) / len(letters)
                if caps_ratio >= PiiDetectionService._CAPS_RATIO:
                    # str.title() is length-preserving.
                    out.append(line.title())
                    continue
            out.append(line)
        return "".join(out)

    def _run_ner(
        self, buffer: str, source_text: str, page_number: int | None, detector_tag: str
    ) -> list[DetectedSpan]:
        """Run spaCy over ``buffer``; return spans sliced from ``source_text``."""
        nlp = _load_spacy()
        if nlp is None:
            return []

        wanted = {"PERSON"}
        if self.config.mask_organizations:
            wanted.add("ORG")

        found: list[DetectedSpan] = []
        for offset in range(0, len(buffer), self._NER_WINDOW):
            window = buffer[offset : offset + self._NER_WINDOW]
            try:
                doc = nlp(window)
            except Exception as exc:  # pragma: no cover
                logger.warning("NER failed on window: %s", type(exc).__name__)
                continue

            for ent in doc.ents:
                if ent.label_ not in wanted:
                    continue
                start = offset + ent.start_char
                end = offset + ent.end_char
                # Always take the text from the ORIGINAL buffer so the value we
                # tokenize matches the document byte-for-byte.
                value = source_text[start:end].strip()
                if not value or not self._is_plausible_name(value):
                    continue

                pii_type = (
                    PiiType.PERSON_NAME
                    if ent.label_ == "PERSON"
                    else PiiType.ORGANIZATION
                )
                if pii_type is PiiType.ORGANIZATION and value.lower() in _PUBLIC_ORGS:
                    continue

                # ORG confidence is lower: spaCy over-tags headings as ORG. It
                # still exceeds min_confidence, so it is masked — noise here is
                # the safe direction.
                confidence = 0.85 if pii_type is PiiType.PERSON_NAME else 0.62
                found.append(
                    DetectedSpan(
                        pii_type=pii_type,
                        text=value,
                        start=start,
                        end=end,
                        confidence=confidence,
                        detector=detector_tag + ":" + ent.label_.lower(),
                        page_number=page_number,
                    )
                )
        return found

    def _detect_columnar(
        self, text: str, page_number: int | None
    ) -> list[DetectedSpan]:
        """Pair column headers with the cells above and below them.

        Tax forms label a value on the preceding line (W-2) or the following
        line (CCH organizer), so both directions are checked. Values are matched
        to labels by column start offset rather than by order, which keeps
        multi-column rows aligned even when cell widths differ.
        """
        lines: list[tuple[str, int]] = []
        offset = 0
        for line in text.splitlines():
            lines.append((line, offset))
            offset += len(line) + 1

        found: list[DetectedSpan] = []
        for index, (line, line_offset) in enumerate(lines):
            label_cells = _split_cells(line, line_offset)
            if not label_cells:
                continue

            # Which cells on this line are recognised labels?
            labelled: list[tuple[_Cell, ColumnLabel]] = []
            for cell in label_cells:
                for rule in _COLUMN_LABELS:
                    if rule.pattern.match(cell.text):
                        labelled.append((cell, rule))
                        break
            if not labelled:
                continue

            # A line that is *entirely* labels is a header row; otherwise it may
            # be a value row that happens to contain one label.
            for neighbour_index in (index - 1, index + 1):
                if not 0 <= neighbour_index < len(lines):
                    continue
                neighbour_line, neighbour_offset = lines[neighbour_index]
                if not neighbour_line.strip():
                    continue
                # Skip if the neighbour is itself a label row.
                neighbour_cells = _split_cells(neighbour_line, neighbour_offset)
                if not neighbour_cells:
                    continue
                if all(
                    any(rule.pattern.match(c.text) for rule in _COLUMN_LABELS)
                    for c in neighbour_cells
                ):
                    continue

                for label_cell, rule in labelled:
                    value_cell = self._match_column(label_cell, neighbour_cells)
                    if value_cell is None:
                        continue
                    value = value_cell.text
                    if not self._is_plausible_cell_value(value, rule.pii_type):
                        continue
                    found.append(
                        DetectedSpan(
                            pii_type=rule.pii_type,
                            text=value,
                            start=value_cell.start,
                            end=value_cell.start + len(value),
                            confidence=rule.confidence,
                            detector="columnar",
                            page_number=page_number,
                        )
                    )
        return found

    @staticmethod
    def _match_column(label: _Cell, candidates: list[_Cell]) -> _Cell | None:
        """Find the candidate cell sharing ``label``'s column."""
        best: _Cell | None = None
        best_distance = _COLUMN_TOLERANCE + 1
        for cell in candidates:
            # Compare positions within their respective lines, so a label and
            # its value line up even though their absolute offsets differ.
            distance = abs(cell.column - label.column)
            if distance < best_distance:
                best_distance = distance
                best = cell
        return best if best_distance <= _COLUMN_TOLERANCE else None

    @staticmethod
    def _is_plausible_cell_value(value: str, pii_type: PiiType) -> bool:
        if not value or len(value) > _MAX_CELL_LENGTH:
            return False
        if value.lower() in _NER_STOPWORDS:
            return False
        # Organizer placeholders for withheld data are not sensitive.
        if value.upper() in {"ON FILE", "N/A", "NONE", "SAME", "X", "-", "--"}:
            return False
        if not any(c.isalnum() for c in value):
            return False
        # A label that leaked into the value column.
        if any(rule.pattern.match(value) for rule in _COLUMN_LABELS):
            return False
        if pii_type is PiiType.PERSON_NAME:
            digit_ratio = sum(c.isdigit() for c in value) / len(value)
            if digit_ratio > 0.3:
                return False
        return True

    def _detect_names(
        self, text: str, page_number: int | None
    ) -> list[DetectedSpan]:
        spans = self._run_ner(text, text, page_number, "ner")
        if not self.config.recase_all_caps:
            return spans

        # Second pass over a title-cased copy to recover block-capital names.
        recased = self._titlecase_preserving_length(text)
        if recased != text:
            spans.extend(self._run_ner(recased, text, page_number, "ner_caps"))
        return spans

    @staticmethod
    def _is_plausible_name(value: str) -> bool:
        if len(value) < _MIN_NAME_LENGTH:
            return False
        if not any(c.isalpha() for c in value):
            return False
        if value.lower() in _NER_STOPWORDS:
            return False
        # A run of 2+ spaces means the span crossed a column boundary, so spaCy
        # glued together unrelated cells ("Initial   Last Name   SSN"). Masking
        # that destroys the form layout the model relies on.
        if _COLUMN_SPLIT_RE.search(value):
            return False
        # Entirely made of form-label words.
        if any(rule.pattern.match(value) for rule in _COLUMN_LABELS):
            return False
        # Reject if every word is a stopword ("Total Interest Income").
        words = [w.strip(".,()'\"").lower() for w in value.split()]
        if words and all(w in _NER_STOPWORDS or not w for w in words):
            return False
        if len(value.split()) > 6:
            return False
        # Mostly digits -> an identifier a pattern rule already owns.
        digit_ratio = sum(c.isdigit() for c in value) / max(len(value), 1)
        return digit_ratio <= 0.4

    def _detect_known_values(
        self, text: str, page_number: int | None
    ) -> list[DetectedSpan]:
        """Literal matches for values the caller already knows are sensitive."""
        found: list[DetectedSpan] = []
        for value in self.config.known_sensitive_values:
            if len(value) < _MIN_NAME_LENGTH:
                continue
            for match in re.finditer(re.escape(value), text, re.IGNORECASE):
                found.append(
                    DetectedSpan(
                        pii_type=PiiType.UNKNOWN_SENSITIVE,
                        text=match.group(),
                        start=match.start(),
                        end=match.end(),
                        confidence=0.99,
                        detector="known_value",
                        page_number=page_number,
                    )
                )
        return found

    # ------------------------------------------------------------- merging

    @staticmethod
    def _specificity(span: DetectedSpan) -> int:
        """Tie-breaker: prefer a specific type over a generic one."""
        if span.pii_type in {PiiType.SSN, PiiType.ITIN, PiiType.EIN}:
            return 3
        if span.pii_type in {
            PiiType.ROUTING_NUMBER,
            PiiType.BANK_ACCOUNT,
            PiiType.CREDIT_CARD,
        }:
            return 2
        if span.pii_type is PiiType.ACCOUNT_NUMBER:
            return 0
        return 1

    def _resolve_overlaps(self, spans: list[DetectedSpan]) -> list[DetectedSpan]:
        """Keep the strongest span in each overlapping cluster.

        Ranking: confidence, then specificity, then length. An SSN detected by
        both the labeled rule and the generic account rule resolves to SSN.
        """
        if not spans:
            return []

        ordered = sorted(
            spans,
            key=lambda s: (-s.confidence, -self._specificity(s), -s.length, s.start),
        )
        kept: list[DetectedSpan] = []
        for candidate in ordered:
            if any(candidate.overlaps(existing) for existing in kept):
                continue
            kept.append(candidate)

        kept.sort(key=lambda s: s.start)
        return kept

    @staticmethod
    def _context_window(text: str, span: DetectedSpan, radius: int = 60) -> str:
        """Masked-safe surrounding text for reviewer display.

        SECURITY: the span's own value is replaced with a placeholder so the
        stored context cannot be used to recover it.
        """
        left = text[max(0, span.start - radius) : span.start]
        right = text[span.end : span.end + radius]
        return f"{left}███{right}".replace("\n", " ").strip()


def summarize_detections(spans: list[DetectedSpan]) -> dict[str, Any]:
    """Audit-safe rollup. SECURITY: counts only, never values."""
    by_type: dict[str, int] = {}
    for span in spans:
        by_type[span.pii_type.value] = by_type.get(span.pii_type.value, 0) + 1
    confidences = [s.confidence for s in spans]
    return {
        "total": len(spans),
        "by_type": by_type,
        "min_confidence": round(min(confidences), 3) if confidences else None,
        "mean_confidence": (
            round(sum(confidences) / len(confidences), 3) if confidences else None
        ),
    }
