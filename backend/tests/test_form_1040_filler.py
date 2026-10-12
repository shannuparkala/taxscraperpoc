"""The filled Form 1040 is the deliverable, so its field mapping is a contract.

IRS field names are opaque (``f1_47[0]``), which makes a mis-mapping invisible
in code review and obvious only on the printed page — in the wrong box, next to
the wrong label, on a document someone signs under penalty of perjury. These
tests read values back out of the generated PDF and assert where they landed.

The tie-out case is a return prepared independently by a licensed firm: total
tax 11,222, payments 12,666, refund 1,444.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.form_1040_filler import (
    IDENTITY_FIELDS,
    LINE_TO_FIELD,
    Form1040Filler,
    TaxpayerIdentity,
    build_identity_from_facts,
    format_money,
)
from app.services.tax_engine.form_1040 import (
    Form1040Calculator,
    IncomeInputs,
    PaymentInputs,
    TaxpayerProfile,
)
from app.services.tax_engine.tax_tables import FilingStatusTax


def _return(**kwargs):  # type: ignore[no-untyped-def]
    """The accountant-copy tie-out unless a test overrides it."""
    defaults = dict(
        wages=Decimal(83704),
        ordinary_dividends=Decimal(9054),
        qualified_dividends=Decimal(9054),
    )
    defaults.update(kwargs)
    withheld = defaults.pop("federal_withheld", Decimal(12666))
    status = defaults.pop("filing_status", FilingStatusTax.SINGLE)
    return Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=status),
        income=IncomeInputs(**defaults),
        payments=PaymentInputs(federal_withheld=withheld),
    )


def _read_back(pdf: bytes) -> dict[str, str]:
    """Field short-name -> printed value, straight from the generated PDF."""
    import fitz

    values: dict[str, str] = {}
    with fitz.open(stream=pdf, filetype="pdf") as document:
        for page in document:
            for widget in page.widgets():
                if widget.field_value not in (None, "", "Off"):
                    short = widget.field_name.split(".")[-1]
                    values[short] = widget.field_value
    return values


def _by_line(pdf: bytes) -> dict[str, str]:
    values = _read_back(pdf)
    return {
        line: values[field]
        for line, field in LINE_TO_FIELD.items()
        if field in values
    }


# ----------------------------------------------------------------- tie-out


def test_filled_form_matches_the_prepared_return() -> None:
    """Every headline figure must land on its own line, not merely exist.

    The figures here are the wages-and-dividends fixture above, which is *not*
    the Basic 5 accountant copy — that tie-out lives in
    ``test_extraction_integrity.test_engine_reproduces_a_real_prepared_return``
    and needs a Schedule C and a §199A deduction this fixture has no room for.
    What this test checks is placement: that each computed total reaches the
    box a preparer expects to read it in.
    """
    lines = _by_line(Form1040Filler().fill(_return()))

    assert lines["9"] == "92,758"      # total income
    assert lines["11"] == "92,758"     # adjusted gross income
    assert lines["12"] == "15,750"     # standard deduction
    assert lines["15"] == "77,008"     # taxable income
    # 11,227 from the Tax Table, which this return's taxable income requires;
    # the rate schedule would give 11,222.10 and is not what a preparer uses.
    assert lines["16"] == "11,227"     # tax
    assert lines["24"] == "11,227"     # total tax
    assert lines["33"] == "12,666"     # total payments
    assert lines["34"] == "1,439"      # overpaid
    assert lines["35a"] == "1,439"     # refunded to you


def test_amount_owed_goes_on_line_37_not_the_refund_lines() -> None:
    """A balance due and a refund are different boxes on the form."""
    lines = _by_line(
        Form1040Filler().fill(_return(federal_withheld=Decimal(0)))
    )

    assert "37" in lines, "amount owed must be printed"
    assert lines.get("34") in (None, "0"), "nothing is overpaid when tax is owed"
    assert "35a" not in lines, "nothing is refunded when tax is owed"


# --------------------------------------------------------- field identity


def test_taxpayer_name_does_not_land_in_the_tax_year_boxes() -> None:
    """Regression on a trap in the form's own field numbering.

    f1_11..f1_13 sit visually where the name row appears and are the "tax year
    beginning / ending" header boxes. Mapping by position alone puts the
    taxpayer's name and SSN into the date fields, on a document that still
    looks entirely official.
    """
    identity = TaxpayerIdentity(
        first_name="ALEX", last_name="MORGAN", ssn="666-00-4321"
    )
    values = _read_back(Form1040Filler().fill(_return(), identity))

    assert values[IDENTITY_FIELDS["first_name"]] == "ALEX"
    assert values[IDENTITY_FIELDS["last_name"]] == "MORGAN"
    assert values[IDENTITY_FIELDS["ssn"]] == "666-00-4321"
    for header_box in ("f1_11[0]", "f1_12[0]", "f1_13[0]"):
        assert header_box not in values, f"{header_box} is a tax-year field"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (FilingStatusTax.SINGLE, "1"),
        (FilingStatusTax.MARRIED_JOINT, "2"),
        (FilingStatusTax.MARRIED_SEPARATE, "3"),
        (FilingStatusTax.HEAD_OF_HOUSEHOLD, "4"),
        (FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE, "5"),
    ],
)
def test_filing_status_checks_the_right_box(
    status: FilingStatusTax, expected: str
) -> None:
    """One radio group, five export values, printed in a fixed order."""
    values = _read_back(
        Form1040Filler().fill(_return(filing_status=status))
    )
    checked = {v for k, v in values.items() if k.startswith("c1_8")}

    assert checked == {expected}


# -------------------------------------------------------------- rendering


def test_untouched_lines_are_left_blank() -> None:
    """Prepared returns do not print a column of zeros.

    Filling every line with 0 buries the figures that matter and misreports
    "not applicable" as "computed, and it is zero".
    """
    lines = _by_line(Form1040Filler().fill(_return()))

    for empty in ("2a", "2b", "4a", "4b", "5a", "5b", "6a", "6b"):
        assert empty not in lines, f"line {empty} should be blank"


def test_running_totals_print_even_when_zero() -> None:
    """On a total, zero is a computed answer the reader needs to see."""
    lines = _by_line(
        Form1040Filler().fill(
            _return(
                wages=Decimal(0),
                ordinary_dividends=Decimal(0),
                qualified_dividends=Decimal(0),
                federal_withheld=Decimal(0),
            )
        )
    )

    assert lines["9"] == "0"    # total income
    assert lines["24"] == "0"   # total tax


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("11221.98"), "11,222"),   # IRS whole-dollar convention
        (Decimal("11221.49"), "11,221"),
        (Decimal(0), "0"),
        (Decimal("-378.74"), "(379)"),     # losses in parentheses
        (Decimal("1444.02"), "1,444"),
    ],
)
def test_money_formatting(amount: Decimal, expected: str) -> None:
    assert format_money(amount) == expected


def test_wrong_tax_year_is_refused() -> None:
    """A 2024 return on the 2025 form would look official and be wrong."""
    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2024, filing_status=FilingStatusTax.SINGLE),
        income=IncomeInputs(wages=Decimal(50000)),
    )

    with pytest.raises(ValueError, match="2025"):
        Form1040Filler().fill(result)


# ----------------------------------------------------------- identity split


@pytest.mark.parametrize(
    ("full_name", "first", "last"),
    [
        ("MICHAEL J ANDERSON", "MICHAEL J", "ANDERSON"),
        ("Alex Morgan", "Alex", "Morgan"),
        ("Cher", "", "Cher"),
        ("", "", ""),
    ],
)
def test_name_splits_on_the_final_token(
    full_name: str, first: str, last: str
) -> None:
    """The form has two boxes; extraction usually supplies one string."""
    identity = build_identity_from_facts({"taxpayer_name": full_name})

    assert identity.first_name == first
    assert identity.last_name == last


def test_only_allow_listed_identity_facts_reach_the_form() -> None:
    identity = build_identity_from_facts(
        {"taxpayer_name": "Alex Morgan", "employer_name": "Acme Inc", "wages": "50000"}
    )
    fields = identity.as_fields()

    assert "Acme Inc" not in fields.values()
    assert "50000" not in fields.values()


def test_line_25d_is_withholding_not_total_payments():
    """25d + 26 must foot to 33, or the printed form contradicts itself.

    25d once carried total_payments, so a return with 4,636 withheld and 2,000
    of estimated tax printed 6,636 on the withholding line and 6,636 again on
    line 33 — asserting the estimated payments had been withheld, and leaving
    the face of the return not adding up.
    """
    from decimal import Decimal as D

    from app.services.tax_engine.form_1040 import (
        Form1040Calculator,
        IncomeInputs,
        PaymentInputs,
        TaxpayerProfile,
    )
    from app.services.tax_engine.tax_tables import FilingStatusTax

    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=FilingStatusTax.SINGLE),
        income=IncomeInputs(wages=D(90000)),
        payments=PaymentInputs(federal_withheld=D(4636), estimated_payments=D(2000)),
    )

    assert result.federal_withheld == D(4636)
    assert result.total_payments == D(6636)

    values = Form1040Filler()._build_values(result)
    fields = {field: value for field, value in values.items()}
    assert fields[LINE_TO_FIELD["25d"]] == "4,636"
    assert fields[LINE_TO_FIELD["33"]] == "6,636"


def test_withholding_is_reported_on_its_own_line():
    """Across nine real workpapers the engine never stated withholding."""
    from decimal import Decimal as D

    from app.services.tax_engine.form_1040 import (
        Form1040Calculator,
        IncomeInputs,
        PaymentInputs,
        TaxpayerProfile,
    )
    from app.services.tax_engine.tax_tables import FilingStatusTax

    result = Form1040Calculator().compute(
        profile=TaxpayerProfile(tax_year=2025, filing_status=FilingStatusTax.SINGLE),
        income=IncomeInputs(wages=D(50000)),
        payments=PaymentInputs(federal_withheld=D(1663)),
    )
    line = result.line("25")
    assert line is not None and line.amount == D(1663)


# ------------------------------------------- the spouse boxes belong to a spouse


def _identity_with_a_spouse() -> TaxpayerIdentity:
    return build_identity_from_facts(
        {
            "taxpayer_name": "ALEX MORGAN",
            "ssn": "666-01-0123",
            "spouse_name": "PATRICIA P MERCER",
            "spouse_ssn": "666-01-0456",
            "street_address": "1 Example Way",
            "city": "Springfield",
            "state": "IL",
            "zip_code": "62701",
        }
    )


def test_a_single_return_does_not_print_a_spouse():
    """An uncorroborated spouse name must not reach the form.

    One stray spouse name used to leave the filing status undetermined, which
    stopped the return being computed at all, so this could not happen. Now
    that it resolves to single, `build_identity_from_facts` still copies the
    name across — it copies whatever extraction found — and the boxes at the
    top of Form 1040 would have attributed a spouse to a return that says
    there is none.
    """
    # The identity object does carry the spouse — so it is the filler's guard
    # that removes it, not an accident of what extraction happened to find.
    assert IDENTITY_FIELDS["spouse_ssn"] in _identity_with_a_spouse().as_fields()

    pdf = Form1040Filler().fill(_return(), identity=_identity_with_a_spouse())
    printed = _read_back(pdf)
    assert "MERCER" not in " ".join(printed.values())
    assert "666-01-0456" not in " ".join(printed.values())
    # The taxpayer's own boxes are untouched.
    assert "MORGAN" in " ".join(printed.values())


def test_a_joint_return_still_prints_the_spouse():
    """The other half: a joint return without them is rejected on submission."""
    pdf = Form1040Filler().fill(
        _return(filing_status=FilingStatusTax.MARRIED_JOINT),
        identity=_identity_with_a_spouse(),
    )
    printed = " ".join(_read_back(pdf).values())
    assert "MERCER" in printed
    assert "666-01-0456" in printed
