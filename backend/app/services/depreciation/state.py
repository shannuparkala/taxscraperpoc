"""State depreciation: the selected state's rules, or an honest refusal.

The state's schedule is computed one of two ways, chosen by the state's
entry in ``state_conformity.json`` for the year the asset was placed in
service:

* **A different regime over the same arithmetic.** A state that disallows
  bonus, allows only part of it, follows the Code as of a date before the
  2025 federal law, or has its own Section 179 limit is the federal engine
  run with those parameters. The state schedule then differs from the
  federal one in exactly the places the rules differ, and both sum to the
  same basis - so the difference reverses over the asset's life by
  construction.
* **Add back and recover.** A state that adds back a percentage of federal
  bonus (or Section 179) and subtracts it in equal parts over the following
  years is the federal schedule plus those adjustments.

SECURITY/correctness: there is no fallback. A state without a verified entry
for the year gets the message "State rules not yet verified for this year"
and the federal result still stands; another state's rules, or federal rules
relabelled as the state's, are never substituted. The researched-but-not-
verified rule can be shown only on request, labelled provisional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.depreciation.engine import (
    FEDERAL,
    HUNDRED,
    ZERO,
    CalculationInput,
    Computation,
    Regime,
    Scenario,
    compute,
    dollars,
)
from app.services.depreciation.rules import DepreciationRules, RuleRef, Section179Limits

NOT_VERIFIED = "State rules not yet verified for this year"


@dataclass(slots=True)
class StateRow:
    year: int
    federal: Decimal
    state: Decimal

    @property
    def adjustment(self) -> Decimal:
        """Positive: add back to state income. Negative: subtract."""
        return self.federal - self.state

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "federal": str(self.federal),
            "state": str(self.state),
            "adjustment": str(self.adjustment),
        }


@dataclass(slots=True)
class StateOutcome:
    code: str
    name: str
    status: str  # computed | provisional | not_verified | no_income_tax
    message: str
    entry: dict[str, Any] | None
    rows: list[StateRow] = field(default_factory=list)
    computation: Computation | None = None
    carryforward: Decimal = ZERO
    notes: list[str] = field(default_factory=list)
    refs: list[RuleRef] = field(default_factory=list)
    provisional_available: bool = False

    @property
    def computed(self) -> bool:
        return self.status in ("computed", "provisional")

    def deduction_in(self, year: int) -> Decimal:
        return sum((row.state for row in self.rows if row.year == year), ZERO)

    @property
    def total(self) -> Decimal:
        return sum((row.state for row in self.rows), ZERO)


def computable(entry: dict[str, Any] | None, needs_179: bool = True) -> bool:
    """Can this entry produce a state schedule?

    An unknown Section 179 limit does not block a calculation that elects no
    Section 179: the unknown figure never enters it.
    """
    if not entry or not entry.get("income_tax"):
        return False
    if entry["bonus"]["mode"] == "unknown":
        return False
    return not (needs_179 and entry["section_179"]["mode"] == "unknown")


def _regime(code: str, entry: dict[str, Any], year: int, rules: DepreciationRules, needs_179: bool = True) -> Regime:
    bonus = entry["bonus"]
    s179 = entry["section_179"]
    mode = bonus["mode"]
    limits: Section179Limits | None = None
    if s179["mode"] == "own" and needs_179:
        federal = rules.section_179(year)
        threshold = s179.get("phaseout_threshold")
        limits = Section179Limits(
            limit=Decimal(s179["limit"]),
            phaseout_threshold=None if threshold is None else Decimal(threshold),
            suv_cap=min(federal.suv_cap, Decimal(s179["limit"])),
            ref=_entry_ref(code, year, entry, f"{code} Section 179 limit ({year})"),
        )
    after = bonus.get("applies_if_acquired_after")
    return Regime(
        key=code,
        bonus_mode={"follow": "federal", "addback": "federal"}.get(mode, mode),
        bonus_pct=None if bonus.get("allowed_pct") is None else Decimal(str(bonus["allowed_pct"])),
        bonus_applies_if_acquired_after=date.fromisoformat(after) if after else None,
        section_179=limits,
        allow_qpp=entry.get("decouples_168n") is not True,
    )


def _entry_ref(code: str, year: int, entry: dict[str, Any], label: str) -> RuleRef:
    return RuleRef(
        key=f"state.{code}.{year}",
        label=label,
        source_citation=entry.get("source_citation", ""),
        source_url=entry.get("source_url", ""),
        last_verified=entry.get("last_verified"),
        verified=entry.get("status") == "verified",
        verify_note=entry.get("verify_note", ""),
    )


def evaluate_state(
    request: CalculationInput,
    rules: DepreciationRules,
    scenario: Scenario,
    federal: Computation,
) -> StateOutcome | None:
    if not request.state:
        return None
    code = request.state.upper()
    state = rules.state(code)
    if state is None:  # validate() rejects this first; never fall through to anyone else's rules
        raise ValueError(f"Unsupported state {code}")
    name = state["name"]
    entry = rules.state_entry(code, request.tax_year)
    pis_years = sorted({a.placed_in_service.year for a in request.assets})
    entries = {year: rules.state_entry(code, year) for year in pis_years}

    if entry and entry.get("status") == "no_income_tax":
        extra = f" {state['business_tax']} is a separate business tax with its own rules." if state.get("business_tax") else ""
        return StateOutcome(
            code, name, "no_income_tax",
            f"{name} has no individual income tax, so there is no state income tax depreciation "
            f"deduction.{extra} Entity-level taxes (franchise, gross receipts, corporate income) can "
            "have their own depreciation rules and are not computed here.",
            entry, notes=[entry.get("special_rules", "")] if entry.get("special_rules") else [],
            refs=[_entry_ref(code, request.tax_year, entry, f"{name} income tax status")],
        )

    needs = {
        year: bool(federal.section_179.get(year) and federal.section_179[year].elected)
        for year in pis_years
    }
    all_verified = all(e and e.get("status") == "verified" and computable(e, needs[y]) for y, e in entries.items())
    all_computable = all(computable(e, needs[y]) for y, e in entries.items())
    if not all_verified and not (request.include_provisional_state and all_computable):
        unverified_years = [str(y) for y, e in entries.items() if not (e and e.get("status") == "verified")]
        return StateOutcome(
            code, name, "not_verified",
            f"{NOT_VERIFIED} ({name}, {', '.join(unverified_years) or request.tax_year}). "
            "The federal result below is unaffected; no other state's rules are substituted.",
            entry,
            provisional_available=all_computable,
            refs=[_entry_ref(code, y, e, f"{name} conformity ({y})") for y, e in entries.items() if e],
        )

    status = "computed" if all_verified else "provisional"
    # Every entry is present here: a missing one is not computable and
    # returned "not verified" above.
    known: dict[int, dict[str, Any]] = {year: e for year, e in entries.items() if e is not None}
    regimes = {year: _regime(code, known[year], year, rules, needs[year]) for year in pis_years}
    computation = compute(request, rules, scenario, lambda year: regimes.get(year, FEDERAL))

    # Add back and recover, on top of the regime's schedule.
    per_year: dict[int, Decimal] = {}
    for asset in computation.assets:
        for row in asset.rows:
            per_year[row.year] = per_year.get(row.year, ZERO) + row.total
    notes: list[str] = []

    def add_back(start: int, added: Decimal, years: int) -> None:
        per_year[start] = per_year.get(start, ZERO) - added
        share = dollars(added / years)
        for offset in range(1, years + 1):
            part = share if offset < years else added - share * (years - 1)
            per_year[start + offset] = per_year.get(start + offset, ZERO) + part

    # Bonus: a share of each asset's federal bonus.
    for asset in computation.assets:
        start = asset.placed_in_service.year
        rule = known[start]["bonus"]
        if rule["mode"] != "addback" or asset.bonus <= 0:
            continue
        added = dollars(asset.bonus * Decimal(str(rule["addback_pct"])) / HUNDRED)
        years = int(rule["recovery_years"])
        add_back(start, added, years)
        notes.append(
            f"{name} adds back {Decimal(str(rule['addback_pct'])).normalize():f}% of federal bonus depreciation on "
            f"{asset.description or asset.class_label} (${added:,.0f}) in {start} and subtracts it in equal parts "
            f"over the next {years} years."
        )

    # Section 179: a share of the federal deduction - or of the part above
    # what the state's own (older) limit would have allowed - per year.
    for year in pis_years:
        rule = known[year]["section_179"]
        if rule["mode"] != "addback":
            continue
        federal_179 = sum((a.section_179_allowed for a in computation.assets if a.placed_in_service.year == year), ZERO)
        if federal_179 <= 0:
            continue
        excess = federal_179
        if rule.get("limit") is not None:
            summary = computation.section_179.get(year)
            cost = summary.total_cost if summary else ZERO
            threshold = rule.get("phaseout_threshold")
            reduction = max(ZERO, cost - Decimal(str(threshold))) if threshold is not None else ZERO
            state_allowed = min(federal_179, max(ZERO, Decimal(str(rule["limit"])) - reduction))
            excess = federal_179 - state_allowed
        if excess <= 0:
            continue
        added = dollars(excess * Decimal(str(rule["addback_pct"])) / HUNDRED)
        years = int(rule["recovery_years"])
        add_back(year, added, years)
        base = (
            f"federal Section 179 above the ${Decimal(str(rule['limit'])):,.0f} state limit"
            if rule.get("limit") is not None else "federal Section 179"
        )
        notes.append(
            f"{name} adds back {Decimal(str(rule['addback_pct'])).normalize():f}% of {base} (${added:,.0f}) in {year} "
            f"and subtracts it in equal parts over the next {years} years."
        )

    federal_by_year = {row.year: row.total for row in federal.schedule()}
    schedule_years = sorted(set(per_year) | set(federal_by_year))
    rows = [StateRow(y, federal_by_year.get(y, ZERO), per_year.get(y, ZERO)) for y in schedule_years]

    for e in known.values():
        if e.get("special_rules"):
            notes.append(e["special_rules"])
        if e.get("decouples_168n") is None and any(a.special_allowance for a in federal.assets):
            notes.append(f"{name}'s treatment of the section 168(n) allowance is not confirmed in the rule data.")
    message = (
        f"{name} rules for {request.tax_year} applied."
        if status == "computed"
        else f"Provisional: {name}'s rule is researched but {NOT_VERIFIED.lower()}. Shown at your request; "
        "do not rely on it without checking the source."
    )
    return StateOutcome(
        code, name, status, message, entry,
        rows=rows,
        computation=computation,
        carryforward=computation.carryforward,
        notes=list(dict.fromkeys(n for n in notes if n)),
        refs=[_entry_ref(code, y, e, f"{name} conformity ({y})") for y, e in known.items()],
    )
