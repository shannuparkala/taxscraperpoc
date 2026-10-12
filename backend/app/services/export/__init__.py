"""Export adapters: a computed return, rendered for another tax package.

Public surface is deliberately small — build a fact set, render the configured
targets. Everything vendor-specific lives in ``resources/export_maps``.
"""

from __future__ import annotations

from app.services.export.adapter import (
    ExportFile,
    ExportMap,
    load_maps,
    render_exports,
)
from app.services.export.fact_set import (
    EXPORT_FACT_KEYS,
    FACT_SET_VERSION,
    ReturnFactSet,
    build_fact_set,
    vocabulary,
)

__all__ = [
    "EXPORT_FACT_KEYS",
    "FACT_SET_VERSION",
    "ExportFile",
    "ExportMap",
    "ReturnFactSet",
    "build_fact_set",
    "load_maps",
    "render_exports",
    "vocabulary",
]
