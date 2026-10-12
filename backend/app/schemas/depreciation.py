"""Request models for the depreciation calculator.

Collected deliberately: an asset description, amounts and dates. No name,
SSN, EIN, address or other identifier is asked for anywhere. ``state`` is
validated here against the calculator's allow-list (50 states and DC) and
anything else is a 422 - never mapped to a neighbour or to federal.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.depreciation.addition_report import AdditionAsset
from app.services.depreciation.engine import AssetInput, CalculationInput

_MONEY_MAX = Decimal(100000000000)


class DepreciationAssetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=120)
    asset_class: str = Field(min_length=1, max_length=40)
    cost: Decimal = Field(gt=0, le=_MONEY_MAX)
    placed_in_service: date
    acquired: date | None = None
    business_use_pct: Decimal = Field(default=Decimal(100), gt=0, le=100)
    land_value: Decimal = Field(default=Decimal(0), ge=0, le=_MONEY_MAX)
    recovery_years: str | None = Field(default=None, max_length=4)
    section_179_amount: Decimal | None = Field(default=None, ge=0, le=_MONEY_MAX)
    elect_out_bonus: bool = False
    elect_reduced_bonus: bool = False
    clean_vehicle_credit: Decimal = Field(default=Decimal(0), ge=0, le=_MONEY_MAX)
    suv_cap_exempt: bool = False
    qpp_elect: bool = False
    qpp_construction_began: date | None = None
    #: "HY" | "MQ" | "MM"; omitted or null applies the law's test.
    convention: str | None = Field(default=None, max_length=4)

    def to_engine(self) -> AssetInput:
        return AssetInput(
            id=self.id,
            description=self.description.strip(),
            asset_class=self.asset_class,
            cost=self.cost,
            placed_in_service=self.placed_in_service,
            acquired=self.acquired or self.placed_in_service,
            business_use_pct=self.business_use_pct,
            land_value=self.land_value,
            recovery_years=self.recovery_years,
            section_179_amount=self.section_179_amount,
            elect_out_bonus=self.elect_out_bonus,
            elect_reduced_bonus=self.elect_reduced_bonus,
            clean_vehicle_credit=self.clean_vehicle_credit,
            suv_cap_exempt=self.suv_cap_exempt,
            qpp_elect=self.qpp_elect,
            qpp_construction_began=self.qpp_construction_began,
            convention=self.convention or None,
        )


class DepreciationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(ge=1900, le=2200)
    state: str | None = Field(default=None, max_length=4)
    method: str = Field(default="section_179_bonus", max_length=24)
    assets: list[DepreciationAssetIn] = Field(min_length=1, max_length=100)
    taxable_business_income: Decimal | None = Field(default=None, ge=-_MONEY_MAX, le=_MONEY_MAX)
    total_179_purchases: Decimal | None = Field(default=None, ge=0, le=_MONEY_MAX)
    section_179_carryover: Decimal = Field(default=Decimal(0), ge=0, le=_MONEY_MAX)
    federal_marginal_rate: Decimal | None = Field(default=None, ge=0, le=100)
    state_marginal_rate: Decimal | None = Field(default=None, ge=0, le=100)
    include_provisional_state: bool = False

    @field_validator("state")
    @classmethod
    def _known_state(cls, value: str | None) -> str | None:
        return _state_code(value)

    def to_engine(self) -> CalculationInput:
        return CalculationInput(
            tax_year=self.tax_year,
            assets=tuple(a.to_engine() for a in self.assets),
            method=self.method,
            state=self.state,
            taxable_business_income=self.taxable_business_income,
            total_179_purchases=self.total_179_purchases,
            section_179_carryover=self.section_179_carryover,
            federal_marginal_rate=self.federal_marginal_rate,
            state_marginal_rate=self.state_marginal_rate,
            include_provisional_state=self.include_provisional_state,
        )


class AdditionAssetIn(BaseModel):
    """One row of the current-year additions report, its life already chosen."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=300)
    acquired: date
    cost: Decimal = Field(gt=0, le=_MONEY_MAX)
    asset_class: str = Field(min_length=1, max_length=40)
    recovery_years: str | None = Field(default=None, max_length=4)
    elect_179: bool = True
    #: Bonus is claimed unless elected out; an election out covers the
    #: asset's whole recovery class for the year (IRC 168(k)(7)).
    elect_bonus: bool = True
    suv_cap_exempt: bool = False


class AdditionReportRequest(BaseModel):
    """The additions report: recomputed from these inputs on every request."""

    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(ge=1900, le=2200)
    state: str | None = Field(default=None, max_length=4)
    assets: list[AdditionAssetIn] = Field(min_length=1, max_length=500)

    @field_validator("state")
    @classmethod
    def _known_state(cls, value: str | None) -> str | None:
        return _state_code(value)

    def to_report_assets(self) -> list[AdditionAsset]:
        return [
            AdditionAsset(
                asset_id=a.asset_id.strip(),
                description=a.description.strip(),
                acquired=a.acquired,
                cost=a.cost,
                asset_class=a.asset_class,
                recovery_years=a.recovery_years or None,
                elect_179=a.elect_179,
                elect_bonus=a.elect_bonus,
                suv_cap_exempt=a.suv_cap_exempt,
            )
            for a in self.assets
        ]


class LifeAssetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(default="", max_length=300)
    life_in_file: str | None = Field(default=None, max_length=8)


class LifeRequest(BaseModel):
    """Lives to decide again for a new tax year or jurisdiction."""

    model_config = ConfigDict(extra="forbid")

    tax_year: int = Field(ge=1900, le=2200)
    state: str | None = Field(default=None, max_length=4)
    business_activity: str = Field(default="", max_length=120)
    assets: list[LifeAssetIn] = Field(min_length=1, max_length=500)

    @field_validator("state")
    @classmethod
    def _known_state(cls, value: str | None) -> str | None:
        return _state_code(value)


def _state_code(value: str | None) -> str | None:
    from app.services.depreciation.rules import get_rules

    if value is None or not value.strip():
        return None
    code = value.strip().upper()
    if code not in get_rules().state_codes:
        raise ValueError("state must be the two-letter code of one of the 50 states or DC")
    return code
