"""A review item must state the check that actually stopped it.

Two of the three confidence checks do not test the field's own confidence, and
the review item claimed they did: a field read at 95% off a page whose OCR
scored 41% produced "Extracted with 95% confidence, below the 90% threshold",
and handwriting, whose floor is 95%, produced "Extracted with 90% confidence,
below the 90% threshold". Both sentences contradict themselves, and between
sixty and ninety of them arrive on one workpaper.
"""

from __future__ import annotations

from app.models.enums import ReviewReason
from app.services.workflow_orchestrator import _why_this_field_needs_checking


def _explain(reason: ReviewReason, confidence: float, ocr: float | None) -> str:
    return _why_this_field_needs_checking(
        reason,
        confidence=confidence,
        ocr_confidence=ocr,
        field_floor=0.90,
        ocr_floor=0.60,
    )


def test_handwriting_cites_the_handwriting_floor() -> None:
    text = _explain(ReviewReason.HANDWRITING_UNCERTAIN, 0.90, 0.97)
    assert "handwritten" in text
    assert "95%" in text
    assert "below the 90% threshold" not in text


def test_an_unreadable_page_says_so_rather_than_blaming_the_field() -> None:
    text = _explain(ReviewReason.LOW_CONFIDENCE, 0.95, 0.41)
    assert "41%" in text
    assert "60% floor" in text
    # The old text asserted the opposite of the truth about this field.
    assert "95% confidence, below the 90%" not in text


def test_a_genuinely_weak_field_still_reads_the_way_it_did() -> None:
    text = _explain(ReviewReason.LOW_CONFIDENCE, 0.72, 0.97)
    assert text == "Extracted with 72% confidence, below the 90% threshold."


def test_no_ocr_score_falls_back_to_the_field_threshold() -> None:
    text = _explain(ReviewReason.LOW_CONFIDENCE, 0.72, None)
    assert "below the 90% threshold" in text


def test_every_message_is_arithmetically_true() -> None:
    """Whatever branch runs, the numbers in the sentence must agree with it."""
    cases = [
        (ReviewReason.HANDWRITING_UNCERTAIN, 0.90, 0.99),
        (ReviewReason.LOW_CONFIDENCE, 0.95, 0.41),
        (ReviewReason.LOW_CONFIDENCE, 0.72, 0.97),
        (ReviewReason.LOW_CONFIDENCE, 0.50, None),
    ]
    for reason, confidence, ocr in cases:
        text = _explain(reason, confidence, ocr)
        if "below the 90% threshold" in text:
            assert confidence < 0.90, text
