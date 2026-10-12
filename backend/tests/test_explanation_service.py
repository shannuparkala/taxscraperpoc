"""The explanation must stay tied to the arithmetic it describes.

The risk this suite exists for is drift: the engine changes a line, the
explanation keeps describing the old one, and the result is a confident,
readable, wrong account of someone's return. Two invariants prevent that —
every emitted line has a spec, and every checkable line's operands re-add to the
engine's own figure.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services.explanation_service import (
    SPECS,
    ExplanationContext,
    ExplanationService,
    FlowSection,
    Provenance,
    ValidationStatus,
)
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
from app.tax_knowledge.rule_citations import RULES, rules_for_year


def _cs2_context() -> ExplanationContext:
    """The prepared sample return: single, 66, investment income only.

    Using a real reconciled return rather than invented figures means a
    regression shows up as a disagreement with a document a preparer signed.
    """
    profile = TaxpayerProfile(
        tax_year=2025, filing_status=FilingStatusTax.SINGLE, age_65_or_older=1
    )
    income = IncomeInputs(
        taxable_interest=D(214),
        qualified_dividends=D(1793),
        ordinary_dividends=D(5012),
        social_security=D(27648),
        other_gains=D(5469),
        rental_income=D(161),
    )
    capital_gains = CapitalGainInputs(
        short_term_gain=D(-894),
        short_term_loss_carryover=D(4511),
        long_term_gain=D(7345),
        capital_gain_distributions=D(4698),
    )
    payments = PaymentInputs(
        prior_year_overpayment_applied=D(725),
        apply_overpayment_to_next_year=D(725),
    )
    adjustments = AdjustmentInputs()
    deductions = DeductionInputs()

    result = Form1040Calculator().compute(
        profile=profile,
        income=income,
        adjustments=adjustments,
        deductions=deductions,
        payments=payments,
        capital_gains=capital_gains,
    )
    return ExplanationContext(
        result=result,
        profile=profile,
        income=income,
        adjustments=adjustments,
        deductions=deductions,
        payments=payments,
        capital_gains=capital_gains,
        field_provenance={
            "taxable_interest": [{"document_type": "form_1099_int", "amount": "214"}],
            "ordinary_dividends": [{"document_type": "form_1099_div", "amount": "5012"}],
            "social_security": [{"document_type": "form_ssa_1099", "amount": "27648"}],
            "other_gains": [{"document_type": "form_4797", "amount": "5469"}],
            "rental_income": [{"document_type": "schedule_k1", "amount": "161"}],
        },
        confidence_scores={"taxable_interest": 0.98, "ordinary_dividends": 0.97},
    )


@pytest.fixture(name="explanation")
def _explanation():
    return ExplanationService().build(_cs2_context())


def test_every_emitted_line_is_explained(explanation):
    """No line may reach the reviewer without an account of where it came from."""
    unexplained = [
        line.line for line in explanation.lines if not line.formula and not line.narrative
    ]
    assert unexplained == []

    missing_spec = [line.line for line in explanation.lines if line.line not in SPECS]
    assert missing_spec == [], (
        f"Lines {missing_spec} are emitted by the engine but have no LineSpec. "
        "Add one to SPECS rather than letting the line appear unexplained."
    )


def test_checkable_lines_re_add_to_the_engine_amount(explanation):
    """The declared operands must reproduce the engine's own figure."""
    failures = [
        (line.line, str(line.amount))
        for line in explanation.lines
        if SPECS.get(line.line) and SPECS[line.line].checkable and not line.arithmetic_checked
    ]
    assert failures == [], (
        f"Explanation arithmetic disagrees with the engine on {failures}. "
        "Either the operands are wrong or the line is no longer a simple sum."
    )


def test_cs2_headline_figures(explanation):
    summary = explanation.summary
    assert summary["adjusted_gross_income"] == "20653.00"
    assert summary["taxable_income"] == "0"
    assert summary["total_tax"] == "0"
    assert summary["applied_to_next_year"] == "725.00"
    assert summary["refund"] == "0.00"


def test_social_security_line_explains_the_test_not_just_the_number(explanation):
    line = next(l for l in explanation.lines if l.line == "6b")
    assert line.amount == D("3159.00")
    assert line.rule.id == "social_security_taxable"
    assert line.rule.irc_section == "IRC §86"
    # The narrative has to state the 85% ceiling — it is the single fact that
    # most reassures a taxpayer reading this line.
    assert "85%" in line.narrative
    # And it must name the source document field, not the deposited amount.
    benefits = next(o for o in line.operands if "benefits received" in o.label)
    assert "box 5" in benefits.detail


def test_prior_year_inputs_are_labelled_as_such(explanation):
    """A carryover cannot be presented as if a document reported it."""
    line = next(l for l in explanation.lines if l.line == "D-7")
    carryover = next(
        o for o in line.operands if "carried in from last year" in o.label
    )
    assert carryover.provenance is Provenance.PRIOR_YEAR
    assert carryover.amount == D(4511)


def test_election_is_labelled_as_a_choice(explanation):
    line = next(l for l in explanation.lines if l.line == "36")
    assert line.provenance is Provenance.ELECTION
    assert any(o.provenance is Provenance.ELECTION for o in line.operands)
    assert "carryovers" not in line.narrative


def test_traceable_lines_name_their_source_document(explanation):
    interest = next(l for l in explanation.lines if l.line == "2b")
    assert interest.provenance is Provenance.SOURCE_DOCUMENT
    assert interest.status is ValidationStatus.VERIFIED
    assert "form_1099_int" in interest.source_documents


def test_lines_without_provenance_are_not_claimed_as_verified():
    """Absent provenance must never read as 'verified from source documents'."""
    ctx = _cs2_context()
    ctx.field_provenance = {}
    explanation = ExplanationService().build(ctx)
    verified = [
        line.line
        for line in explanation.lines
        if line.status is ValidationStatus.VERIFIED
    ]
    assert verified == []


def test_low_confidence_forces_review():
    ctx = _cs2_context()
    ctx.confidence_scores = {"taxable_interest": 0.40}
    explanation = ExplanationService().build(ctx)
    interest = next(l for l in explanation.lines if l.line == "2b")
    assert interest.status is ValidationStatus.REVIEW
    assert any("Line 2b" in note for note in explanation.assumptions)


def test_sections_cover_the_full_flow(explanation):
    present = {line.section for line in explanation.lines}
    for required in (
        FlowSection.INCOME,
        FlowSection.AGI,
        FlowSection.DEDUCTIONS,
        FlowSection.TAXABLE_INCOME,
        FlowSection.TAX,
        FlowSection.TOTAL_TAX,
        FlowSection.PAYMENTS,
        FlowSection.OUTCOME,
    ):
        assert required in present, f"{required.value} has no explained lines"


def test_assumptions_disclose_the_election_and_the_carryover(explanation):
    joined = " ".join(explanation.assumptions)
    assert "election" in joined.lower()
    assert "carryover" in joined.lower()
    assert "65 or" in joined


def test_unverified_citations_are_surfaced(explanation):
    """The senior deduction's statutory cite is unconfirmed and must say so."""
    assert explanation.unverified_citations
    senior = RULES["senior_deduction"]
    assert senior.verified is False
    assert senior.title in explanation.unverified_citations


def test_every_rule_citation_has_a_resolvable_url():
    for rule in RULES.values():
        for citation in rule.citations:
            assert citation.url.startswith("https://"), rule.id
            assert citation.title.strip(), rule.id


def test_rules_respect_their_effective_years():
    senior = RULES["senior_deduction"]
    assert not senior.applies_to(2024)
    assert senior.applies_to(2025)
    assert not senior.applies_to(2029)
    assert senior in rules_for_year(2025)


def test_serialization_is_json_safe(explanation):
    import json

    payload = explanation.to_dict()
    encoded = json.dumps(payload)
    assert '"sections"' in encoded
    # Money must serialize as strings, never floats — a float here would
    # reintroduce binary rounding into a number a preparer signs.
    for section in payload["sections"]:
        for line in section["lines"]:
            assert isinstance(line["amount"], str)
            for operand in line["operands"]:
                assert isinstance(operand["amount"], str)


def test_explanation_contains_no_identity_fields(explanation):
    """The payload is amounts and rules — never taxpayer identity."""
    import json

    encoded = json.dumps(explanation.to_dict()).lower()
    for forbidden in ("ssn", "social security number", "date_of_birth", "address"):
        assert forbidden not in encoded


# --- Persistence and rebuild ----------------------------------------------


def test_store_round_trips_and_rebuild_matches(tmp_path):
    """A rebuilt explanation must equal one built directly from the inputs."""
    from app.services.explanation_service import ExplanationStore, build_for_workflow

    ctx = _cs2_context()
    ExplanationStore(tmp_path / "explanations").save(
        "wf-1",
        normalized={
            "taxable_interest": "214",
            "qualified_dividends": "1793",
            "ordinary_dividends": "5012",
            "social_security": "27648",
            "other_gains": "5469",
            "rental_income": "161",
            "short_term_gain": "-894",
            "short_term_loss_carryover": "4511",
            "long_term_gain": "7345",
            "capital_gain_distributions": "4698",
            "prior_year_overpayment_applied": "725",
            "apply_overpayment_to_next_year": "725",
        },
        field_provenance=ctx.field_provenance,
        confidence_scores=ctx.confidence_scores,
        profile={
            "tax_year": 2025,
            "filing_status": "single",
            "age_65_or_older": 1,
            "qualifying_children": 0,
            "other_dependents": 0,
            "state_code": "CA",
        },
    )

    rebuilt = build_for_workflow("wf-1", output_zone_dir=tmp_path)
    assert rebuilt is not None
    assert rebuilt.summary["adjusted_gross_income"] == "20653.00"
    assert next(l for l in rebuilt.lines if l.line == "6b").amount == D("3159.00")


def test_store_never_writes_identity_fields(tmp_path):
    """Identity is excluded at write time, not filtered at read time."""
    import json

    from app.services.explanation_service import ExplanationStore

    ExplanationStore(tmp_path / "explanations").save(
        "wf-2",
        normalized={
            "taxable_interest": "214",
            "taxpayer_name": "Jane Q. Public",
            "ssn": "123-45-6789",
            "address": "1 Main St",
        },
        field_provenance={},
        confidence_scores={},
        profile={"tax_year": 2025, "filing_status": "single"},
    )
    written = (tmp_path / "explanations" / "wf-2.json").read_text(encoding="utf-8")
    assert "Jane" not in written
    assert "123-45-6789" not in written
    assert "1 Main St" not in written
    assert json.loads(written)["normalized"]["taxable_interest"] == "214"


def test_rebuild_returns_none_when_nothing_was_recorded(tmp_path):
    from app.services.explanation_service import build_for_workflow

    assert build_for_workflow("missing", output_zone_dir=tmp_path) is None
