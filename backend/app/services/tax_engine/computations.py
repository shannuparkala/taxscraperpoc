"""Deterministic tax computations.

Every figure that reaches an output package is produced here, never by a
language model. The model proposes extracted facts; this module decides what
the numbers are.

All arithmetic uses ``Decimal`` with explicit rounding at defined points. Two
rounding modes matter:

* ``ROUND_HALF_UP`` — the IRS convention for rounding to whole dollars
  (instructions: "increase amounts from 50 to 99 cents to the next dollar").
  Python's default is banker's rounding, which would round 0.5 to 0 and
  silently disagree with the taxpayer's own arithmetic.
* Cent precision is retained for intermediate sums so that cross-footing a
  hundred-line trial balance ties exactly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_UP,
    Decimal,
    InvalidOperation,
)
from typing import Any

from app.core.logging import get_logger
from app.services.tax_engine.tax_tables import (
    CAPITAL_GAIN_BRACKETS,
    CREDITS,
    LIMITS,
    PAYROLL,
    SENIOR_DEDUCTION,
    SOCIAL_SECURITY_THRESHOLDS,
    FilingStatusTax,
    brackets_for,
    require_year,
    standard_deduction_for,
)

logger = get_logger(__name__)

D = Decimal
ZERO = D("0")
CENT = D("0.01")
DOLLAR = D("1")


def money(value: Any) -> Decimal:
    """Coerce anything to a Decimal amount, tolerating messy source formats.

    Handles the shapes that turn up in scanned workpapers: ``$1,234.56``,
    ``(1,234.56)`` for negatives, ``1 234,56``, empty cells, and stray dashes.
    Returns 0 for anything unparseable rather than raising, because a single
    unreadable cell should produce a review flag, not abort the return.
    """
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return D(str(value))

    text = str(value).strip()
    if not text or text in {"-", "--", "—", "N/A", "n/a", "NONE", "None"}:
        return ZERO

    negative = False
    # Accounting notation: parentheses mean negative.
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace("$", "").replace(",", "").replace(" ", "").strip()
    if text.startswith("-"):
        negative = True
        text = text[1:]
    if not text:
        return ZERO

    try:
        amount = D(text)
    except (InvalidOperation, ValueError):
        logger.debug("Unparseable amount, treated as zero")
        return ZERO
    return -amount if negative else amount


def to_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_dollars(value: Decimal) -> Decimal:
    """Round to whole dollars using the IRS convention (half up)."""
    return value.quantize(DOLLAR, rounding=ROUND_HALF_UP)


def total(values: Iterable[Any]) -> Decimal:
    return to_cents(sum((money(v) for v in values), ZERO))


def non_negative(value: Decimal) -> Decimal:
    """Clamp at zero — many 1040 lines say 'if zero or less, enter -0-'."""
    return max(ZERO, value)


# ---------------------------------------------------------------------------
# Cross-footing
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CrossFootResult:
    """Outcome of checking a stated total against its components."""

    label: str
    stated: Decimal
    computed: Decimal
    tolerance: Decimal

    @property
    def difference(self) -> Decimal:
        return to_cents(self.stated - self.computed)

    @property
    def ok(self) -> bool:
        return abs(self.difference) <= self.tolerance

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "stated": str(self.stated),
            "computed": str(self.computed),
            "difference": str(self.difference),
            "ok": self.ok,
        }


def cross_foot(
    label: str,
    components: Iterable[Any],
    stated_total: Any,
    *,
    tolerance: Decimal = CENT,
) -> CrossFootResult:
    """Verify that components sum to the stated total."""
    return CrossFootResult(
        label=label,
        stated=to_cents(money(stated_total)),
        computed=total(components),
        tolerance=tolerance,
    )


# ---------------------------------------------------------------------------
# Core tax computations
# ---------------------------------------------------------------------------


def tax_on_ordinary_income(
    taxable_income: Decimal, year: int, status: FilingStatusTax
) -> Decimal:
    """Apply the marginal rate schedule to ordinary taxable income."""
    require_year(year)
    income = non_negative(to_cents(taxable_income))
    if income <= ZERO:
        return ZERO

    tax = ZERO
    for bracket in brackets_for(year, status):
        if income <= bracket.lower:
            break
        ceiling = bracket.upper if bracket.upper is not None else income
        taxed_in_band = min(income, ceiling) - bracket.lower
        if taxed_in_band > ZERO:
            tax += taxed_in_band * bracket.rate
    return to_cents(tax)


def marginal_rate(
    taxable_income: Decimal, year: int, status: FilingStatusTax
) -> Decimal:
    require_year(year)
    income = non_negative(to_cents(taxable_income))
    applicable = brackets_for(year, status)[0].rate
    for bracket in brackets_for(year, status):
        if income > bracket.lower:
            applicable = bracket.rate
    return applicable


#: Tax Table band widths, from the table printed in the Form 1040 instructions.
#: Each band is taxed at its *midpoint*, which is why a return computed from the
#: rate schedule disagrees with a prepared one by a few dollars at the same
#: taxable income. The table is not uniformly banded:
#:
#:   $0-$5, $5-$15, $15-$25   three micro-bands at the very bottom
#:   $25 up to $3,000         $25 bands
#:   $3,000 up to $100,000    $50 bands
#:
#: The micro-bands are not a rounding detail. Treating the bottom of the table
#: as $25-wide puts taxable income of zero in a band whose midpoint is 12.50 and
#: charges a dollar of tax on a return that owes nothing — which then cascades
#: into the refund. A return with no taxable income has no tax, and the table's
#: first row says so explicitly.
_TAX_TABLE_BAND = D("50")
_TAX_TABLE_MID_BAND = D("25")
_TAX_TABLE_MID_CEILING = D("3000")
#: (upper bound, midpoint) for the rows below $25.
_TAX_TABLE_MICRO: tuple[tuple[Decimal, Decimal], ...] = (
    (D("5"), D("2.5")),
    (D("15"), D("10")),
    (D("25"), D("20")),
)


def tax_table_lookup(
    taxable_income: Decimal, year: int, status: FilingStatusTax
) -> Decimal:
    """Tax from the IRS Tax Table, which is mandatory below its ceiling.

    The Form 1040 instructions direct any taxpayer with taxable income under
    $100,000 to the Tax Table rather than the Tax Computation Worksheet, and the
    table is banded: every taxable income inside a band pays the tax computed on
    the band's *midpoint*. Applying the rate schedule directly instead produces
    a figure that is close but not equal — on the Basic 5 benchmark, 11,216.66
    against the accountant's 11,222 at the same taxable income of 74,103.

    A few dollars sounds immaterial until a reviewer cross-foots the return
    against the client's own software and finds every line agreeing except the
    tax. Then it costs an hour to discover it was never a disagreement about the
    facts.
    """
    require_year(year)
    income = non_negative(to_cents(taxable_income))
    if income <= ZERO:
        return ZERO

    ceiling = LIMITS[year].tax_table_ceiling
    if income >= ceiling:
        # Tax Computation Worksheet: the rate schedule, applied directly.
        return to_dollars(tax_on_ordinary_income(income, year, status))

    for upper, midpoint in _TAX_TABLE_MICRO:
        if income < upper:
            return to_dollars(tax_on_ordinary_income(midpoint, year, status))

    band = _TAX_TABLE_MID_BAND if income < _TAX_TABLE_MID_CEILING else _TAX_TABLE_BAND
    lower = (income / band).to_integral_value(rounding=ROUND_FLOOR) * band
    midpoint = lower + band / 2
    return to_dollars(tax_on_ordinary_income(midpoint, year, status))


def tax_with_capital_gains(
    *,
    taxable_income: Decimal,
    qualified_income: Decimal,
    year: int,
    status: FilingStatusTax,
    use_tax_table: bool = True,
) -> Decimal:
    """Compute tax where part of taxable income is LTCG / qualified dividends.

    Mirrors the Qualified Dividends and Capital Gain Tax Worksheet: ordinary
    income is taxed at ordinary rates, and the preferential slice is taxed at
    0/15/20% based on where it sits in total taxable income.

    ``use_tax_table`` routes the ordinary slice through the Tax Table, which is
    what the worksheet itself instructs at lines 21 and 24. Set it False only to
    compare against the rate schedule directly.
    """
    require_year(year)
    taxable = non_negative(to_cents(taxable_income))
    preferential = min(non_negative(to_cents(qualified_income)), taxable)
    ordinary = taxable - preferential

    tax = (
        tax_table_lookup(ordinary, year, status)
        if use_tax_table
        else tax_on_ordinary_income(ordinary, year, status)
    )

    # Stack the preferential slice on top of ordinary income.
    remaining = preferential
    position = ordinary
    for rate, ceiling in CAPITAL_GAIN_BRACKETS[year][status]:
        if remaining <= ZERO:
            break
        band_top = ceiling if ceiling is not None else position + remaining
        available = band_top - position
        if available <= ZERO:
            continue
        taxed = min(remaining, available)
        tax += taxed * rate
        remaining -= taxed
        position += taxed

    return to_cents(tax)


def standard_deduction(
    *,
    year: int,
    status: FilingStatusTax,
    age_65_or_older: int = 0,
    blind: int = 0,
    can_be_claimed_as_dependent: bool = False,
    earned_income: Decimal = ZERO,
) -> Decimal:
    """Standard deduction including age/blindness additions.

    A taxpayer who can be claimed as someone else's dependent gets a reduced
    deduction under IRC §63(c)(5): the greater of a fixed floor or earned income
    plus a fixed addition, capped at the normal amount. Missing this materially
    overstates the deduction for student returns.

    Both figures are indexed annually and both now come from ``tax_authority``.
    They were previously written inline and were a year stale in each direction
    — 1,300 for 2025 where Rev. Proc. 2024-40 §.15(2) sets 1,350, and 1,250 for
    2024 where Rev. Proc. 2023-34 sets 1,300 — which is exactly the failure mode
    that hardcoding an indexed figure produces: right once, then quietly wrong
    every year afterwards.
    """
    from app.services.tax_engine.tax_authority import constants_for
    from app.services.tax_engine.tax_tables import ADDITIONAL_STANDARD_DEDUCTION

    require_year(year)
    base = standard_deduction_for(year, status)

    if can_be_claimed_as_dependent:
        const = constants_for(year)
        floor = const.dependent_standard_deduction_floor.value
        addition = const.dependent_standard_deduction_earned_addition.value
        base = min(max(floor, to_cents(earned_income) + addition), base)

    extras = ADDITIONAL_STANDARD_DEDUCTION[year]
    per_condition = (
        extras["married"]
        if status
        in {
            FilingStatusTax.MARRIED_JOINT,
            FilingStatusTax.MARRIED_SEPARATE,
            FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE,
        }
        else extras["single_or_hoh"]
    )
    return to_cents(base + per_condition * (age_65_or_older + blind))


def taxable_social_security(
    *,
    benefits: Decimal,
    other_income: Decimal,
    tax_exempt_interest: Decimal = ZERO,
    exclusions: Decimal = ZERO,
    adjustments: Decimal = ZERO,
    year: int,
    status: FilingStatusTax,
    lived_apart_from_spouse: bool = False,
) -> Decimal:
    """Taxable portion of Social Security benefits.

    A line-for-line transcription of IRS Publication 915, Worksheet 1
    ("Figuring Your Taxable Benefits"), which is the same worksheet printed in
    the Form 1040 instructions for lines 6a and 6b. Each step below is numbered
    to match, so a preparer can tie the computation to the published form.

    This replaced a condensed algebraic form. That version produced identical
    results across 4,000 randomised ordinary cases, but it could not be checked
    against the IRS text, and it silently disagreed with the worksheet in three
    places that the algebra hid.

    Line 6b is *computed*, never read off a document: Form SSA-1099 reports the
    gross benefit in box 5 and says nothing about the taxable portion, because
    that depends on the rest of the return.

    Arguments map to the worksheet as:

    * ``other_income``      — line 3, Form 1040 lines 1z, 2b, 3b, 4b, 5b, 7a, 8
    * ``tax_exempt_interest`` — line 4, Form 1040 line 2a
    * ``exclusions``        — line 5, Forms 8839, 2555 and 4563
    * ``adjustments``       — line 7, Schedule 1 lines 11-20, 23 and 25

    ``lived_apart_from_spouse`` only matters when filing separately, and it
    decides the whole calculation: a separated filer who lived apart for the
    entire year uses the single thresholds, while one who lived with their
    spouse at any point has 85% taxable from the first dollar.
    """
    require_year(year)

    line_1 = non_negative(to_cents(money(benefits)))
    if line_1 <= ZERO:
        return ZERO

    line_2 = to_cents(line_1 * D("0.5"))
    line_3 = to_cents(money(other_income))
    line_4 = non_negative(to_cents(money(tax_exempt_interest)))
    line_5 = non_negative(to_cents(money(exclusions)))
    line_6 = to_cents(line_2 + line_3 + line_4 + line_5)
    line_7 = non_negative(to_cents(money(adjustments)))

    # Line 8: "Is line 7 less than line 6? No — none of the benefits are
    # taxable." Deductions can exceed the income they are measured against.
    if line_7 >= line_6:
        return ZERO
    line_8 = to_cents(line_6 - line_7)

    # Note under line 9: filing separately while living with your spouse
    # removes the thresholds entirely rather than merely lowering them.
    if status is FilingStatusTax.MARRIED_SEPARATE and not lived_apart_from_spouse:
        return to_cents(min(line_8 * D("0.85"), line_1 * D("0.85")))

    base, second = SOCIAL_SECURITY_THRESHOLDS[status]

    # Line 10: "Is line 9 less than line 8? No — none of the benefits are
    # taxable."
    if base >= line_8:
        return ZERO
    line_10 = to_cents(line_8 - base)

    line_12 = non_negative(to_cents(line_10 - second))   # line 11 is `second`
    line_13 = min(line_10, second)
    line_14 = to_cents(line_13 * D("0.5"))
    line_15 = min(line_2, line_14)
    line_16 = to_cents(line_12 * D("0.85"))
    line_17 = to_cents(line_15 + line_16)
    line_18 = to_cents(line_1 * D("0.85"))

    return min(line_17, line_18)   # line 19


@dataclass(slots=True)
class Schedule1A:
    """Schedule 1-A, the four deductions that land on Form 1040 line 13b."""

    tips: Decimal = ZERO             # Part II, line 13
    overtime: Decimal = ZERO         # Part III, line 21
    car_loan_interest: Decimal = ZERO  # Part IV, line 30
    seniors: Decimal = ZERO          # Part V, line 37

    @property
    def total(self) -> Decimal:
        """Line 38, which carries to Form 1040 line 13b."""
        return to_cents(self.tips + self.overtime + self.car_loan_interest
                        + self.seniors)


def _stepped_phaseout(
    *,
    allowance: Decimal,
    magi: Decimal,
    threshold: Decimal,
    per_thousand: Decimal,
    round_steps_up: bool,
) -> Decimal:
    """The $1,000-step phase-out the Schedule 1-A parts share.

    Each part divides the excess MAGI by 1,000, rounds the *number of steps* to
    a whole number, multiplies by a fixed dollar amount and subtracts. The
    rounding direction is not uniform and is stated only on the form: tips and
    overtime round the step count **down** (line 11, line 19), car loan interest
    rounds it **up** (line 28). Down favours the taxpayer, up does not, and
    applying a flat percentage instead — which is what "reduced by $100 per
    $1,000" reads like — is wrong for every taxpayer whose excess is not an
    exact multiple of 1,000.
    """
    excess = non_negative(to_cents(money(magi)) - threshold)
    if excess <= ZERO:
        return non_negative(allowance)

    rounding = ROUND_CEILING if round_steps_up else ROUND_FLOOR
    steps = (excess / D("1000")).to_integral_value(rounding=rounding)
    return non_negative(to_cents(allowance - steps * per_thousand))


def schedule_1a(
    *,
    qualified_tips: Decimal = ZERO,
    qualified_overtime: Decimal = ZERO,
    car_loan_interest: Decimal = ZERO,
    seniors: int = 0,
    modified_agi: Decimal,
    year: int,
    status: FilingStatusTax,
) -> Schedule1A:
    """Work Schedule 1-A, new for 2025 under Pub. L. 119-21.

    Four unrelated deductions share one schedule and one line on the 1040, and
    all four are available whether or not the taxpayer itemizes — which is the
    point of them: this return takes the standard deduction *and* 2,905 of
    overtime deduction on top.

    Only the senior part was implemented before, so a filer with qualified tips
    or overtime lost the deduction entirely. On the Basic 5 benchmark that is
    2,905 of overtime pay reported in W-2 box 1, worth 639 of tax at 22%.
    """
    require_year(year)
    from app.services.tax_engine.tax_authority import constants_for

    scalars = constants_for(year).scalars
    if scalars["senior_deduction_amount"].value <= ZERO:
        return Schedule1A()   # the schedule did not exist before 2025

    joint = status in {FilingStatusTax.MARRIED_JOINT,
                       FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE}
    magi = money(modified_agi)

    def part(prefix: str, claimed: Decimal, cap: Decimal, *, up: bool) -> Decimal:
        allowance = min(non_negative(to_cents(money(claimed))), cap)
        if allowance <= ZERO:
            return ZERO
        return _stepped_phaseout(
            allowance=allowance,
            magi=magi,
            threshold=scalars[
                f"{prefix}_threshold_{'joint' if joint else 'single'}"
            ].value,
            per_thousand=scalars[f"{prefix}_phaseout_per_1000"].value,
            round_steps_up=up,
        )

    return Schedule1A(
        tips=part("tips_deduction", qualified_tips,
                  scalars["tips_deduction_cap"].value, up=False),
        overtime=part(
            "overtime_deduction", qualified_overtime,
            scalars[
                f"overtime_deduction_cap_{'joint' if joint else 'single'}"
            ].value,
            up=False,
        ),
        car_loan_interest=part("car_loan_interest", car_loan_interest,
                               scalars["car_loan_interest_cap"].value, up=True),
        seniors=senior_deduction(
            seniors=seniors, modified_agi=magi, year=year, status=status
        ),
    )


def senior_deduction(
    *,
    seniors: int,
    modified_agi: Decimal,
    year: int,
    status: FilingStatusTax,
) -> Decimal:
    """The 2025 deduction for taxpayers aged 65 or older (Schedule 1-A Part V).

    Introduced by the One Big Beautiful Bill Act and reported on Form 1040 line
    13b. It is *in addition to* the age-based increase to the standard
    deduction on line 12e — a single 65-year-old gets 2,000 there and 6,000
    here, which is why omitting it understated the sample return's deductions
    by exactly 6,000.

    The published form decides the order of operations, and it is not the
    obvious one. Schedule 1-A Part V works like this::

        33  MAGI less the threshold
        34  line 33 x 6%
        35  $6,000 less line 34, floored at zero      <- per person
        36a line 35, if the taxpayer was born before 2 January 1961
        36b line 35, if the spouse was
        37  36a + 36b

    So the phase-out reduces **each person's** 6,000 and the survivors are then
    added — it does not reduce a doubled 12,000 once. Computing it the other
    way overstated a married couple's deduction by the amount of a single
    phase-out: at 200,000 of MAGI, 9,000 against a correct 6,000.
    """
    require_year(year)
    constants = SENIOR_DEDUCTION.get(year)
    if constants is None or seniors <= 0:
        return ZERO

    threshold = (
        constants.phaseout_threshold_joint
        if status
        in {FilingStatusTax.MARRIED_JOINT, FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE}
        else constants.phaseout_threshold_single
    )
    excess = non_negative(to_cents(money(modified_agi)) - threshold)

    # Lines 33-35: one person's allowance, after the taper.
    per_person = non_negative(
        to_cents(constants.amount_per_person - excess * constants.phaseout_rate)
    )
    # Lines 36a, 36b and 37: add it once for each qualifying filer.
    return to_cents(per_person * seniors)


def capital_loss_limitation(
    net_capital_loss: Decimal, year: int, status: FilingStatusTax
) -> tuple[Decimal, Decimal]:
    """Apply the §1211(b) annual capital-loss deduction cap.

    Returns ``(deductible_this_year, carryforward)``. ``net_capital_loss``
    should be negative for a loss.
    """
    require_year(year)
    limits = LIMITS[year]
    cap = (
        limits.capital_loss_deduction_mfs
        if status is FilingStatusTax.MARRIED_SEPARATE
        else limits.capital_loss_deduction
    )
    loss = to_cents(net_capital_loss)
    if loss >= ZERO:
        return (loss, ZERO)

    deductible = max(loss, -cap)
    carryforward = to_cents(loss - deductible)  # negative or zero
    return (deductible, carryforward)


@dataclass(slots=True)
class ScheduleD:
    """Schedule D (Form 1040), Parts I through III."""

    short_term_net: Decimal      # line 7
    long_term_net: Decimal       # line 15
    net: Decimal                 # line 16
    reportable: Decimal          # line 16 or 21 -> Form 1040 line 7a
    limited: bool                # True when §1211(b) capped the loss


def schedule_d(
    *,
    short_term_gain: Decimal = ZERO,
    short_term_from_k1: Decimal = ZERO,
    short_term_loss_carryover: Decimal = ZERO,
    long_term_gain: Decimal = ZERO,
    long_term_from_k1: Decimal = ZERO,
    capital_gain_distributions: Decimal = ZERO,
    long_term_loss_carryover: Decimal = ZERO,
    year: int,
    status: FilingStatusTax,
) -> ScheduleD:
    """Net capital gain or loss for Form 1040 line 7a.

    Line 7a used to be an extracted input, which meant two of its components
    could never appear. Capital gain distributions (Form 1099-DIV box 2a) are
    reported on Schedule D line 13, not on any 1099-B, so netting broker
    proceeds alone omitted them. And the loss carryovers on lines 6 and 14 come
    from the *prior* year's return, so nothing in this year's documents could
    supply them.

    Carryovers are entered on the form as positive numbers and reduce the
    year's result, so they are subtracted here. A caller passing a negative
    carryover would otherwise have a prior loss added back as a gain, which is
    why they are floored at zero rather than trusted.
    """
    require_year(year)

    short_carryover = non_negative(to_cents(money(short_term_loss_carryover)))
    long_carryover = non_negative(to_cents(money(long_term_loss_carryover)))

    line_7 = to_cents(
        money(short_term_gain) + money(short_term_from_k1) - short_carryover
    )
    line_15 = to_cents(
        money(long_term_gain)
        + money(long_term_from_k1)
        + money(capital_gain_distributions)
        - long_carryover
    )
    line_16 = to_cents(line_7 + line_15)
    reportable, _ = capital_loss_limitation(line_16, year, status)

    return ScheduleD(
        short_term_net=line_7,
        long_term_net=line_15,
        net=line_16,
        reportable=reportable,
        limited=reportable != line_16,
    )


def capital_loss_carryover(
    *,
    schedule_d: ScheduleD,
    taxable_income: Decimal,
    year: int,
    status: FilingStatusTax,
) -> tuple[Decimal, Decimal]:
    """Split next year's carryover by character, §1212(b).

    A transcription of the Capital Loss Carryover Worksheet in the Schedule D
    instructions. Returns ``(short_term, long_term)`` as positive amounts, the
    way they are entered on next year's lines 6 and 14.

    The split is not simply "loss beyond 3,000". Two things the flat rule gets
    wrong are encoded here: the deduction is absorbed by short-term loss first,
    so a mixed year carries a different character forward than it would
    otherwise; and when taxable income is low the deduction is not fully used,
    so *more* than the excess carries. Both matter to this engine, because a
    return whose taxable income is zero is exactly the case that produces a
    carryover in the first place.
    """
    require_year(year)
    if schedule_d.net >= ZERO:
        return (ZERO, ZERO)

    # Worksheet lines 1-4: how much of the allowed loss taxable income absorbed.
    line_1 = to_cents(money(taxable_income))
    line_2 = non_negative(-schedule_d.reportable)
    line_3 = to_cents(line_1 + line_2)
    line_4 = non_negative(min(line_2, line_3))

    short_loss = non_negative(-schedule_d.short_term_net)
    long_loss = non_negative(-schedule_d.long_term_net)

    # Lines 5-8: short-term carryover.
    short_carryover = ZERO
    if short_loss > ZERO:
        line_6 = non_negative(schedule_d.long_term_net)
        short_carryover = non_negative(short_loss - (line_4 + line_6))

    # Lines 9-13: long-term carryover, using only what the short-term loss did
    # not absorb.
    long_carryover = ZERO
    if long_loss > ZERO:
        line_10 = non_negative(schedule_d.short_term_net)
        line_11 = non_negative(line_4 - short_loss)
        long_carryover = non_negative(long_loss - (line_10 + line_11))

    return (short_carryover, long_carryover)


def salt_cap_for(
    year: int, status: FilingStatusTax, modified_agi: Decimal = ZERO
) -> Decimal:
    """The §164(b)(6) cap actually available, after any phase-down.

    For 2025 the One Big Beautiful Bill Act raised the cap from 10,000 to 40,000
    (20,000 filing separately) and added a taper: above 500,000 of modified AGI
    (250,000 separately) the cap falls by 30% of the excess, but never below
    10,000 (5,000 separately). That floor is why a very high earner still
    deducts something.

    Pre-2025 years carry a zero phase-down threshold, which this reads as "no
    taper", so the same code path serves both.
    """
    require_year(year)
    limits = LIMITS[year]
    separate = status is FilingStatusTax.MARRIED_SEPARATE
    cap = limits.salt_cap_married_separate if separate else limits.salt_cap

    threshold = limits.salt_phasedown_threshold
    if separate and threshold > ZERO:
        from app.services.tax_engine.tax_authority import scalar

        threshold = scalar(year, "salt_phasedown_threshold_mfs")
    if threshold <= ZERO or limits.salt_phasedown_rate <= ZERO:
        return cap

    excess = non_negative(to_cents(money(modified_agi)) - threshold)
    if excess <= ZERO:
        return cap

    floor = limits.salt_cap_floor
    if separate:
        from app.services.tax_engine.tax_authority import scalar

        floor = scalar(year, "salt_cap_floor_mfs")
    reduced = to_cents(cap - excess * limits.salt_phasedown_rate)
    return max(reduced, floor)


def salt_deduction(
    state_and_local_taxes: Decimal,
    year: int,
    status: FilingStatusTax,
    modified_agi: Decimal = ZERO,
) -> Decimal:
    """Cap the state and local tax deduction, IRC §164(b)(6)."""
    cap = salt_cap_for(year, status, modified_agi)
    return to_cents(min(non_negative(to_cents(state_and_local_taxes)), cap))


def medical_deduction(
    medical_expenses: Decimal, agi: Decimal, year: int
) -> Decimal:
    """Medical expenses exceeding the AGI floor, IRC §213(a)."""
    require_year(year)
    floor = to_cents(non_negative(to_cents(agi)) * LIMITS[year].medical_agi_floor)
    return non_negative(to_cents(money(medical_expenses) - floor))


def child_tax_credit(
    *,
    qualifying_children: int,
    other_dependents: int,
    modified_agi: Decimal,
    year: int,
    status: FilingStatusTax,
) -> Decimal:
    """Child tax credit and credit for other dependents, after phase-out.

    Phase-out is $50 per $1,000 (or fraction) of MAGI over the threshold —
    the "or fraction" is why the excess is rounded *up* to the next $1,000.
    """
    require_year(year)
    constants = CREDITS[year]
    gross = to_cents(
        constants.child_tax_credit * qualifying_children
        + constants.other_dependent_credit * other_dependents
    )
    if gross <= ZERO:
        return ZERO

    threshold = (
        constants.ctc_phaseout_joint
        if status
        in {FilingStatusTax.MARRIED_JOINT, FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE}
        else constants.ctc_phaseout_single
    )
    excess = non_negative(to_cents(modified_agi) - threshold)
    if excess <= ZERO:
        return gross

    # "$50 for each $1,000, or fraction thereof" — so round the number of
    # $1,000 steps UP, never to nearest.
    steps = (excess / D("1000")).to_integral_value(rounding=ROUND_CEILING)
    reduction = to_cents(constants.ctc_phaseout_rate * steps)
    return non_negative(gross - reduction)


def self_employment_tax(
    net_earnings: Decimal, year: int, *, wages: Decimal = ZERO
) -> tuple[Decimal, Decimal]:
    """SE tax and the deductible employer-equivalent half, IRC §1401/§164(f).

    Returns ``(se_tax, deduction)``. Net earnings are reduced to 92.35% before
    the rates apply (§1402(a)(12)).

    ``wages`` is Social Security wages already taxed through payroll. Schedule
    SE line 8 subtracts them from the wage base, because the base is a ceiling
    on a person's earnings for the year, not on each source separately. Omitting
    it charged 12.4% a second time on earnings already at the ceiling: a filer
    with wages at the base and 50,000 of Schedule C profit paid 7,064.78 where
    Schedule SE gives 1,339.08.

    The 0.9% additional Medicare tax (§3101(b)(2)) is deliberately *not* here.
    It is a separate computation on Form 8959 over combined wages and SE
    earnings, reported on Schedule 2 on its own line — see
    ``additional_medicare_tax``.
    """
    require_year(year)
    payroll = PAYROLL[year]
    earnings = non_negative(to_cents(net_earnings)) * payroll.se_net_earnings_rate
    if earnings < payroll.se_minimum_earnings:
        return (ZERO, ZERO)

    # Schedule SE lines 8-10: the wage base less wages already subject to FICA.
    remaining_base = non_negative(
        payroll.social_security_wage_base - non_negative(to_cents(wages))
    )
    ss_taxable = min(earnings, remaining_base)
    # Self-employed pay both halves: 12.4% and 2.9%.
    ss_tax = ss_taxable * payroll.social_security_rate * 2
    medicare_tax = earnings * payroll.medicare_rate * 2
    se_tax = to_cents(ss_tax + medicare_tax)
    return (se_tax, to_cents(se_tax / 2))


def additional_medicare_tax(
    *,
    wages: Decimal,
    self_employment_earnings: Decimal,
    year: int,
    status: FilingStatusTax,
) -> Decimal:
    """The 0.9% surtax on high earnings, IRC §3101(b)(2) / Form 8959.

    Applies to wages plus net self-employment earnings above a threshold that is
    *not* indexed and differs by filing status. Unlike the rest of SE tax there
    is no employer half and no deduction — it is the employee's alone.
    """
    require_year(year)
    payroll = PAYROLL[year]
    if status is FilingStatusTax.MARRIED_JOINT or (
        status is FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE
    ):
        threshold = payroll.additional_medicare_threshold_joint
    elif status is FilingStatusTax.MARRIED_SEPARATE:
        threshold = payroll.additional_medicare_threshold_mfs
    else:
        threshold = payroll.additional_medicare_threshold_single

    base = non_negative(to_cents(wages)) + non_negative(
        to_cents(self_employment_earnings) * payroll.se_net_earnings_rate
    )
    excess = non_negative(to_cents(base) - threshold)
    return to_cents(excess * payroll.additional_medicare_rate)


def net_investment_income_tax(
    *,
    net_investment_income: Decimal,
    modified_agi: Decimal,
    year: int,
    status: FilingStatusTax,
) -> Decimal:
    """The 3.8% tax on investment income, IRC §1411 / Form 8960.

    Charged on the *lesser* of net investment income and the amount by which
    modified AGI exceeds the threshold — so a taxpayer just over the line pays
    on the overage, not on the whole of their investment income.

    Net investment income is interest, dividends, capital gains, annuities,
    royalties and passive rents. Wages and self-employment earnings are not in
    it: they carry their own Medicare surtax instead.
    """
    require_year(year)
    limits = LIMITS[year]
    if status in {FilingStatusTax.MARRIED_JOINT,
                  FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE}:
        threshold = limits.niit_threshold_joint
    elif status is FilingStatusTax.MARRIED_SEPARATE:
        threshold = limits.niit_threshold_mfs
    else:
        threshold = limits.niit_threshold_single

    nii = non_negative(to_cents(net_investment_income))
    excess = non_negative(to_cents(modified_agi) - threshold)
    return to_cents(min(nii, excess) * limits.niit_rate)


@dataclass(slots=True)
class QbiResult:
    """Form 8995 working, so line 13a can be tied back to its components."""

    qualified_business_income: Decimal
    tentative: Decimal           # 20% of QBI
    taxable_income_limit: Decimal  # 20% of TI less net capital gain
    deduction: Decimal
    limited_by_taxable_income: bool
    #: True when income exceeds the §199A(e)(2) threshold, where the W-2 wage
    #: and UBIA limits and the SSTB phase-out begin and this simplified
    #: computation is no longer sufficient on its own.
    above_threshold: bool


def qbi_deduction(
    *,
    qualified_business_income: Decimal,
    taxable_income_before_qbi: Decimal,
    net_capital_gain: Decimal,
    year: int,
    status: FilingStatusTax,
) -> QbiResult:
    """The §199A deduction for pass-through business income (Form 8995).

    Twenty percent of qualified business income, capped at twenty percent of
    taxable income computed *before* this deduction and reduced by net capital
    gain — the cap is what stops a taxpayer whose income is mostly investment
    return from deducting against it.

    ``qualified_business_income`` must already be net of the three deductions
    that are attributable to the business and so reduce it: the deductible half
    of self-employment tax, self-employed health insurance, and self-employed
    retirement contributions.

    Above the §199A(e)(2) threshold the deduction is further limited by the
    business's W-2 wages and the unadjusted basis of its property, and a
    specified service trade phases out entirely. Neither input is present in a
    workpaper, so this reports ``above_threshold`` and the caller raises a
    review item rather than quietly returning the unlimited figure.
    """
    require_year(year)
    limits = LIMITS[year]
    qbi = non_negative(to_cents(money(qualified_business_income)))

    threshold = (
        limits.qbi_threshold_joint
        if status in {FilingStatusTax.MARRIED_JOINT,
                      FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE}
        else limits.qbi_threshold_single
    )

    tentative = to_cents(qbi * limits.qbi_rate)
    reduced_ti = non_negative(
        to_cents(taxable_income_before_qbi) - non_negative(to_cents(net_capital_gain))
    )
    ti_limit = to_cents(reduced_ti * limits.qbi_rate)
    deduction = min(tentative, ti_limit)

    return QbiResult(
        qualified_business_income=qbi,
        tentative=tentative,
        taxable_income_limit=ti_limit,
        deduction=non_negative(deduction),
        limited_by_taxable_income=ti_limit < tentative,
        above_threshold=to_cents(taxable_income_before_qbi) > threshold,
    )


@dataclass(slots=True)
class EitcResult:
    """Schedule EIC working, including why a zero is a zero."""

    credit: Decimal
    qualifying_children: int
    earned_income: Decimal
    phaseout_income: Decimal
    ineligible_reason: str = ""


def earned_income_credit(
    *,
    earned_income: Decimal,
    adjusted_gross_income: Decimal,
    qualifying_children: int,
    investment_income: Decimal,
    year: int,
    status: FilingStatusTax,
    taxpayer_age: int | None = None,
    lived_apart_from_spouse: bool = False,
) -> EitcResult:
    """The earned income credit, IRC §32.

    The credit rises at a fixed rate to a plateau, holds, then falls at a second
    rate once income passes a threshold — measured against AGI or earned income,
    whichever is *greater*, so a taxpayer cannot reach the plateau on earned
    income while phasing out on neither.

    This was previously an extracted input rather than a computation, which
    meant it was structurally always zero for anyone who did not already have a
    return stating it — that is, for exactly the first-time filers it exists to
    help.

    Three disqualifications are checked because each silently zeroes an
    otherwise good credit: too much investment income (§32(i)), filing
    separately without meeting the separated-spouse rules (§32(d)), and, for a
    filer with no qualifying children, being outside the 25-to-64 age band
    (§32(c)(1)(A)(ii)).
    """
    require_year(year)
    from app.services.tax_engine.tax_authority import constants_for

    children = max(0, min(3, int(qualifying_children)))
    earned = non_negative(to_cents(money(earned_income)))
    agi = to_cents(money(adjusted_gross_income))
    table = constants_for(year).eitc[children]

    def refuse(reason: str) -> EitcResult:
        return EitcResult(ZERO, children, earned, max(earned, agi), reason)

    if to_cents(money(investment_income)) > LIMITS[year].eitc_investment_income_limit:
        return refuse(
            f"Investment income exceeds the §32(i) limit of "
            f"{LIMITS[year].eitc_investment_income_limit}."
        )
    if status is FilingStatusTax.MARRIED_SEPARATE and not lived_apart_from_spouse:
        return refuse(
            "Married filing separately without meeting the §32(d) rules for "
            "separated spouses."
        )
    if children == 0 and taxpayer_age is not None and not (25 <= taxpayer_age < 65):
        return refuse(
            "A filer with no qualifying children must be at least 25 and under "
            "65 (§32(c)(1)(A)(ii))."
        )
    if earned <= ZERO:
        return refuse("No earned income.")

    joint = status in {FilingStatusTax.MARRIED_JOINT,
                       FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE}
    threshold = table["threshold_joint" if joint else "threshold_single"].value

    credit = min(
        to_cents(earned * table["credit_rate"].value), table["max_credit"].value
    )
    # §32(a)(2): the phase-out runs off AGI or earned income, whichever is more.
    phaseout_income = max(earned, agi)
    if phaseout_income > threshold:
        reduction = to_cents((phaseout_income - threshold) * table["phaseout_rate"].value)
        credit = non_negative(to_cents(credit - reduction))

    return EitcResult(to_dollars(credit), children, earned, phaseout_income)


def additional_child_tax_credit(
    *,
    qualifying_children: int,
    earned_income: Decimal,
    child_tax_credit_allowed: Decimal,
    child_tax_credit_used: Decimal,
    year: int,
) -> Decimal:
    """The refundable part of the child tax credit, Schedule 8812 Part II.

    The nonrefundable credit stops at the tax; what is left over is refundable
    up to a per-child cap, but only to the extent of 15% of earned income above
    a floor. A family with no earned income gets nothing however many children
    they have — which is the design of §24(d), not an omission here.
    """
    require_year(year)
    credits = CREDITS[year]
    if qualifying_children <= 0:
        return ZERO

    unused = non_negative(
        to_cents(money(child_tax_credit_allowed) - money(child_tax_credit_used))
    )
    if unused <= ZERO:
        return ZERO

    cap = to_cents(credits.child_tax_credit_refundable_cap * qualifying_children)
    earned_limit = non_negative(
        to_cents(
            (non_negative(to_cents(money(earned_income))) - credits.actc_earned_income_floor)
            * credits.actc_rate
        )
    )
    return to_dollars(min(unused, cap, earned_limit))


def payroll_tax_check(
    *, wages: Decimal, withheld_ss: Decimal, withheld_medicare: Decimal, year: int
) -> dict[str, Any]:
    """Recompute expected FICA withholding from wages, for W-2 tie-out."""
    require_year(year)
    payroll = PAYROLL[year]
    gross = non_negative(to_cents(wages))

    expected_ss = to_cents(
        min(gross, payroll.social_security_wage_base) * payroll.social_security_rate
    )
    expected_medicare = to_cents(gross * payroll.medicare_rate)

    return {
        "expected_social_security": str(expected_ss),
        "reported_social_security": str(to_cents(money(withheld_ss))),
        "social_security_variance": str(to_cents(money(withheld_ss) - expected_ss)),
        "expected_medicare": str(expected_medicare),
        "reported_medicare": str(to_cents(money(withheld_medicare))),
        "medicare_variance": str(to_cents(money(withheld_medicare) - expected_medicare)),
    }


# ---------------------------------------------------------------------------
# Depreciation
# ---------------------------------------------------------------------------

#: MACRS half-year convention percentage tables (IRS Pub. 946, Table A-1).
MACRS_HALF_YEAR: dict[int, tuple[Decimal, ...]] = {
    3: (D("0.3333"), D("0.4445"), D("0.1481"), D("0.0741")),
    5: (D("0.20"), D("0.32"), D("0.192"), D("0.1152"), D("0.1152"), D("0.0576")),
    7: (
        D("0.1429"), D("0.2449"), D("0.1749"), D("0.1249"),
        D("0.0893"), D("0.0892"), D("0.0893"), D("0.0446"),
    ),
    10: (
        D("0.10"), D("0.18"), D("0.144"), D("0.1152"), D("0.0922"),
        D("0.0737"), D("0.0655"), D("0.0655"), D("0.0656"), D("0.0655"),
        D("0.0328"),
    ),
    15: (
        D("0.05"), D("0.095"), D("0.0855"), D("0.077"), D("0.0693"),
        D("0.0623"), D("0.059"), D("0.059"), D("0.0591"), D("0.059"),
        D("0.0591"), D("0.059"), D("0.0591"), D("0.059"), D("0.0591"),
        D("0.0295"),
    ),
}


def macrs_depreciation(
    *, basis: Decimal, recovery_years: int, year_in_service: int
) -> Decimal:
    """MACRS depreciation for one year under the half-year convention.

    ``year_in_service`` is 1-based. Returns 0 past the recovery period rather
    than raising, so a fully depreciated asset simply contributes nothing.
    """
    table = MACRS_HALF_YEAR.get(recovery_years)
    if table is None:
        raise ValueError(
            f"No MACRS table for a {recovery_years}-year recovery period. "
            f"Supported: {sorted(MACRS_HALF_YEAR)}"
        )
    if year_in_service < 1 or year_in_service > len(table):
        return ZERO
    return to_cents(non_negative(to_cents(basis)) * table[year_in_service - 1])


def straight_line_depreciation(
    *, basis: Decimal, salvage: Decimal, useful_life_years: int
) -> Decimal:
    if useful_life_years <= 0:
        raise ValueError("Useful life must be a positive number of years.")
    depreciable = non_negative(to_cents(basis) - to_cents(salvage))
    return to_cents(depreciable / D(useful_life_years))


@dataclass(slots=True)
class DepreciationRow:
    """One asset line from a depreciation schedule."""

    description: str
    basis: Decimal
    recovery_years: int
    year_in_service: int
    method: str = "macrs"
    salvage: Decimal = ZERO
    useful_life_years: int = 0
    prior_accumulated: Decimal = ZERO
    stated_current: Decimal | None = None

    def compute(self) -> Decimal:
        if self.method == "straight_line":
            return straight_line_depreciation(
                basis=self.basis,
                salvage=self.salvage,
                useful_life_years=self.useful_life_years or self.recovery_years,
            )
        return macrs_depreciation(
            basis=self.basis,
            recovery_years=self.recovery_years,
            year_in_service=self.year_in_service,
        )


def recompute_depreciation_schedule(
    rows: list[DepreciationRow], *, tolerance: Decimal = D("1.00")
) -> dict[str, Any]:
    """Recompute a whole schedule and flag lines that disagree."""
    lines: list[dict[str, Any]] = []
    computed_total = ZERO
    stated_total = ZERO
    mismatches = 0

    for row in rows:
        try:
            computed = row.compute()
        except ValueError as exc:
            lines.append(
                {
                    "description": row.description,
                    "error": str(exc),
                    "ok": False,
                }
            )
            mismatches += 1
            continue

        computed_total += computed
        entry: dict[str, Any] = {
            "description": row.description,
            "computed": str(computed),
            "method": row.method,
        }
        if row.stated_current is not None:
            stated = to_cents(money(row.stated_current))
            stated_total += stated
            variance = to_cents(stated - computed)
            entry.update(
                stated=str(stated),
                variance=str(variance),
                ok=abs(variance) <= tolerance,
            )
            if abs(variance) > tolerance:
                mismatches += 1
        else:
            entry["ok"] = True
        lines.append(entry)

    return {
        "lines": lines,
        "computed_total": str(to_cents(computed_total)),
        "stated_total": str(to_cents(stated_total)),
        "variance": str(to_cents(stated_total - computed_total)),
        "mismatch_count": mismatches,
        "ok": mismatches == 0,
    }


# ---------------------------------------------------------------------------
# Trial balance
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TrialBalanceLine:
    account: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO


@dataclass(slots=True)
class TrialBalanceResult:
    total_debits: Decimal
    total_credits: Decimal
    line_count: int
    out_of_balance: Decimal
    balanced: bool
    largest_lines: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_debits": str(self.total_debits),
            "total_credits": str(self.total_credits),
            "line_count": self.line_count,
            "out_of_balance": str(self.out_of_balance),
            "balanced": self.balanced,
            "largest_lines": self.largest_lines,
        }


def verify_trial_balance(
    lines: list[TrialBalanceLine], *, tolerance: Decimal = CENT
) -> TrialBalanceResult:
    """Check that debits equal credits."""
    debits = total(line.debit for line in lines)
    credits = total(line.credit for line in lines)
    difference = to_cents(debits - credits)

    ranked = sorted(
        lines, key=lambda line: abs(money(line.debit) - money(line.credit)), reverse=True
    )[:5]

    return TrialBalanceResult(
        total_debits=debits,
        total_credits=credits,
        line_count=len(lines),
        out_of_balance=difference,
        balanced=abs(difference) <= tolerance,
        largest_lines=[
            {
                "account": line.account,
                "debit": str(to_cents(money(line.debit))),
                "credit": str(to_cents(money(line.credit))),
            }
            for line in ranked
        ],
    )
