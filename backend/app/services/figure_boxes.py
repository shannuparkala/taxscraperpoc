"""Where on a page each dollar figure sits, kept without keeping the page.

The drill-down opens the page a figure came off with that figure highlighted,
which needs its bounding box. OCR has every word's box, but the words are raw
document text and are dropped once masking has run. This keeps the one kind of
word the drill-down needs - a dollar amount - and nothing else.

SECURITY: this persists raw word text into the masked zone (``Document.layout``),
so it is a hole in the masking boundary exactly as wide as ``_MONEY`` allows.
Two rules keep it closed, and neither may be relaxed:

* **The shape is strict.** A figure has thousands separators or cents: 1,234 or
  85.00 or (1,234.56). A bare run of digits does not qualify, because that is
  what a ZIP code, an account number or an SSN without its dashes looks like,
  and a dash anywhere disqualifies the word (SSN, EIN, phone, date).
* **Anything the detector flagged is excluded,** whatever its shape. Rule 4:
  when unsure, mask. A figure lost from the drill-down costs a reviewer a few
  seconds; a detected identifier written back to disk is a breach.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

# SECURITY: see the module docstring before widening this. `[ \t]` is not
# needed - a word never spans whitespace - and there is deliberately no `-`.
_MONEY = re.compile(
    r"^\(?\$?(?:\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2})\)?$"
)


def amount_of(text: str) -> Decimal | None:
    """The figure a money-shaped word states, or None if it is not one.

    "(1,234.00)" is -1234. Anything else - a date, an identifier, a bare
    integer - is None, never zero: zero in a money column is itself a figure.
    """
    word = text.strip()
    if not _MONEY.match(word):
        return None
    negative = word.startswith("(") and word.endswith(")")
    digits = word.strip("()").lstrip("$").replace(",", "")
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return -value if negative else value


def figure_words(
    words: Iterable[Any], flagged_texts: Iterable[str]
) -> list[dict[str, Any]]:
    """The money-shaped words on one page, with their boxes.

    ``words`` are OCR ``Word`` objects (``text``, ``bbox``). ``flagged_texts``
    are the original texts of every span the PII detector found on the page.
    """
    # SECURITY: a word is dropped if it sits inside any detected span, or any
    # detected span sits inside it. Substring in both directions, because the
    # detector works on the page text and a word may be a piece of a span or a
    # span plus punctuation.
    flagged = [t.strip() for t in flagged_texts if t and t.strip()]
    out: list[dict[str, Any]] = []
    for word in words:
        text = str(getattr(word, "text", "")).strip()
        if amount_of(text) is None:
            continue
        if any(text in span or span in text for span in flagged):
            continue
        box = getattr(word, "bbox", None)
        if not box or len(box) != 4:
            continue
        out.append({"text": text, "bbox": [round(float(v), 2) for v in box]})
    return out


def locate(value: Any, figures: Sequence[Mapping[str, Any]]) -> list[float] | None:
    """The box of the one figure on the page that states ``value``.

    Exactly one match or nothing. A W-2 commonly prints the same amount in
    boxes 1, 3 and 5, and picking one of three would draw a confident box
    around what may be the wrong one - the drill-down highlights every match
    instead, and the source fact records no box rather than a guess.
    """
    target = _as_decimal(value)
    if target is None:
        return None
    matches = [
        figure["bbox"]
        for figure in figures
        if amount_of(str(figure.get("text", ""))) in (target, -target)
    ]
    distinct = {tuple(box) for box in matches}
    if len(distinct) != 1:
        return None
    return list(matches[0])


def _as_decimal(value: Any) -> Decimal | None:
    text = str(value or "").strip().replace("$", "").replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed != 0 else None
