"""Statutory constants with the authority that sets each one.

Every figure the engine computes with carries the same four things: the value,
the document that fixes it, a resolvable URL, and whether that pairing was
checked against primary text. The values live in ``app/tax_constants/<year>.json``
and are loaded here into the types below; ``tax_tables`` derives its lookup
dicts from this module, so there is still exactly one place a figure comes from.

Why the indirection. A rate table of bare numbers cannot answer the two
questions an auditor actually asks — *which authority says so*, and *was that
checked* — and it cannot be safely rolled forward: the 2025 season needed two
different sources for figures that normally come from one. Rev. Proc. 2024-40
set the 2025 inflation adjustments in October 2024; the One Big Beautiful Bill
Act (Pub. L. 119-21, 4 July 2025) then superseded several of them. A table that
records only numbers cannot express that, and the earlier version of this
codebase carried the Rev. Proc. standard deduction and the Act's senior
deduction side by side, each looking equally settled.

Adding a tax year: copy the most recent ``tax_constants/<year>.json``, update
each value, and point every figure at the revenue procedure for that year. A
figure whose authority you could not confirm carries ``"verify": true`` — the
engine still computes with it and surfaces it as a review item rather than
filing on it silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

D = Decimal


# ---------------------------------------------------------------------------
# Authorities
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Authority:
    """One addressable source that fixes a figure."""

    citation: str
    url: str
    #: "Revenue Procedure" | "Public Law" | "IRC" | "Form Instruction" | "Agency"
    kind: str = "Revenue Procedure"

    def to_dict(self) -> dict[str, str]:
        return {"citation": self.citation, "url": self.url, "kind": self.kind}


RP_2024_40 = Authority(
    "Rev. Proc. 2024-40 (2025 inflation adjustments)",
    "https://www.irs.gov/pub/irs-drop/rp-24-40.pdf",
)
RP_2023_34 = Authority(
    "Rev. Proc. 2023-34 (2024 inflation adjustments)",
    "https://www.irs.gov/pub/irs-drop/rp-23-34.pdf",
)
OBBBA = Authority(
    "Pub. L. 119-21 (One Big Beautiful Bill Act, 4 July 2025)",
    "https://www.congress.gov/bill/119th-congress/house-bill/1/text",
    kind="Public Law",
)
IRS_OBBBA_DEDUCTIONS = Authority(
    "IRS, Working Families Tax Cuts: deductions for working Americans and seniors",
    "https://www.irs.gov/newsroom/one-big-beautiful-bill-act-tax-deductions-for-working-americans-and-seniors",
    kind="Agency",
)
SCH_1A_2025 = Authority(
    "2025 Schedule 1-A (Form 1040), Additional Deductions",
    "https://www.irs.gov/pub/irs-pdf/f1040s1a.pdf",
    kind="Form Instruction",
)
SCH_1_2025 = Authority(
    "2025 Schedule 1 (Form 1040), Additional Income and Adjustments to Income",
    "https://www.irs.gov/pub/irs-pdf/f1040s1.pdf",
    kind="Form Instruction",
)
SCH_2_2025 = Authority(
    "2025 Schedule 2 (Form 1040), Additional Taxes",
    "https://www.irs.gov/pub/irs-pdf/f1040s2.pdf",
    kind="Form Instruction",
)
SCH_A_2025 = Authority(
    "2025 Instructions for Schedule A (Form 1040), line 5e",
    "https://www.irs.gov/instructions/i1040sca",
    kind="Form Instruction",
)
I1040_2025 = Authority(
    "2025 Instructions for Form 1040",
    "https://www.irs.gov/instructions/i1040gi",
    kind="Form Instruction",
)
SSA_WAGE_BASE = Authority(
    "Social Security Administration, Contribution and Benefit Base",
    "https://www.ssa.gov/oact/cola/cbb.html",
    kind="Agency",
)


def irc(section: str) -> Authority:
    """Cite a Code section on Cornell LII, which is stable and free to read."""
    anchor = section.lstrip("§").replace("(", "#").split("#")[0].strip()
    return Authority(
        f"IRC §{section.lstrip('§')}",
        f"https://www.law.cornell.edu/uscode/text/26/{anchor}",
        kind="IRC",
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Constant:
    """One statutory figure and the authority behind it.

    ``verified`` is the honest flag: True only where the value was read out of
    the cited document rather than recalled. An unverified constant still
    computes — refusing to produce a return because one phase-out rate could not
    be confirmed helps nobody — but it is reported, so the figure that rests on
    it can be checked before anyone signs.
    """

    value: Decimal
    authority: Authority
    #: The Code section that imposes the treatment, e.g. "63(c)(2)".
    imposed_by: str = ""
    verified: bool = True
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": str(self.value),
            "imposed_by": f"IRC §{self.imposed_by}" if self.imposed_by else "",
            "authority": self.authority.to_dict(),
            "verified": self.verified,
            "note": self.note,
        }


def C(
    value: str | int | Decimal,
    authority: Authority,
    imposed_by: str = "",
    *,
    verified: bool = True,
    note: str = "",
) -> Constant:
    return Constant(D(str(value)), authority, imposed_by, verified, note)


@dataclass(frozen=True, slots=True)
class YearConstants:
    """Every statutory figure for one tax year."""

    year: int
    #: Ordinary rate brackets: {status: ((rate, lower, upper|None), ...)}
    ordinary_brackets: dict[str, tuple[tuple[Decimal, Decimal, Decimal | None], ...]]
    bracket_authority: Authority
    #: Preferential rate brackets: {status: ((rate, upper|None), ...)}
    capital_gain_brackets: dict[str, tuple[tuple[Decimal, Decimal | None], ...]]
    capital_gain_authority: Authority
    standard_deduction: dict[str, Constant]
    additional_standard_deduction: dict[str, Constant]
    dependent_standard_deduction_floor: Constant
    dependent_standard_deduction_earned_addition: Constant
    scalars: dict[str, Constant] = field(default_factory=dict)
    #: EITC table: {qualifying children (0-3): {field: Constant}}
    eitc: dict[int, dict[str, Constant]] = field(default_factory=dict)

    def unverified(self) -> list[tuple[str, Constant]]:
        """Every constant whose authority pairing was not confirmed."""
        out: list[tuple[str, Constant]] = []
        for name, const in self.scalars.items():
            if not const.verified:
                out.append((name, const))
        for name, const in self.standard_deduction.items():
            if not const.verified:
                out.append((f"standard_deduction.{name}", const))
        for n, table in self.eitc.items():
            for name, const in table.items():
                if not const.verified:
                    out.append((f"eitc.{n}.{name}", const))
        return out


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
#
# The figures themselves live in ``app/tax_constants/<year>.json`` so a filing
# season's numbers can be reviewed, diffed and corrected without reading Python.
# They are loaded here into the dataclasses above, which is what keeps the
# authority pairing and the ``verified`` flag typed rather than leaving every
# consumer to re-parse dicts.
#
# Adding a tax year: copy the most recent JSON file, update each value, and
# point every constant at the revenue procedure for that year. A figure you
# could not confirm against the cited document carries ``"verify": true`` — the
# engine still computes with it and reports it rather than filing on it
# silently.


_CONSTANT_DIR = Path(__file__).resolve().parents[2] / "tax_constants"


def _authority_table(doc: dict[str, Any]) -> dict[str, Authority]:
    return {
        name: Authority(a["citation"], a["url"], a["kind"])
        for name, a in doc["authorities"].items()
    }


def _authority(ref: Any, table: dict[str, Authority]) -> Authority:
    """A named reference into the file's table, or an inlined authority.

    ``irc()`` builds one-off authorities that have no module-level name, so the
    exporter writes those inline. Both spellings have to load.
    """
    if isinstance(ref, str):
        return table[ref]
    return Authority(ref["citation"], ref["url"], ref["kind"])


def _constant(raw: dict[str, Any], table: dict[str, Authority]) -> Constant:
    return Constant(
        D(raw["value"]),
        _authority(raw["authority"], table),
        raw.get("imposed_by", ""),
        # "verify": true in the file is the inverse of verified in the object:
        # the file states what still needs checking, which is the shorter list.
        not raw.get("verify", False),
        raw.get("note", ""),
    )


def load_year(year: int) -> YearConstants:
    """Read one year's figures from ``tax_constants/<year>.json``."""
    path = _CONSTANT_DIR / f"{year}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"No constants file for tax year {year} at {path}. "
            "Every supported year needs one; the engine will not guess."
        )
    doc = json.loads(path.read_text(encoding="utf-8"))
    table = _authority_table(doc)

    def const(raw: dict[str, Any]) -> Constant:
        return _constant(raw, table)

    return YearConstants(
        year=doc["year"],
        ordinary_brackets={
            status: tuple(
                (D(rate), D(lower), None if upper is None else D(upper))
                for rate, lower, upper in rows
            )
            for status, rows in doc["ordinary_brackets"].items()
        },
        bracket_authority=_authority(doc["bracket_authority"], table),
        capital_gain_brackets={
            status: tuple(
                (D(rate), None if upper is None else D(upper)) for rate, upper in rows
            )
            for status, rows in doc["capital_gain_brackets"].items()
        },
        capital_gain_authority=_authority(doc["capital_gain_authority"], table),
        standard_deduction={
            k: const(v) for k, v in doc["standard_deduction"].items()
        },
        additional_standard_deduction={
            k: const(v) for k, v in doc["additional_standard_deduction"].items()
        },
        dependent_standard_deduction_floor=const(
            doc["dependent_standard_deduction_floor"]
        ),
        dependent_standard_deduction_earned_addition=const(
            doc["dependent_standard_deduction_earned_addition"]
        ),
        scalars={k: const(v) for k, v in doc["scalars"].items()},
        eitc={
            int(n): {k: const(v) for k, v in table_.items()}
            for n, table_ in doc["eitc"].items()
        },
    )


def available_years() -> tuple[int, ...]:
    """Every year with a constants file, ascending."""
    return tuple(
        sorted(int(p.stem) for p in _CONSTANT_DIR.glob("[0-9][0-9][0-9][0-9].json"))
    )


YEARS: dict[int, YearConstants] = {y: load_year(y) for y in available_years()}


def constants_for(year: int) -> YearConstants:
    if year not in YEARS:
        raise KeyError(
            f"No constants are loaded for tax year {year}. "
            f"Supported: {', '.join(map(str, sorted(YEARS)))}."
        )
    return YEARS[year]


def scalar(year: int, name: str) -> Decimal:
    """One statutory value. Raises rather than defaulting to zero."""
    table = constants_for(year).scalars
    if name not in table:
        raise KeyError(f"No constant named {name!r} for tax year {year}.")
    return table[name].value


def authority_for(year: int, name: str) -> Constant | None:
    """The full provenance record, for the workpaper's Authority column."""
    return constants_for(year).scalars.get(name)


def unverified_constants(year: int) -> list[tuple[str, Constant]]:
    """Constants the engine will use but whose authority was not confirmed."""
    return constants_for(year).unverified()
