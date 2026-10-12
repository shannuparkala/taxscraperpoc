"""Carryovers that survive from one tax year to the next.

Some Form 1040 inputs appear on no current-year document. Schedule D lines 6 and
14 read "carryover from your Capital Loss Carryover Worksheet"; line 26 reads
"amount applied from your prior return". A pipeline driven purely by this year's
documents cannot know them, and treating them as zero produces a return that
foots, prints, and is wrong — on the CS-2 sample, by 4,511 of capital loss and
725 of payments, with no review item raised about either.

This repository is the missing half of that. A computed return deposits what it
carries forward; the next year's return withdraws it.

Three properties that shaped the design:

**Identity is pseudonymous.** Entries are keyed by a salted hash of the
taxpayer's identifying number, never the number itself. The file lives in the
output zone alongside other derived client data, and a repository of carryover
balances indexed by SSN would be a far more attractive target than the returns
it serves.

**Provenance travels with the amount.** Every balance records where it came from
— a computed return, a prior-year document, or a human. A carryover with no
stated origin is indistinguishable from a guess, and this is precisely the field
where a guess is invisible.

**Withdrawals never invent.** ``carryovers_into`` returns only what was actually
recorded. A missing balance comes back absent, not zero, so the caller can tell
"nothing carried forward" from "we have no idea" — the distinction the pipeline
previously could not make.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 1


class CarryoverKind:
    """The balances tracked. String constants so the JSON stays readable."""

    SHORT_TERM_CAPITAL_LOSS = "short_term_capital_loss"
    LONG_TERM_CAPITAL_LOSS = "long_term_capital_loss"
    OVERPAYMENT_APPLIED = "overpayment_applied"
    AMT_CREDIT = "amt_credit"
    FOREIGN_TAX_CREDIT = "foreign_tax_credit"
    PASSIVE_ACTIVITY_LOSS = "passive_activity_loss"
    NET_OPERATING_LOSS = "net_operating_loss"
    CHARITABLE_CONTRIBUTION = "charitable_contribution"
    GENERAL_BUSINESS_CREDIT = "general_business_credit"
    SECTION_179 = "section_179"
    SUSPENDED_K1_LOSS = "suspended_k1_loss"
    STOCK_BASIS = "stock_basis"
    DEBT_BASIS = "debt_basis"
    STATE = "state"


#: Carryover kind -> the engine input field it populates. Only the kinds the
#: engine can currently consume are mapped; the rest are recorded for the
#: reviewer and for future years until the engine grows a use for them.
ENGINE_FIELD_FOR_KIND: dict[str, str] = {
    CarryoverKind.SHORT_TERM_CAPITAL_LOSS: "short_term_loss_carryover",
    CarryoverKind.LONG_TERM_CAPITAL_LOSS: "long_term_loss_carryover",
    CarryoverKind.OVERPAYMENT_APPLIED: "prior_year_overpayment_applied",
}


class Origin:
    """How a balance came to be known. Never omitted."""

    COMPUTED_RETURN = "computed_return"
    PRIOR_YEAR_DOCUMENT = "prior_year_document"
    MANUAL_ENTRY = "manual_entry"


@dataclass(frozen=True, slots=True)
class CarryoverBalance:
    kind: str
    amount: Decimal
    #: The year this balance is available *to*.
    to_year: int
    origin: str
    #: Free text naming the specific source: a workflow id, a form line.
    origin_detail: str = ""
    recorded_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "amount": str(self.amount),
            "to_year": self.to_year,
            "origin": self.origin,
            "origin_detail": self.origin_detail,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CarryoverBalance | None:
        try:
            return cls(
                kind=str(data["kind"]),
                amount=Decimal(str(data["amount"])),
                to_year=int(data["to_year"]),
                origin=str(data.get("origin") or Origin.MANUAL_ENTRY),
                origin_detail=str(data.get("origin_detail") or ""),
                recorded_at=str(data.get("recorded_at") or ""),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            # A malformed entry is dropped rather than raised on: one bad row
            # must not make every other taxpayer's carryovers unreadable.
            logger.warning("Discarding a malformed carryover entry")
            return None


@dataclass(slots=True)
class CarryoverAudit:
    """What was withdrawn, for the explanation panel and the audit package."""

    taxpayer_key: str
    tax_year: int
    balances: list[CarryoverBalance] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "taxpayer_key": self.taxpayer_key,
            "tax_year": self.tax_year,
            "balances": [b.to_dict() for b in self.balances],
        }


def taxpayer_key(
    *, identifier: str | None = None, name: str | None = None, dob: str | None = None
) -> str | None:
    """A stable pseudonymous key for one taxpayer.

    Derived from the identifying number where there is one, falling back to name
    plus date of birth. Salted from the environment so that two firms running
    this software cannot compare repositories to learn whether they share a
    client.

    Returns None when there is nothing stable to key on — the caller must then
    skip the repository rather than invent a key, because a key collision here
    would hand one taxpayer another's carryovers.
    """
    basis = (identifier or "").strip()
    if not basis:
        if not (name and dob):
            return None
        basis = f"{name.strip().lower()}|{dob.strip()}"

    salt = os.environ.get("CARRYOVER_KEY_SALT", "taxscraper-carryover-v1")
    digest = hashlib.sha256(f"{salt}|{basis}".encode()).hexdigest()
    return digest[:32]


class CarryoverRepository:
    """A JSON-backed store of carryover balances, keyed by taxpayer and year."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    # -- read -------------------------------------------------------------

    def carryovers_into(self, key: str, tax_year: int) -> list[CarryoverBalance]:
        """Balances recorded as available *to* this tax year."""
        data = self._load()
        entries = (
            data.get("taxpayers", {}).get(key, {}).get("balances", [])
        )
        found = []
        for raw in entries:
            balance = CarryoverBalance.from_dict(raw)
            if balance is not None and balance.to_year == tax_year:
                found.append(balance)
        return found

    def engine_inputs(self, key: str, tax_year: int) -> dict[str, str]:
        """Carryovers rendered as engine field names, for the merge.

        Only kinds the engine can consume appear. Amounts are returned as
        strings to match the normalized-field convention, and Schedule D
        carryovers are returned positive because the engine's
        ``short_term_loss_carryover`` field is documented as entered positive.
        """
        fields: dict[str, str] = {}
        for balance in self.carryovers_into(key, tax_year):
            engine_field = ENGINE_FIELD_FOR_KIND.get(balance.kind)
            if engine_field is None:
                continue
            fields[engine_field] = str(abs(balance.amount))
        return fields

    def audit(self, key: str, tax_year: int) -> CarryoverAudit:
        return CarryoverAudit(
            taxpayer_key=key,
            tax_year=tax_year,
            balances=self.carryovers_into(key, tax_year),
        )

    # -- write ------------------------------------------------------------

    def record(
        self,
        key: str,
        balances: list[CarryoverBalance],
        *,
        label: str = "",
    ) -> None:
        """Store balances, replacing any prior entry for the same kind and year.

        Replacing rather than appending is deliberate: re-running a return must
        not double a carryover, and the most recent computation of a given year
        supersedes the earlier one.
        """
        if not balances:
            return

        data = self._load()
        taxpayers = data.setdefault("taxpayers", {})
        record = taxpayers.setdefault(key, {"label": label, "balances": []})
        if label:
            record["label"] = label

        superseded = {(b.kind, b.to_year) for b in balances}
        kept = [
            raw
            for raw in record.get("balances", [])
            if (str(raw.get("kind")), int(raw.get("to_year", -1))) not in superseded
        ]
        record["balances"] = kept + [b.to_dict() for b in balances]
        self._save(data)

    def record_from_return(
        self,
        key: str,
        computed_return: Any,
        *,
        workflow_id: str = "",
        label: str = "",
    ) -> list[CarryoverBalance]:
        """Deposit everything a completed return carries into the next year."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        to_year = int(computed_return.tax_year) + 1
        detail = f"workflow {workflow_id}" if workflow_id else "computed return"

        candidates = [
            (
                CarryoverKind.SHORT_TERM_CAPITAL_LOSS,
                getattr(computed_return, "capital_loss_carryforward_short", None),
                "Schedule D line 6",
            ),
            (
                CarryoverKind.LONG_TERM_CAPITAL_LOSS,
                getattr(computed_return, "capital_loss_carryforward_long", None),
                "Schedule D line 14",
            ),
            (
                CarryoverKind.OVERPAYMENT_APPLIED,
                getattr(computed_return, "applied_to_next_year", None),
                "Form 1040 line 36",
            ),
        ]

        balances = [
            CarryoverBalance(
                kind=kind,
                amount=Decimal(str(amount)),
                to_year=to_year,
                origin=Origin.COMPUTED_RETURN,
                origin_detail=f"{line}, {detail}",
                recorded_at=now,
            )
            for kind, amount, line in candidates
            if amount is not None and Decimal(str(amount)) > 0
        ]
        self.record(key, balances, label=label)
        return balances

    # -- storage ----------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": SCHEMA_VERSION, "taxpayers": {}}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Carryover repository unreadable; starting a new one")
            return {"version": SCHEMA_VERSION, "taxpayers": {}}
        if not isinstance(data, dict):
            return {"version": SCHEMA_VERSION, "taxpayers": {}}
        data.setdefault("version", SCHEMA_VERSION)
        data.setdefault("taxpayers", {})
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Written via a temporary file and replaced: a half-written repository
        # would lose every taxpayer's balances, not just the one being saved.
        temp = self._path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self._path)
