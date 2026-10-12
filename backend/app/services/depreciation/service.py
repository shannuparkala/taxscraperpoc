"""Assemble a full calculator result: schedules, comparison, form lines, sources.

Everything here is arithmetic over ``engine.compute`` and lookups in the rule
files. The result is a plain JSON-ready dict (money as strings) so the
screen, the CSV, the PDF and the explanation prompt all read the same
numbers - an export cannot drift from what was displayed because it is the
same object.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.depreciation import tape
from app.services.depreciation.engine import (
    DISCLAIMER,
    HUNDRED,
    METHOD_LABELS,
    METHODS,
    SCENARIOS,
    ZERO,
    AssetResult,
    CalculationInput,
    Computation,
    compute,
    dollars,
    validate,
)
from app.services.depreciation.rules import DepreciationRules, RuleRef, get_rules
from app.services.depreciation.state import StateOutcome, evaluate_state

ASSUMPTIONS = [
    "Calendar-year taxpayer with a full 12-month tax year (the IRS percentage tables cannot be used for a short year).",
    "General Depreciation System (GDS) unless listed property is used 50% or less for business, which requires ADS.",
    "Property is new to you and qualifies for the special allowance when its class does; used property must meet the acquisition rules.",
    "No dispositions, like-kind exchanges or changes in business use after the first year.",
    "Amounts are in whole dollars. Each year's deduction is rounded at the end of that year's computation; the last year absorbs rounding so each schedule totals its basis exactly.",
    "State figures are for the individual (personal) income tax as it applies to a sole proprietor, pass-through owner or rental owner, using the same business income for the state Section 179 limit.",
]


def calculate(request: CalculationInput, rules: DepreciationRules | None = None) -> dict[str, Any]:
    rules = rules or get_rules()
    validate(request, rules)
    primary_key = "bonus" if request.method == "compare" else request.method
    scenario = SCENARIOS[primary_key]

    federal = compute(request, rules, scenario)
    state = evaluate_state(request, rules, scenario, federal)

    comparison = [_compare(request, rules, key, federal if key == primary_key else None, state if key == primary_key else None)
                  for key in METHODS]

    refs: dict[str, RuleRef] = dict(federal.refs)
    if state:
        for ref in state.refs:
            refs[ref.key] = ref
        if state.computation:
            refs.update(state.computation.refs)
    form_lines, form_ref = rules.form_lines(request.tax_year)
    refs[form_ref.key] = form_ref
    if any(a.asset_class in ("residential_rental", "nonresidential", "qualified_production") for a in request.assets):
        refs["recapture_note"] = rules.ref("recapture_note", "Depreciation recapture on sale")

    warnings = list(dict.fromkeys(federal.warnings))
    if state and state.computation:
        for w in dict.fromkeys(state.computation.warnings):
            if w not in warnings:
                warnings.append(f"{state.name}: {w}")

    notes: list[str] = []
    if "recapture_note" in refs:
        notes.append(rules.federal["recapture_note"]["value"])

    check = _check(federal)
    return {
        "tax_year": request.tax_year,
        "method": request.method,
        "primary_scenario": primary_key,
        "primary_label": METHOD_LABELS[primary_key],
        "supported_years": list(rules.supported_years),
        "assets": [_asset(a, request.tax_year, federal) for a in federal.assets],
        "summary": tape.summary(federal, request.tax_year),
        "tape": tape.total_tape(federal, request.tax_year),
        "federal": {
            "schedule": _federal_rows(federal),
            "tax_year_deduction": str(federal.deduction_in(request.tax_year)),
            "first_year": _first_year(federal, request.tax_year),
            "basis": str(federal.basis),
            "total": str(federal.total),
            "carryforward": str(federal.carryforward),
            "check": check,
            "conventions": {str(y): c for y, c in federal.conventions.items()},
            "q4_share": {str(y): str((s * HUNDRED).quantize(Decimal("0.1"))) for y, s in federal.q4_share.items()},
        },
        "section_179": {str(y): s.to_dict() for y, s in federal.section_179.items()},
        "state": _state(state, request, rules),
        "comparison": comparison,
        "form_4562": _form_4562(federal, request.tax_year, form_lines),
        "warnings": warnings,
        "notes": notes,
        "assumptions": ASSUMPTIONS,
        "sources": [ref.to_dict() for ref in sorted(refs.values(), key=lambda r: r.key)],
        "disclaimer": DISCLAIMER,
    }


def _asset(asset: AssetResult, tax_year: int, computation: Computation) -> dict[str, Any]:
    this_year = asset.row_for(tax_year)
    return {
        "id": asset.id,
        "description": asset.description,
        "asset_class": asset.asset_class,
        "class_label": asset.class_label,
        "recovery_years": asset.recovery_years,
        "system": asset.system,
        "method": asset.method,
        "convention": asset.convention,
        "convention_selected": asset.convention_selected,
        "table": asset.table_ref.label,
        "table_column": asset.table_column,
        "placed_in_service": asset.placed_in_service.isoformat(),
        "cost": str(asset.cost),
        "land_value": str(asset.land_value),
        "business_use_pct": str(asset.business_use_pct),
        "business_basis": str(asset.business_basis),
        "section_179_elected": str(asset.section_179_elected),
        "section_179_allowed": str(asset.section_179_allowed),
        "section_179_carryforward": str(asset.section_179_carryforward),
        "bonus_rate": str(asset.bonus_rate),
        "bonus": str(asset.bonus),
        "special_allowance": str(asset.special_allowance),
        "macrs_basis": str(asset.macrs_basis),
        "tax_year_deduction": str(this_year.total if this_year else ZERO),
        "total": str(asset.total),
        "schedule": tape.year_rows(asset),
        "tape": tape.asset_tape(asset, tax_year, computation.section_179.get(asset.placed_in_service.year)),
        "notes": asset.notes,
    }


def _federal_rows(computation: Computation) -> list[dict[str, Any]]:
    """All assets by year, with running totals and each asset's contribution."""
    out = []
    cumulative = ZERO
    basis = computation.basis - sum((a.section_179_carryforward for a in computation.assets), ZERO)
    for row in computation.schedule():
        cumulative += row.total
        why = []
        for asset in computation.assets:
            own = asset.row_for(row.year)
            if own is not None and own.total:
                why.append(f"{asset.description or asset.class_label}: ${own.total:,.0f}")
        out.append({
            **row.to_dict(),
            "cumulative": str(cumulative),
            "remaining": str(basis - cumulative),
            "why": why or ["No deduction in this year."],
        })
    return out


def _first_year(computation: Computation, tax_year: int) -> dict[str, str]:
    """Deduction in the selected tax year, split by component."""
    row = next((r for r in computation.schedule() if r.year == tax_year), None)
    summary = computation.section_179.get(tax_year)
    carried = summary.carryover_used if summary else ZERO
    if row is None:
        return {"section_179": str(carried), "bonus": "0", "special": "0", "macrs": "0",
                "carryover_used": str(carried), "total": str(carried)}
    return {
        "section_179": str(row.section_179 + carried),
        "bonus": str(row.bonus),
        "special": str(row.special),
        "macrs": str(row.macrs),
        "carryover_used": str(carried),
        "total": str(row.total + carried),
    }


def _check(computation: Computation) -> dict[str, Any]:
    """Every asset's schedule plus its Section 179 carryforward equals its basis."""
    scheduled = computation.total
    asset_carry = sum((a.section_179_carryforward for a in computation.assets), ZERO)
    per_asset = all(a.total + a.section_179_carryforward == a.business_basis for a in computation.assets)
    non_negative = all(r.total >= 0 for a in computation.assets for r in a.rows)
    ok = per_asset and non_negative and scheduled + asset_carry == computation.basis
    return {
        "depreciable_basis": str(computation.basis),
        "scheduled": str(scheduled),
        "section_179_carryforward": str(asset_carry),
        "ok": ok,
        "statement": (
            "Schedule plus Section 179 carryforward equals depreciable basis."
            if ok else "Totals do not reconcile - do not rely on this schedule."
        ),
    }


def _state(state: StateOutcome | None, request: CalculationInput, rules: DepreciationRules) -> dict[str, Any] | None:
    if state is None:
        return None
    entry = state.entry or {}
    cumulative = ZERO
    rows = []
    for row in state.rows:
        cumulative += row.adjustment
        rows.append({**row.to_dict(), "cumulative_difference": str(cumulative)})
    recent = [
        int(year) for year, e in (rules.state(state.code) or {}).get("years", {}).items()
        if e.get("changed_recently") and int(year) >= rules.supported_years[-1] - 1
    ]
    return {
        "code": state.code,
        "name": state.name,
        "status": state.status,
        "message": state.message,
        "provisional_available": state.provisional_available,
        "rows": rows,
        "tax_year_deduction": str(state.deduction_in(request.tax_year)) if state.computed else None,
        "tax_year_adjustment": (
            str(sum((r.adjustment for r in state.rows if r.year == request.tax_year), ZERO))
            if state.computed else None
        ),
        "total": str(state.total) if state.computed else None,
        "carryforward": str(state.carryforward),
        "reverses": state.computed and sum((r.adjustment for r in state.rows), ZERO) == 0,
        "rule": {
            "summary": entry.get("summary", ""),
            "bonus": entry.get("bonus"),
            "section_179": entry.get("section_179"),
            "decouples_168n": entry.get("decouples_168n"),
            "conformity": entry.get("conformity"),
            "status": entry.get("status"),
            "source_url": entry.get("source_url", ""),
            "source_citation": entry.get("source_citation", ""),
            "last_verified": entry.get("last_verified"),
            "verify_note": entry.get("verify_note", ""),
            "change_note": entry.get("change_note", ""),
        },
        "changed_recently_years": sorted(recent),
        "notes": state.notes,
    }


def _compare(
    request: CalculationInput,
    rules: DepreciationRules,
    key: str,
    federal: Computation | None,
    state: StateOutcome | None,
) -> dict[str, Any]:
    scenario = SCENARIOS[key]
    federal = federal or compute(request, rules, scenario)
    if request.state and state is None:
        state = evaluate_state(request, rules, scenario, federal)
    fed_year = federal.deduction_in(request.tax_year)
    state_year = state.deduction_in(request.tax_year) if state and state.computed else None
    fed_effect = (
        dollars(fed_year * request.federal_marginal_rate / HUNDRED)
        if request.federal_marginal_rate is not None else None
    )
    state_effect = (
        dollars(state_year * request.state_marginal_rate / HUNDRED)
        if state_year is not None and request.state_marginal_rate is not None else None
    )
    combined = None
    if fed_effect is not None or state_effect is not None:
        combined = (fed_effect or ZERO) + (state_effect or ZERO)
    return {
        "key": key,
        "label": METHOD_LABELS[key],
        "federal_tax_year_deduction": str(fed_year),
        "federal_first_year": _first_year(federal, request.tax_year),
        "federal_carryforward": str(federal.carryforward),
        "state_tax_year_deduction": None if state_year is None else str(state_year),
        "federal_tax_effect": None if fed_effect is None else str(fed_effect),
        "state_tax_effect": None if state_effect is None else str(state_effect),
        "combined_tax_effect": None if combined is None else str(combined),
        "schedule": [{"year": r.year, "total": str(r.total)} for r in federal.schedule()],
    }


def _form_4562(computation: Computation, tax_year: int, lines: dict[str, Any]) -> list[dict[str, str]]:
    """Reference mapping of this year's amounts to Form 4562 lines."""
    out: list[dict[str, str]] = []
    summary = computation.section_179.get(tax_year)
    if summary and (summary.elected or summary.carryover_in):
        out += [
            {"line": "1", "label": "Maximum Section 179 amount", "amount": str(summary.limit)},
            {"line": "2", "label": "Total cost of Section 179 property placed in service", "amount": str(summary.total_cost)},
            {"line": "3", "label": "Threshold before reduction", "amount": "" if summary.threshold is None else str(summary.threshold)},
            {"line": "4", "label": "Reduction in limitation", "amount": str(summary.reduction)},
            {"line": "5", "label": "Dollar limitation for the year", "amount": str(summary.dollar_limit)},
        ]
        listed = sum((a.section_179_elected for a in computation.assets if a.listed and a.placed_in_service.year == tax_year), ZERO)
        other = summary.elected - listed
        if other:
            out.append({"line": "6 (c)", "label": "Elected cost, Section 179 property", "amount": str(other)})
        if listed:
            out.append({"line": "7", "label": "Listed property elected cost (from line 29)", "amount": str(listed)})
        out += [
            {"line": "8", "label": "Total elected cost", "amount": str(summary.elected)},
            {"line": "9", "label": "Tentative deduction", "amount": str(min(summary.elected, summary.dollar_limit))},
            {"line": "10", "label": "Carryover of disallowed deduction from prior year", "amount": str(summary.carryover_in)},
            {"line": "11", "label": "Business income limitation", "amount": "" if summary.income_limit is None else str(summary.income_limit)},
            {"line": "12", "label": "Section 179 expense deduction", "amount": str(summary.deduction)},
            {"line": "13", "label": "Carryover to next year", "amount": str(summary.carryforward)},
        ]

    current = [a for a in computation.assets if a.placed_in_service.year == tax_year]
    prior = [a for a in computation.assets if a.placed_in_service.year < tax_year]
    special = sum((a.bonus + a.special_allowance for a in current if not a.listed), ZERO)
    if special:
        out.append({"line": lines["bonus"], "label": "Special depreciation allowance (bonus / 168(n)), non-listed property", "amount": str(special)})
    def this_year(asset: AssetResult, field: str) -> Decimal:
        row = asset.row_for(tax_year)
        return getattr(row, field) if row is not None else ZERO

    prior_macrs = sum((this_year(a, "total") for a in prior if not a.listed), ZERO)
    if prior_macrs:
        out.append({"line": lines["macrs_prior_years"], "label": "MACRS on assets placed in service in earlier years", "amount": str(prior_macrs)})
    by_line: dict[str, Decimal] = {}
    for asset in current:
        if asset.listed:
            continue
        row = asset.row_for(tax_year)
        line = lines["macrs_current_year"].get(asset.recovery_years, "19")
        by_line[line] = by_line.get(line, ZERO) + (row.macrs if row else ZERO)
    for line in sorted(by_line):
        if by_line[line]:
            out.append({"line": line, "label": "MACRS (GDS), placed in service this year", "amount": str(by_line[line])})
    listed_bonus = sum((a.bonus for a in current if a.listed), ZERO)
    if listed_bonus:
        out.append({"line": lines["bonus_listed"], "label": "Special allowance, listed property used over 50%", "amount": str(listed_bonus)})
    over = sum((this_year(a, "macrs") for a in computation.assets if a.listed and a.business_use_pct > 50), ZERO)
    under = sum((this_year(a, "macrs") for a in computation.assets if a.listed and a.business_use_pct <= 50), ZERO)
    if over:
        out.append({"line": lines["listed_over_50"], "label": "Listed property used more than 50% for business", "amount": str(over)})
    if under:
        out.append({"line": lines["listed_50_or_less"], "label": "Listed property used 50% or less for business (ADS)", "amount": str(under)})
    out.append({"line": lines["total"], "label": "Total depreciation and Section 179 (this calculation)", "amount": str(computation.deduction_in(tax_year))})
    return out
