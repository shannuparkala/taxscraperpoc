"""Adversarial workpapers, generated from invented values at run time.

Phase 6.6: each synthetic case is a defect the pipeline must *flag* rather than
guess through - a sideways page, a poor scan, a duplicate, a W-2c, somebody
else's form in the bundle, a statement with a page missing, last year's return.
The documents are built here, from values that are invented and sit in the
surrogate ranges the egress guard already recognises (SSN 666-, EIN 00-,
``@example.com``), so nothing generated is anyone's data and the builder can be
committed. The PDFs themselves are not: they are built into a scratch directory
per run.

Every figure a case expects is a constant in this file and in that case's
``expected.json`` - the same number written twice on purpose, because a case
that derived its expectation from the builder would pass whatever the builder
did.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import fitz  # type: ignore[import-untyped]

TAXPAYER = ("Pat Example", "666-12-3456", "100 Sample Street, Springfield IL 62701")
OTHER_PERSON = ("Robin Specimen", "666-98-7654", "9 Other Avenue, Peoria IL 61602")
EMPLOYER = ("Example Widgets Inc", "00-1234567")


def _w2(
    *,
    wages: str,
    withheld: str,
    person: tuple[str, str, str] = TAXPAYER,
    corrected: bool = False,
    year: int = 2025,
) -> list[str]:
    title = f"{year} Form W-2c Corrected Wage and Tax Statement" if corrected else (
        f"{year} Form W-2 Wage and Tax Statement"
    )
    lines = [
        title,
        f"a Employee's social security number {person[1]}",
        f"b Employer identification number (EIN) {EMPLOYER[1]}",
        f"c Employer's name {EMPLOYER[0]}",
        f"e Employee's name {person[0]}",
        f"f Employee's address {person[2]}",
    ]
    if corrected:
        lines += [
            "Previously reported / Correct information",
            f"1 Wages, tips, other compensation  previously 50,000.00  correct {wages}",
            f"2 Federal income tax withheld  previously {withheld}  correct {withheld}",
        ]
    else:
        lines += [
            f"1 Wages, tips, other compensation {wages}",
            f"2 Federal income tax withheld {withheld}",
            f"3 Social security wages {wages}",
            f"5 Medicare wages and tips {wages}",
        ]
    return lines


def _1099b(page: int, of: int) -> list[str]:
    return [
        "2025 Form 1099-B Proceeds From Broker and Barter Exchange Transactions",
        f"Recipient {TAXPAYER[0]}  TIN {TAXPAYER[1]}",
        f"Page {page} of {of}",
        "Short-term transactions for which basis is reported to the IRS (Box A)",
        "1d Proceeds 18,400.00   1e Cost basis 15,150.00   Gain 3,250.00",
        "Summary: Total short-term gain 3,250.00",
    ]


def _organizer_prior_year() -> list[str]:
    return [
        "2024 Form 1040 U.S. Individual Income Tax Return (PRIOR YEAR COPY)",
        f"Name {TAXPAYER[0]}   SSN {TAXPAYER[1]}",
        "Filing status: Single",
        "1a Total amount from Form(s) W-2, box 1 48,900.00",
        "25a Federal income tax withheld from Form(s) W-2 5,410.00",
        "11 Adjusted gross income 48,900.00",
    ]


def _text_page(doc: fitz.Document, lines: list[str]) -> None:
    page = doc.new_page()
    for index, text in enumerate(lines):
        page.insert_text((60, 72 + 20 * index), text, fontsize=11)


def _image_page(
    doc: fitz.Document, lines: list[str], *, rotate: int = 0, dpi: int = 150, noise: bool = False
) -> None:
    """A page with no text layer: the text rendered to pixels, as a scan is."""
    scratch = fitz.open()
    _text_page(scratch, lines)
    pixmap = scratch[0].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    if noise:
        # Speckle every seventh pixel a mid grey: legible to a person, and
        # enough to drag OCR confidence under the floor.
        samples = bytearray(pixmap.samples)
        for i in range(0, len(samples), 7):
            samples[i] = 150
        pixmap = fitz.Pixmap(fitz.csGRAY, pixmap.width, pixmap.height, bytes(samples), False)
    image = pixmap.tobytes("png")
    page = doc.new_page()
    # /Rotate stays 0 while the content is turned: the case trap 12 describes.
    page.insert_image(page.rect, stream=image, rotate=rotate)
    scratch.close()


def _rotated_1099b(doc: fitz.Document) -> None:
    _text_page(doc, _w2(wages="52,340.00", withheld="6,120.00"))
    _image_page(doc, _1099b(1, 1), rotate=90)


def _poor_scan(doc: fitz.Document) -> None:
    _image_page(doc, _w2(wages="52,340.00", withheld="6,120.00"), dpi=60, noise=True)


def _duplicate_w2(doc: fitz.Document) -> None:
    _text_page(doc, _w2(wages="52,340.00", withheld="6,120.00"))
    _text_page(doc, _w2(wages="52,340.00", withheld="6,120.00"))


def _w2c(doc: fitz.Document) -> None:
    _text_page(doc, _w2(wages="50,000.00", withheld="6,120.00"))
    _text_page(doc, _w2(wages="52,340.00", withheld="6,120.00", corrected=True))


def _other_person(doc: fitz.Document) -> None:
    _text_page(doc, _w2(wages="52,340.00", withheld="6,120.00"))
    _text_page(doc, _w2(wages="71,800.00", withheld="9,050.00", person=OTHER_PERSON))


def _missing_pages(doc: fitz.Document) -> None:
    _text_page(doc, _w2(wages="52,340.00", withheld="6,120.00"))
    _text_page(doc, _1099b(1, 3))
    _text_page(doc, _1099b(3, 3))


def _prior_year(doc: fitz.Document) -> None:
    _text_page(doc, _w2(wages="52,340.00", withheld="6,120.00"))
    _text_page(doc, _organizer_prior_year())


BUILDERS: dict[str, Callable[[fitz.Document], None]] = {
    "rotated-1099b": _rotated_1099b,
    "poor-scan": _poor_scan,
    "duplicate-w2": _duplicate_w2,
    "w2c": _w2c,
    "other-person": _other_person,
    "missing-pages": _missing_pages,
    "prior-year": _prior_year,
}


def build(name: str, directory: Path) -> Path:
    """Write one synthetic workpaper and return its path."""
    if name not in BUILDERS:
        raise KeyError(f"no synthetic workpaper {name!r}; known: {', '.join(BUILDERS)}")
    doc = fitz.open()
    BUILDERS[name](doc)
    path = directory / f"synthetic-{name}.pdf"
    doc.save(path)
    doc.close()
    return path
