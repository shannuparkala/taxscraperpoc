"""Phase 6.4: properties every return must have, over seeded random returns.

No new dependency: a fixed-seed generator builds a few hundred invented returns
and each property is asserted on all of them. The seed is fixed so a failure
reproduces exactly; the failing return's seed index is in the message, so the
case can be rebuilt with ``_random_facts(random.Random(SEED + index))``.

The properties:

- tax is never negative,
- more income never lowers the tax before credits,
- a refund and an amount owed are never both non-zero,
- every line has provenance that ends in a document, an authority or a nil.

Qualifying surviving spouse is left out of the generator: the graph fails to
build for it at all, which ``test_engine_thresholds`` records as a strict xfail.
Including it here would fail every property for the same single reason.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.services.tax_engine.graph import (
    Dependent,
    LeafKind,
    SourceFact,
    TaxpayerFacts,
    compute_return,
)
from app.services.tax_engine.tax_tables import FilingStatusTax as Status

SEED = 20250923
D = Decimal

STATUSES = (
    Status.SINGLE,
    Status.MARRIED_JOINT,
    Status.MARRIED_SEPARATE,
    Status.HEAD_OF_HOUSEHOLD,
)

#: Lines that are a tax, and so can never be negative.
TAX_LINES = ("f1040.l16", "f1040.l18", "f1040.l22", "f1040.l24")


def _money(rng: random.Random, high: int) -> Decimal:
    return D(rng.randrange(0, high))


def _random_facts(rng: random.Random, *, dependents: bool = True) -> TaxpayerFacts:
    status = rng.choice(STATUSES)
    ordinary = _money(rng, 20_000)
    money: dict[str, Decimal] = {
        "wages": _money(rng, 400_000),
        "taxable_interest": _money(rng, 15_000),
        "ordinary_dividends": ordinary,
        "qualified_dividends": D(rng.randrange(0, int(ordinary) + 1)),
        "schd_l13": _money(rng, 10_000),
        "federal_withheld_w2": _money(rng, 60_000),
        "estimated_tax_payments": _money(rng, 10_000),
    }
    if rng.random() < 0.4:
        money["schd_l14"] = -_money(rng, 12_000)
    if rng.random() < 0.4:
        money["social_security_benefits"] = _money(rng, 45_000)
    if rng.random() < 0.5:
        money.update(
            scha_l5a=_money(rng, 60_000),
            scha_l5b=_money(rng, 20_000),
            scha_l8a=_money(rng, 40_000),
            scha_l11=_money(rng, 15_000),
            scha_l1=_money(rng, 30_000),
        )
    if rng.random() < 0.2:
        money["f8889_l2"] = _money(rng, 9_000)
    household = ()
    if dependents and rng.random() < 0.2:
        household = (Dependent("DEPENDENT_001", "child", age=rng.randrange(1, 17),
                               qualifies_for_child_tax_credit=True),)
    return TaxpayerFacts(
        tax_year=2025,
        filing_status=status,
        taxpayer_age=rng.randrange(20, 90),
        spouse_age=rng.randrange(20, 90) if status is Status.MARRIED_JOINT else None,
        dependents=household,
        resident_state=rng.choice((None, "IL")),
        money=money,
        provenance={
            name: SourceFact(field=name, document_id=f"doc-{name}", document_type="w2",
                             page=1, confidence=D("0.95"), amount=amount)
            for name, amount in money.items()
        },
    )


def _returns(count: int, *, offset: int = 0, dependents: bool = True) -> list[tuple[int, TaxpayerFacts]]:
    return [
        (index, _random_facts(random.Random(SEED + offset + index), dependents=dependents))
        for index in range(count)
    ]


@pytest.fixture(scope="module")
def sweep() -> list[tuple[int, object]]:
    return [(index, compute_return(facts)) for index, facts in _returns(400)]


def test_tax_is_never_negative(sweep: list) -> None:  # type: ignore[type-arg]
    for index, result in sweep:
        for node_id in TAX_LINES:
            amount = result.amount(node_id)
            assert amount is None or amount >= 0, (index, node_id, amount)


def test_a_refund_and_an_amount_owed_are_never_both_nonzero(sweep: list) -> None:  # type: ignore[type-arg]
    for index, result in sweep:
        overpaid = result.amount("f1040.l34")
        owed = result.amount("f1040.l37")
        if overpaid is None or owed is None:
            continue  # unsupported upstream; the return is not fileable anyway
        assert not (overpaid > 0 and owed > 0), (index, overpaid, owed)


def test_an_unsupported_line_is_never_shown_as_a_figure(sweep: list) -> None:  # type: ignore[type-arg]
    for index, result in sweep:
        for line in result.unsupported:
            assert line.amount is None and line.flags, (index, line.node_id)
        assert result.fileable == (not result.unsupported), index


@pytest.mark.parametrize("step", [D(1), D(1000), D(25_000)])
def test_more_income_never_lowers_the_tax_before_credits(step: Decimal) -> None:
    """Line 18 (tax plus Schedule 2 part I) is monotone in wages.

    The cases that make this interesting are the ones where income also moves
    a deduction - the SALT cap phases down, the taxable part of social security
    rises - which should only ever push the tax up.
    """
    for index, facts in _returns(250, offset=10_000, dependents=False):
        more = dict(facts.money)
        more["wages"] = more["wages"] + step
        richer = TaxpayerFacts(
            tax_year=facts.tax_year, filing_status=facts.filing_status,
            taxpayer_age=facts.taxpayer_age, spouse_age=facts.spouse_age,
            resident_state=facts.resident_state, money=more,
        )
        before = compute_return(facts).amount("f1040.l18")
        after = compute_return(richer).amount("f1040.l18")
        assert before is not None and after is not None, index
        assert after >= before, (index, step, before, after)


def test_every_line_has_provenance_to_a_document_an_authority_or_a_nil() -> None:
    for index, facts in _returns(25, offset=20_000):
        result = compute_return(facts)
        for node_id in result.order:
            line = result[node_id]
            assert line.formula and line.reference, (index, node_id)
            tree = result.explain(node_id)
            assert tree.leaves(), (index, node_id)
            stray = [
                leaf.node_id for leaf in tree.untraced()
                if leaf.leaf is not LeafKind.UNSUPPORTED
            ]
            assert not stray, (index, node_id, stray)
