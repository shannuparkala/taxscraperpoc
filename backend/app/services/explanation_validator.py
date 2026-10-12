"""The gate a model-written explanation must pass: no number it was not given.

A model asked to explain "line 11a: 88,000 - 4,200 = 83,800" in plain English
will, some of the time, helpfully round to "about 84,000", restate the standard
deduction from memory, or compute a figure the engine never produced. Each of
those reads as fluent, checked prose and is exactly rule 3's failure: the model
producing a number. So an explanation may contain only numbers that appear in
the provenance of the line it explains - the line's amount, its inputs, its
formula, its label and its reference - and anything else rejects the whole
explanation in favour of the deterministic one.

The check is on value, not spelling: "$88,000", "88,000.00" and "88000" are the
same number. Sign is ignored, because the prose says "a loss of 3,000" where
the line says "-3,000". Spelled-out magnitudes ("fifty thousand") are rejected
outright - they are a number the digit scan cannot see.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

# A number as prose writes one: optional $, digits with or without thousands
# separators, optional decimals, optional %. Line ids like "11a" and "1z"
# contribute their digits, which is why labels and references are allowed
# sources - "line 11a" is the number 11, and it is in the label.
_NUMBER = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?%?")

#: Words that make a figure without a digit in it.
_SPELLED = re.compile(
    r"\b(hundred|thousand|million|billion|dozen)s?\b", re.IGNORECASE
)


def numbers_in(text: str) -> list[Decimal]:
    """Every number written in digits in ``text``, as a value."""
    found: list[Decimal] = []
    for match in _NUMBER.finditer(text):
        digits = match.group(1).replace(",", "") + (match.group(2) or "")
        try:
            found.append(abs(Decimal(digits)))
        except InvalidOperation:
            continue
    return found


def _normal(value: Decimal) -> Decimal:
    """88000, 88000.00 and 88000.0 compare equal."""
    return abs(value).normalize() if value else Decimal(0)


def allowed_numbers(*sources: object) -> frozenset[Decimal]:
    """Every value a line's provenance states, from amounts and from text."""
    out: set[Decimal] = set()
    for source in sources:
        if source is None:
            continue
        if isinstance(source, Decimal | int):
            out.add(_normal(Decimal(source)))
        elif isinstance(source, str):
            out.update(_normal(n) for n in numbers_in(source))
        elif isinstance(source, Iterable):
            out.update(allowed_numbers(*source))
    return frozenset(out)


def validate_explanation(text: str, allowed: frozenset[Decimal]) -> list[str]:
    """Why ``text`` may not be shown, or an empty list if it may.

    Each entry names one offending number or word, so a rejected explanation
    can say what it tried to introduce.
    """
    problems: list[str] = []
    for match in _NUMBER.finditer(text):
        digits = match.group(1).replace(",", "") + (match.group(2) or "")
        try:
            value = _normal(Decimal(digits))
        except InvalidOperation:
            problems.append(match.group(0))
            continue
        if value not in allowed:
            problems.append(match.group(0))
    problems.extend(m.group(0) for m in _SPELLED.finditer(text))
    if not text.strip():
        problems.append("empty explanation")
    return problems
