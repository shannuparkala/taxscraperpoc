"""The typed input to the engine.

Everything the graph is allowed to know about a taxpayer arrives here, and
nothing reaches a node any other way. Structural facts - year, status, ages,
dependents - are attributes. Monetary facts are a mapping keyed by a declared
vocabulary, because a return draws on a few hundred possible figures and a
dataclass with a few hundred attributes is not more typed, only longer.

The vocabulary is the point. Field names are a contract with two ends: the
extraction prompt names them and the engine consumes them, and when the two
disagree the line is structurally always zero with nothing raising an error.
``federal_withheld`` was in neither for a while, so ``total_payments`` could
never be anything but zero and no return could produce a refund - trap 17.
``MONEY_FIELDS`` is the single place that vocabulary is declared; an unknown key
is rejected at construction rather than silently read as nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from app.services.tax_engine.graph.nodes import SourceFact
from app.services.tax_engine.tax_tables import FilingStatusTax

ZERO = Decimal(0)

#: Every monetary fact a form may consume, with the form that introduced it.
#: Extend this when a form needs a figure the pipeline does not yet supply -
#: and extend the extraction side in the same change, or the line is always 0.
MONEY_FIELDS: dict[str, str] = {
    # Form 1040, income
    "wages": "Form 1040 line 1a - W-2 box 1",
    "household_employee_wages": "Form 1040 line 1b",
    "tip_income": "Form 1040 line 1c - unreported tips",
    "medicaid_waiver_payments": "Form 1040 line 1d",
    "dependent_care_benefits": "Form 1040 line 1e",
    "employer_adoption_benefits": "Form 1040 line 1f",
    "wages_from_form_8919": "Form 1040 line 1g",
    "other_earned_income": "Form 1040 line 1h",
    "nontaxable_combat_pay": "Form 1040 line 1i",
    "tax_exempt_interest": "Form 1040 line 2a",
    "taxable_interest": "Form 1040 line 2b - 1099-INT box 1",
    "qualified_dividends": "Form 1040 line 3a - 1099-DIV box 1b",
    "ordinary_dividends": "Form 1040 line 3b - 1099-DIV box 1a",
    "ira_distributions": "Form 1040 line 4a",
    "ira_taxable": "Form 1040 line 4b",
    "pensions_annuities": "Form 1040 line 5a",
    "pensions_taxable": "Form 1040 line 5b",
    "social_security_benefits": "Form 1040 line 6a - SSA-1099 box 5",
    "capital_gain_or_loss": "Form 1040 line 7 - from Schedule D",
    # Payments
    "federal_withheld_w2": "Form 1040 line 25a - W-2 box 2",
    "federal_withheld_1099": "Form 1040 line 25b - 1099 withholding",
    "federal_withheld_other": "Form 1040 line 25c",
    "estimated_tax_payments": "Form 1040 line 26",
    "prior_year_overpayment_applied": "Form 1040 line 26 - carried forward",
    "amount_applied_to_next_year": "Form 1040 line 36",
}


@dataclass(frozen=True, slots=True)
class Dependent:
    """One dependent, as the front of Form 1040 records them."""

    name_token: str
    relationship: str
    #: Age at the end of the tax year. None when no document stated it.
    age: int | None = None
    qualifies_for_child_tax_credit: bool = False
    qualifies_for_other_dependent_credit: bool = False


class UnknownMoneyField(KeyError):
    """A figure was supplied under a name no form declares.

    Rejected rather than ignored: a misspelled field that reads as zero is the
    failure mode trap 17 describes, and it is invisible on the finished return.
    """


@dataclass(frozen=True, slots=True)
class TaxpayerFacts:
    """Everything the engine is allowed to know, and nothing else."""

    tax_year: int
    filing_status: FilingStatusTax
    taxpayer_age: int | None = None
    spouse_age: int | None = None
    taxpayer_blind: bool = False
    spouse_blind: bool = False
    dependents: tuple[Dependent, ...] = ()
    #: Whether the filing status was stated on a document or inferred. An
    #: inferred status never wins over better evidence and never passes
    #: silently - traps 13 and 30.
    filing_status_is_inferred: bool = False
    #: Two-letter code for the state this return is filed in, or None for a
    #: federal-only return. A state form appears on a return only when this
    #: says so: putting Illinois lines on a Texas return is the failure mode
    #: rule 7 in CLAUDE.md exists to prevent, and it is worse than omitting
    #: them because the lines look worked.
    resident_state: str | None = None
    money: Mapping[str, Decimal] = field(default_factory=dict)
    #: Which documents reported each figure. One ``SourceFact`` or several: a
    #: field summed from two W-2s has two sources, and naming only the first
    #: sends the reviewer to half the figure.
    provenance: Mapping[str, SourceFact | tuple[SourceFact, ...]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        unknown = sorted(set(self.money) - set(MONEY_FIELDS))
        if unknown:
            raise UnknownMoneyField(
                f"no form declares {', '.join(unknown)}. Add it to MONEY_FIELDS "
                "and to the extraction side in the same change."
            )

    def amount(self, name: str) -> Decimal | None:
        """The figure reported for this field, or None if nothing reported it.

        None and zero are different facts. A document stating zero interest is
        not the same as no document mentioning interest, and only the second
        one is worth a reviewer's attention.
        """
        if name not in MONEY_FIELDS:
            raise UnknownMoneyField(f"no form declares {name!r}")
        return self.money.get(name)

    def sources(self, name: str) -> tuple[SourceFact, ...]:
        """Every document and page that reported this field, in order."""
        found = self.provenance.get(name)
        if found is None:
            return ()
        if isinstance(found, SourceFact):
            return (found,)
        return tuple(found)

    def source(self, name: str) -> SourceFact | None:
        """The first document that reported this field."""
        found = self.sources(name)
        return found[0] if found else None

    def files_in(self, state_code: str) -> bool:
        """Whether this return includes that state's forms."""
        return (self.resident_state or "").upper() == state_code.upper()

    @property
    def is_joint(self) -> bool:
        return self.filing_status is FilingStatusTax.MARRIED_JOINT

    @property
    def seniors(self) -> int:
        """Additional-standard-deduction entitlements, not people over 65.

        The engine adds one senior amount per count, so counting a spouse who
        is not on this return buys a deduction for someone the return says is
        not there. A spouse counts only on a joint return: on married filing
        separately each takes their own, and on qualifying surviving spouse the
        additional amount is the survivor's alone. Trap 33.
        """
        count = 0
        if self.taxpayer_age is not None and self.taxpayer_age >= 65:
            count += 1
        if self.is_joint and self.spouse_age is not None and self.spouse_age >= 65:
            count += 1
        return count

    @property
    def blind_count(self) -> int:
        """Blindness entitlements, on the same rule as ``seniors``."""
        count = 1 if self.taxpayer_blind else 0
        if self.is_joint and self.spouse_blind:
            count += 1
        return count
