"""Emit the engine's rule and error knowledge as JSON.

Regenerated from the code, not hand-maintained. A hand-written rules file starts
accurate and drifts silently; this one is wrong only if the code is wrong, and a
diff after a change shows exactly what the change did to the engine's declared
behaviour.

    cd backend && python -m scripts.export_knowledge

Only verified content is emitted. Where a rule set is genuinely empty — because
the engine does not implement it yet — the file says so rather than carrying a
plausible-looking placeholder. A fabricated rule in a knowledge base is worse
than a missing one: it will be trusted, and it will be cited.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models.enums import DocumentType
from app.services.carryover_repository import (
    ENGINE_FIELD_FOR_KIND,
    CarryoverKind,
)
from app.services.workflow_orchestrator import (
    _EXTRACTION_HINTS,
    CARRYFORWARD_FIELDS,
    ENGINE_MONEY_FIELDS,
    NON_SOURCE_DOCUMENT_TYPES,
)
from app.tax_knowledge.rule_citations import RULES

OUT = Path(__file__).resolve().parents[2] / "data" / "learning"
NOW = datetime.now(UTC).isoformat(timespec="seconds")


def _write(name: str, payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": NOW, "generated_by": "scripts/export_knowledge.py", **payload}
    (OUT / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  {name}")


def calculation_rules() -> None:
    _write(
        "CalculationRules.json",
        {
            "description": (
                "Every computation the engine performs, with the authority "
                "behind it. Source: app/tax_knowledge/rule_citations.py."
            ),
            "rule_count": len(RULES),
            "unverified_citations": sorted(
                r.id for r in RULES.values() if not r.verified
            ),
            "rules": [r.to_dict() for r in sorted(RULES.values(), key=lambda r: r.id)],
        },
    )


def extraction_rules() -> None:
    _write(
        "ExtractionRules.json",
        {
            "description": (
                "Per-document-type extraction guidance sent with each LLM "
                "prompt, and the field vocabulary the engine can consume. "
                "Source: app/services/workflow_orchestrator.py."
            ),
            "engine_money_fields": list(ENGINE_MONEY_FIELDS),
            "carryforward_only_fields": sorted(CARRYFORWARD_FIELDS),
            "document_hints": dict(sorted(_EXTRACTION_HINTS.items())),
            "known_gaps": [
                {
                    "gap": "No SSA-1099 document type or extraction hint",
                    "impact": (
                        "Form SSA-1099 is the only source for Form 1040 lines 6a "
                        "and 6b. Without a type it is misclassified (observed as "
                        "'k1' on the CS-2 run) and gets no box-level guidance."
                    ),
                    "evidence": (
                        "Using the prominent 'Paid by check or Direct deposit' "
                        "figure of 25,428 instead of box 5's 27,648 moves line "
                        "6b from 3,159 to 2,604 on the CS-2 sample."
                    ),
                    "status": "open",
                },
            ],
        },
    )


def classification_rules() -> None:
    _write(
        "ClassificationRules.json",
        {
            "description": (
                "Document types the classifier can assign, and how each is "
                "treated when merging amounts."
            ),
            "document_types": sorted(t.value for t in DocumentType),
            "non_source_document_types": {
                "types": sorted(NON_SOURCE_DOCUMENT_TYPES),
                "rule": (
                    "Amounts are excluded from the current year's totals; facts "
                    "are still surfaced for comparison. A prior-year return "
                    "states a complete, plausible set of wages and withholding, "
                    "and folding it in roughly doubles the return."
                ),
                "exception": sorted(CARRYFORWARD_FIELDS),
            },
            "deduplication_rule": {
                "signature": "(field_name, amount)",
                "rationale": (
                    "Excludes the document type deliberately. A consolidated "
                    "broker 1099 states its capital gains on a summary page and "
                    "again across the per-lot detail; the classifier labels "
                    "those 1099_div and 1099_b, and keying on the type made one "
                    "figure look like two. Every drop raises a review flag."
                ),
                "verified_against": "CS-2 run, long_term_gain 7,344.95 seen twice",
            },
        },
    )


def form_selection_rules() -> None:
    _write(
        "FormSelectionRules.json",
        {
            "description": (
                "Which output artifacts the engine produces today, measured "
                "against the accountant package for the one fully reconciled "
                "case (CS-2)."
            ),
            "engine_produces": [
                "Form 1040 (filled PDF)",
                "Schedule D working (lines D-7, D-15, D-16)",
                "Workpaper (.xlsx)",
                "Summary, exceptions, traceability, review notes, audit log",
            ],
            "accountant_package_contained": [
                "Form 1040", "Schedule 1", "Schedule 1-A", "Schedule A",
                "Schedule B", "Schedule D", "Schedule E", "Form 4797",
                "Form 6251", "Form 7203", "Form 1116 (regular and AMT)",
                "Form 8995", "CA Form 540", "CA Schedule CA", "CA Schedule D",
                "20 supporting statements",
            ],
            "not_yet_generated": [
                {"form": "Schedule 1", "note": "Computed internally; not emitted as a form."},
                {"form": "Schedule 1-A", "note": "Senior deduction is computed; the form is not produced."},
                {"form": "Schedule A", "note": "Itemized total is computed for the comparison only."},
                {"form": "Schedule B", "note": "Interest and dividend detail is available but not emitted."},
                {"form": "Form 7203", "note": "Not modelled. Its line 34 gain reached the CS-2 return only because the preparer keyed it onto Form 4797 by hand."},
                {"form": "Form 6251", "note": "AMT not computed."},
                {"form": "Form 1116", "note": "Foreign tax credit not computed."},
                {"form": "State returns", "note": "No state engine. CS-2 required CA Form 540 and Schedule CA."},
            ],
            "status": "measured on one case; re-measure after a full batch run",
        },
    )


def state_tax_rules() -> None:
    _write(
        "StateTaxRules.json",
        {
            "description": (
                "State treatments verified against an accountant-prepared "
                "return. California only — the sole state in the reconciled "
                "case. No state engine exists yet; these are the rules it would "
                "need first."
            ),
            "implemented": False,
            "rules": {
                "CA": [
                    {
                        "rule": "Social Security benefits are not taxed",
                        "mechanic": "Subtract the federal taxable amount on Schedule CA (540) line 6b",
                        "authority": "R&TC 17087",
                        "verified_against": "CS-2: 3,159 subtracted",
                    },
                    {
                        "rule": "No federal short-term capital loss carryover",
                        "mechanic": "Add the federal carryover back on Schedule CA line 7a",
                        "verified_against": "CS-2: 4,511 added back",
                    },
                    {
                        "rule": "Dividends from US government obligations are exempt",
                        "mechanic": "Subtract the US-obligation portion of fund dividends on line 3b",
                        "verified_against": "CS-2: 373 subtracted, from broker percentage tables",
                    },
                    {
                        "rule": "S-corporation state tax deducted federally is added back",
                        "mechanic": "CA Schedule K-1 (100S) adjustment column, to Schedule CA line 5",
                        "verified_against": "CS-2: 800 added",
                    },
                    {
                        "rule": "EIC denied when investment income exceeds the limit",
                        "mechanic": "Form 3514",
                        "verified_against": "CS-2: denied, limit 4,814",
                    },
                ]
            },
        },
    )


def carryover_rules() -> None:
    _write(
        "CarryoverRules.json",
        {
            "description": (
                "Carryover kinds the repository tracks and which ones the "
                "engine currently consumes. Source: "
                "app/services/carryover_repository.py."
            ),
            "repository_location": "data/output/CarryoverRepository.json",
            "identity": "salted SHA-256 of the identifying number; no plaintext PII is stored",
            "tracked_kinds": sorted(
                v for k, v in vars(CarryoverKind).items() if not k.startswith("_")
            ),
            "consumed_by_engine": dict(sorted(ENGINE_FIELD_FOR_KIND.items())),
            "not_yet_consumed": sorted(
                v
                for k, v in vars(CarryoverKind).items()
                if not k.startswith("_") and v not in ENGINE_FIELD_FOR_KIND
            ),
            "precedence": (
                "A figure stated by this year's documents always wins over a "
                "remembered balance. The repository fills only what the "
                "documents left blank."
            ),
        },
    )


def main() -> None:
    print(f"Writing knowledge artifacts to {OUT}")
    calculation_rules()
    extraction_rules()
    classification_rules()
    form_selection_rules()
    state_tax_rules()
    carryover_rules()
    print("done")


if __name__ == "__main__":
    main()
