"""Render a computed return onto the real IRS Form 1040.

The engine produces numbered 1040 lines; this writes them into the official
fillable PDF so the deliverable is the form a preparer actually signs, rather
than a spreadsheet that merely contains the same figures.

SECURITY: this runs AFTER rehydration and therefore handles real taxpayer
identity. The output belongs in the output zone and is never sent outbound.

Field names come from the IRS's own AcroForm (``f1_47[0]`` and friends). They
are opaque, so every entry in ``LINE_TO_FIELD`` was verified by locating the
widget on the page and reading the printed label beside or above it — see
``docs/form_1040_mapping.md``. Two traps found that way:

* ``f1_11``–``f1_13`` look like the name row by position but are the "tax year
  beginning / ending" header boxes. The name fields are ``f1_14``–``f1_16``.
* The engine numbers some lines differently from the printed form: engine "7"
  is form line 7a, engine "12" is form line 12e, engine "11" is 11a and 11b.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.tax_engine.form_1040 import Return1040
from app.services.tax_engine.tax_tables import FilingStatusTax

logger = get_logger(__name__)

#: The blank form, downloaded from irs.gov/pub/irs-pdf/f1040.pdf.
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "resources" / "f1040_2025.pdf"

#: Tax year the bundled template is printed for. Filling a 2024 return onto the
#: 2025 form would produce a document that looks official and is wrong.
TEMPLATE_TAX_YEAR = 2025


#: Engine line number -> AcroForm field. Verified against the printed labels.
LINE_TO_FIELD: dict[str, str] = {
    # --- Page 1: income -------------------------------------------------
    "1a": "f1_47[0]",   # Wages, salaries, tips
    "1z": "f1_57[0]",   # Add lines 1a through 1h
    "2a": "f1_58[0]",   # Tax-exempt interest
    "2b": "f1_59[0]",   # Taxable interest
    "3a": "f1_60[0]",   # Qualified dividends
    "3b": "f1_61[0]",   # Ordinary dividends
    "4a": "f1_62[0]",   # IRA distributions
    "4b": "f1_63[0]",   # IRA distributions - taxable
    "5a": "f1_65[0]",   # Pensions and annuities
    "5b": "f1_66[0]",   # Pensions - taxable
    "6a": "f1_68[0]",   # Social security benefits
    "6b": "f1_69[0]",   # Social security - taxable
    "7": "f1_70[0]",    # Capital gain or (loss)  [form line 7a]
    "8": "f1_72[0]",    # Additional income from Schedule 1
    "9": "f1_73[0]",    # Total income
    "10": "f1_74[0]",   # Adjustments to income
    "11": "f1_75[0]",   # Adjusted gross income   [form line 11a]
    # --- Page 2: tax and payments ---------------------------------------
    "11b": "f2_01[0]",  # AGI carried forward
    "12": "f2_02[0]",   # Standard or itemized deduction  [form line 12e]
    "13b": "f2_04[0]",  # Additional deductions from Schedule 1-A
    "14": "f2_05[0]",   # Add lines 12e, 13a, 13b
    "15": "f2_06[0]",   # Taxable income
    "16": "f2_08[0]",   # Tax
    "18": "f2_10[0]",   # Add lines 16 and 17
    "19": "f2_11[0]",   # Child tax credit / other dependents
    "21": "f2_13[0]",   # Total nonrefundable credits
    "22": "f2_14[0]",   # Subtract line 21 from line 18
    "23": "f2_15[0]",   # Other taxes (incl. self-employment)
    "24": "f2_16[0]",   # Total tax
    "25a": "f2_17[0]",  # Withheld, Form(s) W-2
    "25b": "f2_18[0]",  # Withheld, Form(s) 1099
    "25d": "f2_20[0]",  # Add lines 25a through 25c
    "26": "f2_21[0]",   # Estimated tax payments
    "27a": "f2_23[0]",  # Earned income credit
    "28": "f2_24[0]",   # Additional child tax credit
    "29": "f2_25[0]",   # American opportunity credit
    "32": "f2_28[0]",   # Total other payments and refundable credits
    "33": "f2_29[0]",   # Total payments
    "34": "f2_30[0]",   # Amount overpaid
    "35a": "f2_31[0]",  # Refunded to you
    "36": "f2_34[0]",   # Applied to next year's estimated tax
    "37": "f2_35[0]",   # Amount you owe
}

#: Identity fields. Verified from the labels printed above each box.
IDENTITY_FIELDS: dict[str, str] = {
    "first_name": "f1_14[0]",   # Your first name and middle initial
    "last_name": "f1_15[0]",    # Last name
    "ssn": "f1_16[0]",          # Your social security number
    "spouse_first_name": "f1_17[0]",
    "spouse_last_name": "f1_18[0]",
    "spouse_ssn": "f1_19[0]",
    "street_address": "f1_20[0]",  # Home address (number and street)
    "apartment": "f1_21[0]",       # Apt. no.
    "city": "f1_22[0]",            # City, town, or post office
    "state": "f1_23[0]",           # State
    "zip_code": "f1_24[0]",        # ZIP code
}

#: Lines printed even when they come to zero, because on these a zero is a
#: computed result a reader needs to see ("total tax: 0"), not an absent entry.
ALWAYS_SHOWN_LINES: frozenset[str] = frozenset(
    {"9", "11", "11b", "12", "14", "15", "16", "18", "22", "24", "25d", "33"}
)

#: Filing status is one radio group whose export values are 1-5, in the order
#: the boxes are printed on the form.
FILING_STATUS_FIELD = "c1_8"
FILING_STATUS_VALUES: dict[FilingStatusTax, str] = {
    FilingStatusTax.SINGLE: "1",
    FilingStatusTax.MARRIED_JOINT: "2",
    FilingStatusTax.MARRIED_SEPARATE: "3",
    FilingStatusTax.HEAD_OF_HOUSEHOLD: "4",
    FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE: "5",
}


@dataclass(slots=True)
class TaxpayerIdentity:
    """Real identity values, supplied after rehydration."""

    first_name: str = ""
    last_name: str = ""
    ssn: str = ""
    spouse_first_name: str = ""
    spouse_last_name: str = ""
    spouse_ssn: str = ""
    street_address: str = ""
    apartment: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""

    def as_fields(self) -> dict[str, str]:
        # `slots=True` means there is no __dict__ to iterate.
        return {
            IDENTITY_FIELDS[entry.name]: getattr(self, entry.name)
            for entry in dataclass_fields(self)
            if entry.name in IDENTITY_FIELDS and getattr(self, entry.name)
        }


def format_money(amount: Decimal) -> str:
    """Whole dollars, thousands-separated, losses in parentheses.

    The IRS instructions permit whole-dollar reporting and the prepared returns
    in the sample corpus use it, so 11221.98 is written as 11,222 — matching
    what a preparer's software produces. Parentheses are the form's own
    convention for a negative figure.
    """
    dollars = Decimal(amount).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if dollars < 0:
        return f"({abs(dollars):,})"
    return f"{dollars:,}"


class Form1040Filler:
    """Writes a computed return onto the official IRS Form 1040 PDF."""

    def __init__(self, template_path: Path | None = None) -> None:
        self._template = template_path or TEMPLATE_PATH

    def fill(
        self,
        computed_return: Return1040,
        identity: TaxpayerIdentity | None = None,
    ) -> bytes:
        """Return the filled form as PDF bytes.

        Raises if the return's tax year does not match the bundled template —
        a 2024 return rendered onto the 2025 form would carry the wrong rate
        schedule in its printed instructions while looking entirely official.
        """
        if not self._template.exists():
            raise FileNotFoundError(
                f"Form 1040 template missing at {self._template}. Download it "
                "from https://www.irs.gov/pub/irs-pdf/f1040.pdf"
            )
        if computed_return.tax_year != TEMPLATE_TAX_YEAR:
            raise ValueError(
                f"Return is for {computed_return.tax_year} but the bundled "
                f"Form 1040 is the {TEMPLATE_TAX_YEAR} revision. Add the "
                "matching year's template before rendering this return."
            )

        values = self._build_values(computed_return)
        if identity is not None:
            fields = identity.as_fields()
            if not _files_with_a_spouse(computed_return.filing_status):
                # The spouse name and SSN boxes at the top of Form 1040 belong
                # to a joint or separate return; on any other status they are
                # not boxes this taxpayer has. `build_identity_from_facts`
                # copies whatever extraction found, and an uncorroborated
                # spouse name used to stop the return being computed at all —
                # now that it resolves to single, the name would otherwise be
                # printed on a single return, attributing a spouse to somebody
                # the return says has none.
                for name in ("spouse_first_name", "spouse_last_name", "spouse_ssn"):
                    fields.pop(IDENTITY_FIELDS[name], None)
            values.update(fields)

        return self._write(values, computed_return)

    # ------------------------------------------------------------- internals

    def _build_values(self, result: Return1040) -> dict[str, str]:
        """Map engine lines onto form fields, deriving the form-only subtotals."""
        by_number = {line.number: line.amount for line in result.lines}

        # Lines the form carries that the engine folds into others. Written
        # explicitly so the printed arithmetic reads correctly top to bottom;
        # a preparer checking line 14 against 12e must find them consistent.
        derived: dict[str, Decimal] = {
            "1z": by_number.get("1a", Decimal(0)),
            "11b": result.adjusted_gross_income,
            "14": result.deduction_taken,
            "18": result.tax_before_credits,
            "22": max(Decimal(0), result.tax_before_credits - result.total_credits),
            # 25a/25b deliberately absent: the extraction reports a single
            # federal_withheld figure with no split between W-2 and 1099
            # sources. Writing the whole amount onto 25a would assert it was
            # all W-2 withholding, which we do not know. The total goes on 25d
            # and the empty sub-lines show a preparer what still needs
            # apportioning. 25d is withholding only: it once carried
            # total_payments, which printed estimated payments as though
            # they had been withheld and left 25d + 26 not footing to 33.
            "25d": result.federal_withheld,
            "33": result.total_payments,
        }

        values: dict[str, str] = {}
        for number, field in LINE_TO_FIELD.items():
            amount = by_number.get(number, derived.get(number))
            if amount is None:
                continue
            # Prepared returns leave untouched lines blank rather than printing
            # a row of zeros; a printed 0 should mean "this was computed and it
            # is zero", which is true of the running totals and of nothing
            # else. Filling every line with 0 also buries the figures that
            # matter among two dozen that do not.
            if amount == 0 and number not in ALWAYS_SHOWN_LINES:
                continue
            values[field] = format_money(amount)

        return values

    def _write(self, values: dict[str, str], result: Return1040) -> bytes:
        import fitz

        status = FilingStatusTax(result.filing_status)
        status_value = FILING_STATUS_VALUES.get(status)

        filled = 0
        with fitz.open(self._template) as document:
            for page in document:
                for widget in page.widgets():
                    name = widget.field_name
                    short = name.split(".")[-1]

                    if short in values:
                        widget.field_value = values[short]
                        widget.update()
                        filled += 1
                    elif status_value and short.startswith(FILING_STATUS_FIELD):
                        # One radio group; only the widget whose on-state
                        # matches the status is switched on.
                        if widget.on_state() == status_value:
                            widget.field_value = status_value
                            widget.update()
                            filled += 1

            output = document.tobytes()

        missing = sorted(set(values) - {v for v in values if v})
        logger.info(
            "Form 1040 rendered: %d field(s) filled, filing status %s",
            filled,
            result.filing_status,
        )
        if missing:  # pragma: no cover - defensive
            logger.warning("Form 1040 fields with no value: %s", missing)
        return output


def _split_name(full_name: str) -> tuple[str, str]:
    """Given names and surname, the way the form's two boxes want them.

    Names arrive as a single string ("MICHAEL J ANDERSON") far more often than
    as separate fields, so the last whitespace-separated token is the surname
    and everything before it is the given names.
    """
    parts = str(full_name or "").strip().split()
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return ("", parts[0])
    return (" ".join(parts[:-1]), parts[-1])


#: Extraction fact -> identity attribute, for the fields that copy across as-is.
#: Written as data rather than as a sequence of assignments because the version
#: that listed them by hand covered five of the nine and the omission was
#: invisible: spouse_name and spouse_ssn were extracted, survived the output
#: allow-list, were rehydrated to real values, and were then dropped here. Every
#: joint return went out with the spouse boxes empty, which the IRS rejects.
_DIRECT_IDENTITY_FIELDS: tuple[tuple[str, str], ...] = (
    ("ssn", "ssn"),
    ("spouse_ssn", "spouse_ssn"),
    ("street_address", "street_address"),
    ("apartment", "apartment"),
    ("city", "city"),
    ("state", "state"),
    ("zip_code", "zip_code"),
)


def build_identity_from_facts(facts: dict[str, Any]) -> TaxpayerIdentity:
    """Assemble identity from rehydrated extraction facts."""
    identity = TaxpayerIdentity()

    identity.first_name, identity.last_name = _split_name(
        str(facts.get("taxpayer_name") or "")
    )
    identity.spouse_first_name, identity.spouse_last_name = _split_name(
        str(facts.get("spouse_name") or "")
    )

    for source, target in _DIRECT_IDENTITY_FIELDS:
        value = facts.get(source)
        if value:
            setattr(identity, target, str(value).strip())

    return identity


def _files_with_a_spouse(status: object) -> bool:
    """Whether this status puts a second person on the return.

    `Return1040.filing_status` is serialized as its string value in some paths
    and held as the enum in others, so both are accepted rather than assuming
    one.
    """
    raw = status.value if isinstance(status, FilingStatusTax) else str(status or "")
    return raw in {
        FilingStatusTax.MARRIED_JOINT.value,
        FilingStatusTax.MARRIED_SEPARATE.value,
    }


def missing_identity_for(
    identity: TaxpayerIdentity, status: FilingStatusTax
) -> list[str]:
    """Identity boxes the IRS requires for this filing status but which are empty.

    A joint return without the spouse's name and SSN is rejected on submission,
    so this is a filing blocker rather than a cosmetic gap, and the caller
    raises it as one.
    """
    required = ["first_name", "last_name", "ssn", "street_address", "city",
                "state", "zip_code"]
    if status in {FilingStatusTax.MARRIED_JOINT, FilingStatusTax.MARRIED_SEPARATE}:
        required += ["spouse_first_name", "spouse_last_name", "spouse_ssn"]
    return [name for name in required if not getattr(identity, name, "")]
