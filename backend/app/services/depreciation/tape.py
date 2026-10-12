"""The calculation tape: how every number on the screen was reached.

An adding-machine tape, per asset and in total: each line is a value with
the operator that combines it into the next subtotal (+ - x =), and the
totals the screen shows are the tape's highlighted lines.

SECURITY/correctness: nothing here applies a rate, a limit or a rounding
rule. Every value on the tape is a field the engine already produced (basis,
elected 179, bonus, each year's rate, base, unrounded product, cap and
rounding); the only arithmetic here is running sums and differences of those
fields for the cumulative and remaining-basis columns. A
tape that recomputed would be a second engine, free to disagree with the
first, and the disagreement would look like an explanation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.depreciation.engine import (
    HUNDRED,
    ZERO,
    AssetResult,
    Computation,
    Section179Summary,
)


def _m(value: Decimal) -> str:
    return str(value)


def line(label: str, value: Decimal | str, op: str = "", kind: str = "money", emphasis: bool = False,
         note: str = "") -> dict[str, Any]:
    """One tape line. ``op`` is how it combines: "", "+", "-", "x", "=" or "T" (total)."""
    return {"label": label, "value": str(value), "op": op, "kind": kind, "emphasis": emphasis, "note": note}


def asset_tape(asset: AssetResult, tax_year: int, s179: Section179Summary | None) -> list[dict[str, Any]]:
    pis = asset.placed_in_service.year
    sections: list[dict[str, Any]] = []

    basis = [line("Cost basis", asset.cost)]
    if asset.land_value:
        basis.append(line("Land (never depreciable)", asset.land_value, "-"))
    if asset.clean_vehicle_credit:
        basis.append(line("Clean vehicle credit", asset.clean_vehicle_credit, "-"))
    if asset.business_use_pct != HUNDRED:
        basis.append(line("Business use", asset.business_use_pct, "x", kind="percent"))
    basis.append(line("Depreciable basis", asset.business_basis, "=", emphasis=True))
    sections.append({"title": "Depreciable basis", "lines": basis})

    if asset.section_179_elected:
        rows = []
        if s179:
            rows.append(line(f"Section 179 dollar limit ({pis})", s179.dollar_limit,
                             note="Limit reduced dollar for dollar above the phase-out threshold"))
        rows.append(line("Section 179 elected on this asset", asset.section_179_elected, "T", emphasis=True))
        if asset.section_179_carryforward:
            rows.append(line("Allowed this year (business income limit)", asset.section_179_allowed))
            rows.append(line("Carried forward to next year", asset.section_179_carryforward))
        rows.append(line("Basis after Section 179", asset.business_basis - asset.section_179_elected, "="))
        sections.append({"title": f"Section 179 election ({pis})", "lines": rows})

    after_179 = asset.business_basis - asset.section_179_elected
    if asset.bonus:
        sections.append({"title": f"Bonus depreciation ({pis})", "lines": [
            line("Basis subject to bonus", after_179),
            line(f"Bonus rate for {pis}", asset.bonus_rate, "x", kind="percent",
                 note="Set by the acquisition and placed-in-service dates"),
            line("First-year bonus", asset.bonus, "T", emphasis=True),
        ]})
    if asset.special_allowance:
        sections.append({"title": f"Section 168(n) allowance ({pis})", "lines": [
            line("Qualified production property basis", after_179),
            line("Allowance rate", Decimal(100), "x", kind="percent"),
            line("First-year allowance", asset.special_allowance, "T", emphasis=True),
        ]})

    macrs = [line("Depreciable basis", asset.business_basis)]
    if asset.section_179_elected:
        macrs.append(line("Section 179 elected", asset.section_179_elected, "-"))
    if asset.bonus:
        macrs.append(line("Bonus", asset.bonus, "-"))
    if asset.special_allowance:
        macrs.append(line("Section 168(n) allowance", asset.special_allowance, "-"))
    chosen = ", selected" if asset.convention_selected else ""
    macrs.append(line(f"Basis for regular depreciation ({asset.convention} convention{chosen})", asset.macrs_basis, "=", emphasis=True))
    sections.append({"title": "Remaining basis for regular depreciation", "lines": macrs})

    row = asset.row_for(tax_year)
    if row is not None:
        year_lines = []
        if row.section_179:
            year_lines.append(line("Section 179", row.section_179, "+"))
        if row.bonus:
            year_lines.append(line("Bonus depreciation", row.bonus, "+"))
        if row.special:
            year_lines.append(line("Section 168(n) allowance", row.special, "+"))
        if row.rate is not None and row.base is not None:
            index = row.year - pis + 1
            year_lines.append(line("Basis the rate applies to", row.base))
            year_lines.append(line(f"Year {index} table rate", row.rate, "x", kind="percent",
                                   note=f"{asset.table_ref.label}, column {asset.table_column}"))
            if row.exact is not None:
                year_lines.append(line("Regular depreciation before rounding and limits",
                                       row.exact.quantize(Decimal("0.01")), "="))
        if row.capped and row.cap is not None:
            year_lines.append(line("Section 280F limit for the year (x business use)", row.cap, note="Deduction limited to this cap"))
        if row.after_recovery:
            year_lines.append(line("Unrecovered basis deducted after the recovery period", row.macrs,
                                   note="Up to the succeeding-year Section 280F limit"))
        if row.rounding:
            year_lines.append(line("Rounding settled in the final year", row.rounding, "+",
                                   note="Each year is rounded to whole dollars; the last year makes the total exact"))
        year_lines.append(line(f"{tax_year} depreciation", row.total, "T", emphasis=True))
        sections.append({"title": f"{tax_year} deduction", "lines": year_lines})

    through = [r for r in asset.rows if r.year <= tax_year]
    accumulated = sum((r.total for r in through), ZERO)
    acc_lines = [line(f"{r.year}" + (" (selected)" if r.year == tax_year else ""), r.total, "+",
                      emphasis=r.year == tax_year) for r in through]
    acc_lines.append(line(f"Accumulated 12/31/{str(tax_year)[2:]}", accumulated, "T", emphasis=True))
    sections.append({"title": "All years through the tax year", "lines": acc_lines})

    ending = [line("Depreciable basis", asset.business_basis), line("Accumulated deductions", accumulated, "-")]
    if asset.section_179_carryforward:
        ending.append(line("Section 179 elected, carried forward", asset.section_179_carryforward, "-",
                           note="Reduces basis now; deducted in a later year"))
    ending.append(line(f"Adjusted basis (NBV) 12/31/{str(tax_year)[2:]}",
                       asset.business_basis - accumulated - asset.section_179_carryforward, "=", emphasis=True))
    sections.append({"title": f"Ending values 12/31/{str(tax_year)[2:]}", "lines": ending})
    return sections


def year_rows(asset: AssetResult) -> list[dict[str, Any]]:
    """The asset's schedule with rate, cumulative, remaining basis and a 'why'."""
    out = []
    cumulative = ZERO
    for row in asset.rows:
        cumulative += row.total
        remaining = asset.business_basis - cumulative - asset.section_179_carryforward
        out.append({
            **row.to_dict(),
            "index": row.year - asset.placed_in_service.year + 1,
            "rate": None if row.rate is None else str(row.rate),
            "cumulative": str(cumulative),
            "remaining": str(remaining),
            "capped": row.capped,
            "why": _why(asset, row),
        })
    return out


def _why(asset: AssetResult, row: Any) -> list[str]:
    reasons: list[str] = []
    money = lambda v: f"${v:,.0f}"
    if row.section_179:
        reasons.append(f"Section 179 expense: {money(row.section_179)} elected and allowed this year.")
    if row.bonus:
        reasons.append(f"Bonus: {money(asset.business_basis - asset.section_179_elected)} x "
                       f"{asset.bonus_rate.normalize():f}% = {money(row.bonus)}.")
    if row.special:
        reasons.append(f"Section 168(n): 100% of the qualified production basis = {money(row.special)}.")
    if row.rate is not None and row.base is not None:
        index = row.year - asset.placed_in_service.year + 1
        reasons.append(
            f"MACRS: {money(row.base)} x {row.rate.normalize():f}% (year {index}, {asset.table_ref.label}"
            f", column {asset.table_column}) = ${(row.exact or ZERO):,.2f}."
        )
    if row.capped and row.cap is not None:
        reasons.append(f"Limited to the {money(row.cap)} Section 280F cap for this year.")
    if row.after_recovery:
        reasons.append(f"After the recovery period: unrecovered basis deducted up to {money(row.cap)} a year.")
    if row.rounding:
        reasons.append(f"Includes a {money(row.rounding)} rounding adjustment so the schedule totals the basis exactly.")
    if not reasons:
        reasons.append("Nothing left to depreciate in this year.")
    return reasons


def summary(computation: Computation, tax_year: int) -> dict[str, Any]:
    """Headline numbers at 12/31 of the tax year, each with its formula."""
    assets = [a for a in computation.assets if a.placed_in_service.year <= tax_year]
    cost = sum((a.business_basis for a in assets), ZERO)
    accumulated = sum((r.total for a in assets for r in a.rows if r.year <= tax_year), ZERO)
    carry = sum((a.section_179_carryforward for a in assets), ZERO)
    current = computation.deduction_in(tax_year)
    s179 = computation.section_179.get(tax_year)
    carry_used = s179.carryover_used if s179 else ZERO
    year_short = str(tax_year)[2:]
    per_asset: list[str] = []
    for a in assets:
        row = a.row_for(tax_year)
        name = a.description or a.class_label
        if row is None or not row.total:
            per_asset.append(f"{name}: nothing left to deduct in {tax_year}")
            continue
        steps = _why(a, row)
        if len(assets) > 1:
            per_asset.append(f"{name}: {_fmt(row.total)}")
            per_asset.extend(f"   {step}" for step in steps)
        else:
            per_asset.extend(steps)
    return {
        "current_year": {
            "label": f"Current-year deduction ({tax_year})",
            "value": str(current),
            "why": per_asset + ([f"Prior-year Section 179 carryover used: {_fmt(carry_used)}"] if carry_used else [])
            + [f"Total {tax_year} deduction = {_fmt(current)}"],
        },
        "ending_cost": {
            "label": f"Ending cost 12/31/{year_short}",
            "value": str(cost),
            "why": [
                "Depreciable basis of every asset placed in service by the end of the tax year:",
                "cost, less land and any clean vehicle credit, times the business-use percentage.",
                f"= {_fmt(cost)}",
            ],
        },
        "ending_accumulated": {
            "label": f"Ending accumulated 12/31/{year_short}",
            "value": str(accumulated),
            "why": [
                f"Sum of every year's deduction from the year each asset was placed in service through {tax_year}",
                "(Section 179, bonus, 168(n) and regular MACRS).",
                f"= {_fmt(accumulated)}",
            ],
        },
        "ending_nbv": {
            "label": f"Ending NBV 12/31/{year_short}",
            "value": str(cost - accumulated - carry),
            "why": [
                f"Ending cost {_fmt(cost)}",
                f"- accumulated deductions {_fmt(accumulated)}",
                *([f"- Section 179 elected but carried forward {_fmt(carry)}"] if carry else []),
                f"= adjusted basis {_fmt(cost - accumulated - carry)}",
            ],
        },
    }


def _fmt(value: Decimal) -> str:
    return f"-${-value:,.0f}" if value < 0 else f"${value:,.0f}"


def total_tape(computation: Computation, tax_year: int) -> list[dict[str, Any]]:
    """All assets: one line each for the tax year, then the total."""
    lines = []
    for asset in computation.assets:
        row = asset.row_for(tax_year)
        lines.append(line(asset.description or asset.class_label, row.total if row else ZERO, "+"))
    s179 = computation.section_179.get(tax_year)
    if s179 and s179.carryover_used:
        lines.append(line("Prior-year Section 179 carryover used", s179.carryover_used, "+"))
    lines.append(line(f"{tax_year} deduction, all assets", computation.deduction_in(tax_year), "T", emphasis=True))
    return [{"title": f"{tax_year} deduction by asset", "lines": lines}]
