"""Figure boxes: the one kind of raw word allowed past the masking boundary.

The drill-down needs to know where on a page a figure sits, so the masking
stage keeps the box of every money-shaped word. That is raw text persisted into
the masked zone, and these tests are the width of the hole: identifiers of
every shape the detector knows must fail the shape test on their own, and a
money-shaped word the detector *did* flag must be dropped anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal as D

import pytest

from app.services.figure_boxes import amount_of, figure_words, locate


@dataclass
class W:
    text: str
    bbox: tuple[float, float, float, float] = (10.0, 20.0, 60.0, 30.0)


@pytest.mark.security
@pytest.mark.parametrize(
    "word",
    [
        "666-12-3456",   # SSN, surrogate range
        "666123456",     # SSN without dashes
        "00-1234567",    # EIN, surrogate range
        "555-0100",      # phone, surrogate range
        "(555)",         # area code
        "60601",         # ZIP
        "60601-1234",    # ZIP+4
        "123456789012",  # account number
        "12/31/2024",    # date
        "2025",          # a year is a bare integer
        "4",             # a box number
    ],
)
def test_identifiers_never_pass_the_money_shape(word: str) -> None:
    assert amount_of(word) is None
    assert figure_words([W(word)], []) == []


@pytest.mark.parametrize(
    ("word", "value"),
    [
        ("1,234.00", D("1234.00")),
        ("85.00", D("85.00")),
        ("$5,000", D(5000)),
        ("(1,234.56)", D("-1234.56")),
        ("12,345,678", D(12345678)),
    ],
)
def test_figures_are_read_as_figures(word: str, value: D) -> None:
    assert amount_of(word) == value
    assert figure_words([W(word)], []) == [
        {"text": word, "bbox": [10.0, 20.0, 60.0, 30.0]}
    ]


@pytest.mark.security
def test_a_money_shaped_word_the_detector_flagged_is_dropped() -> None:
    """Rule 4: when unsure, mask. The detector's word beats the regex's."""
    flagged = ["Account 1,234.56 ending"]
    assert figure_words([W("1,234.56"), W("9,999.00")], flagged) == [
        {"text": "9,999.00", "bbox": [10.0, 20.0, 60.0, 30.0]}
    ]


@pytest.mark.security
def test_a_word_containing_a_flagged_span_is_dropped() -> None:
    assert figure_words([W("$1,234.56")], ["1,234.56"]) == []


def test_a_figure_is_located_only_when_it_is_unambiguous() -> None:
    figures = [
        {"text": "50,000.00", "bbox": [1, 1, 2, 2]},
        {"text": "3,100.00", "bbox": [3, 3, 4, 4]},
        {"text": "725.00", "bbox": [5, 5, 6, 6]},
        {"text": "725.00", "bbox": [7, 7, 8, 8]},
    ]
    assert locate("50000", figures) == [1, 1, 2, 2]
    assert locate("3,100.00", figures) == [3, 3, 4, 4]
    # A W-2 prints one amount in several boxes. Picking one would draw a
    # confident box around what may be the wrong one.
    assert locate("725", figures) is None
    assert locate("12", figures) is None
    assert locate("not a number", figures) is None
    # Zero is on every blank form; it locates nothing.
    assert locate("0", [{"text": "0.00", "bbox": [1, 1, 2, 2]}]) is None
