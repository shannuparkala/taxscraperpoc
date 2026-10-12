"""Canonical sensitive-data patterns and validators.

This module is the single source of truth for "what does sensitive data look
like". Three separate consumers import from here, and they must agree:

1. ``services.pii_detection_service`` — finds PII so it can be masked.
2. ``core.logging`` — redacts anything that slips into a log record.
3. ``services.llm_egress_guard`` — refuses outbound payloads containing PII.

If detection and the egress guard used different patterns, the guard could pass
something detection missed, which is exactly the failure mode we cannot have.

Design bias: **recall over precision.** A false positive costs a reviewer a few
seconds. A false negative is a client data breach. Structural validators (ABA
checksum, Luhn, SSN issuance rules) are applied only to *demote* a match to a
lower confidence, never to discard it outright.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class PiiType(str, Enum):
    """Categories of sensitive data recognised by the platform."""

    # --- Identity ---
    PERSON_NAME = "person_name"
    SSN = "ssn"
    ITIN = "itin"
    EIN = "ein"
    DATE_OF_BIRTH = "date_of_birth"
    DRIVERS_LICENSE = "drivers_license"
    STATE_ID = "state_id"
    PASSPORT = "passport"

    # --- Contact ---
    ADDRESS = "address"
    PHONE = "phone"
    EMAIL = "email"

    # --- Financial ---
    BANK_ACCOUNT = "bank_account"
    ROUTING_NUMBER = "routing_number"
    CREDIT_CARD = "credit_card"
    ACCOUNT_NUMBER = "account_number"

    # --- Organisations ---
    EMPLOYER_NAME = "employer_name"
    ORGANIZATION = "organization"

    # --- Practitioner / firm identifiers ---
    PTIN = "ptin"
    EFIN = "efin"
    CAF_NUMBER = "caf_number"
    IP_PIN = "ip_pin"
    PREPARER_ID = "preparer_id"
    CLIENT_ID = "client_id"
    DOCUMENT_ID = "document_id"

    # --- Other ---
    SIGNATURE = "signature"
    CREDENTIAL = "credential"
    URL_WITH_TOKEN = "url_with_token"
    UNKNOWN_SENSITIVE = "unknown_sensitive"


#: Types whose surrogate must preserve the *format* of the original so that
#: downstream form-filling and column widths still work.
FORMAT_PRESERVING_TYPES: frozenset[PiiType] = frozenset(
    {
        PiiType.SSN,
        PiiType.ITIN,
        PiiType.EIN,
        PiiType.PHONE,
        PiiType.ROUTING_NUMBER,
        PiiType.BANK_ACCOUNT,
        PiiType.CREDIT_CARD,
        PiiType.DATE_OF_BIRTH,
        PiiType.PTIN,
        PiiType.EFIN,
    }
)

#: Types that carry the highest breach impact. The egress guard always blocks
#: on these regardless of confidence.
CRITICAL_TYPES: frozenset[PiiType] = frozenset(
    {
        PiiType.SSN,
        PiiType.ITIN,
        PiiType.EIN,
        PiiType.BANK_ACCOUNT,
        PiiType.ROUTING_NUMBER,
        PiiType.CREDIT_CARD,
        PiiType.PASSPORT,
        PiiType.IP_PIN,
        PiiType.CREDENTIAL,
    }
)


@dataclass(frozen=True, slots=True)
class PatternSpec:
    """A named regex with a base confidence and an optional validator."""

    pii_type: PiiType
    name: str
    regex: re.Pattern[str]
    base_confidence: float
    #: Name of a validator in ``VALIDATORS``; applied to the matched text.
    validator: str | None = None
    #: Matches failing the validator keep this (lower) confidence.
    demoted_confidence: float = 0.45


# ---------------------------------------------------------------------------
# Structural validators
# ---------------------------------------------------------------------------


#: A CUSIP is the nine-character public identifier of a security, printed on
#: every trade line of a 1099-B. It is not client data, and the detection
#: service deliberately does not mask it -- masking it would corrupt the
#: brokerage detail the model has to read.
#:
#: The egress guard has to know that too. All-digit CUSIPs are common, and one
#: in nine begins with 9 with a second pair inside an IRS-assigned ITIN group,
#: so a brokerage statement reliably contains a CUSIP that *is* a well-formed
#: ITIN. The guard blocked one, and that workpaper produced no return at all on
#: five consecutive batches. Both sides now read this one definition.
CUSIP_RE = re.compile(r"(?i)\bCUSIP[\s:#]*([A-Z0-9]{9})\b")


def is_valid_ssn(value: str) -> bool:
    """Check SSN issuance rules (SSA never issues these)."""
    digits = re.sub(r"\D", "", value)
    if len(digits) != 9:
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    if area in {"000", "666"}:
        return False
    if area.startswith("9"):  # 900-999 is ITIN space, not SSN
        return False
    if group == "00" or serial == "0000":
        return False
    return True


def is_valid_itin(value: str) -> bool:
    """ITIN: 9xx-NN-xxxx where NN falls in an IRS-assigned range."""
    digits = re.sub(r"\D", "", value)
    if len(digits) != 9 or not digits.startswith("9"):
        return False
    group = int(digits[3:5])
    return (
        50 <= group <= 65
        or 70 <= group <= 88
        or 90 <= group <= 92
        or 94 <= group <= 99
    )


def is_valid_aba_routing(value: str) -> bool:
    """ABA routing transit number checksum (3-7-1 weighting, mod 10)."""
    digits = re.sub(r"\D", "", value)
    if len(digits) != 9:
        return False
    weights = (3, 7, 1, 3, 7, 1, 3, 7, 1)
    total = sum(int(d) * w for d, w in zip(digits, weights, strict=True))
    return total % 10 == 0


def is_valid_luhn(value: str) -> bool:
    """Luhn checksum, used for payment card numbers."""
    digits = [int(c) for c in re.sub(r"\D", "", value)]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, digit in enumerate(digits):
        if i % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def is_plausible_ein(value: str) -> bool:
    """EIN prefixes are IRS campus codes; a few values are never issued."""
    digits = re.sub(r"\D", "", value)
    if len(digits) != 9:
        return False
    return digits[:2] not in {"00", "07", "08", "09", "17", "18", "19", "28",
                              "29", "49", "78", "79", "89"}


VALIDATORS = {
    "ssn": is_valid_ssn,
    "itin": is_valid_itin,
    "aba": is_valid_aba_routing,
    "luhn": is_valid_luhn,
    "ein": is_plausible_ein,
}


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_R = re.compile

PATTERN_SPECS: tuple[PatternSpec, ...] = (
    # --- Government identifiers -------------------------------------------
    # Ordered before generic 9-digit rules so the specific type wins.
    PatternSpec(
        PiiType.SSN,
        "ssn_delimited",
        _R(r"\b(?!000|666|9\d\d)\d{3}[-–\s]\d{2}[-–\s]\d{4}\b"),
        0.98,
        validator="ssn",
        demoted_confidence=0.80,
    ),
    PatternSpec(
        PiiType.SSN,
        "ssn_labeled",
        _R(
            r"(?i)\b(?:s\.?s\.?n\.?|social\s+security(?:\s+(?:no|number|#))?)"
            r"[\s:#]*([0-9]{3}[-–\s]?[0-9]{2}[-–\s]?[0-9]{4})\b"
        ),
        0.97,
    ),
    PatternSpec(
        PiiType.ITIN,
        "itin",
        _R(r"\b9\d{2}[-–\s]?(?:5\d|6[0-5]|7\d|8[0-8]|9[0-24-9])[-–\s]?\d{4}\b"),
        0.94,
        validator="itin",
    ),
    PatternSpec(
        PiiType.EIN,
        "ein_delimited",
        _R(r"\b\d{2}-\d{7}\b"),
        0.93,
        validator="ein",
        demoted_confidence=0.70,
    ),
    PatternSpec(
        PiiType.EIN,
        "ein_labeled",
        _R(
            r"(?i)\b(?:e\.?i\.?n\.?|employer\s+id(?:entification)?"
            r"(?:\s+(?:no|number|#))?|federal\s+id(?:\s+(?:no|number|#))?)"
            r"[\s:#]*(\d{2}-?\d{7})\b"
        ),
        0.95,
    ),
    PatternSpec(
        PiiType.PASSPORT,
        "passport",
        _R(r"(?i)\bpassport(?:\s+(?:no|number|#))?[\s:#]*([A-Z0-9]{6,9})\b"),
        0.90,
    ),
    PatternSpec(
        PiiType.DRIVERS_LICENSE,
        "drivers_license",
        _R(
            r"(?i)\b(?:driver'?s?\s+licen[sc]e|dl|state[-\s]issued\s+id)"
            r"(?:\s+(?:no|number|#))?[\s:#]*([A-Z0-9]{5,20})\b"
        ),
        0.85,
    ),

    # --- Practitioner / IRS identifiers ------------------------------------
    PatternSpec(PiiType.PTIN, "ptin", _R(r"\bP\d{8}\b"), 0.92),
    PatternSpec(
        PiiType.EFIN,
        "efin",
        _R(r"(?i)\befin[\s:#]*(\d{6})\b"),
        0.90,
    ),
    PatternSpec(
        PiiType.CAF_NUMBER,
        "caf",
        _R(r"(?i)\bcaf(?:\s+(?:no|number|#))?[\s:#]*(\d{4}-?\d{5})\b"),
        0.88,
    ),
    PatternSpec(
        PiiType.IP_PIN,
        "ip_pin",
        _R(r"(?i)\b(?:ip\s*pin|identity\s+protection\s+pin)[\s:#]*(\d{6})\b"),
        0.93,
    ),

    # --- Financial ---------------------------------------------------------
    PatternSpec(
        PiiType.ROUTING_NUMBER,
        "routing_labeled",
        _R(
            r"(?i)\b(?:routing|aba|rtn|transit)"
            r"(?:\s+(?:no|number|#|transit))?[\s:#]*(\d{9})\b"
        ),
        0.95,
        validator="aba",
        demoted_confidence=0.70,
    ),
    PatternSpec(
        PiiType.BANK_ACCOUNT,
        "bank_account_labeled",
        _R(
            r"(?i)\b(?:account|acct|a/c)(?:\s+(?:no|number|#))?"
            r"[\s:#]*([0-9][0-9\- ]{5,20}[0-9])\b"
        ),
        0.90,
    ),
    PatternSpec(
        PiiType.CREDIT_CARD,
        "credit_card",
        _R(r"\b(?:\d{4}[-\s]?){3}\d{3,4}\b"),
        0.92,
        validator="luhn",
        demoted_confidence=0.50,
    ),
    PatternSpec(
        PiiType.ACCOUNT_NUMBER,
        "account_bare_long",
        # Brokerage/policy numbers: 8-17 digits standing alone. Deliberately
        # broad; the detection service suppresses money-like and year-like hits.
        _R(r"\b\d{8,17}\b"),
        0.55,
    ),

    # --- Contact -----------------------------------------------------------
    PatternSpec(
        PiiType.EMAIL,
        "email",
        _R(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        0.97,
    ),
    PatternSpec(
        PiiType.PHONE,
        "phone_us",
        _R(
            r"(?:(?<=^)|(?<=[^\d.]))"
            r"(?:\+?1[-.\s]?)?"
            r"(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}"
            r"(?![\d.])"
        ),
        0.85,
    ),
    PatternSpec(
        PiiType.ADDRESS,
        "street_address",
        _R(
            # [ \t] rather than \s throughout: \s matches newlines, which let
            # the match run past the end of the address line and swallow the
            # next line's form label.
            r"(?i)\b\d{1,6}[ \t]+(?:[A-Z0-9][A-Za-z0-9.'\-]*[ \t]+){0,4}"
            r"(?:street|st|avenue|ave|boulevard|blvd|road|rd|drive|dr|lane|ln|"
            r"court|ct|circle|cir|place|pl|terrace|ter|way|parkway|pkwy|"
            r"highway|hwy|route|rte|trail|trl|square|sq|loop|run|path|pass)"
            # Optional directional suffix ("Wooddale Ave S") — without this the
            # match ends early and a trailing unit number escapes masking.
            r"\.?(?:[ \t]+(?:N|S|E|W|NE|NW|SE|SW)\.?)?"
            r"(?:[ \t]*,?[ \t]*(?:apt|apartment|unit|suite|ste|rm|room|fl|floor|#)"
            r"\.?[ \t]*[A-Z0-9\-]+)?\b"
        ),
        0.82,
    ),
    PatternSpec(
        PiiType.ADDRESS,
        "city_state_zip",
        _R(r"\b[A-Z][A-Za-z.\- ]{2,28},\s*(?:[A-Z]{2})\s+\d{5}(?:-\d{4})?\b"),
        0.86,
    ),
    PatternSpec(
        PiiType.ADDRESS,
        "po_box",
        _R(r"(?i)\bP\.?\s?O\.?\s+Box\s+\d{1,7}\b"),
        0.88,
    ),

    # --- Dates of birth ----------------------------------------------------
    PatternSpec(
        PiiType.DATE_OF_BIRTH,
        "dob_labeled",
        _R(
            r"(?i)\b(?:d\.?o\.?b\.?|date\s+of\s+birth|birth\s?date|born)"
            r"[\s:#]*((?:0?[1-9]|1[0-2])[/\-.](?:0?[1-9]|[12]\d|3[01])"
            r"[/\-.](?:19|20)\d{2})\b"
        ),
        0.95,
    ),

    # --- Credentials -------------------------------------------------------
    PatternSpec(
        PiiType.CREDENTIAL,
        "generic_secret",
        # Require an actual assignment delimiter (: or =), optionally through a
        # closing quote, so this matches real secrets ("api_key": "...", token=..)
        # and the JSON shape the egress guard scans — but NOT ordinary prose that
        # merely contains a keyword ("authorization requests", "secret formula").
        _R(
            r"(?i)\b(?:password|passwd|pwd|api[_\-\s]?key|secret|token|"
            r"bearer|authorization|private[_\-\s]?key)"
            r"[\"']?\s*[:=]\s*[\"']?([^\s\"'<>,;]{6,})"
        ),
        0.93,
    ),
    PatternSpec(
        PiiType.URL_WITH_TOKEN,
        "url_credentials",
        _R(r"https?://[^\s/@]+:[^\s/@]+@\S+"),
        0.95,
    ),
)


#: Compact pattern set used by the log redaction filter. Log redaction runs on
#: every record, so it stays cheap: only unambiguous, high-signal patterns.
LOG_REDACTION_SPECS: tuple[PatternSpec, ...] = tuple(
    spec
    for spec in PATTERN_SPECS
    if spec.name
    in {
        "ssn_delimited",
        "ssn_labeled",
        "itin",
        "ein_delimited",
        "ein_labeled",
        "email",
        "phone_us",
        "credit_card",
        "routing_labeled",
        "bank_account_labeled",
        "generic_secret",
        "url_credentials",
        "ptin",
        "ip_pin",
        "city_state_zip",
        "street_address",
    }
)


# ---------------------------------------------------------------------------
# Token vocabulary
# ---------------------------------------------------------------------------

#: Short prefix used when minting tokens, e.g. ``SSN_001``.
TOKEN_PREFIXES: dict[PiiType, str] = {
    PiiType.PERSON_NAME: "PERSON",
    PiiType.SSN: "SSN",
    PiiType.ITIN: "ITIN",
    PiiType.EIN: "EIN",
    PiiType.DATE_OF_BIRTH: "DOB",
    PiiType.DRIVERS_LICENSE: "DL",
    PiiType.STATE_ID: "STATEID",
    PiiType.PASSPORT: "PASSPORT",
    PiiType.ADDRESS: "ADDRESS",
    PiiType.PHONE: "PHONE",
    PiiType.EMAIL: "EMAIL",
    PiiType.BANK_ACCOUNT: "BANK",
    PiiType.ROUTING_NUMBER: "ROUTING",
    PiiType.CREDIT_CARD: "CARD",
    PiiType.ACCOUNT_NUMBER: "ACCT",
    PiiType.EMPLOYER_NAME: "EMPLOYER",
    PiiType.ORGANIZATION: "ORG",
    PiiType.PTIN: "PTIN",
    PiiType.EFIN: "EFIN",
    PiiType.CAF_NUMBER: "CAF",
    PiiType.IP_PIN: "IPPIN",
    PiiType.PREPARER_ID: "PREPARER",
    PiiType.CLIENT_ID: "CLIENT",
    PiiType.DOCUMENT_ID: "DOCID",
    PiiType.SIGNATURE: "SIGNATURE",
    PiiType.CREDENTIAL: "CREDENTIAL",
    PiiType.URL_WITH_TOKEN: "URL",
    PiiType.UNKNOWN_SENSITIVE: "SENSITIVE",
}

#: Matches any token this system mints. Used to recognise already-masked text
#: and to keep the egress guard from flagging our own placeholders.
TOKEN_RE: re.Pattern[str] = _R(
    r"\b(?:" + "|".join(sorted(set(TOKEN_PREFIXES.values()))) + r")_\d{3,6}\b"
)


def apply_validator(spec: PatternSpec, matched_text: str) -> float:
    """Return the confidence for ``matched_text`` under ``spec``."""
    if spec.validator is None:
        return spec.base_confidence
    check = VALIDATORS[spec.validator]
    return spec.base_confidence if check(matched_text) else spec.demoted_confidence
