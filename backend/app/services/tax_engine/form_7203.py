"""Form 7203 — S corporation shareholder stock and debt basis.

Why this exists: when a shareholder loan whose basis has been reduced is repaid,
the repayment is partly a return of basis and partly income. Nothing on the K-1
states that income — it has to be computed here — and no tax software carries it
onto the return automatically. CCH ProSystem *fx* computes Form 7203 line 34,
raises diagnostic 33861, and leaves the figure for a human to key onto Form 4797.

On the sample return that figure was 5,469: 27% of the taxpayer's total income,
arrived at from two numbers on the K-1 and one carried from the prior year.

The character of the gain depends on how the debt is evidenced, and the
difference is not cosmetic:

* **Open account debt** — an informal running balance. Repayment above basis is
  **ordinary** income, reported on Form 4797 Part II.
* **Debt evidenced by a written note** — repayment above basis is **capital**
  gain, reported on Schedule D, and may qualify for long-term rates.

The caller must state which. There is no safe default: guessing ordinary
overstates tax for a note holder, and guessing capital understates it for
everyone else. ``character`` is required for that reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

ZERO = Decimal(0)


def _money(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value))


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal(1), rounding=ROUND_HALF_UP)


class DebtCharacter(str, Enum):
    """How the shareholder loan is evidenced. Decides the gain's character."""

    OPEN_ACCOUNT = "open_account"
    FORMAL_NOTE = "formal_note"


@dataclass(slots=True)
class ShareholderBasisInputs:
    """What Form 7203 needs. Loan balances come from Schedule K-1 line I."""

    #: Prior year's ending stock basis. Not on any current-year document.
    stock_basis_begin: Decimal = ZERO
    #: Prior year's ending debt basis. Likewise.
    debt_basis_begin: Decimal = ZERO

    #: K-1 box 1 and friends.
    ordinary_business_income: Decimal = ZERO
    other_income_items: Decimal = ZERO
    #: K-1 box 16D.
    distributions: Decimal = ZERO
    #: K-1 box 16C — meals, fines, and similar.
    nondeductible_expenses: Decimal = ZERO
    #: Deductible losses and deductions passed through, entered positive.
    losses_and_deductions: Decimal = ZERO

    #: Schedule K-1 line I, beginning and ending.
    loan_balance_begin: Decimal = ZERO
    loan_balance_end: Decimal = ZERO

    character: DebtCharacter = DebtCharacter.OPEN_ACCOUNT

    @property
    def principal_repaid(self) -> Decimal:
        """The decrease in the loan balance over the year."""
        return max(ZERO, _money(self.loan_balance_begin) - _money(self.loan_balance_end))

    @property
    def has_activity(self) -> bool:
        return self.principal_repaid > ZERO or _money(self.loan_balance_begin) > ZERO


@dataclass(slots=True)
class Form7203Result:
    """The completed form, line by line, so it can be rendered and checked."""

    # Part I — stock basis
    stock_basis_begin: Decimal = ZERO
    stock_basis_after_income: Decimal = ZERO
    stock_basis_end: Decimal = ZERO

    # Part II Section A — loan balances
    loan_balance_begin: Decimal = ZERO
    principal_repaid: Decimal = ZERO
    loan_balance_end: Decimal = ZERO

    # Part II Section B — debt basis
    debt_basis_before_repayment: Decimal = ZERO
    basis_ratio: Decimal = ZERO
    nontaxable_repayment: Decimal = ZERO
    debt_basis_end: Decimal = ZERO

    # Part II Section C — the reportable gain
    reportable_gain: Decimal = ZERO
    character: DebtCharacter = DebtCharacter.OPEN_ACCOUNT

    #: Non-blocking notes for the reviewer.
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []

    @property
    def is_ordinary(self) -> bool:
        return self.character is DebtCharacter.OPEN_ACCOUNT

    @property
    def destination(self) -> str:
        """Where line 34 belongs on the return."""
        return (
            "Form 4797 Part II (ordinary)"
            if self.is_ordinary
            else "Schedule D (capital)"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_basis_begin": str(self.stock_basis_begin),
            "stock_basis_end": str(self.stock_basis_end),
            "loan_balance_begin": str(self.loan_balance_begin),
            "principal_repaid": str(self.principal_repaid),
            "loan_balance_end": str(self.loan_balance_end),
            "debt_basis_before_repayment": str(self.debt_basis_before_repayment),
            "basis_ratio": str(self.basis_ratio),
            "nontaxable_repayment": str(self.nontaxable_repayment),
            "debt_basis_end": str(self.debt_basis_end),
            "reportable_gain": str(self.reportable_gain),
            "character": self.character.value,
            "destination": self.destination,
            "warnings": list(self.warnings),
        }


def compute_form_7203(inputs: ShareholderBasisInputs) -> Form7203Result:
    """Work Form 7203 Parts I to III.

    Ordering follows the form, which is also the ordering the statute requires:
    stock basis absorbs income and distributions first, then non-deductible
    expenses, then losses. Only what stock basis cannot absorb reaches debt
    basis — reversing the two overstates the loan's remaining basis and so
    understates the gain on repayment.
    """
    result = Form7203Result(character=inputs.character)

    # --- Part I: stock basis ---------------------------------------------
    begin = _money(inputs.stock_basis_begin)
    income = _money(inputs.ordinary_business_income) + _money(inputs.other_income_items)
    result.stock_basis_begin = begin
    result.stock_basis_after_income = begin + income

    after_distributions = max(ZERO, result.stock_basis_after_income - _money(inputs.distributions))

    nondeductible = _money(inputs.nondeductible_expenses)
    stock_absorbs_nondeductible = min(after_distributions, nondeductible)
    nondeductible_excess = nondeductible - stock_absorbs_nondeductible
    after_nondeductible = after_distributions - stock_absorbs_nondeductible

    losses = _money(inputs.losses_and_deductions)
    stock_absorbs_losses = min(after_nondeductible, losses)
    losses_excess = losses - stock_absorbs_losses
    result.stock_basis_end = after_nondeductible - stock_absorbs_losses

    # --- Part II Section A: the loan ------------------------------------
    result.loan_balance_begin = _money(inputs.loan_balance_begin)
    result.loan_balance_end = _money(inputs.loan_balance_end)
    result.principal_repaid = inputs.principal_repaid

    # --- Part II Section B: debt basis ----------------------------------
    result.debt_basis_before_repayment = _money(inputs.debt_basis_begin)

    if result.principal_repaid <= ZERO or result.loan_balance_begin <= ZERO:
        result.debt_basis_end = max(
            ZERO,
            result.debt_basis_before_repayment - nondeductible_excess - losses_excess,
        )
        return result

    if result.debt_basis_before_repayment >= result.loan_balance_begin:
        # Basis is whole: the repayment is entirely a return of capital.
        result.basis_ratio = Decimal(1)
        result.nontaxable_repayment = result.principal_repaid
    else:
        # Line 25: the proportion of the loan that still has basis behind it.
        # Rounded to six places because that is what the form carries and what
        # line 26 then multiplies by — reproducing the printed worksheet means
        # rounding where it rounds. The instruction asks for at least four
        # places; six matches the prepared return (.153365 for 6,641/43,302).
        result.basis_ratio = (
            result.debt_basis_before_repayment / result.loan_balance_begin
        ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        result.nontaxable_repayment = _round(
            result.basis_ratio * result.principal_repaid
        )

    result.reportable_gain = max(
        ZERO, result.principal_repaid - result.nontaxable_repayment
    )

    remaining = result.debt_basis_before_repayment - result.nontaxable_repayment
    result.debt_basis_end = max(ZERO, remaining - nondeductible_excess - losses_excess)

    if result.reportable_gain > ZERO:
        result.warnings.append(
            f"Repayment of {result.principal_repaid} against a reduced-basis "
            f"shareholder loan produced {result.reportable_gain} of income, "
            f"reported on {result.destination}. No document states this figure; "
            "it is computed from the K-1 loan balances and the prior year's "
            "debt basis."
        )

    if inputs.debt_basis_begin == ZERO and result.loan_balance_begin > ZERO:
        result.warnings.append(
            "Opening debt basis was not supplied, so the entire repayment is "
            "treated as gain. If basis remains, supply the prior year's Form "
            "7203 line 31 — this is the figure the gain is most sensitive to."
        )

    return result
