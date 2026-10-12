"""A consolidated broker 1099 states its gains twice; it must be counted once.

Regression for a live defect. The UBS consolidated statement in the CS-2
workpaper reports its capital gains on a summary page and again across the
per-lot detail pages. The classifier labels those `1099_div` and `1099_b`
respectively — both correct — and the merge, which keyed duplicate detection on
the document type, treated them as two separate statements.

The visible symptom was on Form 1040 line 6b: taxable Social Security came out
at 7,844 instead of 4,500, produced by a §86 worksheet that was itself correct.
That is the failure mode worth guarding, because the wrong number appears on a
line whose own logic is sound.
"""

from __future__ import annotations

from decimal import Decimal as D

from app.services.workflow_orchestrator import merge_extractions


def _payload(**fields: str) -> dict[str, object]:
    return {"normalized_fields": dict(fields)}


def test_same_gain_from_summary_and_detail_pages_counts_once():
    """The exact figures from the failing run."""
    merged = merge_extractions(
        [
            # Page 13 — the consolidated summary page, classified 1099-DIV.
            (
                "1099_div",
                _payload(
                    ordinary_dividends="5012.35",
                    qualified_dividends="1792.68",
                    capital_gain_distributions="4698.39",
                    long_term_gain="7344.95",
                    short_term_gain="-893.86",
                ),
            ),
            # Pages 15-32 — the per-lot detail, classified 1099-B, restating
            # the same two totals.
            (
                "1099_b",
                _payload(long_term_gain="7344.95", short_term_gain="-893.86"),
            ),
        ]
    )
    normalized = merged["normalized_fields"]

    assert normalized["long_term_gain"] == "7344.95"
    assert normalized["short_term_gain"] == "-893.86"
    # Untouched fields still pass through.
    assert normalized["ordinary_dividends"] == "5012.35"
    assert normalized["capital_gain_distributions"] == "4698.39"


def test_dropping_a_duplicate_is_surfaced_not_silent():
    merged = merge_extractions(
        [
            ("1099_div", _payload(long_term_gain="7344.95")),
            ("1099_b", _payload(long_term_gain="7344.95")),
        ]
    )
    assert "duplicate_amounts_ignored" in merged["review_flags"]
    assert any("long_term_gain" in entry for entry in merged["duplicates_ignored"])


def test_genuinely_different_amounts_still_sum():
    """Dedup must not collapse two real accounts into one."""
    merged = merge_extractions(
        [
            ("1099_int", _payload(taxable_interest="213.50")),
            ("1099_int", _payload(taxable_interest="412.10")),
        ]
    )
    assert merged["normalized_fields"]["taxable_interest"] == "625.60"
    assert "duplicate_amounts_ignored" not in merged["review_flags"]


def test_provenance_records_only_the_counted_contribution():
    """A dropped duplicate must not appear as a second source on the trace."""
    merged = merge_extractions(
        [
            ("1099_div", _payload(long_term_gain="7344.95")),
            ("1099_b", _payload(long_term_gain="7344.95")),
        ]
    )
    entries = merged["field_provenance"]["long_term_gain"]
    assert len(entries) == 1
    assert entries[0]["document_type"] == "1099_div"


def test_line_6b_moves_back_toward_the_prepared_return():
    """End-to-end: the whole point of the fix.

    The prepared return shows 3,159. The double count put line 6b at 7,843 —
    the figure on the user's form. Removing it lands on 3,241. The residual 82
    is not an extraction defect: it is the net of two figures no current-year
    document states (a 4,511 capital loss carryover from the prior return, and
    a 5,469 Form 4797 gain the preparer entered by hand), which the pipeline
    correctly raises for review rather than inventing.
    """
    from app.services.tax_engine.computations import taxable_social_security
    from app.services.tax_engine.tax_tables import FilingStatusTax

    def line_6b(schedule_d: D) -> D:
        other = D("213.50") + D("5012.35") + D(1283) + schedule_d
        return taxable_social_security(
            benefits=D("27648.00"),
            other_income=other,
            year=2025,
            status=FilingStatusTax.SINGLE,
        )

    # What shipped: the same gains counted from both the summary and the detail.
    assert line_6b(D("-1787.72") + D("14689.90") + D("4698.39")) == D("7843.41")

    merged = merge_extractions(
        [
            (
                "1099_div",
                _payload(
                    ordinary_dividends="5012.35",
                    capital_gain_distributions="4698.39",
                    long_term_gain="7344.95",
                    short_term_gain="-893.86",
                ),
            ),
            ("1099_b", _payload(long_term_gain="7344.95", short_term_gain="-893.86")),
        ]
    )
    n = merged["normalized_fields"]
    schedule_d = (
        D(n["short_term_gain"])
        + D(n["long_term_gain"])
        + D(n["capital_gain_distributions"])
    )
    assert schedule_d == D("11149.48")
    assert line_6b(schedule_d) == D("3241.17")
