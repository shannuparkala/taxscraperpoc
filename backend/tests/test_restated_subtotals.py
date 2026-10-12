"""A recap page and the detail it recaps must not both be counted.

Basic 4's client organizer carried a wage recap on page 12 (104,308 taxpayer
plus 58,500 spouse) and transcribed the two underlying W-2s on pages 13 and 14
(118,453.63 and 46,213.60). Every one of the four was reported as ``wages`` and
summed, so Form 1040 line 1a read 327,475.23 against a true 164,667.23 and
adjusted gross income came out at 329,557 where the accountant filed 166,749 --
the single largest error in the nine-workpaper batch.
"""

from __future__ import annotations

from app.services.workflow_orchestrator import detect_restated_subtotals


def _prov(field, document_type, *amounts):
    return {field: [{"document_type": document_type, "amount": a} for a in amounts]}


def test_the_basic_4_wage_double_count_is_reported():
    risks = detect_restated_subtotals(
        _prov("wages", "client_organizer", "104308", "58500", "118453.63", "46213.60")
    )
    assert len(risks) == 1
    assert risks[0]["field"] == "wages"
    assert risks[0]["total"] == "327475.23"
    assert "118453.63" in risks[0]["contributions"]


def test_a_taxpayer_and_a_spouse_w2_are_not_flagged():
    """Two figures for one field is ordinary and must stay quiet."""
    assert detect_restated_subtotals(_prov("wages", "w2", "118453.63", "46213.60")) == []


def test_contributions_from_different_documents_are_not_a_recap():
    """Three 1099-INTs genuinely sum; only one document restating itself does not."""
    provenance = {
        "taxable_interest": [
            {"document_type": "1099_int", "amount": "100"},
            {"document_type": "1099_div", "amount": "200"},
            {"document_type": "brokerage_statement", "amount": "300"},
        ]
    }
    assert detect_restated_subtotals(provenance) == []


def test_unreadable_amounts_do_not_crash_the_check():
    risks = detect_restated_subtotals(
        _prov("wages", "client_organizer", "1", "2", "n/a", "3")
    )
    assert risks[0]["total"] == "6"


def test_nothing_is_flagged_without_provenance():
    assert detect_restated_subtotals({}) == []


# --- Documents that were read and reported nothing -------------------------


from app.services.workflow_orchestrator import detect_silent_documents


def test_a_w2_that_contributed_nothing_is_reported():
    """Basic 4 classified a W-2; every wage figure came from the organizer."""
    silent = detect_silent_documents(
        ["w2", "client_organizer"],
        {"wages": [{"document_type": "client_organizer", "amount": "164667.23"}]},
    )
    assert silent == ["w2"]


def test_documents_that_carry_no_money_are_not_expected_to():
    """A consent form reporting nothing is a consent form working correctly."""
    assert detect_silent_documents(
        ["consent_form", "engagement_letter", "1095", "5498"], {}
    ) == []


def test_a_prior_year_return_is_not_expected_to_contribute():
    """It is excluded from the sums on purpose; flagging it would be noise."""
    assert detect_silent_documents(["prior_year_return"], {}) == []


def test_a_document_that_did_contribute_is_quiet():
    assert detect_silent_documents(
        ["1099_int"],
        {"taxable_interest": [{"document_type": "1099_int", "amount": "214"}]},
    ) == []


def test_every_money_document_is_reported_once():
    silent = detect_silent_documents(["w2", "w2", "k1", "1099_b"], {})
    assert silent == ["1099_b", "k1", "w2"]


# --- The review items these detectors raise --------------------------------
#
# A NameError shipped in these descriptions and produced nine consecutive runs
# with no computed return: the recomputation handler caught it, logged only the
# exception type, and carried on. The strings are built by plain functions now
# so that rendering them is a unit test rather than a pipeline run.


from app.services.workflow_orchestrator import (
    restated_subtotal_review_item,
    silent_document_review_item,
)

RISK = {
    "field": "wages",
    "document_type": "client_organizer",
    "total": "327475.23",
    "contributions": "104308, 58500, 118453.63, 46213.60",
}


def test_the_silent_document_item_renders_and_names_the_document():
    item = silent_document_review_item("w2")
    assert item["title"] == "A W2 was read but reported no figures"
    assert "W2" in item["description"]
    assert "\n\n" in item["description"]


def test_the_double_count_item_states_every_contribution():
    """A reviewer must be able to settle it without opening the code."""
    item = restated_subtotal_review_item(RISK)
    assert item["title"] == "Check wages for a double count"
    assert "4 separate figures" in item["description"]
    assert "327475.23" in item["description"]
    assert "118453.63" in item["description"]
    assert item["field_name"] == "wages"
    assert item["proposed_value"] == "327475.23"


def test_both_items_carry_only_keys_the_review_helper_accepts():
    """They are splatted into _add_review_item; an extra key is a TypeError."""
    import inspect

    from app.services.workflow_orchestrator import WorkflowOrchestrator

    accepted = set(inspect.signature(WorkflowOrchestrator._add_review_item).parameters)
    for item in (silent_document_review_item("k1"), restated_subtotal_review_item(RISK)):
        assert set(item) <= accepted, set(item) - accepted


# --- The organizer recaps the forms behind it ------------------------------


from app.services.workflow_orchestrator import merge_extractions


def test_the_organizer_recap_gives_way_to_the_w2():
    """Basic 4: 162,808 recapped + 164,667.23 of real W-2s = 327,475.23.

    Adjusted gross income came out at 332,298 against a filed 166,749. Keeping
    only the W-2 figure gives 166,748 -- a dollar of rounding from the
    accountant's return.
    """
    merged = merge_extractions(
        [
            ("client_organizer", {"normalized_fields": {"wages": "162808"}}),
            ("w2", {"normalized_fields": {"wages": "164667.23"}}),
        ]
    )
    assert merged["normalized_fields"]["wages"] == "164667.23"
    assert any("client organizer recap" in d for d in merged["duplicates_ignored"])


def test_an_organizer_that_is_the_only_source_keeps_its_figure():
    """Dropping it whenever it appears would delete income nothing else reports."""
    merged = merge_extractions(
        [("client_organizer", {"normalized_fields": {"wages": "50000"}})]
    )
    assert merged["normalized_fields"]["wages"] == "50000"
    assert merged["duplicates_ignored"] == []


def test_only_the_recapped_field_is_dropped():
    """A field the source form does not report is untouched."""
    merged = merge_extractions(
        [
            (
                "client_organizer",
                {"normalized_fields": {"wages": "162808", "charitable_cash": "1200"}},
            ),
            ("w2", {"normalized_fields": {"wages": "164667.23"}}),
        ]
    )
    assert merged["normalized_fields"]["wages"] == "164667.23"
    assert merged["normalized_fields"]["charitable_cash"] == "1200"


def test_two_source_documents_still_sum():
    """The rule must not collapse genuinely separate forms.

    Two W-2s -- a taxpayer's and a spouse's -- are separate money. The pair used
    to be a W-2 and a 1099-MISC, which FIELD_SOURCE_DOCUMENTS now rejects, and
    rightly: a 1099-MISC has no wage box.
    """
    merged = merge_extractions(
        [
            ("w2", {"normalized_fields": {"wages": "118453.63"}}),
            ("w2", {"normalized_fields": {"wages": "46213.60"}}),
        ]
    )
    assert merged["normalized_fields"]["wages"] == "164667.23"


def test_the_dropped_recap_leaves_the_provenance_honest():
    """What is reported as the source of a figure must be what produced it."""
    merged = merge_extractions(
        [
            ("client_organizer", {"normalized_fields": {"wages": "162808"}}),
            ("w2", {"normalized_fields": {"wages": "164667.23"}}),
        ]
    )
    sources = {c["document_type"] for c in merged["field_provenance"]["wages"]}
    assert sources == {"w2"}


# --- A form cannot report a figure it has no box for -----------------------


def test_a_1098_cannot_report_wages():
    """Basic 6: 64,929 was read off a mortgage interest statement as wages.

    Added to the W-2's 81,412.87 it produced a line 1a of 146,342 and an
    adjusted gross income of 150,513 against a filed 75,582.
    """
    merged = merge_extractions(
        [
            ("1098", {"normalized_fields": {"wages": "64929", "mortgage_interest": "8000"}}),
            ("w2", {"normalized_fields": {"wages": "81412.87"}}),
        ]
    )
    assert merged["normalized_fields"]["wages"] == "81412.87"
    assert merged["normalized_fields"]["mortgage_interest"] == "8000"
    assert any("does not report this field" in d for d in merged["duplicates_ignored"])


def test_a_summary_document_may_still_report_wages():
    """When the W-2 itself is missing, the organizer is the only source."""
    merged = merge_extractions(
        [("client_organizer", {"normalized_fields": {"wages": "50000"}})]
    )
    assert merged["normalized_fields"]["wages"] == "50000"


def test_fields_outside_the_map_are_unrestricted():
    """The map is an allow-list only for the fields it names."""
    merged = merge_extractions(
        [("1098", {"normalized_fields": {"taxable_interest": "214"}})]
    )
    assert merged["normalized_fields"]["taxable_interest"] == "214"


def test_a_w2_cannot_report_mortgage_interest():
    merged = merge_extractions(
        [
            ("w2", {"normalized_fields": {"mortgage_interest": "9999"}}),
            ("1098", {"normalized_fields": {"mortgage_interest": "8000"}}),
        ]
    )
    assert merged["normalized_fields"]["mortgage_interest"] == "8000"
