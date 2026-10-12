"""Unknown must not be silently reported as zero.

Some Form 1040 inputs appear on no current-year document — capital loss
carryovers and the prior-year overpayment applied. When the prior return is
missing, the pipeline used to treat them as zero and print a return that footed
perfectly. This suite makes the gap speak.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.database_models import (
    Document,
    ReviewItem,
    UploadedFile,
    Workflow,
)
from app.models.enums import DocumentType


def _workflow(session, file_id: str) -> Workflow:
    """A persisted workflow with the parent file the foreign key requires."""
    session.add(
        UploadedFile(
            id=file_id,
            original_filename=f"{file_id}.pdf",
            stored_filename=f"{file_id}.enc",
            content_type="application/pdf",
            extension=".pdf",
            size_bytes=1024,
            content_hash=f"hash-{file_id}",
        )
    )
    workflow = Workflow(uploaded_file_id=file_id, status="running")
    session.add(workflow)
    session.flush()
    return workflow


@pytest.mark.parametrize(
    ("normalized", "expected"),
    [
        # Investment activity with no carryover stated: the carryover is unknown.
        ({"long_term_gain": "7344.95"}, True),
        ({"short_term_gain": "-893.86"}, True),
        ({"capital_gain_distributions": "4698.39"}, True),
        # A stated carryover answers the question, so nothing to raise for it.
        # The overpayment check still fires, so the item is still expected.
        ({"long_term_gain": "100", "short_term_loss_carryover": "4511"}, True),
        # Nothing at all still raises, because the overpayment is unknown.
        ({}, True),
    ],
)
def test_missing_prior_year_inputs_raise_one_review_item(session, normalized, expected):
    from app.services.workflow_orchestrator import WorkflowOrchestrator

    workflow = _workflow(session, "f-1")

    raised = WorkflowOrchestrator(session)._flag_unavailable_prior_year(
        workflow, normalized, []
    )
    assert bool(raised) is expected


def test_a_supplied_prior_year_return_silences_the_warning(session):
    from app.services.workflow_orchestrator import WorkflowOrchestrator

    workflow = _workflow(session, "f-2")

    prior = Document(
        uploaded_file_id="f-2",
        document_type=DocumentType.PRIOR_YEAR_RETURN.value,
        page_start=1,
        page_end=2,
    )
    raised = WorkflowOrchestrator(session)._flag_unavailable_prior_year(
        workflow, {"long_term_gain": "7344.95"}, [prior]
    )
    assert raised == 0


def test_the_item_names_what_could_not_be_determined(session):
    from app.services.workflow_orchestrator import WorkflowOrchestrator

    workflow = _workflow(session, "f-3")

    WorkflowOrchestrator(session)._flag_unavailable_prior_year(
        workflow, {"long_term_gain": "7344.95"}, []
    )
    session.flush()

    item = session.execute(
        select(ReviewItem).where(ReviewItem.workflow_id == workflow.id)
    ).scalars().one()

    assert item.title == "Prior-year return not provided"
    # A preparer must be able to act on it without opening the code.
    assert "capital loss carryover" in item.description
    assert "line 26" in item.description
    assert "treated as zero" in item.description
