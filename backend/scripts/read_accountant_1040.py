"""Read Form 1040 line values out of a scanned accountant-prepared return.

Needed so the engine can be scored against a real preparer's work automatically,
across many returns, instead of one case read by hand.

Two things make this harder than it looks, and both shaped the approach:

**The line-number glyphs are tiny and OCR mangles them.** "6a" comes back as
"6a_", "3a" as "f3a|", "12e" as "12e," or nothing. Anchoring on them loses most
of the page. The *labels* beside them are long words — "Social security
benefits", "adjusted gross income" — and OCR reads those reliably, so the anchor
is the label.

**Amounts live in two fixed columns.** The 1040 puts sub-line amounts (2a, 3a,
6a) in a middle column and the main line in a right column, often on the same
row. Position, not reading order, says which is which.
"""

from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import fitz
import pytesseract
from PIL import Image

#: Label fragment -> (right-column line, middle-column line). Lower-cased and
#: whitespace-stripped before matching, because OCR runs words together
#: ("bTaxableamount", "totalincome").
ANCHORS: list[tuple[str, str, str | None]] = [
    ("totalamountfromform", "1z", None),
    ("taxableinterest", "2b", "2a"),
    ("ordinarydividends", "3b", "3a"),
    ("iradistributions", "4b", "4a"),
    ("pensionsandannuities", "5b", "5a"),
    ("socialsecuritybenefits", "6b", "6a"),
    ("capitalgainorloss", "7", None),
    ("attachscheduledifrequired", "7", None),
    ("additionalincomefromschedule", "8", None),
    ("thisisyourtotalincome", "9", None),
    ("adjustmentstoincomefromschedule", "10", None),
    ("thisisyouradjustedgrossincome", "11", None),
    ("standarddeductionoritemized", "12", None),
    ("qualifiedbusinessincomededuction", "13a", None),
    ("additionaldeductionsfromschedule", "13b", None),
    ("addlines12", "14", None),
    ("thisisyourtaxableincome", "15", None),
    ("addlines16and17", "18", None),
    ("childtaxcredit", "19", None),
    ("addlines19and20", "21", None),
    ("thisisyourtotaltax", "24", None),
    ("addlines22and23", "24", None),
    ("estimatedtaxpaymentsandamount", "26", None),
    ("theseareyourtotalpayments", "33", None),
    ("thisistheamountyouoverpaid", "34", None),
    ("subtractline24fromline33", "34", None),
    ("amountofline34youwantrefunded", "35a", None),
    ("appliedtoyour", "36", None),
    ("amountyouowe", "37", None),
]

#: The middle amount column ends around 62% of page width at 300 DPI.
MIDDLE_COLUMN_MAX = 0.62


def _to_decimal(text: str) -> Decimal | None:
    cleaned = text.strip().replace("$", "").replace(",", "").rstrip(".)|_ ")
    negative = cleaned.startswith("(") or text.strip().startswith("<")
    cleaned = cleaned.lstrip("(<").rstrip(">")
    if not re.fullmatch(r"-?\d{1,12}(\.\d{1,2})?", cleaned or ""):
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -value if negative else value


def _rows(page: fitz.Page, dpi: int = 300) -> list[list[tuple[int, str]]]:
    """OCR the page into rows of (x, token), using tesseract's own line split."""
    pixmap = page.get_pixmap(dpi=dpi)
    data = pytesseract.image_to_data(
        Image.open(io.BytesIO(pixmap.tobytes("png"))),
        output_type=pytesseract.Output.DICT,
    )
    grouped: dict[tuple[int, int, int], list[tuple[int, str]]] = {}
    for index, raw in enumerate(data["text"]):
        token = (raw or "").strip()
        if not token:
            continue
        key = (
            data["block_num"][index],
            data["par_num"][index],
            data["line_num"][index],
        )
        grouped.setdefault(key, []).append((data["left"][index], token))
    return [sorted(row) for _, row in sorted(grouped.items())]


def _amounts_in(row: list[tuple[int, str]], width: int) -> list[tuple[int, Decimal]]:
    """Numeric values on the row, with adjacent fragments rejoined.

    OCR splits "1,793" into "1," and "793]" often enough that reading tokens
    individually loses roughly a third of the figures on a page.
    """
    found: list[tuple[int, Decimal]] = []
    index = 0
    while index < len(row):
        x, token = row[index]
        merged = token
        step = 1
        while (
            index + step < len(row)
            and row[index + step][0] - x < width * 0.045
            and re.fullmatch(r"[\d,.]{1,7}\)?", row[index + step][1])
        ):
            merged += row[index + step][1]
            step += 1
        value = _to_decimal(merged)
        if value is not None and re.search(r"\d", merged):
            found.append((x, value))
            index += step
        else:
            index += 1
    return found


#: Amounts above this are almost certainly two figures OCR ran together.
IMPLAUSIBLE = Decimal(50000000)


def read_form_1040(path: Path, page_index: int) -> dict[str, Decimal]:
    """Every Form 1040 line this page states, keyed by line number."""
    document = fitz.open(path)
    page = document[page_index]
    width = page.get_pixmap(dpi=300).width
    values: dict[str, Decimal] = {}

    for row in _rows(page):
        joined = "".join(token for _, token in row).lower()
        joined = re.sub(r"[^a-z0-9]", "", joined)
        for fragment, right_line, middle_line in ANCHORS:
            if fragment not in joined:
                continue
            amounts = _amounts_in(row, width)
            if not amounts:
                continue
            middle = [v for x, v in amounts if x < width * MIDDLE_COLUMN_MAX]
            right = [v for x, v in amounts if x >= width * MIDDLE_COLUMN_MAX]
            if right and right_line not in values and abs(right[-1]) < IMPLAUSIBLE:
                values[right_line] = right[-1]
            if (
                middle_line
                and middle
                and middle_line not in values
                and abs(middle[-1]) < IMPLAUSIBLE
            ):
                values[middle_line] = middle[-1]
    return values


def find_form_1040_pages(path: Path) -> list[int]:
    """Page indices whose top-left corner identifies them as Form 1040."""
    document = fitz.open(path)
    pages: list[int] = []
    for index, page in enumerate(document):
        box = fitz.Rect(0, 0, page.rect.width * 0.34, page.rect.height * 0.10)
        text = page.get_text(clip=box).strip()
        if len(text) <= 12:
            text = pytesseract.image_to_string(
                Image.open(io.BytesIO(page.get_pixmap(dpi=220, clip=box).tobytes("png")))
            )
        flat = re.sub(r"(?<=\d)\s+(?=\d)", "", " ".join(text.split()))
        if re.search(r"1040", flat) and not re.search(
            r"1040-?[A-Z]|SCHEDULE", flat, re.IGNORECASE
        ):
            pages.append(index)
    return pages


def read_accountant_return(path: Path) -> dict[str, Decimal]:
    """Merge every Form 1040 page found, first value winning."""
    merged: dict[str, Decimal] = {}
    for index in find_form_1040_pages(path):
        for line, value in read_form_1040(path, index).items():
            merged.setdefault(line, value)
    return merged


# --- Corroboration --------------------------------------------------------
#
# OCR of a dense scanned form is roughly 70-75% reliable at the digit level:
# a zero reads as "QO.", and "20,653" fragments into "20" "1" "2" and merges
# back as 201653. Scoring the engine against a misread ground truth would
# manufacture failures that do not exist, which is worse than scoring nothing.
#
# Form 1040 checks itself. Line 9 is the sum of the income lines, 11 is 9 minus
# 10, 14 is 12 plus 13b, and so on. A value that satisfies the form's own
# arithmetic was almost certainly read correctly; one that does not is dropped
# and reported as unread.

#: (target line, [addends], [subtrahends]) drawn from the form's printed
#: instructions, not from the engine — the point is an independent check.
IDENTITIES: list[tuple[str, list[str], list[str]]] = [
    ("9", ["1z", "2b", "3b", "4b", "5b", "6b", "7", "8"], []),
    ("11", ["9"], ["10"]),
    ("14", ["12", "13a", "13b"], []),
    ("15", ["11"], ["14"]),
    ("34", ["33"], ["24"]),
]

#: Whole dollars, so anything under a dollar is rounding, not disagreement.
TOLERANCE = Decimal(1)


def corroborate(values: dict[str, Decimal]) -> tuple[dict[str, Decimal], list[str]]:
    """Keep only figures the form's own arithmetic supports.

    Returns the trusted values and the lines that failed or were never read.
    A line not participating in any identity is kept as-is: there is nothing to
    check it against, and dropping it would discard most of the page.
    """
    trusted = dict(values)
    rejected: list[str] = []

    for target, addends, subtrahends in IDENTITIES:
        if target not in trusted:
            continue
        parts = [trusted.get(name) for name in addends + subtrahends]
        if any(part is None for part in parts):
            continue  # Not enough of the row was read to check anything.
        expected = sum(
            (trusted[name] for name in addends), start=Decimal(0)
        ) - sum((trusted[name] for name in subtrahends), start=Decimal(0))
        # Line 15 floors at zero; the identity holds only above it.
        if target == "15":
            expected = max(Decimal(0), expected)
        if abs(trusted[target] - expected) > TOLERANCE:
            rejected.append(target)
            del trusted[target]

    return trusted, rejected


def read_verified(path: Path) -> tuple[dict[str, Decimal], list[str]]:
    """Ground truth for one accountant copy, with unreliable reads removed."""
    return corroborate(read_accountant_return(path))
