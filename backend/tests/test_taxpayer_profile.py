"""Filing status and age must come from evidence, not from a default.

Every case here is drawn from the nine-workpaper batch, where filing status
could not be determined on 7 of 7 returns and the engine fell back to Single.
On Basic 10 the accountant filed jointly with both spouses over 65 — a 34,700
standard deduction against the 15,750 we produced.
"""

from __future__ import annotations

import pytest

from app.services.tax_engine.tax_tables import FilingStatusTax
from app.services.taxpayer_profile_service import TaxpayerProfileService


def determine(normalized=None, candidates=None, year=2025, prior=None):
    return TaxpayerProfileService().determine(
        normalized=normalized or {},
        candidates=candidates or {},
        tax_year=year,
        prior_year_status=prior,
    )


def _c(field, *pairs):
    return {field: [{"document_type": d, "value": v} for d, v in pairs]}


# --- Filing status --------------------------------------------------------


def test_an_explicit_statement_wins():
    result = determine(candidates=_c("filing_status", ("client_organizer", "Joint")))
    assert result.filing_status.value is FilingStatusTax.MARRIED_JOINT
    assert result.filing_status.confidence >= 0.9


def test_bare_married_does_not_choose_joint_or_separate_silently():
    """The two differ by half the standard deduction."""
    result = determine(candidates=_c("filing_status", ("client_organizer", "Married")))
    assert result.filing_status.value is FilingStatusTax.MARRIED_JOINT
    assert result.filing_status.confidence < 0.8
    assert any("filing status" in i["title"].lower() for i in result.review_items)


def test_a_spouse_on_a_trusted_document_implies_a_married_return():
    """The Basic 10 failure: spouse name, SSN and DOB present, filed as Single."""
    result = determine(
        candidates={
            **_c("spouse_name", ("client_organizer", "Sharon Radcliffe")),
            **_c("spouse_ssn", ("client_organizer", "666-23-6365")),
            **_c("spouse_date_of_birth", ("client_organizer", "01/02/1958")),
        }
    )
    assert result.filing_status.value is FilingStatusTax.MARRIED_JOINT
    assert "spouse" in result.filing_status.evidence.lower()


def test_a_spouse_named_only_on_a_k1_is_not_enough():
    """A partnership K-1 names other partners' spouses, not this taxpayer's.

    So it is not the married return — and it is not a reason to produce
    nothing either, which is what this used to assert. Basic 9's only spouse
    signal is one name on one page and it got no return at all. Single is the
    checkable answer: it overstates the tax rather than understating it, and a
    joint return cannot be prepared from these documents anyway because it
    needs the spouse's SSN. The name is carried into the evidence so the
    preparer can settle it at a glance.
    """
    result = determine(candidates=_c("spouse_name", ("k1", "Patricia P Mercer")))
    assert result.filing_status.value is FilingStatusTax.SINGLE
    assert result.filing_status.confidence == pytest.approx(0.5)
    assert "other people" in result.filing_status.evidence
    assert "Patricia P Mercer" in result.filing_status.evidence
    assert any(
        "before filing" in i["title"]
        for i in result.review_items
        if i["field"] == "filing_status"
    )


def test_the_prior_year_return_carries_the_status_forward():
    result = determine(prior="married_joint")
    assert result.filing_status.value is FilingStatusTax.MARRIED_JOINT
    assert "prior-year" in result.filing_status.evidence.lower()


def test_a_stated_status_beats_the_prior_year():
    result = determine(
        candidates=_c("filing_status", ("client_organizer", "Single")),
        prior="married_joint",
    )
    assert result.filing_status.value is FilingStatusTax.SINGLE


def test_dependents_without_a_spouse_do_not_silently_become_head_of_household():
    """Head of household is never assumed — but single is still computed.

    Its two tests (over half the cost of keeping up the home, the qualifying
    person living there over half the year) are facts about a household that
    no form reports, so they cannot be inferred. Single is a valid status for
    a taxpayer with dependents who fails them, and it takes the *smaller*
    standard deduction of the two, so the error direction is recoverable.
    """
    result = determine(normalized={"qualifying_children": "2"})
    assert result.filing_status.value is FilingStatusTax.SINGLE
    assert result.filing_status.confidence == pytest.approx(0.5)
    assert "head of household" in result.filing_status.evidence.lower()
    assert "2 dependent" in result.filing_status.evidence


def test_nothing_at_all_is_reported_as_undetermined():
    result = determine()
    assert not result.filing_status.resolved
    assert any(
        i["title"] == "Filing status could not be determined" for i in result.review_items
    )


# --- Age ------------------------------------------------------------------


def test_age_65_is_tested_as_born_before_january_2():
    """A 2 January 1961 birthday is not 65 for tax year 2025; 1 January is."""
    assert determine(candidates=_c("date_of_birth", ("client_organizer", "01/01/1961"))).seniors == 1
    assert determine(candidates=_c("date_of_birth", ("client_organizer", "01/02/1961"))).seniors == 0


def test_both_spouses_over_65_are_counted():
    """Basic 10: 31,500 + 1,600 + 1,600 = 34,700 needs both.

    The spouse SSN is here because Basic 10 has one and because it is what
    makes this a joint return: two corroborating spouse fields. `seniors`
    counts entitlements rather than people, so on any other status the second
    addition is not available — see the test below.
    """
    result = determine(
        candidates={
            **_c("date_of_birth", ("client_organizer", "05/07/1954")),
            **_c("spouse_date_of_birth", ("client_organizer", "01/02/1958")),
            **_c("spouse_ssn", ("client_organizer", "666-23-6365")),
        }
    )
    assert result.filing_status.value is FilingStatusTax.MARRIED_JOINT
    assert result.seniors == 2


def test_a_spouse_over_65_who_is_not_on_the_return_is_not_counted():
    """A senior addition for somebody the return does not include.

    One uncorroborated spouse date of birth resolves to single (it is not
    evidence of a married return), and `seniors` fed the engine one addition
    per person over 65 regardless of status — so the single return claimed the
    absent spouse's extra amount, roughly 2,000 of deduction. This appeared
    the moment step 3 began resolving instead of refusing, which is the hazard
    of turning a refusal into an answer: code downstream was written assuming
    the refusal.
    """
    result = determine(
        candidates=_c("spouse_date_of_birth", ("client_organizer", "01/02/1958"))
    )

    assert result.filing_status.value is FilingStatusTax.SINGLE
    assert result.spouse_age_65.value is True
    assert result.seniors == 0


def test_a_missing_date_of_birth_is_raised_not_assumed():
    result = determine()
    assert result.seniors == 0
    assert any(i["field"] == "date_of_birth" for i in result.review_items)


# --- Competing candidates -------------------------------------------------


def test_the_organizer_outranks_a_k1_on_date_of_birth():
    """The exact Basic 10 failure: first-wins took the 1987 date."""
    result = determine(
        candidates=_c(
            "date_of_birth",
            ("k1", "08/14/1987"),
            ("client_organizer", "05/07/1954"),
        )
    )
    assert result.taxpayer_dob.year == 1954
    assert result.seniors == 1


def test_agreement_across_several_weak_documents_picks_the_right_name():
    """Corroboration settles *which* name, not whether there is a spouse."""
    result = determine(
        candidates={
            **_c(
                "spouse_name",
                ("1099_int", "Sharon Radcliffe"),
                ("1099_div", "Sharon Radcliffe"),
                ("1099_b", "Sharon Radcliffe"),
                ("k1", "Susan Coleman"),
            ),
            **_c("spouse_date_of_birth", ("1099_int", "01/02/1958")),
        }
    )
    assert result.filing_status.value is FilingStatusTax.MARRIED_JOINT
    assert "Sharon Radcliffe" in result.filing_status.evidence


def test_a_name_agreed_on_by_many_documents_is_still_only_a_name():
    """Joint brokerage accounts name a second person on every statement.

    Four of eight sample returns were filed jointly on one bare spouse_name
    that the accountant filed single, so a name alone -- however often it is
    repeated -- no longer decides the filing status.
    """
    result = determine(
        candidates=_c(
            "spouse_name",
            ("1099_int", "Sharon Radcliffe"),
            ("1099_div", "Sharon Radcliffe"),
            ("1099_b", "Sharon Radcliffe"),
        )
    )
    _not_a_married_return(result)


def _not_a_married_return(result) -> None:  # type: ignore[no-untyped-def]
    """What the stray-name cases below are actually defending.

    Each used to assert ``not resolved`` — no return at all. The property they
    exist for is narrower: a stray name must not produce a *joint* return,
    which is the expensive error, because joint takes twice the standard
    deduction and cannot even be filed without the spouse's SSN. Single, at a
    confidence low enough to force a review item, is the outcome now. See
    ``test_a_spouse_named_only_on_a_k1_is_not_enough`` for the reasoning.
    """
    assert result.filing_status.value is FilingStatusTax.SINGLE
    assert result.filing_status.confidence < 0.8
    assert any(i["field"] == "filing_status" for i in result.review_items)


def test_one_organizer_repeating_itself_is_not_corroboration():
    """A long document is extracted in segments, so one sighting arrives twice."""
    result = determine(
        candidates=_c(
            "spouse_name",
            ("unknown_workpaper", "Dorothy Chandler"),
            ("unknown_workpaper", "Dorothy Chandler"),
        )
    )
    _not_a_married_return(result)


def test_a_company_in_the_spouse_box_is_not_a_spouse():
    """CS 2 filed jointly on a spouse_name of "Harborview Solutions LLC!"."""
    result = determine(
        candidates={
            **_c("spouse_name", ("client_organizer", "Harborview Solutions LLC!")),
            **_c("spouse_date_of_birth", ("client_organizer", "01/02/1958")),
        }
    )
    _not_a_married_return(result)


def test_a_single_stray_name_on_a_trusted_document_is_not_enough():
    """Basic 6: one spouse_name on page 28 of the organizer, nothing else."""
    result = determine(candidates=_c("spouse_name", ("client_organizer", "Dorothy Chandler")))
    _not_a_married_return(result)


def test_conflicting_identity_is_surfaced():
    result = determine(
        candidates=_c(
            "spouse_name",
            ("client_organizer", "Sharon Radcliffe"),
            ("k1", "Susan Coleman"),
            ("k1", "Charles Y Barrett"),
        )
    )
    conflict = next(i for i in result.review_items if i["field"] == "spouse_name")
    assert "3 different values" in conflict["description"]
    assert "Susan Coleman" in conflict["description"]


def test_placeholder_values_are_not_treated_as_evidence():
    """'ON FILE' and 'XXX-XX-1412' appeared as spouse SSNs in the batch."""
    result = determine(
        candidates=_c("spouse_ssn", ("client_organizer", "ON FILE"), ("k1", "N/A"))
    )
    assert not result.filing_status.resolved


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Single", FilingStatusTax.SINGLE),
        ("MFJ", FilingStatusTax.MARRIED_JOINT),
        ("Married Filing Separately", FilingStatusTax.MARRIED_SEPARATE),
        ("Head of Household", FilingStatusTax.HEAD_OF_HOUSEHOLD),
        ("Qualifying Surviving Spouse", FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE),
    ],
)
def test_status_wording_variants(text, expected):
    assert determine(candidates=_c("filing_status", ("client_organizer", text))).filing_status.value is expected


# ----------------------------------------- single as a determination, not a default


def _candidates(**fields: list[tuple[str, str]]) -> dict[str, list[dict[str, str]]]:
    return {
        name: [{"value": value, "document_type": document} for value, document in rows]
        for name, rows in fields.items()
    }


def test_no_spouse_and_no_dependents_on_a_household_document_means_single() -> None:
    """Regression: refusing here stopped the sample return computing at all.

    Four of the five statuses require somebody else — joint and separate need a
    spouse, surviving spouse needs a deceased one plus a child, head of household
    needs a qualifying person. With none of them present on documents that would
    have named them, single is the only status left, not a guess.

    Treating it as undetermined produced no return for a single filer with a
    complete workpaper, which is a worse answer than the one it was avoiding.
    """
    result = TaxpayerProfileService().determine(
        normalized={},
        candidates=_candidates(
            taxpayer_name=[("A TAXPAYER", "client_organizer"), ("A TAXPAYER", "w2")]
        ),
        tax_year=2025,
    )

    assert result.filing_status.value is FilingStatusTax.SINGLE
    assert result.filing_status.confidence == pytest.approx(0.70)


def test_identity_from_a_brokerage_form_alone_files_but_never_silently() -> None:
    """A 1099 names an account holder and says nothing about a household.

    This assertion was reversed deliberately, and the reason is worth keeping.
    It used to demand ``value is None``, on the argument that absence of a
    spouse on a form with no spouse box is not evidence of anything. That is
    true, and it is still not a reason to refuse: measured over the sample
    corpus it refused most of it, because a 1099-only or K-1-only workpaper has
    no organizer and no W-2 for the strong witness test to find. The preparer
    was left with no return to check rather than a return to correct.

    So the weaker inference is allowed, and what must hold instead is that it
    is never silent and never wins over better evidence. That is what the rest
    of this test, and the four that follow it, pin down.
    """
    result = TaxpayerProfileService().determine(
        normalized={},
        candidates=_candidates(taxpayer_name=[("A TAXPAYER", "1099_int")]),
        tax_year=2025,
    )

    assert result.filing_status.value is FilingStatusTax.SINGLE
    assert result.filing_status.confidence == pytest.approx(0.55)
    assert "1099 int" in result.filing_status.evidence

    # The mitigation is the whole basis for allowing this, so assert it rather
    # than trusting it: a confidence below the review threshold must produce an
    # item, and its title must say the status gates filing.
    flagged = [i for i in result.review_items if i["field"] == "filing_status"]
    assert len(flagged) == 1
    assert "before filing" in flagged[0]["title"]


def test_a_weak_single_still_loses_to_every_stronger_signal() -> None:
    """The weak tier is last. Each of these must reach its own answer."""
    brokerage = [("A TAXPAYER", "1099_int")]

    stated = TaxpayerProfileService().determine(
        normalized={},
        candidates=_candidates(
            taxpayer_name=brokerage,
            filing_status=[("Married Filing Jointly", "1099_int")],
        ),
        tax_year=2025,
    )
    assert stated.filing_status.value is FilingStatusTax.MARRIED_JOINT

    carried = TaxpayerProfileService().determine(
        normalized={},
        candidates=_candidates(taxpayer_name=brokerage),
        tax_year=2025,
        prior_year_status="head_of_household",
    )
    assert carried.filing_status.value is FilingStatusTax.HEAD_OF_HOUSEHOLD

    spoused = TaxpayerProfileService().determine(
        normalized={},
        candidates=_candidates(
            taxpayer_name=brokerage,
            spouse_name=[("B TAXPAYER", "client_organizer")],
            spouse_ssn=[("666-23-1177", "client_organizer")],
        ),
        tax_year=2025,
    )
    assert spoused.filing_status.value is FilingStatusTax.MARRIED_JOINT

    # A dependent does not change the status, but it must reach the head of
    # household question rather than the generic weak-single evidence.
    with_child = TaxpayerProfileService().determine(
        normalized={"qualifying_children": "1"},
        candidates=_candidates(taxpayer_name=brokerage),
        tax_year=2025,
    )
    assert with_child.filing_status.value is FilingStatusTax.SINGLE
    assert "head of household" in with_child.filing_status.evidence.lower()


def test_an_identity_with_no_recorded_document_still_files() -> None:
    """A merged field carries no document type, and that is not a reason to refuse.

    Candidates are recorded per extraction; a value that reached the merge
    without one arrives with ``document_type == ""``. Keying the inference on
    the document type alone refused these — the same failure as the strong
    witness test, one level down.
    """
    result = TaxpayerProfileService().determine(
        normalized={"taxpayer_name": "A TAXPAYER", "wages": "82000"},
        candidates={},
        tax_year=2025,
    )

    assert result.filing_status.value is FilingStatusTax.SINGLE
    assert result.filing_status.confidence == pytest.approx(0.55)
    assert any(i["field"] == "filing_status" for i in result.review_items)


def test_a_workpaper_that_identifies_nobody_is_still_undetermined() -> None:
    """Step 6 survives the widening: a pile of figures with no taxpayer.

    Every tier above this one needs some document to have named the person the
    return is for. When none did, there is nobody to file for, and that is a
    different thing from a household we cannot describe.
    """
    result = TaxpayerProfileService().determine(
        normalized={"wages": "82000"},
        candidates={},
        tax_year=2025,
    )

    assert result.filing_status.value is None
    assert "identified the taxpayer" in result.filing_status.evidence


def test_a_corroborated_spouse_still_beats_the_single_determination() -> None:
    result = TaxpayerProfileService().determine(
        normalized={},
        candidates=_candidates(
            taxpayer_name=[("A TAXPAYER", "client_organizer")],
            spouse_name=[("B TAXPAYER", "client_organizer")],
            spouse_date_of_birth=[("01/02/1970", "client_organizer")],
        ),
        tax_year=2025,
    )

    assert result.filing_status.value is FilingStatusTax.MARRIED_JOINT


def test_dependents_still_route_to_the_head_of_household_question() -> None:
    """The strong witness must not quietly swallow a possible head of household.

    A client organizer that names the taxpayer and no spouse would otherwise
    reach step 5 and report single at 0.70 with no mention of dependents at
    all. The dependent has to be the thing the preparer is asked about, and at
    the lower confidence, even though the computed status is the same.
    """
    result = TaxpayerProfileService().determine(
        normalized={"qualifying_children": "1"},
        candidates=_candidates(taxpayer_name=[("A TAXPAYER", "client_organizer")]),
        tax_year=2025,
    )

    assert result.filing_status.value is FilingStatusTax.SINGLE
    assert result.filing_status.confidence == pytest.approx(0.5)
    assert "head of household" in result.filing_status.evidence
