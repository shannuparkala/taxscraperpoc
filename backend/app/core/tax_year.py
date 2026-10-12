"""The default tax year, resolved against the years a product supports.

``Settings.default_tax_year`` is the one place the default is set. Each
product has its own list of years it holds rules for (depreciation 2021-2026,
the forms library and State Intelligence 2025-2026, the 1040 engine 2024-2025),
so the configured year is clamped to that list rather than offered where there
are no rules to answer it. Clamping is a fact the caller must be able to
report - a workpaper that falls back to an earlier year says so in a review
item - so ``resolve`` returns whether it happened.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class ResolvedYear:
    year: int
    #: The configured year, before clamping.
    configured: int

    @property
    def clamped(self) -> bool:
        return self.year != self.configured


def configured_default_year() -> int:
    return get_settings().default_tax_year


def resolve(supported: Iterable[int], configured: int | None = None) -> ResolvedYear:
    """The configured year if supported, else the latest supported year before
    it, else the earliest supported year after it."""
    wanted = configured_default_year() if configured is None else configured
    years = sorted(set(supported))
    if not years:
        raise ValueError("A product with no supported tax years has no default year.")
    if wanted in years:
        return ResolvedYear(wanted, wanted)
    earlier = [y for y in years if y < wanted]
    return ResolvedYear(earlier[-1] if earlier else years[0], wanted)


def resolve_default_year(supported: Iterable[int], configured: int | None = None) -> int:
    return resolve(supported, configured).year
