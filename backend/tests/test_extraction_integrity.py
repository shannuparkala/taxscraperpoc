"""Guards against a return being computed from a document nobody read.

Every test here corresponds to a real defect found by tracing why a 37-page
workpaper produced an output package containing nothing but zeros. The failure
was silent at four separate layers, and each layer gets a test:

  * OCR reported 100% confidence on a document it had read 24% of
  * unreadable pages raised an audit event but never reached the review queue
  * the extraction contract named one field; recomputation consumed seven, and
    withholding was in neither, so a refund could not be produced at all
  * the engine computed a well-formed $0 return from an empty extraction and
    the pipeline shipped it as the answer

A $0 return that looks finished is worse than a crash: a crash gets
investigated, and this does not.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import STAGE_LABELS, WORKFLOW_STAGE_ORDER, WorkflowStage
from app.services.ocr_service import (
    DocumentExtraction,
    ExtractionMethod,
    OcrService,
    PageExtraction,
)
from app.services.tax_engine.form_1040 import (
    AdditionalDeductionInputs,
    AdjustmentInputs,
    CapitalGainInputs,
    DeductionInputs,
    Form1040Calculator,
    IncomeInputs,
    PaymentInputs,
    TaxpayerProfile,
)
from app.services.tax_engine.tax_tables import STANDARD_DEDUCTION, FilingStatusTax
from app.services.workflow_orchestrator import (
    ENGINE_MONEY_FIELDS,
    _amount,
    _build_engine_inputs,
    _infer_status,
    _reported_money_fields,
    _stage_note,
    _summarize_detail,
    _summarize_pages,
    merge_extractions,
)


def _page(number: int, *, text: str, confidence: float) -> PageExtraction:
    return PageExtraction(
        page_number=number,
        text=text,
        method=(
            ExtractionMethod.OCR_TESSERACT if text else ExtractionMethod.NONE
        ),
        mean_confidence=confidence,
        is_scanned=True,
    )


def _workpaper_read_at_24_percent() -> DocumentExtraction:
    """The shape of the document that produced the empty package.

    Nine pages carried a thin identity overlay and scored perfectly; the other
    twenty-eight were scanned images with no text layer and no OCR engine
    available, so they yielded nothing.
    """
    readable = {5, 7, 12, 13, 15, 24, 25, 27, 28}
    pages = [
        _page(n, text="MICHAEL J ANDERSON" if n in readable else "",
              confidence=1.0 if n in readable else 0.0)
        for n in range(1, 38)
    ]
    return DocumentExtraction(
        pages=pages,
        engine="text_layer",
        ocr_available=False,
        blocked_pages=[n for n in range(1, 38) if n not in readable],
    )


# --------------------------------------------------------------- confidence


def test_confidence_counts_unread_pages_as_zero() -> None:
    """Regression: a document read at 24% reported full confidence.

    ``mean_confidence`` averaged only over pages that produced text. The nine
    readable pages each scored 1.0, so the document claimed 1.0 while 28 pages
    had never been read — and the pipeline went on to compute a return from it.
    """
    extraction = _workpaper_read_at_24_percent()

    assert extraction.mean_confidence < 0.30, (
        "confidence must describe the whole document, not the subset that "
        f"happened to be readable (got {extraction.mean_confidence})"
    )


def test_coverage_reports_the_fraction_actually_read() -> None:
    extraction = _workpaper_read_at_24_percent()
    assert extraction.coverage == pytest.approx(9 / 37, abs=0.01)


def test_summary_surfaces_blocked_pages_and_coverage() -> None:
    """The summary is what reaches the audit log and the operator."""
    summary = _workpaper_read_at_24_percent().summary()

    assert len(summary["blocked_pages"]) == 28
    assert summary["coverage"] < 0.25
    assert summary["mean_confidence"] < 0.30


def test_fully_read_document_still_reports_high_confidence() -> None:
    """The fix must not penalise a document that genuinely read well."""
    extraction = DocumentExtraction(
        pages=[_page(n, text="Wages 85000.00", confidence=0.95) for n in range(1, 6)]
    )

    assert extraction.mean_confidence == pytest.approx(0.95)
    assert extraction.coverage == 1.0
    assert extraction.summary()["blocked_pages"] == []


def test_low_confidence_pages_exclude_unread_ones() -> None:
    """A page that was not read is blocked, not low-confidence.

    They need different remedies — rescan versus verify — so they must not be
    reported as the same problem.
    """
    extraction = DocumentExtraction(
        pages=[
            _page(1, text="clean", confidence=0.95),
            _page(2, text="smudged", confidence=0.31),
            _page(3, text="", confidence=0.0),
        ],
        blocked_pages=[3],
    )

    assert extraction.low_confidence_pages == [2]


# ------------------------------------------------------ OCR variant choice


def test_alternate_ocr_pass_cannot_win_by_discarding_content() -> None:
    """Regression: confidence alone selects whichever pass read least.

    Measured on the sample corpus, one segmentation mode scored 0.52 against
    0.31 on the same page by returning a sixth of the words. Higher confidence
    about a page you barely read is not an improvement, and a value that never
    left OCR cannot be flagged for review the way a misread one can.
    """
    incumbent = {"words": ["w"] * 1605, "mean_confidence": 0.31}
    sparse_but_confident = {"words": ["w"] * 265, "mean_confidence": 0.52}

    assert not OcrService._is_better(sparse_but_confident, incumbent)


def test_alternate_ocr_pass_wins_when_it_reads_more_at_equal_confidence() -> None:
    incumbent = {"words": ["w"] * 656, "mean_confidence": 0.40}
    fuller = {"words": ["w"] * 1166, "mean_confidence": 0.40}

    assert OcrService._is_better(fuller, incumbent)


def test_alternate_ocr_pass_wins_on_confidence_when_content_is_retained() -> None:
    incumbent = {"words": ["w"] * 100, "mean_confidence": 0.30}
    better = {"words": ["w"] * 95, "mean_confidence": 0.90}

    assert OcrService._is_better(better, incumbent)


# ------------------------------------------------------ page orientation


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_unrotated_boxes_land_back_on_the_page(rotation: int) -> None:
    """A word box read from a turned image must point at the original page.

    The scanned 1099-B pages in the sample corpus are sideways. Reading them
    upright is what makes their amounts legible at all, but if the boxes are
    left in rotated coordinates the review UI highlights the wrong region on
    every one of them — correct text pointing somewhere else is arguably worse
    than no highlight.
    """
    width, height = 612.0, 792.0

    x0, y0, x1, y1 = OcrService._unrotate_bbox(
        (10.0, 20.0, 60.0, 40.0), rotation=rotation, width=width, height=height
    )

    assert x0 < x1 and y0 < y1, "box must stay well-formed"
    assert 0 <= x0 <= width and 0 <= x1 <= width
    assert 0 <= y0 <= height and 0 <= y1 <= height


def test_unrotate_is_identity_for_an_upright_page() -> None:
    box = (10.0, 20.0, 60.0, 40.0)

    assert (
        OcrService._unrotate_bbox(box, rotation=0, width=612.0, height=792.0) == box
    )


def test_unrotate_preserves_box_dimensions_under_quarter_turns() -> None:
    """A quarter turn swaps width and height; it must not resize the box."""
    box = (10.0, 20.0, 60.0, 40.0)
    original_w, original_h = box[2] - box[0], box[3] - box[1]

    x0, y0, x1, y1 = OcrService._unrotate_bbox(
        box, rotation=90, width=612.0, height=792.0
    )

    assert (x1 - x0, y1 - y0) == (original_h, original_w)


# ------------------------------------------------------------ page ranges


def test_blocked_pages_render_as_readable_ranges() -> None:
    """28 comma-separated integers in a queue item is not actionable."""
    pages = [1, 2, 3, 4, 6, 8, 9, 10, 11, 14, 16, 17, 18, 19, 20, 21, 22, 23,
             26, 29, 30, 31, 32, 33, 34, 35, 36, 37]

    assert _summarize_pages(pages) == "1-4, 6, 8-11, 14, 16-23, 26, 29-37"


def test_page_summary_handles_empty_and_single() -> None:
    assert _summarize_pages([]) == "none"
    assert _summarize_pages([7]) == "7"


# --------------------------------------------------- extraction contract


def test_engine_vocabulary_covers_every_input_dataclass() -> None:
    """The prompt publishes this list; recomputation reads it back.

    If they drift, fields go unrequested or unconsumed without any error.
    """
    for source in (IncomeInputs, AdjustmentInputs, DeductionInputs, PaymentInputs):
        declared = {
            entry.name
            for entry in source.__dataclass_fields__.values()
            if "Decimal" in str(entry.type)
        }
        missing = declared - set(ENGINE_MONEY_FIELDS)
        assert not missing, f"{source.__name__} fields not in vocabulary: {missing}"


def test_withholding_reaches_the_engine() -> None:
    """Regression: a refund was structurally impossible.

    Recomputation wired seven income fields by hand and no payment fields at
    all, so ``total_payments`` was always zero and no return could ever show a
    refund, however well the source document was read.
    """
    assert "federal_withheld" in ENGINE_MONEY_FIELDS

    payments = _build_engine_inputs(
        PaymentInputs, {"federal_withheld": "12,666.00"}
    )
    assert payments.federal_withheld == Decimal("12666.00")


def test_deduction_and_adjustment_fields_reach_the_engine() -> None:
    deductions = _build_engine_inputs(
        DeductionInputs, {"mortgage_interest": "9500", "charitable_cash": "1200"}
    )
    adjustments = _build_engine_inputs(
        AdjustmentInputs, {"student_loan_interest": "1750"}
    )

    assert deductions.mortgage_interest == Decimal(9500)
    assert deductions.charitable_cash == Decimal(1200)
    assert adjustments.student_loan_interest == Decimal(1750)


def test_non_monetary_fields_are_not_wired_as_money() -> None:
    """``force_itemize`` is a bool and must not be parsed as an amount."""
    assert "force_itemize" not in ENGINE_MONEY_FIELDS


# -------------------------------------------------------- amount parsing


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("34833.37", Decimal("34833.37")),
        ("$12,666.00", Decimal("12666.00")),
        ("(1,234.56)", Decimal("-1234.56")),  # accounting negative
        ("-500", Decimal(-500)),
        (0, Decimal(0)),
        ("0", Decimal(0)),
    ],
)
def test_amount_parses_document_formats(raw: object, expected: Decimal) -> None:
    assert _amount(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "n/a", "see attached", "-"])
def test_amount_returns_none_for_non_numbers(raw: object) -> None:
    """Absent must stay distinguishable from zero.

    The engine treats them the same, but the sufficiency gate does not: a
    return whose every field defaulted to zero is an empty extraction, not a
    taxpayer with no income.
    """
    assert _amount(raw) is None


def test_zero_is_a_reported_value_but_absent_is_not() -> None:
    assert _reported_money_fields({"wages": "0"}) == ["wages"]
    assert _reported_money_fields({"wages": ""}) == []
    assert _reported_money_fields({}) == []


# ------------------------------------------------ per-document extraction


def test_repeated_documents_sum_rather_than_overwrite() -> None:
    """A taxpayer with three 1099-INTs has the total of all three.

    Extraction runs once per classified document, so the same field name
    arrives more than once. Taking the last one seen would silently drop every
    earlier account.
    """
    merged = merge_extractions(
        [
            ("1099_int", {"normalized_fields": {"taxable_interest": "150.00"}}),
            ("1099_int", {"normalized_fields": {"taxable_interest": "75.50"}}),
            ("1099_int", {"normalized_fields": {"taxable_interest": "12.25"}}),
        ]
    )

    assert merged["normalized_fields"]["taxable_interest"] == "237.75"


def test_prior_year_return_amounts_are_never_summed_in() -> None:
    """A prior-year return states a full set of figures for the wrong year.

    The sample workpaper carries one. Folding its wages and withholding into
    this year's totals would roughly double the return while looking entirely
    plausible on the face of it — the most dangerous kind of wrong answer.
    """
    merged = merge_extractions(
        [
            ("w2", {"normalized_fields": {"wages": "85000", "federal_withheld": "12666"}}),
            (
                "prior_year_return",
                {"normalized_fields": {"wages": "79000", "federal_withheld": "11000"}},
            ),
        ]
    )

    assert merged["normalized_fields"]["wages"] == "85000"
    assert merged["normalized_fields"]["federal_withheld"] == "12666"


def test_prior_year_facts_are_still_reported_for_comparison() -> None:
    """Excluded from the totals, not discarded — a preparer compares years."""
    merged = merge_extractions(
        [
            (
                "prior_year_return",
                {
                    "normalized_fields": {"wages": "79000"},
                    "extracted_tax_facts": [{"field": "wages", "value": "79000"}],
                },
            )
        ]
    )

    assert len(merged["extracted_tax_facts"]) == 1
    assert "wages" not in merged["normalized_fields"]


def test_facts_carry_their_source_document_type() -> None:
    merged = merge_extractions(
        [("1099_b", {"extracted_tax_facts": [{"field": "capital_gain_loss"}]})]
    )

    assert merged["extracted_tax_facts"][0]["document_type"] == "1099_b"


def test_scalar_facts_take_the_first_document_that_states_them() -> None:
    """Filing status cannot be summed; two documents stating it must not fight."""
    merged = merge_extractions(
        [
            ("client_organizer", {"normalized_fields": {"filing_status": "single"}}),
            ("w2", {"normalized_fields": {"filing_status": "married_joint"}}),
        ]
    )

    assert merged["normalized_fields"]["filing_status"] == "single"


def test_merging_nothing_yields_an_empty_extraction_not_a_crash() -> None:
    merged = merge_extractions([])

    assert merged["extracted_tax_facts"] == []
    assert _reported_money_fields(merged["normalized_fields"]) == []


# --------------------------------------------------------- filing status


@pytest.mark.parametrize(
    ("stated", "expected"),
    [
        ("Joint", FilingStatusTax.MARRIED_JOINT),
        ("joint", FilingStatusTax.MARRIED_JOINT),
        ("Married Filing Jointly", FilingStatusTax.MARRIED_JOINT),
        ("MFJ", FilingStatusTax.MARRIED_JOINT),
        ("Single", FilingStatusTax.SINGLE),
        ("Head of Household", FilingStatusTax.HEAD_OF_HOUSEHOLD),
        ("married filing separately", FilingStatusTax.MARRIED_SEPARATE),
        ("Qualifying Widow(er)", FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE),
    ],
)
def test_filing_status_aliases(stated: str, expected: FilingStatusTax) -> None:
    """Regression: the sample workpaper states "Joint".

    It was absent from the alias table and silently became Single — around a
    $15,000 error in the standard deduction alone, on a return that otherwise
    looked completely ordinary.
    """
    assert _infer_status({"filing_status": stated}) is expected


@pytest.mark.parametrize("stated", ["", "   ", "married", "unknown", "n/a"])
def test_unrecognised_filing_status_is_not_guessed(stated: str) -> None:
    """Returning None forces the caller to raise a review item.

    Bare "married" is deliberately unmapped: it does not distinguish joint from
    separate, and the two produce materially different returns. Choosing for
    the taxpayer is exactly the guess to avoid.
    """
    assert _infer_status({"filing_status": stated}) is None


def test_missing_filing_status_key_is_not_guessed() -> None:
    assert _infer_status({}) is None


# ------------------------------------------------------------- tax tables


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (FilingStatusTax.SINGLE, "15750"),
        (FilingStatusTax.MARRIED_JOINT, "31500"),
        (FilingStatusTax.MARRIED_SEPARATE, "15750"),
        (FilingStatusTax.HEAD_OF_HOUSEHOLD, "23625"),
        (FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE, "31500"),
    ],
)
def test_2025_standard_deduction_matches_published_figures(
    status: FilingStatusTax, expected: str
) -> None:
    """Regression: the table held the superseded pre-OBBBA projections.

    The One Big Beautiful Bill Act raised the 2025 standard deduction above
    what inflation indexing alone had projected ($15,000 / $30,000 / $22,500).
    Those projections were still in the table, understating every standard
    deduction by about 5% and so overstating taxable income on every return
    that does not itemize.

    Verified against the IRS "New and enhanced deductions for individuals"
    guidance; the sample accountant copy independently shows 15750 for a
    single filer.
    """
    assert STANDARD_DEDUCTION[2025][status] == Decimal(expected)


def test_2025_standard_deduction_exceeds_2024() -> None:
    """Cheap directional guard: these only ever move up with inflation."""
    for status, amount in STANDARD_DEDUCTION[2025].items():
        assert amount > STANDARD_DEDUCTION[2024][status], status


#: Basic 5, read off the accountant copy's own Form 1040 (pages 25-26) and the
#: CCH Return Summary (page 7, FEDERAL column). These are stated on the prepared
#: return; everything else about this case is inference.
BASIC_5 = {
    "wages": Decimal(91933),          # line 1a, W-2 box 1
    "taxable_interest": Decimal(1014),  # line 2b
    "capital_loss": Decimal(-189),    # line 7a
    "agi": Decimal(92758),            # line 11
    "standard_deduction": Decimal(15750),   # line 12e
    "qbi": Decimal(0),                # line 13a — blank on the return
    "schedule_1a": Decimal(2905),     # line 13b — qualified OVERTIME deduction
    "total_deductions": Decimal(18655),     # line 14
    "taxable_income": Decimal(74103), # line 15
    "tax": Decimal(11222),            # line 16
    "other_taxes": Decimal(0),        # line 23 — blank
    "total_tax": Decimal(11222),      # line 24
    "withholding": Decimal(12666),    # line 25d
    "refund": Decimal(1444),          # line 35a
}


def test_engine_reproduces_a_real_prepared_return() -> None:
    """Tie-out against the accountant copy for the Basic 5 sample.

    A return prepared independently by a licensed firm on commercial software,
    which makes it the strongest check available on the engine.

    Two earlier versions of this test were wrong, in the same way and for the
    same reason: both reverse-fitted a composition that reached the right
    totals instead of reading the prepared return.

    The first reconstructed the income as wages plus 9,054 of qualified
    dividends and asserted a refund of 1,444 with no self-employment tax. The
    second — written after decomposing the Return Summary arithmetically —
    decided the 2,905 on line 13b was a §199A deduction and that 2,888 of
    self-employment tax explained the balance, and asserted an amount *owed*.

    The prepared return settles it. Line 13a (QBI) is blank. Line 23 (other
    taxes) is blank. Line 13b is 2,905 of **qualified overtime compensation**
    under Schedule 1-A Part III, from W-2 box 1. And the Return Summary reads
    ``AMOUNT DUE <REFUND> -1444`` — the same sign convention it uses for
    withholding, so it is a refund.

    The lesson both times: a benchmark decomposed from totals can be
    self-consistent and still describe a different return. Read the form.
    """
    computed = Form1040Calculator().compute(
        profile=TaxpayerProfile(
            tax_year=2025, filing_status=FilingStatusTax.SINGLE, taxpayer_age=43
        ),
        income=IncomeInputs(
            wages=BASIC_5["wages"],
            taxable_interest=BASIC_5["taxable_interest"],
        ),
        capital_gains=CapitalGainInputs(
            short_term_gain=Decimal("-35.51"),
            long_term_gain=Decimal("-153.86"),
        ),
        additional_deductions=AdditionalDeductionInputs(
            qualified_overtime=BASIC_5["schedule_1a"],
        ),
        payments=PaymentInputs(federal_withheld=BASIC_5["withholding"]),
    )

    lines = {line.number: line.amount for line in computed.lines}

    # Whole dollars: the prepared return is rounded and the engine carries cents.
    def ties(actual: Decimal, expected: Decimal) -> bool:
        return abs(actual - expected) < Decimal(1)

    assert ties(lines["1a"], BASIC_5["wages"])
    assert ties(lines["2b"], BASIC_5["taxable_interest"])
    assert ties(lines["7"], BASIC_5["capital_loss"])
    assert ties(computed.total_income, BASIC_5["agi"])
    assert ties(computed.adjusted_gross_income, BASIC_5["agi"])
    assert computed.deduction_taken == BASIC_5["standard_deduction"]
    assert computed.deduction_method == "standard"
    assert "13a" not in lines, "the prepared return claims no QBI deduction"
    assert ties(lines["13b"], BASIC_5["schedule_1a"])
    assert ties(lines["14"], BASIC_5["total_deductions"])
    assert ties(computed.taxable_income, BASIC_5["taxable_income"])
    assert ties(computed.tax_before_credits, BASIC_5["tax"])
    assert computed.other_taxes == BASIC_5["other_taxes"]
    assert ties(computed.total_tax, BASIC_5["total_tax"])
    assert ties(computed.total_payments, BASIC_5["withholding"])
    assert ties(computed.refund, BASIC_5["refund"])
    assert computed.amount_owed == 0


def test_basic_5_line_13b_is_overtime_not_a_senior_deduction() -> None:
    """The filer was born in 1982, so Schedule 1-A Part V cannot apply.

    Only the senior part of Schedule 1-A was implemented, so this line came out
    blank for a 43-year-old with overtime pay — losing the whole 2,905.
    """
    computed = Form1040Calculator().compute(
        profile=TaxpayerProfile(
            tax_year=2025,
            filing_status=FilingStatusTax.SINGLE,
            age_65_or_older=0,
            taxpayer_age=43,
        ),
        income=IncomeInputs(wages=BASIC_5["wages"]),
        additional_deductions=AdditionalDeductionInputs(
            qualified_overtime=BASIC_5["schedule_1a"]
        ),
    )

    assert computed.schedule_1a is not None
    assert computed.schedule_1a.overtime == BASIC_5["schedule_1a"]
    assert computed.schedule_1a.seniors == 0
    assert computed.additional_deductions == BASIC_5["schedule_1a"]


def test_basic_5_uses_the_tax_table_not_the_rate_schedule() -> None:
    """The five dollars that separate a tie-out from a near miss.

    At 74,103 of taxable income the rate schedule gives 11,216.66 and the Tax
    Table gives 11,222. The prepared return says 11,222, because the Form 1040
    instructions send every return under 100,000 to the table, where each $50
    band is taxed at its midpoint.
    """
    from app.services.tax_engine.computations import (
        tax_on_ordinary_income,
        tax_table_lookup,
    )

    taxable = BASIC_5["taxable_income"]
    schedule = tax_on_ordinary_income(taxable, 2025, FilingStatusTax.SINGLE)
    table = tax_table_lookup(taxable, 2025, FilingStatusTax.SINGLE)

    assert schedule == Decimal("11216.66")
    assert table == BASIC_5["tax"]


# --------------------------------------------------------- refusal gate


def test_identity_only_extraction_reports_no_monetary_fields() -> None:
    """The exact payload that produced the all-zero package.

    Thirteen facts were extracted and every one was an identifier, because the
    only pages with a text layer were the ones carrying the client's name and
    address. This is the condition the pipeline must refuse to compute from.
    """
    identity_only = {
        "taxpayer_name": "MICHAEL J ANDERSON",
        "street_address": "125 PINE RIDGE DRIVE",
        "city": "PORTLAND",
        "state": "ME",
        "zip_code": "04101",
        "ssn": "666-00-1234",
        "phone_number": "555-555-0142",
    }

    assert _reported_money_fields(identity_only) == []


def test_a_single_extracted_amount_is_enough_to_compute() -> None:
    """The gate must block empty extractions, not partial ones.

    A partial return is a legitimate work product that a reviewer completes; an
    empty one is a failure wearing a result's clothes.
    """
    assert _reported_money_fields({"wages": "85000.00"}) == ["wages"]


# --------------------------------------------------- progress reporting


def test_stage_order_matches_execution_order() -> None:
    """OCR runs before classification, and the order tuple must say so.

    Every position-derived number is built from this tuple — ``stage_index``,
    ``progress_percent``, the UI timeline, the streaming progress bar. It listed
    classification first, so a watching user saw progress jump from 33% back to
    11% partway through a run.
    """
    order = list(WORKFLOW_STAGE_ORDER)

    assert order.index(WorkflowStage.OCR) < order.index(WorkflowStage.CLASSIFICATION), (
        "there is no text to classify until OCR has produced some"
    )
    assert order[0] is WorkflowStage.UPLOAD
    assert order[-1] is WorkflowStage.OUTPUT


def test_progress_percentages_never_decrease() -> None:
    total = len(WORKFLOW_STAGE_ORDER)
    percents = [round((i + 1) / total * 100) for i in range(total)]

    assert percents == sorted(percents)
    assert percents[-1] == 100


def test_every_stage_has_a_plain_english_label() -> None:
    """The enum values ("llm_processing") mean nothing to someone waiting."""
    for stage in WORKFLOW_STAGE_ORDER:
        label = STAGE_LABELS.get(stage)
        assert label, f"{stage.value} has no label"
        assert stage.value not in label, f"{stage.value} label is just the enum name"


def test_stage_notes_carry_counts_not_content() -> None:
    """The note is shown to the user and is not covered by masking.

    It is built from audit detail, which is counters only. This guards the
    habit: if a stage ever starts putting document text in its detail, the note
    must not pass it through.
    """
    note = _stage_note(
        WorkflowStage.LLM_PROCESSING,
        {"facts_returned": 21, "documents_extracted": 11, "wages": "85000"},
    )

    assert note == "Pulled 21 figures from 11 documents"
    assert "85000" not in note


def test_progress_note_reports_unread_pages() -> None:
    """Regression: the note could only ever announce success.

    ``_stage_note`` was fed ``run.detail`` — the output of
    ``_summarize_detail``, which keeps scalars only so that document content
    never reaches the persisted audit record. That filter also strips
    ``blocked_pages`` and ``low_confidence_pages``, the two lists this note
    exists to report, so both counts read as zero. A 55-page workpaper on a
    machine where OCR was blocked reported "Read all 55 pages clearly" while
    reading none of them.
    """
    every_page_failed = {
        "page_count": 55,
        "blocked_pages": list(range(1, 56)),
        "low_confidence_pages": [],
    }

    note = _stage_note(WorkflowStage.OCR, every_page_failed)

    assert "clearly" not in note
    assert "55 could not be read" in note


def test_progress_note_survives_the_audit_filter_being_applied_first() -> None:
    """Guard the wiring, not just the function.

    Passing the filtered dict is the mistake that caused the bug, so assert the
    two produce different notes — if a later change reintroduces the filter on
    this path, this fails.
    """
    detail = {
        "page_count": 55,
        "blocked_pages": list(range(1, 56)),
        "low_confidence_pages": [],
    }
    filtered = _summarize_detail(detail)

    assert _stage_note(WorkflowStage.OCR, detail) != _stage_note(
        WorkflowStage.OCR, filtered
    )


# ------------------------------------------------- partial text-layer overlay


class _FakePage:
    """A page whose layout we control, standing in for a fitz.Page.

    The real failure needs a scanned PDF with an identity overlay, which cannot
    be committed here: the corpus that exhibits it is live client data. The
    geometry is what matters and it reproduces exactly.
    """

    class _Rect:
        def __init__(self, w: float, h: float) -> None:
            self.width, self.height = w, h

    def __init__(self, *, image_area: float, words: list[tuple], text: str) -> None:
        self.rect = self._Rect(612.0, 792.0)
        self._image_area = image_area
        self._words = words
        self._text = text

    def get_text(self, kind: str = "text"):  # type: ignore[no-untyped-def]
        if kind == "words":
            return self._words
        if kind == "dict":
            side = self._image_area ** 0.5
            return {"blocks": [{"type": 1, "bbox": (0, 0, 612.0 * side, 792.0 * side)}]}
        return self._text


def test_identity_overlay_on_a_scan_is_not_accepted_as_a_text_layer() -> None:
    """The Basic 5 failure, in miniature.

    Nine of that workpaper's 37 pages carried 71-287 characters of name, SSN and
    address over a full-page raster. Every one cleared the 60-character bar, was
    scored at perfect confidence and skipped OCR, discarding 90 money-shaped
    values — 44% of the document's figures, both W-2s among them. The pipeline
    reported an AGI of -75 against a prepared 92,758.
    """
    overlay = _FakePage(
        image_area=1.0,
        # A name and address block: a handful of small boxes on a full page.
        words=[(50, 50 + 12 * i, 260, 60 + 12 * i, "x") for i in range(8)],
        text=(
            "XXX-XX-6789\nMICHAEL J ANDERSON\n125 PINE RIDGE DRIVE\n"
            "PORTLAND ME 04101\n"
        ),
    )

    assert OcrService._is_usable_text(overlay.get_text()) is True
    assert OcrService._is_partial_overlay(overlay) is True


def test_a_real_digital_form_keeps_its_text_layer() -> None:
    """The gate must not send every page to OCR to be safe.

    A born-digital form has no raster behind it, so it is accepted whatever its
    text covers.
    """
    digital = _FakePage(
        image_area=0.0,
        words=[(40, 40 + 10 * i, 560, 52 + 10 * i, "x") for i in range(60)],
        text="Form 1040 " + "wages and salaries 12,345.00 " * 20,
    )

    assert OcrService._is_partial_overlay(digital) is False


def test_a_full_transcription_over_a_scan_is_kept() -> None:
    """A scan whose text layer really does transcribe it is still usable.

    This is the case the coverage test must not break: OCR-under-image PDFs
    produced by a proper document scanner carry a word box for every printed
    word, so the text area is substantial even though the page is all raster.
    """
    transcribed = _FakePage(
        image_area=1.0,
        words=[(40, 40 + 11 * i, 570, 52 + 11 * i, "x") for i in range(64)],
        text="Wages, tips, other compensation 83,704.00 " * 30,
    )

    assert OcrService._is_partial_overlay(transcribed) is False


# ------------------------------------------------- which document a fact came off


def test_a_fact_is_attributed_to_the_document_that_reported_it() -> None:
    """Provenance was `documents[0]` for every fact in the workflow.

    Whatever row the query happened to return first became the source of every
    figure, so each `ExtractionResult` claimed provenance it did not have —
    and "which document and page did this come off" is the question the
    workpaper exists to answer.

    The knock-on was larger than the mislabelling: `assess_field_confidence`
    reads that row's OCR score and handwriting flag, so one handwritten
    organizer page at the head of the list marked all 84 figures on Basic 7 as
    needing review, most of them off pages read cleanly. Ninety queue items,
    nearly all wrong, is a queue nobody reads.
    """
    from app.services.workflow_orchestrator import _source_document_types

    sources = _source_document_types(
        {
            "field_provenance": {
                "wages": [{"document_type": "w2", "amount": "83704"}],
                "taxable_interest": [
                    {"document_type": "1099_int", "amount": "214"},
                    {"document_type": "brokerage_statement", "amount": "18"},
                ],
            },
            "scalar_candidates": {
                "taxpayer_name": [{"document_type": "client_organizer", "value": "X"}],
                # An empty document type must not win the field.
                "ssn": [{"document_type": "", "value": "666-01-0123"},
                        {"document_type": "w2", "value": "666-01-0123"}],
            },
        }
    )

    assert sources["wages"] == "w2"
    # A field summed from two documents keeps the first: one row points at one
    # document, and the workpaper still lists both contributions.
    assert sources["taxable_interest"] == "1099_int"
    assert sources["taxpayer_name"] == "client_organizer"
    assert sources["ssn"] == "w2"
    assert "total_income" not in sources


def test_several_documents_of_one_type_are_split_by_page() -> None:
    """Two W-2s in one workpaper are two documents, and the page says which."""
    from app.services.workflow_orchestrator import _pick_document

    class _Doc:
        def __init__(self, name: str, start: int, end: int) -> None:
            self.name, self.page_start, self.page_end = name, start, end

    first = _Doc("first", 3, 4)
    second = _Doc("second", 11, 12)

    assert _pick_document([first, second], 11).name == "second"  # type: ignore[arg-type]
    assert _pick_document([first, second], 3).name == "first"  # type: ignore[arg-type]
    # No page, or a page inside neither: the first is the honest guess.
    assert _pick_document([first, second], None).name == "first"  # type: ignore[arg-type]
    assert _pick_document([first, second], 40).name == "first"  # type: ignore[arg-type]
    assert _pick_document([], 3) is None
