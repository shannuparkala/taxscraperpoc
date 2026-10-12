"""Lookup tables the engine computes against, derived from ``tax_authority``.

This module holds no figures of its own. Every value here is projected from
``tax_authority.YEARS``, where each one is declared alongside the revenue
procedure or public law that sets it and a flag saying whether that pairing was
checked against primary text.

The split exists because the two jobs pull in opposite directions. Computation
wants a flat dict keyed by year and filing status; auditing wants provenance
attached to every number. Carrying provenance inline made the tables unreadable,
and carrying bare numbers made them unciteable — so the authority module is the
single source and this module is its computed view.

An unknown year is a hard error rather than a silent fallback to the nearest
available one: quietly computing a 2025 return on 2024 brackets produces a wrong
return that looks right.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import NamedTuple

from app.services.tax_engine.tax_authority import YEARS, constants_for

D = Decimal


class FilingStatusTax(str, Enum):
    """Filing statuses as used by the rate tables (IRC §1)."""

    SINGLE = "single"
    MARRIED_JOINT = "married_joint"
    MARRIED_SEPARATE = "married_separate"
    HEAD_OF_HOUSEHOLD = "head_of_household"
    QUALIFYING_SURVIVING_SPOUSE = "qualifying_surviving_spouse"


class Bracket(NamedTuple):
    """One marginal rate band. ``upper`` of ``None`` means unbounded."""

    rate: Decimal
    lower: Decimal
    upper: Decimal | None


def _statuses(table: dict[str, object]) -> dict[FilingStatusTax, object]:
    """Key a status-named dict by the enum, adding the QSS alias.

    Qualifying surviving spouse uses the married-joint schedule (IRC §1(a)), so
    it is never stored separately — storing it twice is how the two drift.
    """
    out = {FilingStatusTax(name): value for name, value in table.items()}
    out[FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE] = out[FilingStatusTax.MARRIED_JOINT]
    return out


#: Ordinary income brackets: {year: {status: (Bracket, ...)}}
ORDINARY_BRACKETS: dict[int, dict[FilingStatusTax, tuple[Bracket, ...]]] = {
    year: _statuses(
        {
            name: tuple(Bracket(rate, lower, upper) for rate, lower, upper in bands)
            for name, bands in const.ordinary_brackets.items()
        }
    )
    for year, const in YEARS.items()
}

#: Long-term capital gain / qualified dividend brackets, IRC §1(h).
CAPITAL_GAIN_BRACKETS: dict[
    int, dict[FilingStatusTax, tuple[tuple[Decimal, Decimal | None], ...]]
] = {
    year: _statuses(dict(const.capital_gain_brackets))
    for year, const in YEARS.items()
}

#: Standard deduction, IRC §63(c).
STANDARD_DEDUCTION: dict[int, dict[FilingStatusTax, Decimal]] = {
    year: _statuses({n: c.value for n, c in const.standard_deduction.items()})
    for year, const in YEARS.items()
}

#: Additional standard deduction per qualifying condition (age 65+, blind).
ADDITIONAL_STANDARD_DEDUCTION: dict[int, dict[str, Decimal]] = {
    year: {n: c.value for n, c in const.additional_standard_deduction.items()}
    for year, const in YEARS.items()
}


class PayrollConstants(NamedTuple):
    social_security_wage_base: Decimal
    social_security_rate: Decimal          # employee share
    medicare_rate: Decimal                 # employee share
    additional_medicare_rate: Decimal      # IRC §3101(b)(2)
    additional_medicare_threshold_single: Decimal
    additional_medicare_threshold_joint: Decimal
    additional_medicare_threshold_mfs: Decimal
    se_net_earnings_rate: Decimal          # IRC §1402(a)(12)
    se_minimum_earnings: Decimal


PAYROLL: dict[int, PayrollConstants] = {
    year: PayrollConstants(
        *(const.scalars[name].value for name in PayrollConstants._fields)
    )
    for year, const in YEARS.items()
}


class CreditConstants(NamedTuple):
    child_tax_credit: Decimal
    child_tax_credit_refundable_cap: Decimal
    other_dependent_credit: Decimal
    ctc_phaseout_single: Decimal
    ctc_phaseout_joint: Decimal
    ctc_phaseout_rate: Decimal             # per $1,000 of excess MAGI
    ctc_max_age: Decimal
    actc_earned_income_floor: Decimal
    actc_rate: Decimal


CREDITS: dict[int, CreditConstants] = {
    year: CreditConstants(
        *(const.scalars[name].value for name in CreditConstants._fields)
    )
    for year, const in YEARS.items()
}


class Limits(NamedTuple):
    salt_cap: Decimal                      # IRC §164(b)(6)
    salt_cap_married_separate: Decimal
    salt_phasedown_threshold: Decimal
    salt_phasedown_rate: Decimal
    salt_cap_floor: Decimal
    capital_loss_deduction: Decimal        # IRC §1211(b)
    capital_loss_deduction_mfs: Decimal
    qbi_threshold_single: Decimal          # IRC §199A
    qbi_threshold_joint: Decimal
    qbi_phasein_range_single: Decimal
    qbi_phasein_range_joint: Decimal
    qbi_rate: Decimal
    student_loan_interest_cap: Decimal     # IRC §221
    educator_expense_cap: Decimal          # IRC §62(a)(2)(D)
    medical_agi_floor: Decimal             # IRC §213(a)
    charitable_agi_ceiling_cash: Decimal   # IRC §170(b)
    niit_rate: Decimal                     # IRC §1411
    niit_threshold_single: Decimal
    niit_threshold_joint: Decimal
    niit_threshold_mfs: Decimal
    eitc_investment_income_limit: Decimal  # IRC §32(i)
    tax_table_ceiling: Decimal


LIMITS: dict[int, Limits] = {
    year: Limits(*(const.scalars[name].value for name in Limits._fields))
    for year, const in YEARS.items()
}


#: Pub 915 Worksheet 1 thresholds: (line 9 base amount, line 11 second amount).
#:
#: Line 9 is the amount below which no benefit is taxable. Line 11 is the width
#: of the 50% band above it — NOT the adjusted base. An earlier version stored
#: (25000, 34000) and treated the second entry as the adjusted base, which is
#: the same calculation expressed differently but does not line up with the
#: published worksheet, so nobody could check it against the form.
#:
#: Congress has never indexed either figure. They have stood at these levels
#: since 1984 and 1993, which is why an ordinary retiree's benefits are now
#: routinely taxable — so they are not year-keyed.
#:
#: Married filing separately appears here with the single amounts because those
#: apply when the taxpayer lived apart from their spouse for the whole year. A
#: separate filer who lived with their spouse at any point never reaches this
#: table: the worksheet sends them straight to 85%.
SOCIAL_SECURITY_THRESHOLDS: dict[FilingStatusTax, tuple[Decimal, Decimal]] = {
    FilingStatusTax.SINGLE: (D("25000"), D("9000")),
    FilingStatusTax.HEAD_OF_HOUSEHOLD: (D("25000"), D("9000")),
    FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE: (D("25000"), D("9000")),
    FilingStatusTax.MARRIED_JOINT: (D("32000"), D("12000")),
    FilingStatusTax.MARRIED_SEPARATE: (D("25000"), D("9000")),
}


class SeniorDeduction(NamedTuple):
    """The One Big Beautiful Bill Act deduction for taxpayers aged 65+.

    New for 2025 and reported on Schedule 1-A, which carries to Form 1040 line
    13b — a separate deduction from the long-standing additional *standard*
    deduction for age, which continues to apply on line 12e. A 65-year-old
    single filer therefore gets both: 15,750 + 2,000 on 12e, and 6,000 on 13b.
    """

    amount_per_person: Decimal
    phaseout_threshold_single: Decimal
    phaseout_threshold_joint: Decimal
    phaseout_rate: Decimal
    minimum_age: int


def _senior(year: int) -> SeniorDeduction | None:
    scalars = YEARS[year].scalars
    amount = scalars["senior_deduction_amount"].value
    if amount <= 0:
        return None
    return SeniorDeduction(
        amount_per_person=amount,
        phaseout_threshold_single=scalars["senior_deduction_threshold_single"].value,
        phaseout_threshold_joint=scalars["senior_deduction_threshold_joint"].value,
        phaseout_rate=scalars["senior_deduction_phaseout_rate"].value,
        minimum_age=int(scalars["senior_deduction_minimum_age"].value),
    )


SENIOR_DEDUCTION: dict[int, SeniorDeduction | None] = {
    year: _senior(year) for year in YEARS
}


#: Years whose figures have been checked against published IRS guidance.
#:
#: 2025 is here because every constant it uses now names the document that sets
#: it and most were read out of that document this filing season. The handful
#: that could not be confirmed carry ``verified=False`` individually and are
#: surfaced per return by ``unverified_constants`` — which is a far more useful
#: signal than marking the whole year provisional, because a blanket warning on
#: every 2025 return trains reviewers to dismiss the one case that matters.
VERIFIED_YEARS: frozenset[int] = frozenset({2024, 2025})

SUPPORTED_YEARS: tuple[int, ...] = tuple(sorted(ORDINARY_BRACKETS))


class UnsupportedTaxYearError(ValueError):
    """Raised when no rate table exists for the requested year."""


def require_year(year: int) -> None:
    """Fail loudly for a year we have no tables for.

    Deliberately not falling back to the nearest year: computing a return on the
    wrong year's brackets yields a plausible-looking but incorrect result, which
    is worse than refusing to compute.
    """
    if year not in ORDINARY_BRACKETS:
        raise UnsupportedTaxYearError(
            f"No rate tables are loaded for tax year {year}. "
            f"Supported: {', '.join(map(str, SUPPORTED_YEARS))}. "
            "Add the year's figures to tax_authority.py before processing."
        )


def verify_tax_year(year: int) -> tuple[bool, str]:
    """Report whether a year's figures are confirmed or provisional."""
    if year not in ORDINARY_BRACKETS:
        return (False, f"Tax year {year} is not supported.")
    unverified = constants_for(year).unverified()
    if year in VERIFIED_YEARS and not unverified:
        return (True, f"Tax year {year} figures verified against IRS guidance.")
    if year in VERIFIED_YEARS:
        names = ", ".join(name for name, _ in unverified[:4])
        message = (
            f"Tax year {year} is verified except for {len(unverified)} "
            f"constant(s) ({names}) whose authority was not confirmed. "
            "Check those before filing."
        )
        return (False, message)
    message = (
        f"Tax year {year} figures are PROVISIONAL and must be confirmed "
        "against the applicable IRS revenue procedure before filing."
    )
    return (False, message)


def brackets_for(year: int, status: FilingStatusTax) -> tuple[Bracket, ...]:
    require_year(year)
    return ORDINARY_BRACKETS[year][status]


def standard_deduction_for(year: int, status: FilingStatusTax) -> Decimal:
    require_year(year)
    return STANDARD_DEDUCTION[year][status]
