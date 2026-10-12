"""Render the schedules the engine already computes onto the real IRS forms.

Every figure here was being calculated and then discarded. Schedule A was worked
out in full purely to decide whether itemizing beat the standard deduction, and
then thrown away; Schedule 1's components were summed into one number on Form
1040 line 8 and the detail was lost. A preparer received a Form 1040 with no
schedules behind it, which is not a return anyone can file.

This module adds no tax logic. It takes what the engine already produced and
puts it on the form, which is why it can be trusted immediately: if a number is
wrong here, it was wrong on Form 1040 too.

Field maps come from ``scripts/derive_form_map.py``, which reads the line number
the IRS prints immediately left of each amount box. That beats transcribing
opaque names like ``f1_37[0]`` by hand — the two mistakes documented in
``form_1040_filler`` both came from doing it by eye.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import fitz

from app.core.logging import get_logger
from app.services.tax_engine.form_1040 import (
    AdjustmentInputs,
    CapitalGainInputs,
    DeductionInputs,
    IncomeInputs,
    PaymentInputs,
    Return1040,
    TaxpayerProfile,
)

logger = get_logger(__name__)

RESOURCES = Path(__file__).resolve().parent.parent / "resources"
ZERO = Decimal(0)

#: Tax year the bundled templates are printed for. Filling a 2024 return onto a
#: 2025 schedule would produce something that looks official and is wrong.
TEMPLATE_TAX_YEAR = 2025


def _money(amount: Decimal) -> str:
    """Whole dollars, negatives in parentheses.

    Accounting style, not a minus sign: it is what the printed form uses and
    what a reviewer's eye is calibrated for. A "-5,405" in a box that reads
    "( )" on either side is read as a positive by anyone skimming.
    """
    rounded = amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if rounded < 0:
        return f"({abs(rounded):,})"
    return f"{rounded:,}"


@dataclass(frozen=True, slots=True)
class RenderedSchedule:
    name: str
    filename: str
    content: bytes
    #: Line numbers actually written, for the audit trail.
    lines_written: tuple[str, ...]


class ScheduleTemplate:
    """One blank IRS form plus its derived line map."""

    def __init__(self, stem: str, title: str) -> None:
        self.stem = stem
        self.title = title
        self._pdf = RESOURCES / f"{stem}_{TEMPLATE_TAX_YEAR}.pdf"
        self._map = RESOURCES / f"{stem}_{TEMPLATE_TAX_YEAR}_map.json"

    @property
    def available(self) -> bool:
        return self._pdf.exists() and self._map.exists()

    def line_to_field(self) -> dict[str, str]:
        data = json.loads(self._map.read_text(encoding="utf-8"))
        return data.get("line_to_field", {})

    def fill(
        self, values: dict[str, Decimal], *, name: str = "", ssn: str = ""
    ) -> tuple[bytes, tuple[str, ...]]:
        """Write the values onto the form. Returns the PDF and the lines used."""
        mapping = self.line_to_field()
        wanted = {
            mapping[line]: _money(amount)
            for line, amount in values.items()
            if line in mapping
        }
        missing = sorted(set(values) - set(mapping))
        if missing:
            # Loud, because a silently dropped line is a figure the preparer
            # believes was reported and was not.
            logger.warning(
                "%s: no field for line(s) %s; they were not written",
                self.stem,
                ", ".join(missing),
            )

        written: list[str] = []
        with fitz.open(self._pdf) as document:
            for page in document:
                for widget in page.widgets():
                    short = (widget.field_name or "").split(".")[-1]
                    if short in wanted:
                        widget.field_value = wanted[short]
                        widget.update()
                        written.append(short)
                    elif name and short in {"f1_1[0]", "f1_01[0]"}:
                        widget.field_value = name
                        widget.update()
                    elif ssn and short in {"f1_2[0]", "f1_02[0]"}:
                        widget.field_value = ssn
                        widget.update()
            content = document.tobytes()

        used = tuple(
            line for line, field in mapping.items() if field in set(written)
        )
        return content, used


TEMPLATES: dict[str, ScheduleTemplate] = {
    "schedule_1": ScheduleTemplate("f1040s1", "Schedule 1 — Additional Income and Adjustments"),
    "schedule_1a": ScheduleTemplate("f1040s1a", "Schedule 1-A — Additional Deductions"),
    "schedule_2": ScheduleTemplate("f1040s2", "Schedule 2 — Additional Taxes"),
    "schedule_3": ScheduleTemplate("f1040s3", "Schedule 3 — Additional Credits and Payments"),
    "schedule_a": ScheduleTemplate("f1040sa", "Schedule A — Itemized Deductions"),
    "schedule_b": ScheduleTemplate("f1040sb", "Schedule B — Interest and Ordinary Dividends"),
    "schedule_d": ScheduleTemplate("f1040sd", "Schedule D — Capital Gains and Losses"),
}


# --- Line builders --------------------------------------------------------
#
# Each returns {form line number: amount}. Zero-valued lines are dropped: the
# IRS forms are read with blanks meaning "none", and printing 0 on thirty lines
# makes the two that matter harder to find.


def _drop_zeros(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Drop exact zeros. Negatives are meaningful and are kept."""
    return {line: amount for line, amount in values.items() if amount != ZERO}


def schedule_1_lines(
    result: Return1040, income: IncomeInputs, adjustments: AdjustmentInputs
) -> dict[str, Decimal]:
    line_8 = result.line("8")
    line_10 = result.line("10")
    return _drop_zeros(
        {
            "3": Decimal(income.business_income),
            "4": Decimal(income.other_gains),
            "5": Decimal(income.rental_income),
            "8z": Decimal(income.other_income),
            "9": Decimal(income.other_income),
            "10": line_8.amount if line_8 else ZERO,
            # Part II — adjustments.
            "11": Decimal(adjustments.educator_expenses),
            "13": Decimal(adjustments.hsa_deduction),
            "15": Decimal(adjustments.self_employment_tax_deduction),
            "16": Decimal(adjustments.self_employed_retirement),
            "17": Decimal(adjustments.self_employed_health_insurance),
            "20": Decimal(adjustments.ira_deduction),
            "21": Decimal(adjustments.student_loan_interest),
            "26": line_10.amount if line_10 else ZERO,
        }
    )


def schedule_1a_lines(
    result: Return1040, profile: TaxpayerProfile
) -> dict[str, Decimal]:
    if result.additional_deductions <= ZERO:
        return {}
    agi = result.adjusted_gross_income
    threshold = Decimal(150000 if result.filing_status == "married_joint" else 75000)
    return _drop_zeros(
        {
            "1": agi,
            "3": agi,
            "31": agi,
            "32": threshold,
            # Genuinely negative when income is below the threshold, and the
            # form wants that: it is what shows the deduction was not phased
            # out. Kept out of _drop_zeros' way by being non-zero.
            "33": agi - threshold,
            "35": result.additional_deductions,
            "36a": result.additional_deductions,
            "37": result.additional_deductions,
            "38": result.additional_deductions,
        }
    )


def schedule_2_lines(result: Return1040) -> dict[str, Decimal]:
    """Part II — the other taxes that make up Form 1040 line 23.

    The engine's ``other_taxes`` is self-employment tax and nothing else today,
    so line 4 and the line 21 total are the same figure. If another other-tax is
    ever added to the engine, line 4 must stop mirroring the total — the
    assertion below is what will catch that rather than a silently wrong form.
    """
    other = result.other_taxes
    if other <= ZERO:
        return {}
    line_23 = result.line("23")
    se_tax = line_23.amount if line_23 is not None else other
    return _drop_zeros({"4": se_tax, "21": other})


def schedule_3_lines(result: Return1040, payments: PaymentInputs) -> dict[str, Decimal]:
    """Part I — nonrefundable credits other than the child tax credit.

    The child tax credit is reported on Form 1040 line 19 directly and must not
    appear here as well; line 8 of this schedule lands on Form 1040 line 20, and
    the two are added together on line 21.

    Part II is not rendered: the engine folds ``other_payments`` straight into
    total payments without a line 31, so there is no figure here that could be
    traced back to the return.
    """
    other = Decimal(payments.other_nonrefundable_credits)
    if other <= ZERO:
        return {}
    return _drop_zeros({"6z": other, "7": other, "8": other})


def schedule_a_lines(
    result: Return1040, deductions: DeductionInputs
) -> dict[str, Decimal]:
    agi = result.adjusted_gross_income
    medical = Decimal(deductions.medical_expenses)
    floor = (agi * Decimal("0.075")).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    salt = (
        Decimal(deductions.state_local_income_tax)
        + Decimal(deductions.real_estate_tax)
        + Decimal(deductions.personal_property_tax)
    )
    gifts = Decimal(deductions.charitable_cash) + Decimal(deductions.charitable_noncash)
    return _drop_zeros(
        {
            "1": medical,
            "2": agi,
            "3": floor,
            "4": max(ZERO, medical - floor),
            "5a": Decimal(deductions.state_local_income_tax),
            "5b": Decimal(deductions.real_estate_tax),
            "5c": Decimal(deductions.personal_property_tax),
            "5d": salt,
            "7": salt,
            "8a": Decimal(deductions.mortgage_interest),
            "9": Decimal(deductions.investment_interest),
            "11": Decimal(deductions.charitable_cash),
            "12": Decimal(deductions.charitable_noncash),
            "14": gifts,
            "15": Decimal(deductions.casualty_losses),
            "16": Decimal(deductions.other_itemized),
        }
    )


def schedule_b_lines(result: Return1040, income: IncomeInputs) -> dict[str, Decimal]:
    interest = Decimal(income.taxable_interest)
    dividends = Decimal(income.ordinary_dividends)
    return _drop_zeros(
        {
            "2": interest,
            "4": interest,
            "6": dividends,
        }
    )


def schedule_d_lines(
    result: Return1040, capital_gains: CapitalGainInputs
) -> dict[str, Decimal]:
    detail = result.schedule_d
    if detail is None:
        return {}
    return _drop_zeros(
        {
            "5": Decimal(capital_gains.short_term_from_k1),
            "6": Decimal(capital_gains.short_term_loss_carryover),
            "7": detail.short_term_net,
            "12": Decimal(capital_gains.long_term_from_k1),
            "13": Decimal(capital_gains.capital_gain_distributions),
            "14": Decimal(capital_gains.long_term_loss_carryover),
            "15": detail.long_term_net,
            "16": detail.net,
        }
    )


# --- Orchestration --------------------------------------------------------


def render_schedules(
    *,
    result: Return1040,
    income: IncomeInputs,
    adjustments: AdjustmentInputs,
    deductions: DeductionInputs,
    capital_gains: CapitalGainInputs,
    payments: PaymentInputs,
    profile: TaxpayerProfile,
    taxpayer_name: str = "",
    taxpayer_ssn: str = "",
) -> list[RenderedSchedule]:
    """Every schedule the return actually needs, in filing order.

    A schedule with nothing on it is not produced. An empty Schedule B in a
    package tells the reader the preparer did not know whether it applied.
    """
    if result.tax_year != TEMPLATE_TAX_YEAR:
        logger.warning(
            "Schedules not rendered: templates are for %s, return is %s",
            TEMPLATE_TAX_YEAR,
            result.tax_year,
        )
        return []

    plan = [
        ("schedule_1", "Schedule 1", schedule_1_lines(result, income, adjustments)),
        ("schedule_1a", "Schedule 1-A", schedule_1a_lines(result, profile)),
        ("schedule_2", "Schedule 2", schedule_2_lines(result)),
        ("schedule_3", "Schedule 3", schedule_3_lines(result, payments)),
        # Schedule A is rendered only when it was actually used. Including the
        # losing side of the standard-versus-itemized comparison would put a
        # form in the package that does not belong to the return.
        (
            "schedule_a",
            "Schedule A",
            schedule_a_lines(result, deductions)
            if result.deduction_method == "itemized"
            else {},
        ),
        ("schedule_b", "Schedule B", schedule_b_lines(result, income)),
        ("schedule_d", "Schedule D", schedule_d_lines(result, capital_gains)),
    ]

    rendered: list[RenderedSchedule] = []
    for key, label, values in plan:
        if not values:
            continue
        template = TEMPLATES[key]
        if not template.available:
            logger.warning("%s template missing; skipping", label)
            continue
        try:
            content, used = template.fill(
                values, name=taxpayer_name, ssn=taxpayer_ssn
            )
        except Exception as exc:  # noqa: BLE001 - one form must not sink the rest
            logger.error("%s not rendered: %s", label, type(exc).__name__)
            continue
        # Numbered beneath the Form 1040 they belong to, so the package lists
        # 1 - Form 1040, then 1.1, 1.2 ... and the schedules cannot collide
        # with the guides and reports that take the whole numbers. They did:
        # a delivered package held both "2 - START HERE.md" and
        # "2 - Schedule 1 (2025).pdf", which sort apart and read as unrelated.
        rendered.append(
            RenderedSchedule(
                name=label,
                filename=(
                    f"1.{len(rendered) + 1} - {label} ({result.tax_year}).pdf"
                ),
                content=content,
                lines_written=used,
            )
        )
    return rendered
