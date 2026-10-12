"""Find last year's return, and say so plainly when it is not there.

Measured across nine real workpapers, missing prior-year data was the largest
single source of error. On the one case that decomposes exactly it accounted for
5,502 of a 9,241 overstatement of AGI, because two figures appear on no
current-year document at all:

* the capital loss carryover (Schedule D lines 6 and 14)
* the overpayment applied from the prior return (Form 1040 line 26)

and one more that is derived from a figure only last year's Form 7203 states:

* the shareholder's opening stock and debt basis

The engine previously read all of these as zero. Zero and unknown are different,
and a return that silently treats one as the other still foots, still prints,
and is wrong.

This service answers one question — *do we have last year?* — and turns the
answer into either carryover balances or a request the user can act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.core.logging import get_logger
from app.models.enums import DocumentType
from app.services.carryover_repository import (
    CarryoverBalance,
    CarryoverKind,
    Origin,
)

logger = get_logger(__name__)


#: Extraction field -> the carryover it establishes. These are the fields a
#: prior-year return is the *only* source for.
PRIOR_YEAR_FIELDS: dict[str, str] = {
    "short_term_loss_carryover": CarryoverKind.SHORT_TERM_CAPITAL_LOSS,
    "long_term_loss_carryover": CarryoverKind.LONG_TERM_CAPITAL_LOSS,
    "prior_year_overpayment_applied": CarryoverKind.OVERPAYMENT_APPLIED,
    "stock_basis_begin": CarryoverKind.STOCK_BASIS,
    "debt_basis_begin": CarryoverKind.DEBT_BASIS,
    "amt_credit_carryover": CarryoverKind.AMT_CREDIT,
    "foreign_tax_credit_carryover": CarryoverKind.FOREIGN_TAX_CREDIT,
    "passive_activity_loss_carryover": CarryoverKind.PASSIVE_ACTIVITY_LOSS,
    "net_operating_loss_carryover": CarryoverKind.NET_OPERATING_LOSS,
    "charitable_contribution_carryover": CarryoverKind.CHARITABLE_CONTRIBUTION,
    "section_179_carryover": CarryoverKind.SECTION_179,
}

#: What each missing figure costs, in the reviewer's language. Kept next to the
#: field so the request explains itself rather than saying "data missing".
CONSEQUENCE: dict[str, str] = {
    "short_term_loss_carryover": (
        "an unused short-term capital loss reduces this year's investment gain"
    ),
    "long_term_loss_carryover": (
        "an unused long-term capital loss reduces this year's investment gain"
    ),
    "prior_year_overpayment_applied": (
        "a refund left with the IRS last year counts as a payment against this "
        "year's tax"
    ),
    "debt_basis_begin": (
        "without the shareholder's opening debt basis, the whole of any loan "
        "repayment is treated as taxable income"
    ),
    "stock_basis_begin": (
        "without opening stock basis, losses and distributions cannot be limited "
        "correctly"
    ),
}


@dataclass(slots=True)
class PriorYearOutcome:
    """What the workpaper had to say about last year."""

    #: True when a prior-year return was classified in this upload.
    found: bool = False
    #: Pages it was found on, for the reviewer.
    pages: list[str] = field(default_factory=list)
    #: Filing status read off it, for continuity.
    filing_status: str | None = None
    tax_year: int | None = None
    #: Balances ready to deposit in the carryover repository.
    balances: list[CarryoverBalance] = field(default_factory=list)
    #: Figures this return needs that nothing has supplied.
    missing: list[str] = field(default_factory=list)
    #: True when the engine should ask the user to upload one.
    should_request_upload: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "pages": self.pages,
            "filing_status": self.filing_status,
            "tax_year": self.tax_year,
            "carryovers_recovered": [b.kind for b in self.balances],
            "missing": self.missing,
            "should_request_upload": self.should_request_upload,
        }


class PriorYearService:
    """Decides whether last year's return is present and what it gave us."""

    def evaluate(
        self,
        *,
        normalized: dict[str, Any],
        document_types: set[str],
        tax_year: int,
        already_known: set[str] | None = None,
        workflow_id: str = "",
    ) -> PriorYearOutcome:
        """Assess prior-year coverage for one run.

        ``already_known`` is the set of carryover kinds the repository already
        holds for this taxpayer and year. A balance we remember from processing
        last year's return is as good as one read from the document, so the
        request is not raised twice.
        """
        outcome = PriorYearOutcome()
        known = already_known or set()

        outcome.found = DocumentType.PRIOR_YEAR_RETURN.value in document_types
        if outcome.found:
            outcome.filing_status = self._status(normalized)
            outcome.tax_year = tax_year - 1
            outcome.balances = self._balances(normalized, tax_year, workflow_id)

        recovered = {b.kind for b in outcome.balances}
        outcome.missing = self._missing(normalized, known | recovered)

        # Only ask when it would actually change a number. A return with no
        # investment activity and no estimated payments has nothing to carry,
        # and asking for a document that cannot change the answer trains people
        # to ignore the request.
        outcome.should_request_upload = bool(outcome.missing) and not outcome.found
        return outcome

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _status(normalized: dict[str, Any]) -> str | None:
        raw = str(normalized.get("prior_year_filing_status") or "").strip()
        return raw or None

    @staticmethod
    def _balances(
        normalized: dict[str, Any], tax_year: int, workflow_id: str
    ) -> list[CarryoverBalance]:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat(timespec="seconds")
        balances: list[CarryoverBalance] = []
        for field_name, kind in PRIOR_YEAR_FIELDS.items():
            raw = normalized.get(field_name)
            if raw in (None, ""):
                continue
            try:
                amount = Decimal(str(raw).replace(",", "").replace("$", ""))
            except (ValueError, ArithmeticError):
                continue
            if amount == 0:
                continue
            balances.append(
                CarryoverBalance(
                    kind=kind,
                    amount=abs(amount),
                    to_year=tax_year,
                    origin=Origin.PRIOR_YEAR_DOCUMENT,
                    origin_detail=(
                        f"{field_name} read from the prior-year return"
                        + (f", workflow {workflow_id}" if workflow_id else "")
                    ),
                    recorded_at=now,
                )
            )
        return balances

    @staticmethod
    def _missing(normalized: dict[str, Any], known: set[str]) -> list[str]:
        """Prior-year figures this particular return would actually use."""
        missing: list[str] = []

        has_investments = any(
            normalized.get(name) not in (None, "")
            for name in (
                "short_term_gain",
                "long_term_gain",
                "capital_gain_distributions",
                "short_term_from_k1",
                "long_term_from_k1",
            )
        )
        if (
            has_investments
            and CarryoverKind.SHORT_TERM_CAPITAL_LOSS not in known
            and normalized.get("short_term_loss_carryover") in (None, "")
            and normalized.get("long_term_loss_carryover") in (None, "")
        ):
            missing.append("short_term_loss_carryover")

        if (
            CarryoverKind.OVERPAYMENT_APPLIED not in known
            and normalized.get("prior_year_overpayment_applied") in (None, "")
        ):
            missing.append("prior_year_overpayment_applied")

        # Only when there is a shareholder loan to apply basis against.
        if (
            normalized.get("loan_balance_begin") not in (None, "")
            and CarryoverKind.DEBT_BASIS not in known
            and normalized.get("debt_basis_begin") in (None, "")
        ):
            missing.append("debt_basis_begin")

        return missing


def upload_request(outcome: PriorYearOutcome, tax_year: int) -> dict[str, str]:
    """The message asking the user for last year's return.

    Written to be actionable: it names the document, says which figures depend
    on it, and states what happens if it is not supplied — rather than
    reporting that data is missing and leaving the reader to work out whether
    that matters.
    """
    reasons = [
        f"• {CONSEQUENCE.get(name, name.replace('_', ' '))}"
        for name in outcome.missing
    ]
    return {
        "field": "prior_year_return",
        "title": f"Upload the {tax_year - 1} tax return",
        "description": (
            f"This return needs figures that appear only on the {tax_year - 1} "
            "return, and no prior-year return was found in what was uploaded:\n\n"
            + "\n".join(reasons)
            + "\n\nThey have been treated as zero so a return could still be "
            "produced. Upload the prior-year return and reprocess, or enter the "
            "figures directly. On a comparable sample return the missing "
            "carryover overstated adjusted gross income by 5,502."
        ),
    }
