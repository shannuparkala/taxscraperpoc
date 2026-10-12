"""Phase 6.3: the engine at every threshold and phase-out edge, per filing status.

Each test puts a return one dollar below, exactly at, and one dollar above an
edge, and checks the engine against a reference computed *here* from the same
constants - independently of the engine's own arithmetic. An edge is where
off-by-one errors live and where a reviewer spot-checks, and "the tax is right
at 50,000" says nothing about 48,475.

Expected values are derived from ``tax_authority`` constants, never typed in, so
a constant corrected later moves the expectation with it.

Two tests are strict ``xfail``: defects this suite found and Phase 6 does not
fix. Each names what it is waiting for.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest

from app.services.tax_engine.graph import TaxpayerFacts, compute_return
from app.services.tax_engine.tax_authority import constants_for
from app.services.tax_engine.tax_tables import FilingStatusTax as Status

YEAR = 2025
C = constants_for(YEAR)
D = Decimal
ONE = D(1)

STATUSES = [
    Status.SINGLE,
    Status.MARRIED_JOINT,
    Status.MARRIED_SEPARATE,
    Status.HEAD_OF_HOUSEHOLD,
    pytest.param(
        Status.QUALIFYING_SURVIVING_SPOUSE,
        marks=pytest.mark.xfail(
            strict=True,
            raises=KeyError,
            reason="FINDING: the QDCG worksheet looks up capital-gain brackets by "
            "status and there is no 'qualifying_surviving_spouse' entry; the whole "
            "graph fails to build. QSS takes the joint brackets.",
        ),
    ),
]


def _v(value: Any) -> Decimal:
    return value.value if hasattr(value, "value") else Decimal(value)


def _table_key(status: Status) -> str:
    """Tables are keyed by status; QSS shares the joint figures."""
    return (
        Status.MARRIED_JOINT.value
        if status is Status.QUALIFYING_SURVIVING_SPOUSE
        else status.value
    )


def _dollars(amount: Decimal) -> Decimal:
    return amount.quantize(ONE, rounding=ROUND_HALF_UP)


def _schedule_tax(taxable: Decimal, status: Status) -> Decimal:
    """The rate schedule, summed bracket by bracket from the constants."""
    tax = D(0)
    for rate, low, high in C.ordinary_brackets[_table_key(status)]:
        top = taxable if high is None else min(taxable, _v(high))
        if top > _v(low):
            tax += (top - _v(low)) * _v(rate)
    return tax


def _reference_tax(taxable: Decimal, status: Status) -> Decimal:
    """Form 1040 line 16 for ordinary income, as the instructions compute it.

    Below the Tax Table ceiling the tax is the schedule's tax on the midpoint of
    the taxable income's row, rounded to the dollar: rows of $5, $10 and $10
    under $25, $25 wide to $3,000, $50 wide above. At or above the ceiling it is
    the schedule itself.
    """
    if taxable >= _v(C.scalars["tax_table_ceiling"]):
        return _dollars(_schedule_tax(taxable, status))
    if taxable < 5:
        return D(0)
    if taxable < 15:
        mid = D(10)
    elif taxable < 25:
        mid = D(20)
    elif taxable < 3000:
        mid = (taxable // 25) * 25 + D("12.5")
    else:
        mid = (taxable // 50) * 50 + 25
    return _dollars(_schedule_tax(mid, status))


def _std(status: Status) -> Decimal:
    return _v(C.standard_deduction[_table_key(status)])


def _facts(status: Status, **money: Decimal | int) -> TaxpayerFacts:
    return TaxpayerFacts(
        tax_year=YEAR,
        filing_status=status,
        taxpayer_age=40,
        spouse_age=40 if status is Status.MARRIED_JOINT else None,
        money={k: D(v) for k, v in money.items()},
    )


def _edges(value: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    return (value - 1, value, value + 1)


# ------------------------------------------------------- ordinary brackets


def _bracket_edges() -> list[Any]:
    cases: list[Any] = []
    for status in STATUSES:
        raw = status.values[0] if hasattr(status, "values") else status
        marks = status.marks if hasattr(status, "marks") else ()
        key = _table_key(raw)
        tops = [_v(high) for _, _, high in C.ordinary_brackets[key] if high is not None]
        tops.append(_v(C.scalars["tax_table_ceiling"]))
        for top in tops:
            for taxable in _edges(top):
                cases.append(
                    pytest.param(raw, taxable, marks=marks, id=f"{raw.value}-{taxable}")
                )
    return cases


@pytest.mark.parametrize(("status", "taxable"), _bracket_edges())
def test_tax_at_every_bracket_edge(status: Status, taxable: Decimal) -> None:
    result = compute_return(_facts(status, wages=taxable + _std(status)))
    assert result.amount("f1040.l15") == taxable
    assert result.amount("f1040.l16") == _reference_tax(taxable, status)


@pytest.mark.parametrize("status", STATUSES)
def test_tax_never_decreases_across_the_table_ceiling(status: Status) -> None:
    ceiling = _v(C.scalars["tax_table_ceiling"])
    taxes = [
        compute_return(_facts(status, wages=t + _std(status))).amount("f1040.l16")
        for t in _edges(ceiling)
    ]
    assert taxes == sorted(taxes)


# ------------------------------------------------------ standard deduction


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("age", [64, 65])
def test_standard_deduction_and_the_age_65_edge(status: Status, age: int) -> None:
    facts = TaxpayerFacts(
        tax_year=YEAR, filing_status=status, taxpayer_age=age, money={"wages": D(90000)}
    )
    extra = D(0)
    if age >= 65:
        married = status in (Status.MARRIED_JOINT, Status.MARRIED_SEPARATE,
                             Status.QUALIFYING_SURVIVING_SPOUSE)
        extra = _v(C.additional_standard_deduction["married" if married else "single_or_hoh"])
    assert compute_return(facts).amount("f1040.l12e") == _std(status) + extra


@pytest.mark.xfail(
    strict=True,
    reason="FINDING: a taxpayer 65 or older is entitled to the Schedule 1-A "
    "senior deduction, and f1040.l13b enters -0- as 'nothing feeds Schedule 1-A' "
    "instead of marking the line unsupported. An unsupported item must be "
    "flagged, never silently zero (Phase 6.7 target).",
)
def test_a_senior_deduction_the_engine_cannot_compute_is_flagged() -> None:
    facts = TaxpayerFacts(
        tax_year=YEAR, filing_status=Status.SINGLE, taxpayer_age=66,
        money={"wages": D(40000)},
    )
    line = compute_return(facts)["f1040.l13b"]
    assert line.amount is None or line.amount > 0


# ------------------------------------------------ capital gain breakpoints


def _zero_rate_top(status: Status) -> Decimal:
    (_, top), *_ = C.capital_gain_brackets[_table_key(status)]
    return _v(top)


@pytest.mark.parametrize("status", STATUSES)
def test_qualified_dividends_at_the_zero_rate_breakpoint(status: Status) -> None:
    """All taxable income is qualified dividends: 0% to the breakpoint, 15% past it."""
    top = _zero_rate_top(status)
    for taxable in _edges(top):
        result = compute_return(
            _facts(status, wages=_std(status), ordinary_dividends=taxable,
                   qualified_dividends=taxable)
        )
        assert result.amount("f1040.l15") == taxable
        # The worksheet's tax is not rounded here: the form permits whole
        # dollars but does not require them, and the engine keeps the cents.
        expected = max(taxable - top, D(0)) * D("0.15")
        assert result.amount("f1040.l16") == expected, taxable


# ---------------------------------------------------- capital loss limit


@pytest.mark.parametrize("status", STATUSES)
def test_capital_loss_deduction_limit(status: Status) -> None:
    key = (
        "capital_loss_deduction_mfs"
        if status is Status.MARRIED_SEPARATE
        else "capital_loss_deduction"
    )
    limit = _v(C.scalars[key])
    for loss in _edges(limit):
        result = compute_return(_facts(status, wages=D(80000), schd_l14=-loss))
        assert result.amount("schd.l21") == -min(loss, limit), loss
        assert result.amount("f1040.l7a") == -min(loss, limit), loss


# ------------------------------------------------------------ SALT cap


@pytest.mark.parametrize("status", STATUSES)
def test_salt_cap_phasedown_edges(status: Status) -> None:
    mfs = status is Status.MARRIED_SEPARATE
    cap = _v(C.scalars["salt_cap_married_separate" if mfs else "salt_cap"])
    threshold = _v(C.scalars["salt_phasedown_threshold_mfs" if mfs else "salt_phasedown_threshold"])
    floor = _v(C.scalars["salt_cap_floor_mfs" if mfs else "salt_cap_floor"])
    rate = _v(C.scalars["salt_phasedown_rate"])

    def allowed(agi: Decimal) -> Decimal:
        return max(cap - max(agi - threshold, D(0)) * rate, floor)

    # Past the floor too: the phase-down stops, it does not keep going.
    beyond = threshold + (cap - floor) / rate
    for agi in (*_edges(threshold), *_edges(beyond)):
        result = compute_return(_facts(status, wages=agi, scha_l5a=cap * 2))
        assert result.amount("f1040.l11a") == agi
        assert result.amount("scha.l5e") == allowed(agi), agi


# --------------------------------------------------------- medical floor


@pytest.mark.parametrize("status", STATUSES)
def test_medical_expenses_at_the_agi_floor(status: Status) -> None:
    agi = D(80000)
    floor = agi * _v(C.scalars["medical_agi_floor"])
    for spent in _edges(floor):
        result = compute_return(_facts(status, wages=agi, scha_l1=spent))
        assert result.amount("scha.l4") == max(spent - floor, D(0)), spent


# ------------------------------------------------- social security base


@pytest.mark.parametrize(
    ("status", "base"),
    [(Status.SINGLE, D(25000)), (Status.HEAD_OF_HOUSEHOLD, D(25000)),
     (Status.MARRIED_JOINT, D(32000))],
)
def test_social_security_is_untaxed_to_the_base_amount_and_taxed_past_it(
    status: Status, base: Decimal
) -> None:
    """Provisional income = other income + half the benefits (IRC section 86).

    The base amounts are statutory and not inflation-adjusted, which is why
    they are written here rather than read from the year's constants.
    """
    benefits = D(20000)
    for provisional in _edges(base):
        wages = provisional - benefits / 2
        result = compute_return(_facts(status, wages=wages, social_security_benefits=benefits))
        expected = max((provisional - base) / 2, D(0))
        assert result.amount("f1040.l6b") == expected, provisional


# ---------------------------------------------------------------- HSA


@pytest.mark.parametrize("family", [False, True])
def test_hsa_contribution_limit_and_the_age_55_catch_up(family: bool) -> None:
    limit = _v(C.scalars["hsa_contribution_limit_family" if family else "hsa_contribution_limit_self_only"])
    catch_up = _v(C.scalars["hsa_catch_up"])
    for age, ceiling in ((54, limit), (55, limit + catch_up)):
        for contributed in _edges(ceiling):
            facts = TaxpayerFacts(
                tax_year=YEAR, filing_status=Status.SINGLE, taxpayer_age=age,
                money={"wages": D(90000), "f8889_l2": contributed,
                       "f8889_family_coverage": D(1 if family else 0)},
            )
            assert compute_return(facts).amount("f8889.l13") == min(contributed, ceiling), (
                age, contributed,
            )


# ------------------------------------------------------ Illinois exemption


@pytest.mark.parametrize(
    ("status", "cutoff_key"),
    [(Status.SINGLE, "il_exemption_cutoff_agi"),
     (Status.MARRIED_JOINT, "il_exemption_cutoff_agi_joint")],
)
def test_illinois_exemption_stops_past_the_agi_cutoff(status: Status, cutoff_key: str) -> None:
    cutoff = _v(C.scalars[cutoff_key])
    amounts = {}
    for agi in _edges(cutoff):
        facts = TaxpayerFacts(
            tax_year=YEAR, filing_status=status, taxpayer_age=40,
            spouse_age=40 if status is Status.MARRIED_JOINT else None,
            resident_state="IL", money={"wages": agi},
        )
        amounts[agi] = compute_return(facts).amount("il1040.l10a")
    assert amounts[cutoff - 1] and amounts[cutoff], "the exemption applies up to the cutoff"
    assert amounts[cutoff + 1] == 0, "and not a dollar past it"
