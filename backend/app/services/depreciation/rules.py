"""Loads the depreciation rule data and answers rule questions by year.

All figures live in ``app/tax_rules/depreciation/*.json``, never in code.
This module only reads them and looks things up. Every lookup that returns a
figure also returns a :class:`RuleRef`, so whatever the UI shows can be
traced to the entry - and the source - it came from.

A year outside ``supported_years`` raises :class:`UnsupportedYearError`
rather than borrowing the nearest year's figures: a 2027 Section 179 limit
that is really 2026's is a wrong number that looks right.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

RULES_DIR = Path(__file__).resolve().parents[2] / "tax_rules" / "depreciation"


class UnsupportedYearError(ValueError):
    """The year is outside the range the rule files cover."""


@dataclass(frozen=True, slots=True)
class RuleRef:
    """Where a value shown to the user came from."""

    key: str
    label: str
    source_citation: str
    source_url: str
    last_verified: str | None
    verified: bool
    verify_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "source_citation": self.source_citation,
            "source_url": self.source_url,
            "last_verified": self.last_verified,
            "verified": self.verified,
            "verify_note": self.verify_note,
        }


def _ref(key: str, label: str, entry: dict[str, Any]) -> RuleRef:
    return RuleRef(
        key=key,
        label=label,
        source_citation=entry.get("source_citation", ""),
        source_url=entry.get("source_url", ""),
        last_verified=entry.get("last_verified"),
        verified=bool(entry.get("verified")),
        verify_note=entry.get("verify_note", ""),
    )


@dataclass(frozen=True, slots=True)
class AssetClass:
    key: str
    label: str
    recovery_years: str | None
    allowed_recovery_years: tuple[str, ...]
    table_family: str
    section_179_eligible: bool
    bonus_eligible: bool
    listed: bool
    real_property: bool
    luxury_auto_caps: bool
    suv_cap: bool
    qpp: bool
    ads_years: str | None
    note: str
    ref: RuleRef


@dataclass(frozen=True, slots=True)
class Section179Limits:
    limit: Decimal
    phaseout_threshold: Decimal | None
    suv_cap: Decimal
    ref: RuleRef


@dataclass(frozen=True, slots=True)
class AutoCaps:
    first: Decimal
    second: Decimal
    third: Decimal
    succeeding: Decimal
    with_bonus: bool
    ref: RuleRef

    def for_year_index(self, index: int) -> Decimal:
        """Cap for the 1-based year of ownership."""
        return (self.first, self.second, self.third)[index - 1] if index <= 3 else self.succeeding


class DepreciationRules:
    """Read-only view over the four rule files."""

    def __init__(self, directory: Path = RULES_DIR) -> None:
        self.directory = directory
        self.federal = self._load("federal_rules.json")
        self.tables = self._load("macrs_tables.json")
        self.classes_data = self._load("asset_classes.json")
        self.states_data = self._load("state_conformity.json")
        self.supported_years: tuple[int, ...] = tuple(self.federal["supported_years"])
        self.classes: dict[str, AssetClass] = {
            key: AssetClass(
                key=key,
                label=value["label"],
                recovery_years=value.get("recovery_years"),
                allowed_recovery_years=tuple(value.get("allowed_recovery_years") or ()),
                table_family=value["table_family"],
                section_179_eligible=bool(value["section_179_eligible"]),
                bonus_eligible=bool(value["bonus_eligible"]),
                listed=bool(value.get("listed")),
                real_property=bool(value.get("real_property")),
                luxury_auto_caps=bool(value.get("luxury_auto_caps")),
                suv_cap=bool(value.get("suv_cap")),
                qpp=bool(value.get("qpp")),
                ads_years=value.get("ads_years"),
                note=value.get("note", ""),
                ref=_ref(f"class.{key}", value["label"], value),
            )
            for key, value in self.classes_data["classes"].items()
        }

    def _load(self, name: str) -> dict[str, Any]:
        return json.loads((self.directory / name).read_text(encoding="utf-8"))

    # --- Years ------------------------------------------------------------

    def require_year(self, year: int) -> None:
        if year not in self.supported_years:
            first, last = self.supported_years[0], self.supported_years[-1]
            raise UnsupportedYearError(
                f"Tax year {year} is not supported. The rule data covers {first}-{last}; "
                "figures for other years have not been verified, so none are guessed."
            )

    # --- Section 179 ------------------------------------------------------

    def section_179(self, year: int) -> Section179Limits:
        self.require_year(year)
        entry = self.federal["section_179"][str(year)]
        return Section179Limits(
            limit=Decimal(entry["limit"]),
            phaseout_threshold=Decimal(entry["phaseout_threshold"]),
            suv_cap=Decimal(entry["suv_cap"]),
            ref=_ref(f"section_179.{year}", f"Section 179 limits for {year}", entry),
        )

    def section_179_income_ref(self) -> RuleRef:
        return _ref("section_179_income_limit", "Section 179 business income limit",
                    self.federal["section_179_income_limit"])

    # --- Bonus ------------------------------------------------------------

    def bonus_rate(self, acquired: date, placed_in_service: date) -> tuple[Decimal, RuleRef, dict[str, Any]]:
        """The federal special allowance rate for one asset.

        Turns on the acquisition date (Jan. 19, 2025 is the line) and, for
        earlier acquisitions, on the placed-in-service year.
        """
        for rule in self.federal["bonus"]["rules"]:
            after = date.fromisoformat(rule["acquired_after"])
            before = date.fromisoformat(rule["acquired_before"]) if rule.get("acquired_before") else None
            if acquired > after and (before is None or acquired < before):
                ref = _ref(f"bonus.{rule['id']}", rule["label"], rule)
                if "rate" in rule:
                    return Decimal(rule["rate"]), ref, rule
                rates = rule["rate_by_placed_in_service_year"]
                year = str(placed_in_service.year)
                rate = rates.get(year)
                if rate is None:
                    last = max(int(y) for y in rates)
                    rate = rule["rate_after_last_year"] if placed_in_service.year > last else 0
                return Decimal(rate), ref, rule
        return Decimal(0), RuleRef("bonus.none", "Acquired before Sept. 28, 2017", "", "", None, True), {}

    def reduced_bonus_election(self) -> tuple[Decimal, tuple[int, ...]]:
        """The reduced-rate election (40% instead of 100%): its rate and the
        placed-in-service years it is available for, from the rule data."""
        for rule in self.federal["bonus"]["rules"]:
            election = rule.get("reduced_rate_election")
            if election:
                return Decimal(election["rate"]), tuple(int(y) for y in election["tax_years"])
        return Decimal(0), ()

    def pre_obbba_rate(self, placed_in_service: date) -> tuple[Decimal, RuleRef]:
        """The phase-down rate as if P.L. 119-21 had not been enacted.

        Used for a state that conforms to the Code as of a date before July 4,
        2025: its law still carries the TCJA schedule whatever the
        acquisition date.
        """
        rule = self.federal["bonus"]["rules"][0]
        rates = rule["rate_by_placed_in_service_year"]
        year = placed_in_service.year
        if str(year) in rates:
            rate = rates[str(year)]
        else:
            rate = rule["rate_after_last_year"] if year > max(int(y) for y in rates) else 100
        return Decimal(rate), _ref(f"bonus.{rule['id']}", rule["label"], rule)

    def bonus_eligibility_ref(self) -> RuleRef:
        return _ref("bonus.eligibility", "Special depreciation allowance eligibility",
                    self.federal["bonus"]["eligibility"])

    # --- 168(n) -----------------------------------------------------------

    def qpp(self) -> tuple[dict[str, Any], RuleRef]:
        entry = self.federal["qualified_production_property"]
        return entry, _ref("qpp", "Qualified production property (168(n))", entry)

    # --- 280F -------------------------------------------------------------

    def auto_caps(self, placed_in_service_year: int, with_bonus: bool) -> AutoCaps:
        self.require_year(placed_in_service_year)
        entry = self.federal["luxury_auto_caps"][str(placed_in_service_year)]
        values = entry["with_bonus" if with_bonus else "without_bonus"]
        table = "Table 1 (bonus applies)" if with_bonus else "Table 2 (no bonus)"
        first, second, third, succeeding = (Decimal(v) for v in values)
        return AutoCaps(
            first=first,
            second=second,
            third=third,
            succeeding=succeeding,
            with_bonus=with_bonus,
            ref=_ref(f"luxury_auto_caps.{placed_in_service_year}",
                     f"Section 280F limits, placed in service {placed_in_service_year}, {table}", entry),
        )

    def ref(self, key: str, label: str) -> RuleRef:
        return _ref(key, label, self.federal[key])

    # --- MACRS tables -----------------------------------------------------

    def table_ref(self, table_id: str) -> RuleRef:
        table = self.tables["tables"][table_id]
        return RuleRef(
            key=f"macrs.{table_id}",
            label=table["citation"],
            source_citation=table["citation"],
            source_url=self.tables["source_url"],
            last_verified=self.tables["last_verified"],
            verified=bool(self.tables["verified"]),
        )

    def rates(self, table_id: str, column: str) -> list[Decimal]:
        """Percentages (of 100) for one column of one table."""
        table = self.tables["tables"][table_id]
        values = (table.get("periods") or table["months"])[column]
        return [Decimal(v) for v in values]

    # --- Form 4562 --------------------------------------------------------

    def form_lines(self, year: int) -> tuple[dict[str, Any], RuleRef]:
        for layout in self.federal["form_4562_lines"]["layouts"]:
            if year in layout["years"]:
                return layout["lines"], _ref(f"form_4562.{year}", f"Form 4562 ({year}) line layout", layout)
        self.require_year(year)
        raise UnsupportedYearError(f"No Form 4562 layout recorded for {year}.")

    # --- States -----------------------------------------------------------

    @property
    def state_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self.states_data["states"]))

    def state(self, code: str) -> dict[str, Any] | None:
        return self.states_data["states"].get(code.upper())

    def state_entry(self, code: str, year: int) -> dict[str, Any] | None:
        state = self.state(code)
        if state is None:
            return None
        return state["years"].get(str(year))


@lru_cache(maxsize=1)
def get_rules() -> DepreciationRules:
    return DepreciationRules()
