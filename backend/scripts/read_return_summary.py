"""Read the headline figures out of a CCH "Return Summary" page.

Ground truth for scoring. The obvious source is the filled Form 1040 itself, but
OCR of that page is only ~70% reliable at the digit level: a zero comes back as
"QO.", and "20,653" fragments into "20" "1" "2" and reassembles as 201653.
Scoring the engine against a misread benchmark manufactures failures that do not
exist, which is worse than not scoring at all.

The Return Summary page is a sparse, labelled, large-type table that CCH
ProSystem *fx* emits for every return, and it OCRs cleanly. It carries exactly
the figures that matter for accuracy — AGI, deductions, taxable income, tax,
payments, refund — each next to a full-word label rather than a two-character
line number.

One trap: the page is two columns, FEDERAL then the state. The first number
after a label is the federal one; taking the last silently scores the engine
against California.
"""

from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import fitz
import pytesseract
from PIL import Image

#: Label as printed -> the Form 1040 line it corresponds to.
LABELS: list[tuple[str, str]] = [
    ("ADJUSTED GROSS INCOME", "11"),
    ("ITEMIZED OR STANDARD DEDUCTION", "12"),
    ("ADDITIONAL DEDUCTIONS", "13b"),
    ("TAXABLE INCOME", "15"),
    ("INCOME TAX WITHHELD", "25"),
    ("ESTIMATED TAX PAID", "26"),
    ("AMOUNT OVERPAID", "34"),
    ("AMOUNT OF REFUND CREDITED TO NEXT YEAR", "36"),
    ("AMOUNT DUE", "37"),
    # "TAX" last: it is a substring of several labels above, so it must only
    # match what none of them claimed.
    ("TAX", "16"),
]

SUMMARY_HEADING = re.compile(r"Return\s+Summary", re.IGNORECASE)
FILING_STATUS = re.compile(
    r"FILING\s+STATUS\s+(SINGLE|MARRIED FILING JOINTLY|MARRIED FILING SEPARATELY"
    r"|HEAD OF HOUSEHOLD|QUALIFYING [A-Z ]+)",
    re.IGNORECASE,
)

#: A money token as CCH prints it: 20,653.  -17,750.  <REFUND> 0.  725.
MONEY = re.compile(r"<?-?[\d,]+\.?\d*>?")


def _to_decimal(token: str) -> Decimal | None:
    negative = token.startswith(("-", "<"))
    cleaned = token.strip("<>").lstrip("-").rstrip(".").replace(",", "")
    if not re.fullmatch(r"\d{1,12}(\.\d{1,2})?", cleaned or ""):
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -value if negative else value


def _page_text(page: fitz.Page, dpi: int = 200) -> str:
    """Page text, OCR'd if there is no usable layer.

    ``--psm 6`` — treat the image as a single uniform block — matters more than
    resolution here. Tesseract's default page segmentation reads this two-column
    table as prose and silently drops the number columns entirely, keeping every
    label and none of the values. At 400 DPI it was still dropping them; with
    psm 6 they come through at 200.
    """
    text = page.get_text().strip()
    if len(text) > 120:
        return " ".join(text.split())
    pixmap = page.get_pixmap(dpi=dpi)
    return " ".join(
        pytesseract.image_to_string(
            Image.open(io.BytesIO(pixmap.tobytes("png"))), config="--psm 6"
        ).split()
    )


#: CCH prints the Return Summary in the front matter, before the forms. Scanning
#: the whole package costs a minute of OCR per return to find a page that is
#: always in the first couple of dozen.
SEARCH_LIMIT = 24


def read_summary(path: Path, *, limit: int = SEARCH_LIMIT) -> dict[str, object]:
    """Federal headline figures, keyed by Form 1040 line, plus filing status."""
    document = fitz.open(path)
    values: dict[str, Decimal] = {}
    filing_status: str | None = None
    pages_used: list[int] = []

    for index, page in enumerate(document):
        if index >= limit:
            break
        text = _page_text(page)
        if not SUMMARY_HEADING.search(text):
            # Stop once past the summary block, but allow a two-page gap: the
            # figures and the filing status sit on consecutive Return Summary
            # pages and OCR occasionally misses the heading on one of them.
            if pages_used and index - (pages_used[-1] - 1) > 2:
                break
            continue
        pages_used.append(index + 1)

        if filing_status is None:
            match = FILING_STATUS.search(text)
            if match:
                filing_status = match.group(1).strip().lower().replace(" ", "_")

        upper = text.upper()
        for label, line in LABELS:
            if line in values:
                continue
            # Word-bounded, not substring: a plain find() for "TAX" matches
            # inside "TAXABLE INCOME" and reads that row's figure as the tax.
            # It agreed by coincidence on a return where both were zero, which
            # is exactly how a benchmark bug survives its first test.
            match = re.search(rf"(?<![A-Z]){re.escape(label)}(?![A-Z])", upper)
            if match is None:
                continue
            # The federal column comes first, so take the first money token
            # after the label rather than the last.
            tail = text[match.end() : match.end() + 90]
            for token in MONEY.findall(tail):
                amount = _to_decimal(token)
                if amount is not None:
                    values[line] = abs(amount)
                    break

    return {
        "lines": values,
        "filing_status": filing_status,
        "summary_pages": pages_used,
    }


def has_summary(path: Path) -> bool:
    return bool(read_summary(path)["summary_pages"])
