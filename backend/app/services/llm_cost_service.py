"""What a return's model calls cost, summed from the ``llm_calls`` ledger.

Figures are what each call cost at the time it was made, from the price file
in force then - see ``llm_meter``. A call the price file had no rate for is
counted as *unpriced*, not as zero and not as an estimate: the total says how
many calls it leaves out, so a partial figure never passes for a whole one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.database_models import Document, LlmCall, Workflow
from app.services.llm_meter import price_book

ZERO = Decimal(0)


@dataclass
class CostBucket:
    """Calls, tokens and cost for one slice - a stage, a model, or everything."""

    key: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    thinking_tokens: int = 0
    cost_usd: Decimal = ZERO
    unpriced_calls: int = 0
    stub_calls: int = 0
    failed_calls: int = 0

    def add(self, row: LlmCall) -> None:
        self.calls += 1
        self.input_tokens += row.input_tokens
        self.output_tokens += row.output_tokens
        self.cached_tokens += row.cached_tokens
        self.thinking_tokens += row.thinking_tokens
        self.stub_calls += int(row.stub)
        self.failed_calls += int(not row.succeeded)
        if row.cost_usd is None:
            self.unpriced_calls += 1
        else:
            self.cost_usd += Decimal(row.cost_usd)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "thinking_tokens": self.thinking_tokens,
            "cost_usd": str(self.cost_usd.quantize(Decimal("0.000001"))),
            "unpriced_calls": self.unpriced_calls,
            "stub_calls": self.stub_calls,
            "failed_calls": self.failed_calls,
        }


@dataclass
class CostSummary:
    workflow_id: str
    total: CostBucket
    by_stage: list[CostBucket] = field(default_factory=list)
    by_model: list[CostBucket] = field(default_factory=list)
    pages: int = 0
    #: Price-file dates behind these figures; more than one if prices changed.
    prices_as_of: list[str] = field(default_factory=list)
    prices_source: str = ""

    @property
    def cost_per_page(self) -> Decimal | None:
        return None if not self.pages else self.total.cost_usd / self.pages

    def to_dict(self) -> dict[str, Any]:
        per_page = self.cost_per_page
        return {
            "workflow_id": self.workflow_id,
            "total": self.total.to_dict(),
            "by_stage": [b.to_dict() for b in self.by_stage],
            "by_model": [b.to_dict() for b in self.by_model],
            "pages": self.pages,
            "cost_per_page_usd": None
            if per_page is None
            else str(per_page.quantize(Decimal("0.000001"))),
            "prices_as_of": self.prices_as_of,
            "prices_source": self.prices_source,
        }


def summarize(workflow_id: str, rows: Iterable[LlmCall], *, pages: int = 0) -> CostSummary:
    """Pure: the ledger rows for one return, summed three ways."""
    total = CostBucket("total")
    stages: dict[str, CostBucket] = {}
    models: dict[str, CostBucket] = {}
    as_of: set[str] = set()
    for row in rows:
        total.add(row)
        stages.setdefault(row.stage, CostBucket(row.stage)).add(row)
        models.setdefault(row.model, CostBucket(row.model)).add(row)
        if row.prices_as_of:
            as_of.add(row.prices_as_of)
    try:
        source = price_book().source
    except (OSError, ValueError, KeyError):
        source = ""
    return CostSummary(
        workflow_id=workflow_id,
        total=total,
        # Most expensive first: the panel opens on the thing worth changing.
        by_stage=sorted(stages.values(), key=lambda b: (-b.cost_usd, b.key)),
        by_model=sorted(models.values(), key=lambda b: (-b.cost_usd, b.key)),
        pages=pages,
        prices_as_of=sorted(as_of),
        prices_source=source,
    )


def pages_in(session: Session, workflow: Workflow) -> int:
    """Pages in the upload behind a return: the last page any document covers."""
    found = session.execute(
        select(func.max(Document.page_end)).where(
            Document.uploaded_file_id == workflow.uploaded_file_id
        )
    ).scalar()
    return int(found or 0)


def workflow_cost(session: Session, workflow: Workflow) -> CostSummary:
    rows = session.execute(
        select(LlmCall).where(LlmCall.workflow_id == workflow.id)
    ).scalars()
    return summarize(workflow.id, rows, pages=pages_in(session, workflow))
