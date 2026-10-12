"""Per-line provenance for a computed return: source, formula, authority.

One row per line of every form and schedule the return uses, answering the three
questions a reviewer asks about any figure on a tax return:

* **Source** — which document, which page, which field this came off.
* **Formula** — the arithmetic that produced it, with the actual operands
  substituted, so the reader can redo it on paper rather than take it on trust.
* **Authority** — the Code section, revenue procedure or form instruction that
  requires the treatment, with a URL that resolves.

The trail is reconstructed from the computed return and the inputs it was given,
rather than recorded as the engine runs. That is a deliberate trade. Threading a
trail through ``Form1040Calculator.compute`` would put citation strings in the
middle of the arithmetic, where they are read by nobody and drift silently from
the computation beside them. Here the two are checked against each other: every
row carries the amount the engine produced *and* the formula that should yield
it, and ``verify`` recomputes the formula and reports any row where the two
disagree. A citation that stops matching its line is then a test failure rather
than a wrong number in a deliverable.

Nothing here is a second implementation of the tax rules. The formulas are
descriptions of what the engine did, and ``verify`` is the proof they still
describe it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.services.tax_engine.computations import ZERO, money, to_cents
from app.services.tax_engine.form_1040 import (
    AdjustmentInputs,
    CapitalGainInputs,
    DeductionInputs,
    IncomeInputs,
    PaymentInputs,
    Return1040,
    TaxpayerProfile,
)
from app.services.tax_engine.tax_authority import (
    I1040_2025,
    authority_for,
    constants_for,
    irc,
)

D = Decimal


@dataclass(slots=True)
class TrailRow:
    """One line of one form, with everything needed to audit it."""

    form: str
    line: str
    label: str
    amount: Decimal
    #: Where the number came from: a document and page, or the line that fed it.
    source: str = ""
    #: The arithmetic, with operands substituted.
    formula: str = ""
    authority: str = ""
    authority_url: str = ""
    #: Forward cross-reference: the form and line that consume this figure.
    feeds_into: str = ""
    #: Backward cross-reference: the lines this figure was computed from.
    derived_from: str = ""
    #: "extracted" | "computed" | "statutory" | "flagged"
    basis: str = "computed"
    #: Set when the figure must not be relied on without a human looking.
    flag: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "line": self.line,
            "label": self.label,
            "amount": str(self.amount),
            "source": self.source,
            "formula": self.formula,
            "authority": self.authority,
            "authority_url": self.authority_url,
            "feeds_into": self.feeds_into,
            "derived_from": self.derived_from,
            "basis": self.basis,
            "flag": self.flag,
        }


def _fmt(amount: Any) -> str:
    """A figure as a reader expects to check it: whole dollars with commas."""
    value = to_cents(money(amount))
    whole = value.quantize(D("1"))
    if value == whole:
        return f"{whole:,}"
    return f"{value:,.2f}"


def _sum_formula(parts: list[tuple[str, Decimal]], result: Decimal) -> str:
    """``1a 83,704 + 2b 214 = 83,918``, skipping the zero lines."""
    used = [(label, amount) for label, amount in parts if money(amount) != ZERO]
    if not used:
        return f"= {_fmt(result)}"
    body = " + ".join(f"{label} {_fmt(amount)}" for label, amount in used)
    return f"{body} = {_fmt(result)}"


class CalculationTrailBuilder:
    """Builds the trail for one computed return."""

    def __init__(
        self,
        *,
        result: Return1040,
        profile: TaxpayerProfile,
        income: IncomeInputs,
        adjustments: AdjustmentInputs,
        deductions: DeductionInputs,
        payments: PaymentInputs,
        capital_gains: CapitalGainInputs,
        field_provenance: dict[str, list[dict[str, str]]] | None = None,
    ) -> None:
        self.r = result
        self.profile = profile
        self.income = income
        self.adjustments = adjustments
        self.deductions = deductions
        self.payments = payments
        self.capital_gains = capital_gains
        self.provenance = field_provenance or {}
        self.year = result.tax_year
        self._lines = {line.number: line.amount for line in result.lines}

    # -- helpers -----------------------------------------------------------

    def _line(self, number: str) -> Decimal:
        return self._lines.get(number, ZERO)

    def _source_for(self, *fields: str) -> str:
        """Document and page behind one or more extracted fields.

        ``W-2 p.12; 1099-INT p.15`` — the form of answer a preparer can act on.
        When nothing was extracted for the field the return still has a figure,
        and saying so plainly is better than leaving the cell blank, which reads
        as an oversight rather than as a fact about the documents.
        """
        seen: list[str] = []
        for name in fields:
            for entry in self.provenance.get(name, []):
                label = str(entry.get("document_type") or "").replace("_", "-").upper()
                page = entry.get("page")
                text = f"{label} p.{page}" if page else label
                if text not in seen:
                    seen.append(text)
        return "; ".join(seen) if seen else "Not extracted from any document"

    def _authority(self, name: str) -> tuple[str, str]:
        """Citation and URL for a statutory constant, from tax_authority."""
        const = authority_for(self.year, name)
        if const is None:
            return ("", "")
        cite = const.authority.citation
        if const.imposed_by:
            cite = f"IRC §{const.imposed_by} — {cite}"
        return (cite, const.authority.url)

    @staticmethod
    def _irc(section: str, extra: str = "") -> tuple[str, str]:
        auth = irc(section)
        return (f"{auth.citation}{f' — {extra}' if extra else ''}", auth.url)

    def _row(self, form: str, line: str, label: str, amount: Decimal, **kw: Any) -> TrailRow:
        return TrailRow(form=form, line=line, label=label,
                        amount=to_cents(money(amount)), **kw)

    # -- the trail ---------------------------------------------------------

    def build(self) -> list[TrailRow]:
        rows: list[TrailRow] = []
        rows += self._income_rows()
        rows += self._adjustment_rows()
        rows += self._deduction_rows()
        rows += self._tax_rows()
        rows += self._credit_rows()
        rows += self._other_tax_rows()
        rows += self._payment_rows()
        rows += self._balance_rows()
        return rows

    # ---- income ----------------------------------------------------------

    def _income_rows(self) -> list[TrailRow]:
        i = self.income
        f1040 = "Form 1040"
        instr = (I1040_2025.citation, I1040_2025.url)
        rows = [
            self._row(f1040, "1a", "Wages, salaries, tips", money(i.wages),
                      source=self._source_for("wages"), basis="extracted",
                      formula="Sum of box 1 on every Form W-2",
                      authority="IRC §61(a)(1) — Form W-2 box 1",
                      authority_url=irc("61").url,
                      feeds_into="Form 1040 line 9"),
            self._row(f1040, "2a", "Tax-exempt interest", money(i.tax_exempt_interest),
                      source=self._source_for("tax_exempt_interest"), basis="extracted",
                      formula="Form 1099-INT box 8. Not included in total income",
                      authority="IRC §103 — Form 1099-INT box 8",
                      authority_url=irc("103").url,
                      feeds_into="Pub 915 Worksheet 1 line 4"),
            self._row(f1040, "2b", "Taxable interest", money(i.taxable_interest),
                      source=self._source_for("taxable_interest"), basis="extracted",
                      formula="Sum of box 1 on every Form 1099-INT",
                      authority="IRC §61(a)(4) — Form 1099-INT box 1",
                      authority_url=irc("61").url,
                      feeds_into="Form 1040 line 9"),
            self._row(f1040, "3a", "Qualified dividends", money(i.qualified_dividends),
                      source=self._source_for("qualified_dividends"), basis="extracted",
                      formula="Form 1099-DIV box 1b. Taxed at preferential rates",
                      authority="IRC §1(h)(11) — Form 1099-DIV box 1b",
                      authority_url=irc("1").url,
                      feeds_into="Qualified Dividends and Capital Gain Tax Worksheet"),
            self._row(f1040, "3b", "Ordinary dividends", money(i.ordinary_dividends),
                      source=self._source_for("ordinary_dividends"), basis="extracted",
                      formula="Sum of box 1a on every Form 1099-DIV",
                      authority="IRC §61(a)(7) — Form 1099-DIV box 1a",
                      authority_url=irc("61").url,
                      feeds_into="Form 1040 line 9"),
            self._row(f1040, "4b", "IRA distributions — taxable", money(i.ira_taxable),
                      source=self._source_for("ira_taxable", "ira_distributions"),
                      basis="extracted",
                      formula="Form 1099-R box 2a where the IRA box is checked",
                      authority="IRC §408(d) — Form 1099-R box 2a",
                      authority_url=irc("408").url,
                      feeds_into="Form 1040 line 9"),
            self._row(f1040, "5b", "Pensions and annuities — taxable",
                      money(i.pensions_taxable),
                      source=self._source_for("pensions_taxable", "pensions"),
                      basis="extracted",
                      formula="Form 1099-R box 2a",
                      authority="IRC §72 — Form 1099-R box 2a",
                      authority_url=irc("72").url,
                      feeds_into="Form 1040 line 9"),
            self._row(f1040, "6a", "Social security benefits", money(i.social_security),
                      source=self._source_for("social_security"), basis="extracted",
                      formula="Form SSA-1099 box 5 (gross benefits)",
                      authority="IRC §86 — Form SSA-1099 box 5",
                      authority_url=irc("86").url,
                      feeds_into="Pub 915 Worksheet 1 line 1"),
        ]

        # Line 6b is computed, never read: SSA-1099 reports the gross benefit
        # and says nothing about the taxable share, which depends on the rest of
        # the return.
        taxable_ss = self._line("6b")
        rows.append(
            self._row(
                f1040, "6b", "Social security — taxable", taxable_ss,
                source="Computed from line 6a and the rest of the return",
                basis="computed",
                formula=(
                    f"Pub 915 Worksheet 1 on benefits {_fmt(i.social_security)} "
                    f"against other income; result {_fmt(taxable_ss)} "
                    f"(capped at 85% = {_fmt(money(i.social_security) * D('0.85'))})"
                    if money(i.social_security) > ZERO
                    else "No benefits reported"
                ),
                authority="IRC §86 — Publication 915, Worksheet 1",
                authority_url="https://www.irs.gov/publications/p915",
                derived_from="Form 1040 lines 1a, 2a, 2b, 3b, 4b, 5b, 7, 8; Schedule 1",
                feeds_into="Form 1040 line 9",
            )
        )

        # Line 7 and its schedule.
        cg = self._line("7")
        sched_d = self.r.schedule_d
        if sched_d is not None:
            rows.append(
                self._row("Schedule D", "7", "Net short-term capital gain or (loss)",
                          sched_d.short_term_net,
                          source=self._source_for("short_term_gain", "short_term_from_k1"),
                          basis="computed",
                          formula=_sum_formula(
                              [("1a-3 proceeds", money(self.capital_gains.short_term_gain)),
                               ("5 from K-1", money(self.capital_gains.short_term_from_k1)),
                               ("6 carryover", -money(self.capital_gains.short_term_loss_carryover))],
                              sched_d.short_term_net),
                          authority="IRC §1222(5)-(6) — Schedule D Part I",
                          authority_url="https://www.irs.gov/instructions/i1040sd",
                          feeds_into="Schedule D line 16")
            )
            rows.append(
                self._row("Schedule D", "15", "Net long-term capital gain or (loss)",
                          sched_d.long_term_net,
                          source=self._source_for("long_term_gain", "capital_gain_distributions"),
                          basis="computed",
                          formula=_sum_formula(
                              [("8a-10 proceeds", money(self.capital_gains.long_term_gain)),
                               ("12 from K-1", money(self.capital_gains.long_term_from_k1)),
                               ("13 cap gain distributions", money(self.capital_gains.capital_gain_distributions)),
                               ("14 carryover", -money(self.capital_gains.long_term_loss_carryover))],
                              sched_d.long_term_net),
                          authority="IRC §1222(7)-(8) — Schedule D Part II",
                          authority_url="https://www.irs.gov/instructions/i1040sd",
                          feeds_into="Schedule D line 16; QDCG Worksheet line 3")
            )
            rows.append(
                self._row("Schedule D", "16", "Net capital gain or (loss)", sched_d.net,
                          source="Schedule D lines 7 and 15", basis="computed",
                          formula=_sum_formula(
                              [("line 7", sched_d.short_term_net),
                               ("line 15", sched_d.long_term_net)], sched_d.net),
                          authority="IRC §1222(11) — Schedule D Part III",
                          authority_url="https://www.irs.gov/instructions/i1040sd",
                          derived_from="Schedule D lines 7, 15",
                          feeds_into="Form 1040 line 7")
            )

        limited = sched_d is not None and sched_d.limited
        cap_cite, cap_url = self._authority("capital_loss_deduction")
        rows.append(
            self._row(f1040, "7", "Capital gain or (loss)", cg,
                      source="Schedule D line 16" if sched_d else self._source_for("capital_gain_loss"),
                      basis="computed" if sched_d else "extracted",
                      formula=(
                          f"Schedule D line 16 {_fmt(sched_d.net)} limited to "
                          f"{_fmt(cg)} by the annual capital loss cap"
                          if limited else
                          f"Schedule D line 16 = {_fmt(cg)}" if sched_d
                          else f"As reported = {_fmt(cg)}"
                      ),
                      authority=(cap_cite if limited else "IRC §1222 — Schedule D"),
                      authority_url=(cap_url if limited else
                                     "https://www.irs.gov/instructions/i1040sd"),
                      derived_from="Schedule D line 16" if sched_d else "",
                      feeds_into="Form 1040 line 9")
        )

        # Schedule 1 income.
        sched1 = self._line("8")
        for line, label, amount, fields in (
            ("3", "Business income or (loss) — Schedule C", money(self.income.business_income), ("business_income",)),
            ("4", "Other gains or (losses) — Form 4797", money(self.income.other_gains), ("other_gains",)),
            ("5", "Rental real estate, royalties, partnerships — Schedule E", money(self.income.rental_income), ("rental_income",)),
            ("9", "Other income", money(self.income.other_income), ("other_income",)),
        ):
            if amount != ZERO:
                rows.append(
                    self._row("Schedule 1", line, label, amount,
                              source=self._source_for(*fields), basis="extracted",
                              formula=f"As reported = {_fmt(amount)}",
                              authority="IRC §61 — Schedule 1 Part I",
                              authority_url="https://www.irs.gov/pub/irs-pdf/f1040s1.pdf",
                              feeds_into="Form 1040 line 8")
                )
        rows.append(
            self._row(f1040, "8", "Additional income from Schedule 1", sched1,
                      source="Schedule 1 Part I", basis="computed",
                      formula=_sum_formula(
                          [("Sch 1 line 3", money(self.income.business_income)),
                           ("line 4", money(self.income.other_gains)),
                           ("line 5", money(self.income.rental_income)),
                           ("line 9", money(self.income.other_income))], sched1),
                      authority="IRC §61 — Schedule 1 line 10",
                      authority_url="https://www.irs.gov/pub/irs-pdf/f1040s1.pdf",
                      derived_from="Schedule 1 lines 3, 4, 5, 9",
                      feeds_into="Form 1040 line 9")
        )

        rows.append(
            self._row(f1040, "9", "Total income", self.r.total_income,
                      source="Form 1040 lines 1a through 8", basis="computed",
                      formula=_sum_formula(
                          [("1a", money(i.wages)), ("2b", money(i.taxable_interest)),
                           ("3b", money(i.ordinary_dividends)),
                           ("4b", money(i.ira_taxable)), ("5b", money(i.pensions_taxable)),
                           ("6b", taxable_ss), ("7", cg), ("8", sched1)],
                          self.r.total_income),
                      authority=instr[0] + " — line 9", authority_url=instr[1],
                      derived_from="Form 1040 lines 1a, 2b, 3b, 4b, 5b, 6b, 7, 8",
                      feeds_into="Form 1040 line 11")
        )
        return rows

    # ---- adjustments -----------------------------------------------------

    def _adjustment_rows(self) -> list[TrailRow]:
        a = self.adjustments
        rows: list[TrailRow] = []
        components: list[tuple[str, Decimal]] = []

        entries = (
            ("11", "Educator expenses", money(a.educator_expenses),
             ("educator_expenses",), "educator_expense_cap", "62(a)(2)(D)"),
            ("13", "Health savings account deduction", money(a.hsa_deduction),
             ("hsa_deduction",), None, "223"),
            ("15", "Deductible part of self-employment tax",
             money(a.self_employment_tax_deduction),
             ("self_employment_tax_deduction",), None, "164(f)"),
            ("16", "Self-employed SEP, SIMPLE and qualified plans",
             money(a.self_employed_retirement), ("self_employed_retirement",), None, "404"),
            ("17", "Self-employed health insurance deduction",
             money(a.self_employed_health_insurance),
             ("self_employed_health_insurance",), None, "162(l)"),
            ("20", "IRA deduction", money(a.ira_deduction), ("ira_deduction",), None, "219"),
            ("21", "Student loan interest deduction", money(a.student_loan_interest),
             ("student_loan_interest",), "student_loan_interest_cap", "221"),
            ("24z", "Other adjustments", money(a.other_adjustments),
             ("other_adjustments",), None, "62"),
        )
        for line, label, amount, fields, cap_name, section in entries:
            if amount == ZERO:
                continue
            capped = amount
            formula = f"As reported = {_fmt(amount)}"
            if cap_name:
                cap = constants_for(self.year).scalars[cap_name].value
                capped = min(amount, cap)
                if capped < amount:
                    formula = (
                        f"Reported {_fmt(amount)}, limited to the statutory "
                        f"maximum {_fmt(cap)}"
                    )
            cite, url = (self._authority(cap_name) if cap_name
                         else self._irc(section))
            components.append((f"Sch 1 line {line}", capped))
            rows.append(
                self._row("Schedule 1", line, label, capped,
                          source=(
                              "Computed on Schedule SE"
                              if line == "15"
                              else self._source_for(*fields)
                          ),
                          basis="computed" if line == "15" else "extracted",
                          formula=formula, authority=cite, authority_url=url,
                          feeds_into="Form 1040 line 10")
            )

        line_10 = self._line("10")
        rows.append(
            self._row("Form 1040", "10", "Adjustments to income", line_10,
                      source="Schedule 1 Part II", basis="computed",
                      formula=_sum_formula(components, line_10),
                      authority="IRC §62 — Schedule 1 line 26",
                      authority_url=irc("62").url,
                      derived_from="Schedule 1 Part II",
                      feeds_into="Form 1040 line 11")
        )
        rows.append(
            self._row("Form 1040", "11", "Adjusted gross income",
                      self.r.adjusted_gross_income,
                      source="Form 1040 lines 9 and 10", basis="computed",
                      formula=(f"line 9 {_fmt(self.r.total_income)} − line 10 "
                               f"{_fmt(line_10)} = {_fmt(self.r.adjusted_gross_income)}"),
                      authority="IRC §62 — Form 1040 line 11",
                      authority_url=irc("62").url,
                      derived_from="Form 1040 lines 9, 10",
                      feeds_into="Form 1040 lines 12, 13a, 13b, 15; every phase-out")
        )
        return rows

    # ---- deductions ------------------------------------------------------

    def _deduction_rows(self) -> list[TrailRow]:
        rows: list[TrailRow] = []
        status = self.profile.filing_status
        std_cite, std_url = "", ""
        const = constants_for(self.year)
        sd = const.standard_deduction.get(status.value)
        if sd is not None:
            std_cite = f"IRC §{sd.imposed_by} — {sd.authority.citation}"
            std_url = sd.authority.url

        if self.r.deduction_method == "standard":
            base = sd.value if sd else ZERO
            extra_count = self.profile.age_65_or_older + self.profile.blind
            extra = const.additional_standard_deduction[
                "married" if status.value.startswith("married")
                or status.value == "qualifying_surviving_spouse"
                else "single_or_hoh"
            ].value
            formula = f"Base {_fmt(base)} for {status.value.replace('_', ' ')}"
            if extra_count:
                formula += (
                    f" + {extra_count} × {_fmt(extra)} for age 65 or blindness"
                    f" = {_fmt(self.r.deduction_taken)}"
                )
            rows.append(
                self._row("Form 1040", "12", "Standard deduction",
                          self.r.deduction_taken,
                          source=f"Statutory amount for {status.value.replace('_', ' ')}",
                          basis="statutory", formula=formula,
                          authority=std_cite, authority_url=std_url,
                          feeds_into="Form 1040 line 14")
            )
        else:
            rows += self._schedule_a_rows()
            rows.append(
                self._row("Form 1040", "12", "Itemized deductions",
                          self.r.deduction_taken,
                          source="Schedule A line 17", basis="computed",
                          formula=(f"Schedule A total {_fmt(self.r.deduction_taken)}, "
                                   f"which exceeds the standard deduction"),
                          authority="IRC §63(a) — Schedule A",
                          authority_url="https://www.irs.gov/instructions/i1040sca",
                          derived_from="Schedule A",
                          feeds_into="Form 1040 line 14")
            )

        # Line 13a — §199A.
        qbi = self.r.qbi
        if qbi is not None and qbi.deduction > ZERO:
            rate = const.scalars["qbi_rate"].value
            rows.append(
                self._row("Form 8995", "15", "Qualified business income deduction",
                          qbi.deduction,
                          source="Schedule 1 business and rental income, net of "
                                 "the deductions attributable to the business",
                          basis="computed",
                          formula=(
                              f"lesser of {rate:.0%} × QBI {_fmt(qbi.qualified_business_income)} "
                              f"= {_fmt(qbi.tentative)} and {rate:.0%} × taxable income "
                              f"less net capital gain = {_fmt(qbi.taxable_income_limit)}"
                              f" → {_fmt(qbi.deduction)}"
                          ),
                          authority="IRC §199A(a) — Form 8995",
                          authority_url="https://www.irs.gov/forms-pubs/about-form-8995",
                          derived_from="Schedule 1 lines 3, 5, 15, 16, 17",
                          feeds_into="Form 1040 line 13a",
                          flag=("Above the §199A threshold: the W-2 wage and property "
                                "limits and the specified-service phase-out apply and "
                                "are not in the documents. Confirm on Form 8995-A."
                                if qbi.above_threshold else ""))
            )
            rows.append(
                self._row("Form 1040", "13a", "Qualified business income deduction",
                          qbi.deduction, source="Form 8995 line 15", basis="computed",
                          formula=f"Form 8995 line 15 = {_fmt(qbi.deduction)}",
                          authority="IRC §199A(a) — Form 8995",
                          authority_url="https://www.irs.gov/forms-pubs/about-form-8995",
                          derived_from="Form 8995",
                          feeds_into="Form 1040 line 14")
            )

        # Line 13b — Schedule 1-A.
        if self.r.additional_deductions > ZERO:
            cite, url = self._authority("senior_deduction_amount")
            amount_each = const.scalars["senior_deduction_amount"].value
            rows.append(
                self._row("Schedule 1-A", "31", "Deduction for taxpayers age 65 or older",
                          self.r.additional_deductions,
                          source=f"{self.profile.age_65_or_older} filer(s) aged 65 or over",
                          basis="statutory",
                          formula=(
                              f"{self.profile.age_65_or_older} × {_fmt(amount_each)}, "
                              f"phased out above the threshold on modified AGI "
                              f"{_fmt(self.r.adjusted_gross_income)} "
                              f"→ {_fmt(self.r.additional_deductions)}"
                          ),
                          authority=cite, authority_url=url,
                          feeds_into="Form 1040 line 13b")
            )
            rows.append(
                self._row("Form 1040", "13b", "Additional deductions from Schedule 1-A",
                          self.r.additional_deductions,
                          source="Schedule 1-A", basis="computed",
                          formula=f"Schedule 1-A total = {_fmt(self.r.additional_deductions)}",
                          authority=cite, authority_url=url,
                          derived_from="Schedule 1-A",
                          feeds_into="Form 1040 line 14")
            )

        qbi_amount = qbi.deduction if qbi else ZERO
        line_14 = to_cents(
            self.r.deduction_taken + qbi_amount + self.r.additional_deductions
        )
        rows.append(
            self._row("Form 1040", "14", "Total deductions", line_14,
                      source="Form 1040 lines 12, 13a and 13b", basis="computed",
                      formula=_sum_formula(
                          [("12", self.r.deduction_taken), ("13a", qbi_amount),
                           ("13b", self.r.additional_deductions)], line_14),
                      authority=f"{I1040_2025.citation} — line 14",
                      authority_url=I1040_2025.url,
                      derived_from="Form 1040 lines 12, 13a, 13b",
                      feeds_into="Form 1040 line 15")
        )
        rows.append(
            self._row("Form 1040", "15", "Taxable income", self.r.taxable_income,
                      source="Form 1040 lines 11 and 14", basis="computed",
                      formula=(
                          f"line 11 {_fmt(self.r.adjusted_gross_income)} − line 14 "
                          f"{_fmt(line_14)} = {_fmt(self.r.taxable_income)}"
                          + (" (floored at zero)"
                             if self.r.adjusted_gross_income - line_14 < ZERO else "")
                      ),
                      authority="IRC §63(a) — Form 1040 line 15",
                      authority_url=irc("63").url,
                      derived_from="Form 1040 lines 11, 14",
                      feeds_into="Form 1040 line 16")
        )
        return rows

    def _schedule_a_rows(self) -> list[TrailRow]:
        d = self.deductions
        agi = self.r.adjusted_gross_income
        const = constants_for(self.year)
        rows: list[TrailRow] = []

        floor_rate = const.scalars["medical_agi_floor"].value
        medical = money(d.medical_expenses)
        if medical > ZERO:
            floor = to_cents(agi * floor_rate)
            cite, url = self._authority("medical_agi_floor")
            rows.append(
                self._row("Schedule A", "4", "Medical and dental expenses",
                          max(ZERO, to_cents(medical - floor)),
                          source=self._source_for("medical_expenses"), basis="computed",
                          formula=(f"{_fmt(medical)} − {floor_rate:.1%} × AGI "
                                   f"{_fmt(agi)} ({_fmt(floor)}) = "
                                   f"{_fmt(max(ZERO, to_cents(medical - floor)))}"),
                          authority=cite, authority_url=url,
                          feeds_into="Schedule A line 17")
            )

        elected = max(money(d.state_local_income_tax), money(d.state_local_sales_tax))
        salt_gross = to_cents(
            elected + money(d.real_estate_tax) + money(d.personal_property_tax)
        )
        if salt_gross > ZERO:
            from app.services.tax_engine.computations import salt_cap_for

            cap = salt_cap_for(self.year, self.profile.filing_status, agi)
            cite, url = self._authority("salt_cap")
            rows.append(
                self._row("Schedule A", "5e", "State and local taxes",
                          min(salt_gross, cap),
                          source=self._source_for("state_local_income_tax",
                                                  "real_estate_tax",
                                                  "personal_property_tax"),
                          basis="computed",
                          formula=(f"{_fmt(salt_gross)} limited to the cap "
                                   f"{_fmt(cap)}" if salt_gross > cap
                                   else f"{_fmt(salt_gross)}, below the {_fmt(cap)} cap"),
                          authority=cite, authority_url=url,
                          feeds_into="Schedule A line 17")
            )

        for line, label, amount, fields, section in (
            ("8a", "Home mortgage interest", money(d.mortgage_interest),
             ("mortgage_interest",), "163(h)"),
            ("9", "Investment interest", money(d.investment_interest),
             ("investment_interest",), "163(d)"),
            ("11", "Gifts to charity by cash or check", money(d.charitable_cash),
             ("charitable_cash",), "170"),
            ("12", "Gifts to charity other than cash", money(d.charitable_noncash),
             ("charitable_noncash",), "170"),
            ("15", "Casualty and theft losses", money(d.casualty_losses),
             ("casualty_losses",), "165(h)"),
        ):
            if amount != ZERO:
                cite, url = self._irc(section)
                rows.append(
                    self._row("Schedule A", line, label, amount,
                              source=self._source_for(*fields), basis="extracted",
                              formula=f"As reported = {_fmt(amount)}",
                              authority=cite, authority_url=url,
                              feeds_into="Schedule A line 17")
                )

        rows.append(
            self._row("Schedule A", "17", "Total itemized deductions",
                      self.r.deduction_taken,
                      source="Schedule A lines 4 through 16", basis="computed",
                      formula=f"Sum of Schedule A = {_fmt(self.r.deduction_taken)}",
                      authority="IRC §63(d) — Schedule A line 17",
                      authority_url="https://www.irs.gov/instructions/i1040sca",
                      feeds_into="Form 1040 line 12")
        )
        return rows

    # ---- tax, credits, other taxes, payments -----------------------------

    def _tax_rows(self) -> list[TrailRow]:
        ceiling = constants_for(self.year).scalars["tax_table_ceiling"].value
        used_table = self.r.taxable_income < ceiling
        method = (
            f"IRS Tax Table (taxable income below {_fmt(ceiling)}; each $50 band "
            "is taxed at its midpoint)"
            if used_table else "Tax Computation Worksheet (rate schedule)"
        )
        preferential = self.r.qbi is None and money(self.income.qualified_dividends) > ZERO
        return [
            self._row("Form 1040", "16", "Tax", self.r.tax_before_credits,
                      source="Form 1040 line 15", basis="computed",
                      formula=(
                          f"Tax on taxable income {_fmt(self.r.taxable_income)} "
                          f"via the {method} = {_fmt(self.r.tax_before_credits)}"
                          + (". Qualified dividends and net long-term gain are "
                             "taxed at 0/15/20% under the Qualified Dividends and "
                             "Capital Gain Tax Worksheet" if preferential else "")
                      ),
                      authority="IRC §1(j) — 2025 Tax Table, Form 1040 instructions",
                      authority_url="https://www.irs.gov/instructions/i1040tt",
                      derived_from="Form 1040 line 15",
                      feeds_into="Form 1040 lines 22 and 24")
        ]

    def _credit_rows(self) -> list[TrailRow]:
        rows: list[TrailRow] = []
        ctc = self._line("19")
        if ctc > ZERO or self.profile.qualifying_children or self.profile.other_dependents:
            cite, url = self._authority("child_tax_credit")
            per_child = constants_for(self.year).scalars["child_tax_credit"].value
            per_other = constants_for(self.year).scalars["other_dependent_credit"].value
            rows.append(
                self._row("Schedule 8812", "14", "Child tax credit and credit for "
                          "other dependents", ctc,
                          source=(f"{self.profile.qualifying_children} qualifying "
                                  f"child(ren), {self.profile.other_dependents} other "
                                  "dependent(s)"),
                          basis="statutory",
                          formula=(
                              f"{self.profile.qualifying_children} × {_fmt(per_child)} "
                              f"+ {self.profile.other_dependents} × {_fmt(per_other)}, "
                              f"phased out on AGI {_fmt(self.r.adjusted_gross_income)} "
                              f"→ {_fmt(ctc)}"
                          ),
                          authority=cite, authority_url=url,
                          feeds_into="Form 1040 line 19")
            )
        rows.append(
            self._row("Form 1040", "21", "Total nonrefundable credits",
                      self.r.total_credits,
                      source="Form 1040 lines 19 and 20", basis="computed",
                      formula=(f"Credits {_fmt(ctc)} limited to the tax "
                               f"{_fmt(self.r.tax_before_credits)} — a nonrefundable "
                               f"credit cannot reduce tax below zero "
                               f"→ {_fmt(self.r.total_credits)}"),
                      authority="IRC §26(a) — Form 1040 line 21",
                      authority_url=irc("26").url,
                      derived_from="Form 1040 lines 19, 20",
                      feeds_into="Form 1040 line 22")
        )
        return rows

    def _other_tax_rows(self) -> list[TrailRow]:
        rows: list[TrailRow] = []
        if self.r.self_employment_tax > ZERO:
            const = constants_for(self.year)
            rate = const.scalars["se_net_earnings_rate"].value
            net = to_cents(money(self.income.business_income) * rate)
            rows.append(
                self._row("Schedule SE", "12", "Self-employment tax",
                          self.r.self_employment_tax,
                          source="Schedule 1 line 3 (Schedule C net profit)",
                          basis="computed",
                          formula=(
                              f"Net profit {_fmt(self.income.business_income)} × "
                              f"{rate} = {_fmt(net)} net earnings; 12.4% OASDI on the "
                              f"lesser of that and the wage base less W-2 wages "
                              f"{_fmt(self.income.wages)}, plus 2.9% Medicare "
                              f"→ {_fmt(self.r.self_employment_tax)}"
                          ),
                          authority="IRC §1401 — Schedule SE",
                          authority_url="https://www.irs.gov/instructions/i1040sse",
                          feeds_into="Schedule 2 line 4")
            )
        if self.r.additional_medicare_tax > ZERO:
            cite, url = self._authority("additional_medicare_rate")
            rows.append(
                self._row("Form 8959", "18", "Additional Medicare tax",
                          self.r.additional_medicare_tax,
                          source="Wages and self-employment earnings", basis="computed",
                          formula=(f"0.9% of wages plus net self-employment earnings "
                                   f"above the threshold "
                                   f"= {_fmt(self.r.additional_medicare_tax)}"),
                          authority=cite, authority_url=url,
                          feeds_into="Schedule 2 line 11")
            )
        if self.r.net_investment_income_tax > ZERO:
            cite, url = self._authority("niit_rate")
            rows.append(
                self._row("Form 8960", "17", "Net investment income tax",
                          self.r.net_investment_income_tax,
                          source="Interest, dividends, capital gain and passive income",
                          basis="computed",
                          formula=(f"3.8% of the lesser of net investment income and "
                                   f"modified AGI {_fmt(self.r.adjusted_gross_income)} "
                                   f"over the threshold "
                                   f"= {_fmt(self.r.net_investment_income_tax)}"),
                          authority=cite, authority_url=url,
                          feeds_into="Schedule 2 line 12")
            )
        if self.r.other_taxes > ZERO:
            rows.append(
                self._row("Form 1040", "23", "Other taxes from Schedule 2",
                          self.r.other_taxes,
                          source="Schedule 2 Part II", basis="computed",
                          formula=_sum_formula(
                              [("Sch SE", self.r.self_employment_tax),
                               ("Form 8959", self.r.additional_medicare_tax),
                               ("Form 8960", self.r.net_investment_income_tax)],
                              self.r.other_taxes),
                          authority="Schedule 2 (Form 1040), Part II",
                          authority_url="https://www.irs.gov/pub/irs-pdf/f1040s2.pdf",
                          derived_from="Schedule SE; Form 8959; Form 8960",
                          feeds_into="Form 1040 line 24")
            )
        rows.append(
            self._row("Form 1040", "24", "Total tax", self.r.total_tax,
                      source="Form 1040 lines 22 and 23", basis="computed",
                      formula=(f"line 16 {_fmt(self.r.tax_before_credits)} − line 21 "
                               f"{_fmt(self.r.total_credits)} + line 23 "
                               f"{_fmt(self.r.other_taxes)} = {_fmt(self.r.total_tax)}"),
                      authority=f"{I1040_2025.citation} — line 24",
                      authority_url=I1040_2025.url,
                      derived_from="Form 1040 lines 16, 21, 23",
                      feeds_into="Form 1040 lines 34 and 37")
        )
        return rows

    def _payment_rows(self) -> list[TrailRow]:
        rows = [
            self._row("Form 1040", "25d", "Federal income tax withheld",
                      self.r.federal_withheld,
                      source=self._source_for("federal_withheld"), basis="extracted",
                      formula="Sum of W-2 box 2 and 1099 withholding boxes",
                      authority="IRC §31(a) — Form 1040 line 25d",
                      authority_url=irc("31").url,
                      feeds_into="Form 1040 line 33")
        ]
        for line, label, amount, cite, url, note in (
            ("26", "Estimated tax payments and amount applied from prior return",
             self._line("26"), "IRC §6654 — Form 1040 line 26", irc("6654").url,
             "Payments made during the year plus any prior-year overpayment applied"),
            ("27", "Earned income credit", self._line("27"),
             *self._authority_pair_eitc(),
             "Computed from earned income and AGI under §32, not extracted"),
            ("28", "Additional child tax credit", self._line("28"),
             "IRC §24(d) — Schedule 8812 Part II",
             "https://www.irs.gov/instructions/i1040s8",
             "The refundable remainder of the child tax credit"),
        ):
            if amount > ZERO:
                rows.append(
                    self._row("Form 1040", line, label, amount,
                              source=note, basis="computed",
                              formula=f"= {_fmt(amount)}",
                              authority=cite, authority_url=url,
                              feeds_into="Form 1040 line 33")
                )
        rows.append(
            self._row("Form 1040", "33", "Total payments", self.r.total_payments,
                      source="Form 1040 lines 25d through 32", basis="computed",
                      formula=_sum_formula(
                          [("25d", self.r.federal_withheld), ("26", self._line("26")),
                           ("27", self._line("27")), ("28", self._line("28"))],
                          self.r.total_payments),
                      authority=f"{I1040_2025.citation} — line 33",
                      authority_url=I1040_2025.url,
                      derived_from="Form 1040 lines 25d, 26, 27, 28, 29",
                      feeds_into="Form 1040 lines 34 and 37")
        )
        return rows

    def _authority_pair_eitc(self) -> tuple[str, str]:
        return ("IRC §32 — Schedule EIC", irc("32").url)

    def _balance_rows(self) -> list[TrailRow]:
        rows: list[TrailRow] = []
        if self.r.refund > ZERO or self.r.applied_to_next_year > ZERO:
            overpaid = to_cents(self.r.total_payments - self.r.total_tax)
            rows.append(
                self._row("Form 1040", "34", "Amount overpaid", overpaid,
                          source="Form 1040 lines 33 and 24", basis="computed",
                          formula=(f"line 33 {_fmt(self.r.total_payments)} − line 24 "
                                   f"{_fmt(self.r.total_tax)} = {_fmt(overpaid)}"),
                          authority=f"{I1040_2025.citation} — line 34",
                          authority_url=I1040_2025.url,
                          derived_from="Form 1040 lines 24, 33",
                          feeds_into="Form 1040 lines 35a and 36")
            )
            if self.r.refund > ZERO:
                rows.append(
                    self._row("Form 1040", "35a", "Amount refunded to you", self.r.refund,
                              source="Form 1040 line 34 less line 36", basis="computed",
                              formula=(f"overpayment {_fmt(overpaid)} − applied forward "
                                       f"{_fmt(self.r.applied_to_next_year)} = "
                                       f"{_fmt(self.r.refund)}"),
                              authority="IRC §6402 — Form 1040 line 35a",
                              authority_url=irc("6402").url,
                              derived_from="Form 1040 line 34")
                )
            if self.r.applied_to_next_year > ZERO:
                rows.append(
                    self._row("Form 1040", "36", "Applied to next year's estimated tax",
                              self.r.applied_to_next_year,
                              source="Taxpayer election", basis="extracted",
                              formula=f"Elected amount = {_fmt(self.r.applied_to_next_year)}",
                              authority="IRC §6402(b) — Form 1040 line 36",
                              authority_url=irc("6402").url,
                              derived_from="Form 1040 line 34")
                )
        if self.r.amount_owed > ZERO:
            rows.append(
                self._row("Form 1040", "37", "Amount you owe", self.r.amount_owed,
                          source="Form 1040 lines 24 and 33", basis="computed",
                          formula=(f"line 24 {_fmt(self.r.total_tax)} − line 33 "
                                   f"{_fmt(self.r.total_payments)} = "
                                   f"{_fmt(self.r.amount_owed)}"),
                          authority=f"{I1040_2025.citation} — line 37",
                          authority_url=I1040_2025.url,
                          derived_from="Form 1040 lines 24, 33")
            )
        return rows


def build_trail(
    *,
    result: Return1040,
    engine_inputs: dict[str, Any],
    field_provenance: dict[str, list[dict[str, str]]] | None = None,
) -> list[TrailRow]:
    """Trail for a return, from the same inputs the calculator was given."""
    return CalculationTrailBuilder(
        result=result,
        profile=engine_inputs["profile"],
        income=engine_inputs.get("income") or IncomeInputs(),
        adjustments=engine_inputs.get("adjustments") or AdjustmentInputs(),
        deductions=engine_inputs.get("deductions") or DeductionInputs(),
        payments=engine_inputs.get("payments") or PaymentInputs(),
        capital_gains=engine_inputs.get("capital_gains") or CapitalGainInputs(),
        field_provenance=field_provenance,
    ).build()


def verify(rows: list[TrailRow], result: Return1040) -> list[str]:
    """Check the trail still describes the return it claims to describe.

    Returns a list of complaints, empty when every row agrees with the engine.
    Run as part of output generation: a workpaper whose formulas have drifted
    from the computation is worse than one with no formulas at all, because it
    reads as evidence.
    """
    problems: list[str] = []
    lines = {line.number: line.amount for line in result.lines}

    for row in rows:
        if row.form != "Form 1040":
            continue
        if row.line not in lines:
            continue
        if abs(to_cents(row.amount) - to_cents(lines[row.line])) > D("0.01"):
            problems.append(
                f"Trail row {row.form} line {row.line} shows {row.amount} but "
                f"the computed return has {lines[row.line]}."
            )

    for row in rows:
        if not row.authority:
            problems.append(f"{row.form} line {row.line} has no authority cited.")
        elif not row.authority_url.startswith("https://"):
            problems.append(
                f"{row.form} line {row.line} cites {row.authority!r} with no "
                "resolvable URL."
            )
        if not row.formula:
            problems.append(f"{row.form} line {row.line} has no formula shown.")

    return problems
