"""The depreciation engine: inputs in, a full schedule out. Pure arithmetic.

No network, no clock, no randomness, no LLM. Every figure comes from
``rules.DepreciationRules`` (the JSON rule files); every rate is applied as
an exact ``Decimal``. The same input always produces the same output.

Order of operations, per placed-in-service year:

1. **Basis.** Cost, less land, less any clean-vehicle credit, times the
   business-use percentage. Rounded to whole dollars once, here (Form 4562
   is filed in whole dollars).
2. **Section 179** (Form 4562 Part I). Dollar limit reduced dollar for dollar
   above the phase-out threshold (lines 1-5); elected cost (line 8); prior
   carryover (line 10); business income limit (line 11); deduction (line
   12); carryforward (line 13). Basis is reduced by the amount *elected*,
   including any part that carries forward.
3. **Special allowance.** Section 168(k) bonus at the rate set by the
   acquisition and placed-in-service dates, on the basis left after 179; or
   the section 168(n) allowance for qualified production property.
4. **Convention.** Mid-quarter if more than 40% of the year's depreciable
   basis (after 179, before bonus, excluding buildings) was placed in service
   in Q4; half-year otherwise; mid-month for buildings. The user may instead
   select the convention per asset (``AssetInput.convention``); the selection
   is applied as given, and a warning says so whenever it differs from what
   the 40% test requires. Mid-month exists only for buildings and half-year /
   mid-quarter only for personal property - there are no Pub. 946 tables for
   the other combinations, so those are input errors.
5. **MACRS** on what is left, from the Pub. 946 percentage tables.
6. **Section 280F** limits for passenger automobiles.

Rounding rule (documented in the README): each year's deduction for each
asset is computed exactly and rounded half-up to whole dollars at the end of
that year's computation; the last year of the schedule takes whatever
difference rounding left, so every asset's schedule sums exactly to its
recoverable basis.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services.depreciation.rules import (
    AssetClass,
    DepreciationRules,
    RuleRef,
    Section179Limits,
    UnsupportedYearError,
)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
DOLLAR = Decimal(1)

DISCLAIMER = (
    "General information, not tax advice. Figures are computed from published IRS and state "
    "rules for the inputs you entered; your return may differ. Confirm with a tax professional "
    "before filing."
)

METHODS = ("macrs", "bonus", "section_179", "section_179_bonus")
METHOD_LABELS = {
    "macrs": "Standard MACRS (elect out of bonus, no Section 179)",
    "bonus": "Bonus depreciation, then MACRS",
    "section_179": "Section 179, then MACRS (elect out of bonus)",
    "section_179_bonus": "Section 179, then bonus, then MACRS",
}


class InputError(ValueError):
    """The request cannot be computed; ``errors`` says why, field by field."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


#: The start of the warning an election out of bonus adds (it covers a whole class).
ELECT_OUT_WARNING = "Election out of bonus depreciation applied"
#: Shown when Section 179 is elected with no business income entered.
NO_INCOME_LIMIT_WARNING = (
    "No taxable business income entered, so the Section 179 business income limit was not "
    "applied. Section 179 cannot create or increase a business loss."
)


def dollars(value: Decimal) -> Decimal:
    return value.quantize(DOLLAR, rounding=ROUND_HALF_UP)


# ===========================================================================
# Inputs
# ===========================================================================


@dataclass(frozen=True, slots=True)
class AssetInput:
    id: str
    description: str
    asset_class: str
    cost: Decimal
    placed_in_service: date
    acquired: date
    business_use_pct: Decimal = HUNDRED
    land_value: Decimal = ZERO
    recovery_years: str | None = None
    section_179_amount: Decimal | None = None
    elect_out_bonus: bool = False
    elect_reduced_bonus: bool = False
    clean_vehicle_credit: Decimal = ZERO
    suv_cap_exempt: bool = False
    qpp_elect: bool = False
    qpp_construction_began: date | None = None
    #: "HY" | "MQ" | "MM" to use that convention; None applies the law's
    #: test (40% Q4 test for personal property, mid-month for buildings).
    convention: str | None = None


#: Conventions a user may select, and their names.
CONVENTION_NAMES = {"HY": "half-year", "MQ": "mid-quarter", "MM": "mid-month"}


@dataclass(frozen=True, slots=True)
class CalculationInput:
    tax_year: int
    assets: tuple[AssetInput, ...]
    method: str = "section_179_bonus"
    state: str | None = None
    taxable_business_income: Decimal | None = None
    total_179_purchases: Decimal | None = None
    section_179_carryover: Decimal = ZERO
    federal_marginal_rate: Decimal | None = None
    state_marginal_rate: Decimal | None = None
    include_provisional_state: bool = False
    bonus_by_asset: bool = False


@dataclass(frozen=True, slots=True)
class Scenario:
    key: str
    use_179: bool
    use_bonus: bool

    @property
    def label(self) -> str:
        return METHOD_LABELS[self.key]


SCENARIOS = {
    "macrs": Scenario("macrs", use_179=False, use_bonus=False),
    "bonus": Scenario("bonus", use_179=False, use_bonus=True),
    "section_179": Scenario("section_179", use_179=True, use_bonus=False),
    "section_179_bonus": Scenario("section_179_bonus", use_179=True, use_bonus=True),
}


@dataclass(frozen=True, slots=True)
class Regime:
    """Jurisdiction parameters. The federal regime is the default instance.

    A state that decouples is a different regime over the same arithmetic,
    so the federal and state schedules can never disagree about anything but
    the rules that actually differ.
    """

    key: str = "federal"
    #: "federal" | "none" | "percent" | "pre_obbba"
    bonus_mode: str = "federal"
    bonus_pct: Decimal | None = None
    #: For "percent": the state rate applies only to property acquired after
    #: this date; earlier acquisitions follow the federal rate.
    bonus_applies_if_acquired_after: date | None = None
    section_179: Section179Limits | None = None
    allow_qpp: bool = True


FEDERAL = Regime()


# ===========================================================================
# Outputs
# ===========================================================================


@dataclass(slots=True)
class YearRow:
    year: int
    section_179: Decimal = ZERO
    bonus: Decimal = ZERO
    special: Decimal = ZERO  # 168(n)
    macrs: Decimal = ZERO
    # How ``macrs`` was produced - recorded, never recomputed, so the
    # calculation tape shows the engine's own steps.
    #: Table percentage applied this year (None after the recovery period).
    rate: Decimal | None = None
    #: The basis the rate was applied to, and the unrounded product.
    base: Decimal | None = None
    exact: Decimal | None = None
    #: Section 280F limit for the year, when one applies.
    cap: Decimal | None = None
    capped: bool = False
    #: Rounding residual settled in this year (last year of the schedule).
    rounding: Decimal = ZERO
    after_recovery: bool = False

    @property
    def total(self) -> Decimal:
        return self.section_179 + self.bonus + self.special + self.macrs

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "section_179": str(self.section_179),
            "bonus": str(self.bonus),
            "special": str(self.special),
            "macrs": str(self.macrs),
            "total": str(self.total),
        }


@dataclass(slots=True)
class AssetResult:
    id: str
    description: str
    asset_class: str
    class_label: str
    recovery_years: str
    system: str  # GDS | ADS
    method: str  # 200DB | 150DB | SL
    convention: str  # HY | MQ | MM
    table_ref: RuleRef
    table_column: str
    cost: Decimal
    land_value: Decimal
    clean_vehicle_credit: Decimal
    business_use_pct: Decimal
    business_basis: Decimal
    section_179_elected: Decimal
    section_179_allowed: Decimal
    section_179_carryforward: Decimal
    bonus_rate: Decimal
    bonus: Decimal
    special_allowance: Decimal
    macrs_basis: Decimal
    rows: list[YearRow]
    placed_in_service: date
    listed: bool
    notes: list[str] = field(default_factory=list)
    #: True when the user selected the convention rather than the law's test.
    convention_selected: bool = False

    @property
    def total(self) -> Decimal:
        return sum((row.total for row in self.rows), ZERO)

    @property
    def recoverable(self) -> Decimal:
        return self.business_basis - self.section_179_carryforward

    def row_for(self, year: int) -> YearRow | None:
        return next((row for row in self.rows if row.year == year), None)


@dataclass(slots=True)
class Section179Summary:
    year: int
    limit: Decimal
    total_cost: Decimal
    threshold: Decimal | None
    reduction: Decimal
    dollar_limit: Decimal
    elected: Decimal
    carryover_in: Decimal
    income_limit: Decimal | None
    deduction: Decimal
    carryforward: Decimal
    ref: RuleRef
    #: Part of ``deduction`` that is prior-year carryover (belongs to no asset here).
    carryover_used: Decimal = ZERO

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "line_1_limit": str(self.limit),
            "line_2_total_cost": str(self.total_cost),
            "line_3_threshold": None if self.threshold is None else str(self.threshold),
            "line_4_reduction": str(self.reduction),
            "line_5_dollar_limit": str(self.dollar_limit),
            "line_9_tentative": str(min(self.elected, self.dollar_limit)),
            "line_10_carryover": str(self.carryover_in),
            "line_11_income_limit": None if self.income_limit is None else str(self.income_limit),
            "line_12_deduction": str(self.deduction),
            "line_13_carryforward": str(self.carryforward),
            "source": self.ref.to_dict(),
        }


@dataclass(slots=True)
class Computation:
    """One jurisdiction under one scenario."""

    regime: Regime
    scenario: Scenario
    assets: list[AssetResult]
    section_179: dict[int, Section179Summary]
    conventions: dict[int, str]
    q4_share: dict[int, Decimal]
    warnings: list[str]
    refs: dict[str, RuleRef]

    def years(self) -> list[int]:
        return sorted({row.year for asset in self.assets for row in asset.rows})

    def schedule(self) -> list[YearRow]:
        by_year: dict[int, YearRow] = {}
        for asset in self.assets:
            for row in asset.rows:
                total = by_year.setdefault(row.year, YearRow(row.year))
                total.section_179 += row.section_179
                total.bonus += row.bonus
                total.special += row.special
                total.macrs += row.macrs
        return [by_year[year] for year in sorted(by_year)]

    def deduction_in(self, year: int) -> Decimal:
        """Everything deductible in ``year``, including prior Section 179 carryover used."""
        scheduled = sum((row.total for row in self.schedule() if row.year == year), ZERO)
        summary = self.section_179.get(year)
        return scheduled + (summary.carryover_used if summary else ZERO)

    @property
    def basis(self) -> Decimal:
        return sum((asset.business_basis for asset in self.assets), ZERO)

    @property
    def carryforward(self) -> Decimal:
        return sum((s.carryforward for s in self.section_179.values()), ZERO)

    @property
    def total(self) -> Decimal:
        return sum((asset.total for asset in self.assets), ZERO)


# ===========================================================================
# Validation
# ===========================================================================


def validate(request: CalculationInput, rules: DepreciationRules, *, max_assets: int = 100) -> None:
    """Raise ``UnsupportedYearError`` or ``InputError``; return on success.

    ``max_assets`` is 100 for the interactive form; an imported additions
    list (``addition_report``) allows more, because every asset of the year
    shares one Section 179 limit and one mid-quarter test.
    """
    rules.require_year(request.tax_year)
    errors: list[str] = []
    if request.method not in (*METHODS, "compare"):
        errors.append(f"Unknown method '{request.method}'.")
    if not request.assets:
        errors.append("Enter at least one asset.")
    if len(request.assets) > max_assets:
        errors.append(f"At most {max_assets} assets per calculation.")
    if request.state is not None and rules.state(request.state) is None:
        errors.append(f"'{request.state}' is not a supported state code (50 states and DC).")
    if request.section_179_carryover < 0:
        errors.append("Section 179 carryover cannot be negative.")
    if request.total_179_purchases is not None and request.total_179_purchases < 0:
        errors.append("Total Section 179 purchases cannot be negative.")
    for label, rate in (("Federal", request.federal_marginal_rate), ("State", request.state_marginal_rate)):
        if rate is not None and not (ZERO <= rate <= HUNDRED):
            errors.append(f"{label} marginal rate must be between 0 and 100.")

    seen: set[str] = set()
    for position, asset in enumerate(request.assets, start=1):
        name = f"Asset {position}" + (f" ({asset.description})" if asset.description else "")
        if asset.id in seen:
            errors.append(f"{name}: duplicate asset id.")
        seen.add(asset.id)
        cls = rules.classes.get(asset.asset_class)
        if cls is None:
            errors.append(f"{name}: unknown asset class '{asset.asset_class}'.")
            continue
        if cls.recovery_years is None and asset.recovery_years not in cls.allowed_recovery_years:
            errors.append(f"{name}: choose a recovery period ({', '.join(cls.allowed_recovery_years)} years).")
        if asset.cost <= 0:
            errors.append(f"{name}: cost basis must be greater than zero.")
        if asset.land_value < 0:
            errors.append(f"{name}: land value cannot be negative.")
        if asset.land_value > asset.cost:
            errors.append(f"{name}: land value cannot exceed the cost basis.")
        if asset.land_value > 0 and not (cls.real_property or cls.key == "land_improvements"):
            errors.append(f"{name}: land value applies only to buildings and land improvements.")
        if asset.clean_vehicle_credit < 0:
            errors.append(f"{name}: clean vehicle credit cannot be negative.")
        if asset.clean_vehicle_credit > 0 and cls.key not in ("passenger_vehicle", "heavy_vehicle"):
            errors.append(f"{name}: a clean vehicle credit applies only to vehicles.")
        if asset.clean_vehicle_credit > asset.cost - asset.land_value:
            errors.append(f"{name}: the clean vehicle credit cannot exceed the cost basis.")
        if not (ZERO < asset.business_use_pct <= HUNDRED):
            errors.append(f"{name}: business use must be more than 0% and at most 100%.")
        if asset.acquired > asset.placed_in_service:
            errors.append(f"{name}: the acquisition date cannot be after the placed-in-service date.")
        if asset.placed_in_service.year > request.tax_year:
            errors.append(
                f"{name}: placed in service in {asset.placed_in_service.year}, after tax year "
                f"{request.tax_year}. An asset is depreciated from the year it is placed in service."
            )
        if asset.placed_in_service.year not in rules.supported_years:
            errors.append(
                f"{name}: placed in service in {asset.placed_in_service.year}; rules are verified only "
                f"for {rules.supported_years[0]}-{rules.supported_years[-1]}."
            )
        if asset.section_179_amount is not None and asset.section_179_amount < 0:
            errors.append(f"{name}: the Section 179 amount cannot be negative.")
        if asset.qpp_elect and not cls.qpp:
            errors.append(f"{name}: the section 168(n) election applies only to qualified production property.")
        if asset.qpp_elect and asset.qpp_construction_began is None:
            errors.append(f"{name}: enter the date construction began to elect section 168(n).")
        if asset.elect_reduced_bonus:
            reduced_rate, reduced_years = rules.reduced_bonus_election()
            if asset.placed_in_service.year not in reduced_years:
                years = ", ".join(map(str, reduced_years)) or "no year"
                errors.append(
                    f"{name}: the {reduced_rate}% election is available only for property placed in "
                    f"service in {years}."
                )
        if asset.convention is not None:
            if asset.convention not in CONVENTION_NAMES:
                errors.append(f"{name}: convention must be half-year, mid-quarter or mid-month.")
            elif cls.real_property and asset.convention != "MM":
                errors.append(
                    f"{name}: buildings use the mid-month convention; there are no half-year or "
                    "mid-quarter tables for residential rental or nonresidential real property."
                )
            elif not cls.real_property and asset.convention == "MM":
                errors.append(
                    f"{name}: the mid-month convention applies only to residential rental and "
                    "nonresidential real property; choose half-year or mid-quarter."
                )
    if errors:
        raise InputError(errors)


# ===========================================================================
# Engine
# ===========================================================================


@dataclass(slots=True)
class _Work:
    """One asset while it is being computed."""

    position: int
    asset: AssetInput
    cls: AssetClass
    period: str
    ads: bool
    business_basis: Decimal
    s179_max: Decimal = ZERO
    s179_requested: Decimal = ZERO
    s179_elected: Decimal = ZERO
    s179_allowed: Decimal = ZERO
    s179_carryforward: Decimal = ZERO
    bonus_rate: Decimal = ZERO
    bonus: Decimal = ZERO
    special: Decimal = ZERO
    notes: list[str] = field(default_factory=list)

    @property
    def pis(self) -> date:
        return self.asset.placed_in_service

    @property
    def quarter(self) -> int:
        return (self.pis.month - 1) // 3 + 1


def compute(
    request: CalculationInput,
    rules: DepreciationRules,
    scenario: Scenario,
    regime_for_year: Any = None,
) -> Computation:
    """Run one scenario under one regime. ``validate`` must have passed.

    ``regime_for_year`` maps a placed-in-service year to a :class:`Regime`
    (states change rules by year); ``None`` means federal throughout.
    ``bonus_by_asset`` is reserved for additions-report planning; that caller
    must flag mixed class selections before the figures are used for filing.
    """
    regime_lookup = regime_for_year or (lambda _year: FEDERAL)
    warnings: list[str] = []
    refs: dict[str, RuleRef] = {}
    results: list[AssetResult] = []
    summaries: dict[int, Section179Summary] = {}
    conventions: dict[int, str] = {}
    q4_share: dict[int, Decimal] = {}

    by_year: dict[int, list[_Work]] = defaultdict(list)
    for position, asset in enumerate(request.assets):
        by_year[asset.placed_in_service.year].append(_prepare(position, asset, rules, refs))

    for year in sorted(by_year):
        group = by_year[year]
        regime: Regime = regime_lookup(year)
        if not request.bonus_by_asset:
            _elect_out_by_class(group, scenario, warnings)
        summaries[year] = _section_179(year, group, request, rules, regime, scenario, warnings, refs)
        for work in group:
            _special_allowance(work, rules, regime, scenario, warnings, refs)
        convention, share = _convention(group, rules, refs)
        conventions[year], q4_share[year] = convention, share
        personal = [w for w in group if not w.cls.real_property]
        automatic = [w for w in personal if w.asset.convention is None]
        if convention == "MQ" and automatic:
            warnings.append(
                f"Mid-quarter convention applied to {year} personal property because "
                f"{_pct(share)} of its depreciable basis was placed in service in the fourth quarter "
                "(more than 40%)."
            )
        _selected_convention_warnings(year, personal, convention, share, warnings)
        for work in group:
            results.append(_schedule(work, convention, rules, refs, warnings))

    results.sort(key=lambda r: next(i for i, a in enumerate(request.assets) if a.id == r.id))
    return Computation(
        regime=regime_lookup(request.tax_year),
        scenario=scenario,
        assets=results,
        section_179=summaries,
        conventions=conventions,
        q4_share=q4_share,
        warnings=warnings,
        refs=refs,
    )


def _prepare(position: int, asset: AssetInput, rules: DepreciationRules, refs: dict[str, RuleRef]) -> _Work:
    cls = rules.classes[asset.asset_class]
    refs[cls.ref.key] = cls.ref
    period = cls.recovery_years or str(asset.recovery_years)
    depreciable = asset.cost - asset.land_value - asset.clean_vehicle_credit
    business = dollars(depreciable * asset.business_use_pct / HUNDRED)
    ads = cls.listed and asset.business_use_pct <= 50
    work = _Work(position, asset, cls, period, ads, business)
    if asset.land_value > 0:
        work.notes.append(f"Land of ${asset.land_value:,.0f} excluded: land is never depreciable.")
    if asset.clean_vehicle_credit > 0:
        refs["clean_vehicle_credit_basis"] = rules.ref("clean_vehicle_credit_basis", "Clean vehicle credit basis reduction")
        work.notes.append(f"Basis reduced by the ${asset.clean_vehicle_credit:,.0f} clean vehicle credit.")
    if asset.business_use_pct < HUNDRED:
        work.notes.append(f"Only the {asset.business_use_pct.normalize():f}% business-use portion is depreciable.")
    if ads:
        refs["listed_property"] = rules.ref("listed_property", "Listed property at 50% or less business use")
        work.notes.append(
            "Listed property used 50% or less for business: ADS straight line is required, and neither "
            "Section 179 nor bonus depreciation is allowed."
        )
    return work


def _elect_out_by_class(group: list[_Work], scenario: Scenario, warnings: list[str]) -> None:
    """An election out of bonus covers every asset in the class that year."""
    if not scenario.use_bonus:
        return
    out_classes = {w.period for w in group if w.asset.elect_out_bonus and w.cls.bonus_eligible}
    for work in group:
        if work.period in out_classes and not work.asset.elect_out_bonus and work.cls.bonus_eligible:
            work.notes.append(
                f"Bonus not taken: the election out applies to all {work.period}-year property "
                f"placed in service in {work.pis.year}."
            )
    for period in sorted(out_classes):
        warnings.append(
            f"{ELECT_OUT_WARNING} to all {period}-year property placed in "
            f"service in {group[0].pis.year} (the election is made by class)."
        )
    for work in group:
        if work.period in out_classes:
            work.asset = replace(work.asset, elect_out_bonus=True)


def _section_179(
    year: int,
    group: list[_Work],
    request: CalculationInput,
    rules: DepreciationRules,
    regime: Regime,
    scenario: Scenario,
    warnings: list[str],
    refs: dict[str, RuleRef],
) -> Section179Summary:
    limits = regime.section_179 or rules.section_179(year)
    refs[limits.ref.key] = limits.ref
    federal_suv = rules.section_179(year).suv_cap
    eligible = [w for w in group if w.cls.section_179_eligible and not w.ads]

    total_cost = sum((w.business_basis for w in eligible), ZERO)
    if year == request.tax_year and request.total_179_purchases is not None:
        total_cost = max(total_cost, dollars(request.total_179_purchases))
    threshold = limits.phaseout_threshold
    reduction = max(ZERO, total_cost - threshold) if threshold is not None else ZERO
    dollar_limit = max(ZERO, limits.limit - reduction)

    if scenario.use_179:
        for work in eligible:
            cap = work.business_basis
            if work.cls.suv_cap and not work.asset.suv_cap_exempt:
                suv = min(federal_suv, limits.limit)
                if cap > suv:
                    work.notes.append(f"Section 179 limited to the ${suv:,.0f} SUV cap for {year}.")
                cap = min(cap, suv)
            if work.cls.luxury_auto_caps:
                first = rules.auto_caps(year, with_bonus=False).first * work.asset.business_use_pct / HUNDRED
                cap = min(cap, dollars(first))
            work.s179_max = cap
            requested = work.asset.section_179_amount
            work.s179_requested = cap if requested is None else min(dollars(requested), cap)
            if requested is not None and requested > cap:
                work.notes.append(f"Section 179 amount reduced to the ${cap:,.0f} allowed for this asset.")

        remaining = dollar_limit
        # Explicit elections first. Then the property where 179 adds the
        # most this year: the lowest bonus rate first - 179 on an asset that
        # takes 100% bonus anyway adds nothing, while on a 40% asset it adds
        # the other 60% - and within a rate, longest-lived first, since a
        # dollar expensed now is worth most on property that would otherwise
        # take longest to recover.
        order = sorted(
            eligible,
            key=lambda w: (
                w.asset.section_179_amount is None,
                _bonus_rate(w, rules, regime)[0] if _takes_bonus(w, scenario) else ZERO,
                -Decimal(w.period),
                w.position,
            ),
        )
        for work in order:
            work.s179_elected = min(work.s179_requested, remaining)
            remaining -= work.s179_elected
        if sum((w.s179_requested for w in eligible), ZERO) > dollar_limit:
            warnings.append(
                f"Section 179 for {year} limited to the ${dollar_limit:,.0f} dollar limit "
                f"(${limits.limit:,.0f} reduced by ${reduction:,.0f} of purchases above the threshold)."
            )
    elected = sum((w.s179_elected for w in eligible), ZERO)

    carry_in = dollars(request.section_179_carryover) if year == request.tax_year else ZERO
    income_limit: Decimal | None = None
    if year == request.tax_year and request.taxable_business_income is not None:
        income_limit = min(max(ZERO, dollars(request.taxable_business_income)), dollar_limit)
        refs["section_179_income_limit"] = rules.section_179_income_ref()
    elif elected and year == request.tax_year:
        warnings.append(NO_INCOME_LIMIT_WARNING)
    elif elected:
        warnings.append(
            f"Section 179 for assets placed in service in {year} assumes the {year} business income "
            "limit did not apply."
        )

    ceiling = dollar_limit if income_limit is None else income_limit
    allowed_current = min(elected, ceiling)
    allowed_carry = min(carry_in, ceiling - allowed_current)
    deduction = allowed_current + allowed_carry
    carryforward = (elected - allowed_current) + (carry_in - allowed_carry)

    # Share this year's allowed amount across the elections, pro rata, in
    # whole dollars, with the remainder on the last one.
    electing = [w for w in eligible if w.s179_elected > 0]
    shared = ZERO
    for index, work in enumerate(electing):
        if index == len(electing) - 1:
            work.s179_allowed = allowed_current - shared
        else:
            work.s179_allowed = dollars(allowed_current * work.s179_elected / elected)
            shared += work.s179_allowed
        work.s179_carryforward = work.s179_elected - work.s179_allowed
    if carryforward > 0:
        warnings.append(
            f"Section 179 limited by taxable business income; ${carryforward:,.0f} carried forward "
            f"to {year + 1} (Form 4562 line 13)."
        )

    return Section179Summary(
        year=year,
        limit=limits.limit,
        total_cost=total_cost,
        threshold=threshold,
        reduction=reduction,
        dollar_limit=dollar_limit,
        elected=elected,
        carryover_in=carry_in,
        income_limit=income_limit,
        deduction=deduction,
        carryforward=carryforward,
        ref=limits.ref,
        carryover_used=allowed_carry,
    )


def _special_allowance(
    work: _Work,
    rules: DepreciationRules,
    regime: Regime,
    scenario: Scenario,
    warnings: list[str],
    refs: dict[str, RuleRef],
) -> None:
    remaining = work.business_basis - work.s179_elected
    asset = work.asset

    if work.cls.qpp and asset.qpp_elect:
        entry, ref = rules.qpp()
        refs[ref.key] = ref
        began = asset.qpp_construction_began
        ok_start = began is not None and (
            date.fromisoformat(entry["construction_begins_after"]) < began
            < date.fromisoformat(entry["construction_begins_before"])
        )
        ok_pis = (
            date.fromisoformat(entry["placed_in_service_after"]) < work.pis
            < date.fromisoformat(entry["placed_in_service_before"])
        )
        if not (ok_start and ok_pis):
            work.notes.append(
                "Section 168(n) not allowed: construction must begin after Jan. 19, 2025 and before 2029, "
                "and the property must be placed in service after July 4, 2025 and before 2031."
            )
        elif not regime.allow_qpp:
            work.notes.append("This state disallows the section 168(n) allowance; the building is depreciated over 39 years.")
        else:
            work.special = dollars(remaining * Decimal(entry["rate"]) / HUNDRED)
            work.notes.append(
                "Section 168(n) 100% allowance taken. It is recaptured as ordinary income if the "
                "production use ends within 10 years."
            )
        return

    if not _takes_bonus(work, scenario):
        return

    rate, ref, federal_rate, reduced = _bonus_rate(work, rules, regime)
    refs[ref.key] = ref
    refs["bonus.eligibility"] = rules.bonus_eligibility_ref()
    if reduced is not None:
        work.notes.append(f"Elected the {reduced}% rate instead of {federal_rate}% for {work.pis.year}.")

    work.bonus_rate = rate
    work.bonus = dollars(remaining * rate / HUNDRED)


def _takes_bonus(work: _Work, scenario: Scenario) -> bool:
    """Whether the asset is in line for Sec. 168(k) bonus (not 168(n), not ADS, not elected out)."""
    asset = work.asset
    if work.cls.qpp and asset.qpp_elect:
        return False
    return scenario.use_bonus and work.cls.bonus_eligible and not work.ads and not asset.elect_out_bonus


def _bonus_rate(work: _Work, rules: DepreciationRules, regime: Regime) -> tuple[Decimal, RuleRef, Decimal, Decimal | None]:
    """(rate, rule ref, federal rate, reduced rate elected or None) for one asset under ``regime``."""
    asset = work.asset
    federal_rate, ref, rule = rules.bonus_rate(asset.acquired, work.pis)
    rate = federal_rate
    reduced: Decimal | None = None
    election = (rule.get("reduced_rate_election") or {}) if rule else {}
    if asset.elect_reduced_bonus and work.pis.year in election.get("tax_years", []):
        rate = reduced = Decimal(election["rate"])

    if regime.bonus_mode == "none":
        rate = ZERO
    elif regime.bonus_mode == "percent" and regime.bonus_pct is not None:
        cutoff = regime.bonus_applies_if_acquired_after
        if cutoff is None or asset.acquired > cutoff:
            rate = min(rate, regime.bonus_pct)
    elif regime.bonus_mode == "pre_obbba":
        rate = min(rate, rules.pre_obbba_rate(work.pis)[0])
    return rate, ref, federal_rate, reduced


def _convention(group: list[_Work], rules: DepreciationRules, refs: dict[str, RuleRef]) -> tuple[str, Decimal]:
    personal = [w for w in group if not w.cls.real_property]
    total = sum((w.business_basis - w.s179_elected for w in personal), ZERO)
    q4 = sum((w.business_basis - w.s179_elected for w in personal if w.quarter == 4), ZERO)
    if total <= 0:
        return "HY", ZERO
    share = q4 / total
    threshold = Decimal(rules.federal["mid_quarter_test"]["threshold_pct"]) / HUNDRED
    refs["mid_quarter_test"] = rules.ref("mid_quarter_test", "Mid-quarter convention (40% test)")
    return ("MQ" if share > threshold else "HY"), share


def _selected_convention_warnings(
    year: int, personal: list[_Work], required: str, share: Decimal, warnings: list[str]
) -> None:
    """Say plainly when a selected convention departs from the 40% test.

    The selection is honoured - the user asked for it - but mid-quarter is
    not elective: Sec. 168(d)(3) requires it when the test is met, and it
    applies to all personal property placed in service that year.
    """
    for work in personal:
        chosen = work.asset.convention
        if chosen is None or chosen == required:
            continue
        name = work.asset.description or f"Asset {work.position + 1}"
        warnings.append(
            f"{name}: {CONVENTION_NAMES[chosen]} convention used as selected. The 40% test for "
            f"{year} ({_pct(share)} of personal-property basis placed in service in the fourth "
            f"quarter) calls for {CONVENTION_NAMES[required]}. Confirm before filing."
        )
    effective = {work.asset.convention or required for work in personal}
    if len(effective) > 1:
        warnings.append(
            f"{year} personal property uses more than one convention. The half-year or mid-quarter "
            "convention normally applies to all personal property placed in service in the same year."
        )


def _table(work: _Work, convention: str) -> tuple[str, str, str, str, str]:
    """(table id, column, system, method, convention) for one asset.

    ``convention`` is the year's convention from the 40% test; an asset's own
    selection, when it has one, takes its place.
    """
    convention = work.asset.convention or convention
    family = work.cls.table_family
    if family in ("residential_mm", "nonresidential_mm"):
        return family, str(work.pis.month), "GDS", "SL", "MM"
    if work.ads:
        period = work.cls.ads_years or work.period
        prefix, system, method = "sl", "ADS", "SL"
    elif family == "sl":
        period, prefix, system, method = work.period, "sl", "GDS", "SL"
    else:
        period, prefix, system = work.period, "gds", "GDS"
        method = "150DB" if period in ("15", "20") else "200DB"
    if convention == "MQ":
        return f"{prefix}_mq{work.quarter}", period, system, method, "MQ"
    return f"{prefix}_hy", period, system, method, "HY"


def _schedule(
    work: _Work,
    convention: str,
    rules: DepreciationRules,
    refs: dict[str, RuleRef],
    warnings: list[str],
) -> AssetResult:
    table_id, column, system, method, conv = _table(work, convention)
    table_ref = rules.table_ref(table_id)
    refs[table_ref.key] = table_ref
    rates = rules.rates(table_id, column)
    macrs_basis = work.business_basis - work.s179_elected - work.bonus - work.special
    recoverable = work.business_basis - work.s179_carryforward
    start = work.pis.year

    exact: list[Decimal] = [macrs_basis * rate / HUNDRED for rate in rates]
    rows = [YearRow(start + i, rate=rate, base=macrs_basis, exact=value) for i, (rate, value) in enumerate(zip(rates, exact))]
    rows[0].section_179 = work.s179_allowed
    rows[0].bonus = work.bonus
    rows[0].special = work.special

    if work.cls.luxury_auto_caps:
        rows = _luxury_auto(work, rows, rates, exact, rules, refs, recoverable)
    else:
        for row, value in zip(rows, exact):
            row.macrs = dollars(value)
        _plug(rows, recoverable)

    return AssetResult(
        id=work.asset.id,
        description=work.asset.description,
        asset_class=work.cls.key,
        class_label=work.cls.label,
        recovery_years=work.cls.ads_years if work.ads and work.cls.ads_years else work.period,
        system=system,
        method=method,
        convention=conv,
        table_ref=table_ref,
        table_column=column,
        cost=work.asset.cost,
        land_value=work.asset.land_value,
        clean_vehicle_credit=work.asset.clean_vehicle_credit,
        business_use_pct=work.asset.business_use_pct,
        business_basis=work.business_basis,
        section_179_elected=work.s179_elected,
        section_179_allowed=work.s179_allowed,
        section_179_carryforward=work.s179_carryforward,
        bonus_rate=work.bonus_rate,
        bonus=work.bonus,
        special_allowance=work.special,
        macrs_basis=macrs_basis,
        rows=rows,
        placed_in_service=work.pis,
        listed=work.cls.listed,
        notes=work.notes,
        convention_selected=work.asset.convention is not None,
    )


def _plug(rows: list[YearRow], recoverable: Decimal) -> None:
    """Put the rounding residual in the last year with MACRS depreciation."""
    residual = recoverable - sum((row.total for row in rows), ZERO)
    if residual == 0:
        return
    for row in reversed(rows):
        if row.macrs != 0 or row is rows[0]:
            row.macrs += residual
            row.rounding += residual
            return


def _luxury_auto(
    work: _Work,
    rows: list[YearRow],
    rates: list[Decimal],
    exact: list[Decimal],
    rules: DepreciationRules,
    refs: dict[str, RuleRef],
    recoverable: Decimal,
) -> list[YearRow]:
    """Apply the section 280F limits, then recover the rest after year 6."""
    caps = rules.auto_caps(work.pis.year, with_bonus=work.bonus > 0)
    refs[caps.ref.key] = caps.ref
    use = work.asset.business_use_pct / HUNDRED

    def cap(index: int) -> Decimal:
        return dollars(caps.for_year_index(index) * use)

    first_cap = cap(1)
    for index, row in enumerate(rows, start=1):
        row.cap = cap(index)
    first_uncapped = work.s179_allowed + work.bonus + exact[0]
    safe_harbor = work.bonus_rate == HUNDRED and first_uncapped > first_cap
    if first_uncapped > first_cap:
        # Allocate the cap in the order the deductions are taken.
        room = first_cap
        rows[0].section_179 = min(work.s179_allowed, room)
        room -= rows[0].section_179
        rows[0].bonus = min(work.bonus, room)
        room -= rows[0].bonus
        rows[0].macrs = dollars(min(exact[0], room))
        rows[0].capped = True
        work.notes.append(
            f"First-year deduction limited to the ${first_cap:,.0f} section 280F cap "
            f"({'with' if caps.with_bonus else 'without'} bonus, placed in service {work.pis.year})."
        )
    else:
        rows[0].macrs = dollars(exact[0])

    if safe_harbor:
        refs["luxury_auto_100pct_safe_harbor"] = rules.ref(
            "luxury_auto_100pct_safe_harbor", "Rev. Proc. 2019-13 safe harbor for 100% bonus autos"
        )
        remaining_basis = work.business_basis - work.s179_elected - rows[0].total
        later = [remaining_basis * rate / HUNDRED for rate in rates[1:]]
        for row, value in zip(rows[1:], later):
            row.base, row.exact = remaining_basis, value
        work.notes.append(
            "Years 2 onward use the Rev. Proc. 2019-13 safe harbor: table percentages applied to the "
            "basis left after the first-year cap."
        )
    else:
        later = exact[1:]
    capped = first_uncapped > first_cap
    for index, value in enumerate(later, start=2):
        rows[index - 1].macrs = dollars(min(value, cap(index)))
        rows[index - 1].capped = value > cap(index)
        capped = capped or value > cap(index)

    recovered = sum((row.total for row in rows), ZERO)
    if recovered > recoverable or not capped:
        # No limit bit, so any difference is rounding: settle it in the
        # last year rather than inventing a one-dollar tail year.
        _plug(rows, recoverable)
        return rows
    remaining = recoverable - recovered
    succeeding = cap(4)
    year = rows[-1].year
    while remaining > 0 and succeeding > 0:
        year += 1
        amount = min(remaining, succeeding)
        rows.append(YearRow(year, macrs=amount, cap=succeeding, capped=amount == succeeding, after_recovery=True))
        remaining -= amount
    if len(rows) > len(rates):
        work.notes.append(
            f"Basis not recovered by the end of the recovery period is deducted at up to "
            f"${succeeding:,.0f} a year until fully recovered."
        )
    return rows


def _pct(share: Decimal) -> str:
    return f"{(share * HUNDRED).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def ensure_supported(year: int, rules: DepreciationRules) -> None:
    rules.require_year(year)


__all__ = [
    "DISCLAIMER",
    "FEDERAL",
    "METHODS",
    "METHOD_LABELS",
    "SCENARIOS",
    "AssetInput",
    "CalculationInput",
    "Computation",
    "InputError",
    "Regime",
    "Scenario",
    "UnsupportedYearError",
    "compute",
    "dollars",
    "validate",
]
