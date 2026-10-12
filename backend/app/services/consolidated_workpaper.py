"""The single workpaper: every form, every schedule, every number's provenance.

One file per return. It replaces the eight separate artifacts the package used
to emit — a form, a merged return, a workpaper, a summary, reviewer notes, an
exception list, a traceability CSV and an audit log — because scattering the
evidence across eight files meant the reviewer's first job was reassembling it,
and the file that answered "where did this number come from" was never the file
open in front of them.

Sheets, in the order a reviewer works:

  Index              what this return says, and what still needs a human
  Form 1040          the return as filed, with live formulas between the lines
  Schedules          every supporting form, grouped, with its own subtotals
  Calculation Trail  one row per line: source, formula, authority, cross-refs
  Cross-Reference    each figure forward to what consumes it and back to source
  Source Documents   which document and page each extracted field came off
  Exceptions         anything a preparer must resolve before signing
  Authorities        every citation used, with a URL and whether it was verified

The Form 1040 sheet carries real Excel formulas rather than pasted results, so a
reviewer can change an input cell and watch the return recompute. That is the
difference between a workpaper and a printout: the arithmetic is inspectable,
and a figure that does not move when its inputs move is visibly broken.

SECURITY: this runs after rehydration and contains real taxpayer identity. It
belongs in the output zone and is never sent outbound.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from app.core.logging import get_logger
from app.services.tax_engine.calculation_trail import TrailRow, build_trail, verify
from app.services.tax_engine.form_1040 import Return1040
from app.services.tax_engine.tax_authority import constants_for

logger = get_logger(__name__)

D = Decimal

# --- presentation ----------------------------------------------------------
# Arial throughout, per the house convention for deliverables. Blue marks a
# figure that came off a document; black marks one the engine computed. That is
# the financial-model convention (inputs blue, formulas black) and it happens to
# be exactly the distinction a tax reviewer cares about most.
_FONT = "Arial"
_INK = "1F1F1F"
_INPUT_BLUE = "0000FF"
_LINK_GREEN = "008000"
_FLAG_RED = "9B2C2C"
_HEADER_FILL = "1F3864"
_BAND_FILL = "EEF2F8"
_MONEY = '#,##0;(#,##0);"-"'
_MONEY_CENTS = '#,##0.00;(#,##0.00);"-"'


@dataclass(slots=True)
class WorkpaperInputs:
    """Everything the workpaper needs, gathered by the caller."""

    computed_return: Return1040
    engine_inputs: dict[str, Any]
    identity: dict[str, Any]
    field_provenance: dict[str, list[dict[str, str]]]
    review_items: list[dict[str, str]]
    documents: list[dict[str, Any]]
    confidence_scores: dict[str, Any]
    workflow_id: str = ""
    ocr_summary: dict[str, Any] | None = None


class ConsolidatedWorkpaperBuilder:
    """Renders one return into one workbook."""

    def __init__(self, data: WorkpaperInputs) -> None:
        self.d = data
        self.r = data.computed_return
        self.trail: list[TrailRow] = build_trail(
            result=self.r,
            engine_inputs=data.engine_inputs,
            field_provenance=data.field_provenance,
        )
        #: Populated by the Form 1040 sheet so later sheets can point at cells.
        self._cell_for_line: dict[str, str] = {}

    # -- public ------------------------------------------------------------

    def build(self) -> bytes:
        from openpyxl import Workbook

        book = Workbook()
        book.remove(book.active)

        self._sheet_form_1040(book)     # first, so line cells are known
        self._sheet_index(book)
        self._sheet_schedules(book)
        self._sheet_trail(book)
        self._sheet_cross_reference(book)
        self._sheet_sources(book)
        self._sheet_exceptions(book)
        self._sheet_authorities(book)

        # Index reads best first; openpyxl appends, so reorder once at the end.
        order = ["Index", "Form 1040", "Schedules", "Calculation Trail",
                 "Cross-Reference", "Source Documents", "Exceptions", "Authorities"]
        book._sheets = [book[name] for name in order if name in book.sheetnames]
        book.active = 0

        buffer = BytesIO()
        book.save(buffer)
        return buffer.getvalue()

    # -- helpers -----------------------------------------------------------

    def _new(self, book: Any, title: str, widths: list[float]) -> Any:
        sheet = book.create_sheet(title)
        from openpyxl.utils import get_column_letter

        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        sheet.sheet_view.showGridLines = False
        return sheet

    def _title(self, sheet: Any, row: int, text: str, subtitle: str = "") -> int:
        from openpyxl.styles import Font

        sheet.cell(row=row, column=1, value=text).font = Font(
            name=_FONT, size=15, bold=True, color=_HEADER_FILL
        )
        if subtitle:
            sheet.cell(row=row + 1, column=1, value=subtitle).font = Font(
                name=_FONT, size=9, italic=True, color="5A6472"
            )
            return row + 3
        return row + 2

    def _header(self, sheet: Any, row: int, labels: list[str]) -> int:
        from openpyxl.styles import Alignment, Font, PatternFill

        for column, label in enumerate(labels, start=1):
            cell = sheet.cell(row=row, column=column, value=label)
            cell.font = Font(name=_FONT, size=9, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=_HEADER_FILL)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.row_dimensions[row].height = 26
        sheet.freeze_panes = sheet.cell(row=row + 1, column=1)
        return row + 1

    @staticmethod
    def _text(cell: Any, *, bold: bool = False, color: str = _INK,
              size: int = 10, wrap: bool = False, italic: bool = False) -> None:
        from openpyxl.styles import Alignment, Font

        cell.font = Font(name=_FONT, size=size, bold=bold, color=color, italic=italic)
        if wrap:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    @staticmethod
    def _money(cell: Any, *, cents: bool = False, bold: bool = False,
               color: str = _INK) -> None:
        from openpyxl.styles import Alignment, Font

        cell.font = Font(name=_FONT, size=10, bold=bold, color=color)
        cell.number_format = _MONEY_CENTS if cents else _MONEY
        cell.alignment = Alignment(horizontal="right")

    @staticmethod
    def _number(amount: Any) -> float | None:
        """A float, when the value is a number at all — otherwise None.

        Engine figures arrive as Decimals, but the Source Documents sheet
        prints the *extracted* value of every field, which is whatever the
        model transcribed off the page: "1,234.00", "$5,000", "(320)" for a
        negative, and — for every field that is not money — a name, a date or
        an address. `Decimal("A TAXPAYER")` raises `InvalidOperation`, the
        exception escaped to the caller's `except`, and one such row therefore
        cost the entire workbook: measured over the sample corpus, *every*
        document logged "Consolidated workpaper not built" and shipped a
        package with no workpaper in it.
        """
        if amount is None or amount == "":
            return None
        if isinstance(amount, int | float | Decimal):
            return float(amount)
        text = re.sub(r"[,$\s]", "", str(amount))
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1]
        try:
            value = float(Decimal(text))
        except (InvalidOperation, ValueError):
            return None
        return -value if negative else value

    @staticmethod
    def _f(amount: Any) -> float:
        number = ConsolidatedWorkpaperBuilder._number(amount)
        return 0.0 if number is None else number

    # -- Form 1040 ---------------------------------------------------------

    def _sheet_form_1040(self, book: Any) -> None:
        """The return as filed, with the arithmetic between lines left live.

        Every subtotal is an Excel formula over the cells above it. A reviewer
        who corrects an extracted figure sees the whole return move, which is
        the only way to check that a correction lands where it should.
        """
        sheet = self._new(book, "Form 1040", [9, 52, 16, 46])
        row = self._title(
            sheet,
            1,
            f"Form 1040 — U.S. Individual Income Tax Return {self.r.tax_year}",
            f"{self._describe_taxpayer()} · filing status: "
            f"{self.r.filing_status.replace('_', ' ')} · "
            f"deduction taken: {self.r.deduction_method}",
        )
        row = self._header(sheet, row, ["Line", "Description", "Amount", "Note"])

        lines = {line.number: line for line in self.r.lines}
        cells: dict[str, str] = {}

        def put(number: str, label: str, amount: Any, note: str = "",
                formula: str | None = None, bold: bool = False) -> None:
            nonlocal row
            self._text(sheet.cell(row=row, column=1, value=number), bold=bold)
            self._text(sheet.cell(row=row, column=2, value=label), bold=bold)
            cell = sheet.cell(row=row, column=3)
            cell.value = formula if formula else self._f(amount)
            # Blue where the figure came off a document, black where computed —
            # the same convention a financial model uses for inputs.
            self._money(cell, cents=True, bold=bold,
                        color=_INK if formula else _INPUT_BLUE)
            if note:
                self._text(sheet.cell(row=row, column=4, value=note), size=9,
                           color="5A6472", wrap=True)
            cells[number] = f"C{row}"
            row += 1

        def blank(heading: str = "") -> None:
            nonlocal row
            if heading:
                self._text(sheet.cell(row=row, column=2, value=heading), bold=True,
                           color=_HEADER_FILL, size=9)
            row += 1

        blank("INCOME")
        income_lines = ["1a", "2b", "3b", "4b", "5b", "6b", "7", "8"]
        for number in income_lines:
            line = lines.get(number)
            if line is None:
                continue
            put(number, line.label, line.amount, line.note)
        for number in ("2a", "3a"):
            line = lines.get(number)
            if line is not None and line.amount:
                put(number, line.label, line.amount, line.note)

        present = [cells[n] for n in income_lines if n in cells]
        put("9", "Total income", self.r.total_income,
            "Sum of the income lines above",
            formula=("=" + "+".join(present)) if present else None, bold=True)

        blank("ADJUSTED GROSS INCOME")
        if "10" in lines:
            put("10", lines["10"].label, lines["10"].amount, lines["10"].note)
        put("11", "Adjusted gross income", self.r.adjusted_gross_income,
            "Line 9 less line 10",
            formula=f"={cells['9']}-{cells.get('10', '0')}" if "10" in cells
            else f"={cells['9']}", bold=True)

        blank("DEDUCTIONS")
        put("12", f"{self.r.deduction_method.capitalize()} deduction",
            self.r.deduction_taken,
            lines["12"].note if "12" in lines else "")
        if "13a" in lines:
            put("13a", lines["13a"].label, lines["13a"].amount, lines["13a"].note)
        if self.r.additional_deductions:
            put("13b", "Additional deductions from Schedule 1-A",
                self.r.additional_deductions,
                "Schedule 1-A, separate from the age addition in line 12")
        deduction_cells = [cells[n] for n in ("12", "13a", "13b") if n in cells]
        put("14", "Total deductions", None, "Lines 12, 13a and 13b",
            formula="=" + "+".join(deduction_cells), bold=True)
        put("15", "Taxable income", self.r.taxable_income,
            "Line 11 less line 14, not below zero",
            formula=f"=MAX(0,{cells['11']}-{cells['14']})", bold=True)

        blank("TAX AND CREDITS")
        ceiling = constants_for(self.r.tax_year).scalars["tax_table_ceiling"].value
        put("16", "Tax", self.r.tax_before_credits,
            f"IRS Tax Table (taxable income below {ceiling:,.0f})"
            if self.r.taxable_income < ceiling
            else "Tax Computation Worksheet")
        for number in ("19", "21"):
            if number in lines:
                put(number, lines[number].label, lines[number].amount,
                    lines[number].note)

        blank("OTHER TAXES")
        for number, label in (("23a", "Self-employment tax (Schedule SE)"),
                              ("23b", "Additional Medicare tax (Form 8959)"),
                              ("23c", "Net investment income tax (Form 8960)")):
            if number in lines:
                put(number, label, lines[number].amount)
        if self.r.other_taxes:
            component_cells = [cells[n] for n in ("23a", "23b", "23c") if n in cells]
            put("23", "Total other taxes (Schedule 2)", self.r.other_taxes,
                "Schedule 2 Part II",
                formula="=" + "+".join(component_cells) if component_cells else None)
        put("24", "Total tax", self.r.total_tax, "Line 16 less line 21 plus line 23",
            formula=(
                f"=MAX(0,{cells['16']}-{cells.get('21', '0')}"
                f"+{cells.get('23', '0')})"
            ), bold=True)

        blank("PAYMENTS")
        put("25d", "Federal income tax withheld", self.r.federal_withheld)
        for number in ("26", "27", "28", "29"):
            if number in lines:
                put(number, lines[number].label, lines[number].amount,
                    lines[number].note)
        payment_cells = [cells[n] for n in ("25d", "26", "27", "28", "29")
                         if n in cells]
        put("33", "Total payments", self.r.total_payments,
            "Withholding plus estimated payments and refundable credits",
            formula="=" + "+".join(payment_cells), bold=True)

        blank("REFUND OR AMOUNT DUE")
        if self.r.refund > 0 or self.r.applied_to_next_year > 0:
            put("34", "Amount overpaid", None, "Line 33 less line 24",
                formula=f"=MAX(0,{cells['33']}-{cells['24']})", bold=True)
            if self.r.refund > 0:
                put("35a", "Amount refunded to you", self.r.refund,
                    formula=f"={cells['34']}-{self._f(self.r.applied_to_next_year)}",
                    bold=True)
            if self.r.applied_to_next_year > 0:
                put("36", "Applied to next year's estimated tax",
                    self.r.applied_to_next_year, "Taxpayer election")
        if self.r.amount_owed > 0:
            put("37", "Amount you owe", None, "Line 24 less line 33",
                formula=f"=MAX(0,{cells['24']}-{cells['33']})", bold=True)

        self._cell_for_line = cells

        row += 1
        self._text(
            sheet.cell(row=row, column=2,
                       value="Blue figures were read from a source document; black "
                             "figures are computed by formula from the cells above. "
                             "Every line is traced on the Calculation Trail sheet."),
            size=9, italic=True, color="5A6472", wrap=True)

    # -- Index -------------------------------------------------------------

    def _sheet_index(self, book: Any) -> None:
        sheet = self._new(book, "Index", [34, 24, 64])
        row = self._title(
            sheet, 1,
            f"Tax Return Workpaper — {self.r.tax_year}",
            "One file. Every form, every schedule, and the source, formula and "
            "authority behind every figure.",
        )

        outstanding = len(self.d.review_items)
        flagged = [r for r in self.trail if r.flag]
        drift = verify(self.trail, self.r)

        facts = [
            ("Taxpayer", self._describe_taxpayer()),
            ("Filing status", self.r.filing_status.replace("_", " ").title()),
            ("Tax year", str(self.r.tax_year)),
            ("Adjusted gross income", f"{self.r.adjusted_gross_income:,.2f}"),
            ("Taxable income", f"{self.r.taxable_income:,.2f}"),
            ("Total tax", f"{self.r.total_tax:,.2f}"),
            ("Total payments", f"{self.r.total_payments:,.2f}"),
            (
                "Refund" if self.r.refund > 0 else "Amount you owe",
                f"{(self.r.refund or self.r.amount_owed):,.2f}",
            ),
            ("Deduction method", self.r.deduction_method),
            ("Open review items", str(outstanding)),
            ("Lines flagged for a preparer", str(len(flagged))),
            ("Workflow", self.d.workflow_id or "—"),
            ("Prepared", datetime.now(UTC).strftime("%d %b %Y %H:%M UTC")),
        ]
        for label, value in facts:
            self._text(sheet.cell(row=row, column=1, value=label), bold=True, size=10)
            cell = sheet.cell(row=row, column=2, value=value)
            self._text(cell, size=10,
                       color=_FLAG_RED if label.startswith(("Open", "Lines")) and value != "0"
                       else _INK)
            row += 1

        row += 1
        status = (
            "READY FOR REVIEW"
            if not outstanding and not drift
            else "NOT READY — resolve the Exceptions sheet before signing"
        )
        self._text(sheet.cell(row=row, column=1, value=status), bold=True, size=12,
                   color=_LINK_GREEN if not outstanding and not drift else _FLAG_RED)
        row += 2

        if drift:
            self._text(sheet.cell(row=row, column=1,
                                  value="Calculation trail disagrees with the "
                                        "computed return:"), bold=True, color=_FLAG_RED)
            row += 1
            for problem in drift[:10]:
                self._text(sheet.cell(row=row, column=1, value=problem), size=9,
                           color=_FLAG_RED, wrap=True)
                row += 1
            row += 1

        self._text(sheet.cell(row=row, column=1, value="What is in this file"),
                   bold=True, size=11, color=_HEADER_FILL)
        row += 1
        for name, purpose in (
            ("Form 1040", "The return as filed, with live formulas between the lines."),
            ("Schedules", "Every supporting form and schedule, with its own subtotals."),
            ("Calculation Trail",
             ("One row per line: where it came from, how it was computed, and "
              "the authority that requires it.")),
            ("Cross-Reference",
             ("Each figure forward to what consumes it and back to what "
              "produced it.")),
            ("Source Documents",
             "Which document and page each extracted field came off."),
            ("Exceptions", "Everything a preparer must resolve before signing."),
            ("Authorities",
             "Every citation used, with a URL and its verification status."),
        ):
            self._text(sheet.cell(row=row, column=1, value=name), bold=True, size=10)
            self._text(sheet.cell(row=row, column=2, value=purpose), size=9,
                       color="5A6472", wrap=True)
            sheet.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
            row += 1

    def _describe_taxpayer(self) -> str:
        name = str(self.d.identity.get("taxpayer_name") or "").strip()
        spouse = str(self.d.identity.get("spouse_name") or "").strip()
        # "A and B" only where the return has two people on it. An extracted
        # spouse name that did not corroborate a married return now resolves
        # to single rather than refusing, and heading a single return with two
        # names says the return is something it is not.
        joint = str(self.r.filing_status or "") in {"married_joint", "married_separate"}
        if name and spouse and joint:
            return f"{name} and {spouse}"
        return name or "Taxpayer name not extracted"

    # -- Schedules ---------------------------------------------------------

    def _sheet_schedules(self, book: Any) -> None:
        """Every supporting form, grouped, so the 1040's totals have a behind."""
        sheet = self._new(book, "Schedules", [22, 9, 52, 18])
        row = self._title(
            sheet, 1, "Supporting forms and schedules",
            "Each figure here feeds a Form 1040 line. The Calculation Trail sheet "
            "shows which one.",
        )
        row = self._header(sheet, row, ["Form", "Line", "Description", "Amount"])

        supporting = [r for r in self.trail if r.form != "Form 1040"]
        if not supporting:
            self._text(sheet.cell(row=row, column=1,
                                  value="This return needs no supporting schedules."),
                       italic=True, color="5A6472")
            return

        from openpyxl.styles import PatternFill

        current = None
        for entry in supporting:
            if entry.form != current:
                current = entry.form
                for column in range(1, 5):
                    sheet.cell(row=row, column=column).fill = PatternFill(
                        "solid", fgColor=_BAND_FILL
                    )
                self._text(sheet.cell(row=row, column=1, value=current), bold=True,
                           color=_HEADER_FILL)
                row += 1
            self._text(sheet.cell(row=row, column=2, value=entry.line), size=10)
            self._text(sheet.cell(row=row, column=3, value=entry.label), size=10)
            self._money(sheet.cell(row=row, column=4, value=self._f(entry.amount)),
                        cents=True)
            row += 1

    # -- Calculation trail -------------------------------------------------

    def _sheet_trail(self, book: Any) -> None:
        """The heart of the file: every line's source, formula and authority."""
        sheet = self._new(book, "Calculation Trail",
                          [16, 8, 38, 15, 30, 56, 46, 13, 30])
        row = self._title(
            sheet, 1, "Calculation trail",
            "Every figure on this return, with the document it came from, the "
            "arithmetic that produced it, and the authority that requires that "
            "treatment. A URL that does not resolve is a defect, not a citation.",
        )
        row = self._header(sheet, row, [
            "Form", "Line", "Description", "Amount", "Source",
            "Formula", "Authority", "Basis", "Flag",
        ])

        from openpyxl.styles import Font

        for entry in self.trail:
            self._text(sheet.cell(row=row, column=1, value=entry.form), size=9)
            self._text(sheet.cell(row=row, column=2, value=entry.line), size=9)
            self._text(sheet.cell(row=row, column=3, value=entry.label), size=9,
                       wrap=True)
            self._money(sheet.cell(row=row, column=4, value=self._f(entry.amount)),
                        cents=True,
                        color=_INPUT_BLUE if entry.basis == "extracted" else _INK)
            self._text(sheet.cell(row=row, column=5, value=entry.source), size=9,
                       wrap=True, color="5A6472")
            self._text(sheet.cell(row=row, column=6, value=entry.formula), size=9,
                       wrap=True)
            cite = sheet.cell(row=row, column=7, value=entry.authority)
            if entry.authority_url:
                cite.hyperlink = entry.authority_url
                cite.font = Font(name=_FONT, size=9, color=_LINK_GREEN,
                                 underline="single")
            else:
                self._text(cite, size=9)
            self._text(sheet.cell(row=row, column=8, value=entry.basis), size=9,
                       color="5A6472")
            if entry.flag:
                self._text(sheet.cell(row=row, column=9, value=entry.flag), size=9,
                           color=_FLAG_RED, wrap=True)
            row += 1

        sheet.auto_filter.ref = f"A{row - len(self.trail) - 1}:I{row - 1}"

    # -- Cross-reference ---------------------------------------------------

    def _sheet_cross_reference(self, book: Any) -> None:
        """Trace any number in both directions.

        Forward answers "if I change this, what moves?"; backward answers "this
        looks wrong, where did it come from?". A reviewer needs both and they are
        not the same index.
        """
        sheet = self._new(book, "Cross-Reference", [16, 8, 38, 15, 48, 48])
        row = self._title(
            sheet, 1, "Cross-reference",
            "Forward: what consumes this figure. Backward: what produced it.",
        )
        row = self._header(sheet, row, [
            "Form", "Line", "Description", "Amount",
            "Feeds into (forward)", "Derived from (backward)",
        ])

        for entry in self.trail:
            if not entry.feeds_into and not entry.derived_from:
                continue
            self._text(sheet.cell(row=row, column=1, value=entry.form), size=9)
            self._text(sheet.cell(row=row, column=2, value=entry.line), size=9)
            self._text(sheet.cell(row=row, column=3, value=entry.label), size=9,
                       wrap=True)
            self._money(sheet.cell(row=row, column=4, value=self._f(entry.amount)),
                        cents=True)
            self._text(sheet.cell(row=row, column=5, value=entry.feeds_into or "—"),
                       size=9, wrap=True, color=_LINK_GREEN)
            self._text(sheet.cell(row=row, column=6,
                                  value=entry.derived_from or entry.source or "—"),
                       size=9, wrap=True, color="5A6472")
            row += 1

    # -- Source documents --------------------------------------------------

    def _sheet_sources(self, book: Any) -> None:
        sheet = self._new(book, "Source Documents", [30, 22, 10, 16, 14, 40])
        row = self._title(
            sheet, 1, "Source documents",
            "Each extracted field, the document and page it came off, and the "
            "confidence the extraction reported.",
        )
        row = self._header(sheet, row, [
            "Field", "Document", "Page", "Amount", "Confidence", "Note",
        ])

        for name in sorted(self.d.field_provenance):
            for entry in self.d.field_provenance[name]:
                self._text(sheet.cell(row=row, column=1, value=name), size=9)
                self._text(
                    sheet.cell(row=row, column=2,
                               value=str(entry.get("document_type") or "")
                               .replace("_", "-").upper()),
                    size=9)
                self._text(sheet.cell(row=row, column=3,
                                      value=entry.get("page") or "—"), size=9)
                # Not every extracted field is money: a filing status, a name
                # and a date of birth all land here too. Printing those as
                # 0.00 in a money column is worse than leaving the column
                # empty, so a non-numeric value is shown as what it is.
                amount = self._number(entry.get("amount"))
                if amount is None:
                    self._text(
                        sheet.cell(row=row, column=6,
                                   value=str(entry.get("amount") or "")[:80]),
                        size=9, color=_INPUT_BLUE)
                else:
                    self._money(sheet.cell(row=row, column=4, value=amount),
                                cents=True, color=_INPUT_BLUE)
                score = self.d.confidence_scores.get(name)
                cell = sheet.cell(row=row, column=5,
                                  value=f"{float(score):.0%}" if score else "—")
                self._text(cell, size=9,
                           color=_FLAG_RED if score and float(score) < 0.85 else _INK)
                row += 1

        if self.d.documents:
            row += 1
            self._text(sheet.cell(row=row, column=1, value="Documents read"),
                       bold=True, size=11, color=_HEADER_FILL)
            row += 1
            for document in self.d.documents:
                self._text(sheet.cell(row=row, column=1,
                                      value=str(document.get("document_type") or "")
                                      .replace("_", "-").upper()), size=9)
                self._text(sheet.cell(row=row, column=2,
                                      value=str(document.get("pages") or "")), size=9)
                confidence = document.get("confidence")
                self._text(sheet.cell(row=row, column=5,
                                      value=f"{float(confidence):.0%}"
                                      if confidence else "—"), size=9)
                row += 1

        if self.d.ocr_summary:
            row += 1
            summary = self.d.ocr_summary
            self._text(
                sheet.cell(row=row, column=1,
                           value=(
                               f"OCR read {summary.get('coverage', 0):.0%} of the "
                               f"document at {summary.get('mean_confidence', 0):.0%} "
                               f"mean confidence. Unread pages count as zero, so "
                               f"this figure describes the whole document."
                           )),
                size=9, italic=True, color="5A6472", wrap=True)
            sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)

    # -- Exceptions --------------------------------------------------------

    def _sheet_exceptions(self, book: Any) -> None:
        sheet = self._new(book, "Exceptions", [10, 26, 40, 70])
        row = self._title(
            sheet, 1, "Exceptions",
            "Everything a preparer must resolve before signing. An empty sheet "
            "means the return computed cleanly — it does not mean it is correct.",
        )
        row = self._header(sheet, row, ["#", "Field", "Title", "What to do"])

        number = 0
        for item in self.d.review_items:
            number += 1
            self._text(sheet.cell(row=row, column=1, value=number), size=9)
            self._text(sheet.cell(row=row, column=2,
                                  value=item.get("field_name") or "—"), size=9)
            self._text(sheet.cell(row=row, column=3, value=item.get("title") or ""),
                       size=9, bold=True, wrap=True)
            self._text(sheet.cell(row=row, column=4,
                                  value=item.get("description") or ""), size=9,
                       wrap=True, color="5A6472")
            row += 1

        for entry in self.trail:
            if not entry.flag:
                continue
            number += 1
            self._text(sheet.cell(row=row, column=1, value=number), size=9)
            self._text(sheet.cell(row=row, column=2,
                                  value=f"{entry.form} line {entry.line}"), size=9)
            self._text(sheet.cell(row=row, column=3, value=entry.label), size=9,
                       bold=True, wrap=True)
            self._text(sheet.cell(row=row, column=4, value=entry.flag), size=9,
                       wrap=True, color=_FLAG_RED)
            row += 1

        for warning in self.r.warnings:
            number += 1
            self._text(sheet.cell(row=row, column=1, value=number), size=9)
            self._text(sheet.cell(row=row, column=2, value="engine"), size=9)
            self._text(sheet.cell(row=row, column=3, value="Computation warning"),
                       size=9, bold=True)
            self._text(sheet.cell(row=row, column=4, value=warning), size=9,
                       wrap=True, color="5A6472")
            row += 1

        if number == 0:
            self._text(sheet.cell(row=row, column=2,
                                  value="No exceptions were raised."),
                       italic=True, color=_LINK_GREEN)

    # -- Authorities -------------------------------------------------------

    def _sheet_authorities(self, book: Any) -> None:
        """Every citation, so a reviewer can check the law rather than trust it."""
        sheet = self._new(book, "Authorities", [34, 62, 56, 14, 52])
        row = self._title(
            sheet, 1, f"Authorities relied on — tax year {self.r.tax_year}",
            "Every statutory figure used in this return, the document that sets "
            "it, and whether that pairing was read out of the document or "
            "recalled. Anything marked 'unverified' must be confirmed before "
            "filing.",
        )
        row = self._header(sheet, row, [
            "Constant", "Authority", "Link", "Verified", "Note",
        ])

        from openpyxl.styles import Font

        constants = constants_for(self.r.tax_year)
        entries = list(constants.scalars.items())
        entries += [(f"standard_deduction.{k}", v)
                    for k, v in constants.standard_deduction.items()]
        entries += [("dependent_standard_deduction_floor",
                     constants.dependent_standard_deduction_floor)]

        for name, const in sorted(entries):
            self._text(sheet.cell(row=row, column=1,
                                  value=f"{name} = {const.value:,}"), size=9)
            citation = const.authority.citation
            if const.imposed_by:
                citation = f"IRC §{const.imposed_by} — {citation}"
            self._text(sheet.cell(row=row, column=2, value=citation), size=9,
                       wrap=True)
            link = sheet.cell(row=row, column=3, value=const.authority.url)
            link.hyperlink = const.authority.url
            link.font = Font(name=_FONT, size=9, color=_LINK_GREEN,
                             underline="single")
            verified = sheet.cell(row=row, column=4,
                                  value="yes" if const.verified else "UNVERIFIED")
            self._text(verified, size=9, bold=not const.verified,
                       color=_INK if const.verified else _FLAG_RED)
            self._text(sheet.cell(row=row, column=5, value=const.note), size=9,
                       wrap=True, color="5A6472")
            row += 1


def build_consolidated_workpaper(data: WorkpaperInputs) -> bytes:
    """Render one return into one workbook."""
    return ConsolidatedWorkpaperBuilder(data).build()
