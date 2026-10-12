"""An export must carry the engine's figures, and only under names it declares.

Two failure modes matter here and neither is arithmetic — the return is already
computed and checked by the time an adapter sees it.

The first is drift. ``CLAUDE.md`` trap 17 is the same shape as this package: the
extraction prompt named one field, recomputation consumed seven, and the two
ends of that contract disagreed silently for the life of the bug. An export map
is a contract with two ends too, so the vocabulary is derived from the engine
and a map that strays from it must fail to load rather than write a blank into
a return someone files.

The second is leakage. These files carry rehydrated identity, so they belong to
the output zone: they must never survive with a mask token in them, and they
must never be mistaken for something the egress guard would let outbound.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import fields as dataclass_fields
from decimal import Decimal as D

import pytest

from app.core.errors import ExportMapError
from app.services.export.adapter import (
    MAP_SCHEMA_VERSION,
    ExportMap,
    load_maps,
    render_exports,
)
from app.services.export.fact_set import (
    EXPORT_FACT_KEYS,
    FACT_SET_VERSION,
    MONEY_FACT_KEYS,
    build_fact_set,
    vocabulary,
)
from app.services.form_1040_filler import TaxpayerIdentity
from app.services.tax_engine.form_1040 import (
    AdjustmentInputs,
    CapitalGainInputs,
    DeductionInputs,
    Form1040Calculator,
    IncomeInputs,
    PaymentInputs,
    TaxpayerProfile,
)
from app.services.tax_engine.tax_tables import FilingStatusTax

# Synthetic throughout: reserved-range SSN, example.com-style surrogate values.
# No figure here comes from a client file.
SYNTHETIC_IDENTITY = TaxpayerIdentity(
    first_name="ALEX",
    last_name="SAMPLE",
    ssn="666-01-0001",
    street_address="100 TEST WAY",
    city="SPRINGFIELD",
    state="IL",
    zip_code="62701",
)


def _engine_inputs():
    return {
        "profile": TaxpayerProfile(
            tax_year=2025,
            filing_status=FilingStatusTax.MARRIED_JOINT,
            age_65_or_older=1,
        ),
        "income": IncomeInputs(
            wages=D(82000),
            taxable_interest=D(214),
            ordinary_dividends=D(5012),
            qualified_dividends=D(1793),
        ),
        "capital_gains": CapitalGainInputs(long_term_gain=D(7345)),
        "adjustments": AdjustmentInputs(ira_deduction=D(3000)),
        "deductions": DeductionInputs(mortgage_interest=D(9200)),
        "payments": PaymentInputs(federal_withheld=D(11500)),
    }


def _fact_set(identity: TaxpayerIdentity | None = SYNTHETIC_IDENTITY):
    inputs = _engine_inputs()
    computed = Form1040Calculator().compute(**inputs)
    return build_fact_set(
        computed_return=computed, engine_inputs=inputs, identity=identity
    )


def _map(**overrides) -> ExportMap:
    data = {
        "schema_version": MAP_SCHEMA_VERSION,
        "fact_set_version": FACT_SET_VERSION,
        "target": "test",
        "label": "Test Target",
        "format": "csv",
        "extension": "csv",
        "money": "exact",
        "fields": {"input.wages": "WAGES", "result.total_tax": "TOTAL_TAX"},
    }
    data.update(overrides)
    return ExportMap(data, source="test.json")


# --------------------------------------------------------------- vocabulary


def test_vocabulary_covers_every_engine_money_input():
    """The engine's inputs are exportable by construction, not by transcription.

    Adding a field to ``form_1040`` must make it exportable in the same step.
    The orchestrator derives its own list the same way; if these two ever
    disagree, a figure the engine consumes cannot be handed downstream.
    """
    from app.services.workflow_orchestrator import (
        ENGINE_MONEY_FIELDS,
        SHAREHOLDER_BASIS_FIELDS,
    )

    engine_inputs = set(ENGINE_MONEY_FIELDS) - set(SHAREHOLDER_BASIS_FIELDS)
    exported = {k.split(".", 1)[1] for k in EXPORT_FACT_KEYS if k.startswith("input.")}
    assert engine_inputs == exported


def test_vocabulary_covers_every_identity_field():
    identity = {f"identity.{e.name}" for e in dataclass_fields(TaxpayerIdentity)}
    assert identity <= EXPORT_FACT_KEYS


def test_vocabulary_has_no_duplicates():
    assert len(vocabulary()) == len(set(vocabulary()))


# ----------------------------------------------------------------- fact set


def test_fact_set_carries_inputs_lines_and_results():
    facts = _fact_set()

    assert facts.values["input.wages"] == "82000"
    assert facts.values["identity.ssn"] == "666-01-0001"
    assert facts.values["profile.filing_status"] == "married_joint"
    assert facts.values["result.tax_year"] == "2025"
    # A computed line, not an input: proof the engine's own output is carried.
    # Compared as an amount, not a string — the engine's line values keep their
    # cents ("82000.00") and the map's money format decides how they are written.
    assert D(facts.values["line.1a"]) == D(82000)
    assert D(facts.values["result.adjusted_gross_income"]) < D(
        facts.values["result.total_income"]
    )


def test_fact_set_omits_identity_when_not_rehydrated():
    """The fact set is buildable without ever touching the vault.

    SECURITY: identity is supplied by the caller that has already rehydrated,
    so nothing in this package can reach for it on its own.
    """
    facts = _fact_set(identity=None)
    assert not [key for key in facts.values if key.startswith("identity.")]
    assert facts.values["input.wages"] == "82000"


def test_fact_set_money_is_string_never_float():
    facts = _fact_set()
    for key in facts.values:
        assert isinstance(facts.values[key], str)
    assert facts.values["input.wages"] == "82000"
    assert MONEY_FACT_KEYS & set(facts.values)


def test_fact_set_omits_facts_the_return_does_not_state():
    """Absent is not zero.

    A return with no rental income should not assert a rental figure of 0 into
    a vendor field — the downstream package may treat a stated zero as an
    answered question.
    """
    inputs = _engine_inputs()
    computed = Form1040Calculator().compute(**inputs)
    facts = build_fact_set(computed_return=computed, engine_inputs=None)
    assert "input.wages" not in facts.values
    assert facts.values["result.total_tax"]


# --------------------------------------------------------- map validation


def test_map_rejects_unknown_fact_key():
    with pytest.raises(ExportMapError, match="unknown fact key"):
        _map(fields={"input.wagez": "WAGES"})


def test_map_rejects_two_facts_on_one_field():
    """Silently losing one of them is the failure this prevents."""
    with pytest.raises(ExportMapError, match="mapped from both"):
        _map(fields={"input.wages": "AMOUNT", "result.total_tax": "AMOUNT"})


def test_map_rejects_stale_fact_set_version():
    with pytest.raises(ExportMapError, match="fact set version"):
        _map(fact_set_version=FACT_SET_VERSION + 1)


def test_map_rejects_unknown_schema_version():
    with pytest.raises(ExportMapError, match="schema version"):
        _map(schema_version=MAP_SCHEMA_VERSION + 1)


def test_map_rejects_unsupported_format():
    with pytest.raises(ExportMapError, match="unsupported format"):
        _map(format="xlsx")


def test_map_rejects_illegal_xml_element_name():
    with pytest.raises(ExportMapError, match="valid XML element name"):
        _map(format="xml", extension="xml", fields={"input.wages": "2 Wages"})


def test_map_without_fields_is_the_whole_vocabulary():
    export_map = _map(fields=None)
    assert set(export_map.fields) == set(vocabulary())


# ------------------------------------------------------------- rendering


def test_csv_render_writes_mapped_fields_only():
    rendered = _map().render(_fact_set())
    text = rendered.content.decode("utf-8")

    assert text.splitlines()[0] == "field,value"
    assert "WAGES,82000" in text
    assert "TOTAL_TAX," in text
    assert "input.wages" not in text  # our name, not theirs
    assert rendered.fields_written == ("WAGES", "TOTAL_TAX")


def test_json_render_is_parseable_and_carries_the_version():
    rendered = _map(format="json", extension="json").render(_fact_set())
    document = json.loads(rendered.content)

    assert document["fact_set_version"] == FACT_SET_VERSION
    assert document["tax_year"] == 2025
    assert document["fields"]["WAGES"] == "82000"


def test_xml_render_is_parseable():
    rendered = _map(
        format="xml", extension="xml", xml_root="Export", xml_record="Return"
    ).render(_fact_set())
    root = ET.fromstring(rendered.content)

    assert root.tag == "Export"
    assert root.find("./Return/WAGES").text == "82000"


def test_whole_dollars_rounds_without_separators_or_parentheses():
    """An import parser reads "11,222" and "(265)" as text, not as numbers."""
    inputs = _engine_inputs()
    inputs["income"] = IncomeInputs(wages=D("82000.49"))
    computed = Form1040Calculator().compute(**inputs)
    facts = build_fact_set(computed_return=computed, engine_inputs=inputs)

    rendered = _map(money="whole_dollars").render(facts)
    text = rendered.content.decode("utf-8")

    assert "WAGES,82000" in text
    assert "," not in text.split("WAGES,")[1].split("\r\n")[0]
    assert "(" not in text


def test_absent_facts_are_reported_not_written():
    export_map = _map(
        fields={"input.wages": "WAGES", "identity.spouse_ssn": "SPOUSE_SSN"}
    )
    rendered = export_map.render(_fact_set())

    assert rendered.fields_written == ("WAGES",)
    assert rendered.facts_absent == ("identity.spouse_ssn",)
    assert b"SPOUSE_SSN" not in rendered.content


# ------------------------------------------------------------- the registry


def test_shipped_maps_all_load():
    """Every map in resources must be valid; a broken one ships nothing."""
    maps = load_maps()
    assert maps, "no export maps found"
    assert "generic" in {m.target for m in maps}


def test_generic_target_renders_the_whole_return():
    files = render_exports(_fact_set(), targets={"generic"})
    assert len(files) == 1

    text = files[0].content.decode("utf-8")
    assert files[0].filename.endswith("(2025).csv")
    assert "input.wages,82000" in text
    assert "identity.ssn,666-01-0001" in text


def test_a_broken_map_is_skipped_not_raised(tmp_path):
    """One bad vendor file must not cost the preparer the whole package."""
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    good = {
        "schema_version": MAP_SCHEMA_VERSION,
        "fact_set_version": FACT_SET_VERSION,
        "target": "good",
        "format": "csv",
        "extension": "csv",
        "fields": {"input.wages": "WAGES"},
    }
    (tmp_path / "good.json").write_text(json.dumps(good), encoding="utf-8")

    files = render_exports(_fact_set(), directory=tmp_path)
    assert [f.target for f in files] == ["good"]


# --------------------------------------------------------------- security


@pytest.mark.security
def test_export_holds_no_mask_tokens():
    """A surviving token means a lost vault entry; the package must not ship."""
    import re

    for rendered in render_exports(_fact_set()):
        assert not re.findall(r"[A-Z_]+_\d{3,}", rendered.content.decode("utf-8"))


@pytest.mark.security
def test_export_of_real_identity_would_be_blocked_by_the_egress_guard():
    """This artifact is output-zone by construction, and provably so.

    A finished export carries a rehydrated SSN. If one were ever handed to an
    outbound path the guard must stop it, which is the same thing as saying
    this file is not something any LLM call may serialize.

    The identity here deliberately sits OUTSIDE the reserved surrogate ranges.
    ``SYNTHETIC_IDENTITY`` uses SSN area 666, which the guard recognises
    structurally as one of our own surrogates (``CLAUDE.md`` trap 4) and
    correctly lets through — so it proves nothing about real client data.
    123-45-6789 is the standard dummy SSN, never issued, and it is what a
    rehydrated value looks like to the guard.
    """
    from app.services.llm_egress_guard import EgressGuard

    real_shaped = TaxpayerIdentity(
        first_name="ALEX", last_name="SAMPLE", ssn="123-45-6789"
    )
    rendered = render_exports(_fact_set(identity=real_shaped), targets={"generic"})[0]
    report = EgressGuard().scan(rendered.content.decode("utf-8"))

    assert not report.is_safe
    assert any(f.pii_type.value == "ssn" for f in report.blocking)


@pytest.mark.security
def test_export_package_has_no_outbound_capability():
    """No adapter may acquire a network client without this test noticing.

    Producing an import file is not the same as pushing one to a vendor API;
    the second is a new outbound path carrying full PII and a policy decision,
    not a refactor.
    """
    from pathlib import Path

    package = Path(__file__).resolve().parent.parent / "app" / "services" / "export"
    for source in package.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        for forbidden in ("import requests", "import httpx", "urllib.request"):
            assert forbidden not in text, f"{source.name} reaches the network"
