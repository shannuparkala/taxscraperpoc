"""The canonical fact set every export adapter consumes.

An export is a serialization problem, not a tax problem. By the time this runs
the return is already computed, checked and rehydrated; all that remains is to
write the same figures out in whatever shape a downstream tax package wants to
read. So the vocabulary is fixed here, once, and each vendor is a map file over
it — never a second traversal of ``Return1040`` with its own opinions.

SECURITY: the fact set is built AFTER rehydration and therefore carries real
taxpayer identity — name, SSN, address. It is an output-zone structure. Nothing
in this package opens a socket, and nothing here may be handed to
``gemini_service`` or any other outbound path.

Five namespaces, flat and dotted:

===========  ===========================================================
``identity`` who the taxpayer is (``identity.ssn``)
``profile``  the non-monetary facts that drove the computation
``input``    what the engine was given (``input.wages``)
``line``     what the engine put on a numbered 1040 line (``line.1a``)
``result``   the engine's own summary totals (``result.total_tax``)
===========  ===========================================================

Every namespace is derived from a dataclass or map the rest of the application
already owns, rather than transcribed. Trap 17 in ``CLAUDE.md`` is what that
guards against: the extraction prompt named one field, recomputation consumed
seven, and ``federal_withheld`` was in neither, so no return could produce a
refund. An export map is the same contract with the same two ends, so it is
validated against a vocabulary that cannot drift from the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from decimal import Decimal
from enum import Enum
from typing import Any

from app.core.logging import get_logger
from app.services.form_1040_filler import LINE_TO_FIELD, TaxpayerIdentity
from app.services.tax_engine.form_1040 import (
    AdditionalDeductionInputs,
    AdjustmentInputs,
    CapitalGainInputs,
    DeductionInputs,
    IncomeInputs,
    PaymentInputs,
    Return1040,
    TaxpayerProfile,
)

logger = get_logger(__name__)

#: Bumped whenever a key changes meaning or leaves the vocabulary. A map
#: declares the version it was written against, so a stale map fails to load
#: rather than quietly writing the wrong figure into a vendor field.
FACT_SET_VERSION = 1

IDENTITY = "identity"
PROFILE = "profile"
INPUT = "input"
LINE = "line"
RESULT = "result"

#: The engine's input dataclasses, in the order the calculator takes them.
_ENGINE_INPUT_SOURCES = (
    IncomeInputs,
    CapitalGainInputs,
    AdjustmentInputs,
    DeductionInputs,
    AdditionalDeductionInputs,
    PaymentInputs,
)

#: Slot in ``engine_inputs`` -> the dataclass it holds, for the ``input``
#: namespace. ``profile`` is handled separately: it is not monetary.
_ENGINE_INPUT_SLOTS = (
    "income",
    "capital_gains",
    "adjustments",
    "deductions",
    "additional_deductions",
    "payments",
)


def _money_field_names(source: type) -> list[str]:
    """The Decimal-typed fields of one dataclass.

    ``from __future__ import annotations`` renders annotations as strings, so
    the type is matched textually — the same test ``workflow_orchestrator``
    applies when it derives ``ENGINE_MONEY_FIELDS``.
    """
    return [
        entry.name
        for entry in dataclass_fields(source)
        if "Decimal" in str(entry.type)
    ]


def _identity_keys() -> tuple[str, ...]:
    return tuple(f"{IDENTITY}.{e.name}" for e in dataclass_fields(TaxpayerIdentity))


def _profile_keys() -> tuple[str, ...]:
    return tuple(f"{PROFILE}.{e.name}" for e in dataclass_fields(TaxpayerProfile))


def _input_keys() -> tuple[str, ...]:
    names: list[str] = []
    for source in _ENGINE_INPUT_SOURCES:
        names += _money_field_names(source)
    return tuple(f"{INPUT}.{name}" for name in dict.fromkeys(names))


#: Non-monetary summary facts. Everything else in ``Return1040`` an export
#: could want is a Decimal and is picked up automatically.
_RESULT_SCALARS = ("tax_year", "filing_status", "deduction_method")


def _result_keys() -> tuple[str, ...]:
    money = _money_field_names(Return1040)
    return tuple(f"{RESULT}.{name}" for name in (*_RESULT_SCALARS, *money))


def _line_keys() -> tuple[str, ...]:
    """Every numbered 1040 line the application can place on the form.

    Deliberately the filler's own map rather than a fresh list: a line we
    cannot render is not a line we report, so the two stay in step. A return
    that computes a line outside this set still carries it in the fact set —
    it just cannot be referenced from a map until it is on the form.
    """
    return tuple(f"{LINE}.{number}" for number in LINE_TO_FIELD)


#: Every key a map may reference. Frozen at import; see the module docstring.
EXPORT_FACT_KEYS: frozenset[str] = frozenset(
    (
        *_identity_keys(),
        *_profile_keys(),
        *_input_keys(),
        *_result_keys(),
        *_line_keys(),
    )
)

#: The subset carrying money, so an adapter can apply a vendor's number format
#: without having to guess from the value.
MONEY_FACT_KEYS: frozenset[str] = frozenset(
    (
        *_input_keys(),
        *(f"{RESULT}.{name}" for name in _money_field_names(Return1040)),
        *_line_keys(),
    )
)


def vocabulary() -> tuple[str, ...]:
    """The full key list in a stable, readable order."""
    return (
        *_identity_keys(),
        *_profile_keys(),
        *_input_keys(),
        *_result_keys(),
        *_line_keys(),
    )


def _scalar(value: Any) -> str | None:
    """Render one fact. ``None`` means this return does not state it."""
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return str(value)
    text = str(value).strip()
    return text or None


@dataclass(frozen=True, slots=True)
class ReturnFactSet:
    """One computed return, flattened to the export vocabulary.

    SECURITY: contains rehydrated identity. Output zone only.
    """

    version: int
    tax_year: int
    values: dict[str, str]

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    @property
    def money_keys(self) -> frozenset[str]:
        return MONEY_FACT_KEYS

    def unknown_keys(self) -> tuple[str, ...]:
        """Keys present in the data but outside the declared vocabulary.

        Non-empty means the engine computed a line the form map does not
        carry. Not an error — the figure is real and worth exporting — but it
        cannot be referenced from a map, so it is worth surfacing.
        """
        return tuple(sorted(set(self.values) - EXPORT_FACT_KEYS))


def build_fact_set(
    *,
    computed_return: Return1040,
    engine_inputs: dict[str, Any] | None = None,
    identity: TaxpayerIdentity | None = None,
) -> ReturnFactSet:
    """Flatten a computed return into the export vocabulary.

    ``engine_inputs`` carries the dataclasses the calculator was given. Absent,
    the ``input.*`` and ``profile.*`` namespaces are simply empty and the export
    still ships what the engine computed — the same degradation
    ``_build_schedules`` accepts when the inputs were not retained.

    ``identity`` is supplied only by a caller that has already rehydrated. It
    is optional so that the fact set can be built and tested without ever
    touching the vault.
    """
    values: dict[str, str] = {}

    def put(key: str, raw: Any) -> None:
        rendered = _scalar(raw)
        if rendered is not None:
            values[key] = rendered

    if identity is not None:
        for entry in dataclass_fields(identity):
            put(f"{IDENTITY}.{entry.name}", getattr(identity, entry.name))

    inputs = engine_inputs or {}

    profile = inputs.get("profile")
    if profile is not None:
        for entry in dataclass_fields(profile):
            put(f"{PROFILE}.{entry.name}", getattr(profile, entry.name))

    # KNOWN GAP: every field of an engine input dataclass defaults to ZERO, so
    # a field extraction never found is indistinguishable here from one it read
    # as zero, and both export as "0". Harmless in a report a human reads, but
    # a vendor import may treat a stated zero as an answered question and
    # overwrite a figure already keyed into the return. The distinction exists
    # upstream — `_reported_money_fields` knows which fields extraction actually
    # supplied — and closing this means threading that set down to here. Do it
    # before wiring a target that writes into an existing return.
    for slot in _ENGINE_INPUT_SLOTS:
        source = inputs.get(slot)
        if source is None:
            continue
        for name in _money_field_names(type(source)):
            put(f"{INPUT}.{name}", getattr(source, name))

    for line in computed_return.lines:
        put(f"{LINE}.{line.number}", line.amount)

    put(f"{RESULT}.tax_year", computed_return.tax_year)
    put(f"{RESULT}.filing_status", computed_return.filing_status)
    put(f"{RESULT}.deduction_method", computed_return.deduction_method)
    for name in _money_field_names(Return1040):
        put(f"{RESULT}.{name}", getattr(computed_return, name))

    fact_set = ReturnFactSet(
        version=FACT_SET_VERSION,
        tax_year=computed_return.tax_year,
        values=values,
    )
    extra = fact_set.unknown_keys()
    if extra:
        logger.info(
            "Fact set carries %d key(s) outside the map vocabulary: %s",
            len(extra),
            ", ".join(extra),
        )
    return fact_set
