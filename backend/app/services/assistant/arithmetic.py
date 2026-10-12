"""Checking the arithmetic an answer shows, without adding any figure of its own.

A calculation answer shows its steps ("$27,400 × 5.8% = $1,589.20",
"Taxable income: $54,000 ($75,000 − $15,700 − $5,300)") and leads with a
result. The model does that arithmetic, and on 2026-10-11 a Maine answer
led with $3,374.88, totalled its steps to $3,411.70 and noted $3,411.50 -
three figures for one tax, each looking checked.

This module recomputes only what the answer itself wrote: an expression and
the figure it says the expression equals. It never introduces a rate, a
threshold or an amount (CLAUDE.md rule 8 - figures come from sources), and
anything it cannot parse is left alone, so prose can never be mistaken for a
wrong sum. Two checks:

* **A step that does not add up** - an expression whose stated result differs
  from its value by more than rounding.
* **A headline that disagrees with the total** - the lead paragraph states a
  figure close to the "Total ..." line's figure but not equal to it.

Messages carry numbers only, formatted here: they are fed back into the
regeneration prompt, and model text never is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

#: Rounding a shown step may carry: a tax table rounds to the dollar.
TOLERANCE = Decimal("1.00")
#: A lead figure this close to the total (relatively) is meant to be it.
_SAME_FIGURE = Decimal("0.25")

_NUMBER = r"\$?\s?\d[\d,]*(?:\.\d+)?%?"
_BOLD_NUMBER = re.compile(rf"(?P<marker>\*\*|__)(?P<number>{_NUMBER})(?P=marker)")
_OP = r"[×x*÷/+\-−–]"
#: "EXPR = RESULT": two or more numbers joined by operators, then "=".
_EQUALS = re.compile(
    rf"(?P<expr>{_NUMBER}(?:\s*{_OP}\s*{_NUMBER})+)\s*=\s*(?P<result>{_NUMBER})"
)
#: "RESULT (EXPR)": a figure followed by the expression that produced it.
_PAREN = re.compile(
    rf"(?P<result>{_NUMBER})\s*\((?P<expr>{_NUMBER}(?:\s*{_OP}\s*{_NUMBER})+)\)"
)
_TOKEN = re.compile(rf"\s*(?:(?P<num>{_NUMBER})|(?P<op>{_OP}))")
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
_BASE_PLUS_RATE = re.compile(r"^[ \t*]*(?:plus\b|\+)[ \t*]*\d+(?:\.\d+)?[ \t]*%", re.IGNORECASE)
_TOTAL_LINE = re.compile(r"^[\s>*+\-\d.)]*\**\s*(?:the\s+)?(?:total|estimated total)\b[^\n:]*:\**\s*(?P<rest>[^\n]*)",
                         re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Finding:
    code: str  # "arithmetic_error" | "inconsistent_total"
    message: str


def _number(token: str) -> Decimal | None:
    text = token.replace("$", "").replace(",", "").replace(" ", "")
    percent = text.endswith("%")
    try:
        value = Decimal(text.rstrip("%"))
    except InvalidOperation:
        return None
    return value / 100 if percent else value


def evaluate(expression: str) -> Decimal | None:
    """The value of ``a op b op c ...`` with × and ÷ before + and −, or None."""
    values: list[Decimal] = []
    ops: list[str] = []
    position = 0
    expect_number = True
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if not match or match.end() == position:
            if expression[position:].strip():
                return None
            break
        position = match.end()
        if expect_number:
            if match["num"] is None:
                return None
            number = _number(match["num"])
            if number is None:
                return None
            values.append(number)
        else:
            if match["op"] is None:
                return None
            ops.append({"x": "×", "*": "×", "/": "÷", "-": "−", "–": "−"}.get(match["op"], match["op"]))
        expect_number = not expect_number
    if expect_number or not ops:
        return None
    # × and ÷ first, left to right.
    terms = [values[0]]
    signs: list[str] = []
    for op, value in zip(ops, values[1:]):
        if op == "×":
            terms[-1] *= value
        elif op == "÷":
            if value == 0:
                return None
            terms[-1] /= value
        else:
            signs.append(op)
            terms.append(value)
    total = terms[0]
    for sign, term in zip(signs, terms[1:]):
        total = total + term if sign == "+" else total - term
    return total


def _fmt(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,}"


def check(text: str) -> list[Finding]:
    text = _BOLD_NUMBER.sub(r"\g<number>", text)
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for pattern in (_EQUALS, _PAREN):
        for match in pattern.finditer(text):
            expr, result = match["expr"], match["result"]
            if (expr, result) in seen or "%" in result or _not_arithmetic(expr, parenthesised=pattern is _PAREN):
                continue
            seen.add((expr, result))
            value, stated = evaluate(expr), _number(result)
            if value is None or stated is None:
                continue
            if abs(value - stated) > TOLERANCE:
                shown = re.sub(r"\s+", " ", expr.strip())
                findings.append(Finding(
                    "arithmetic_error",
                    f"A calculation step does not add up: {_digits_only(shown)} is {_fmt(value)}, "
                    f"not {_fmt(stated)}. Recompute every step and use the corrected figure everywhere.",
                ))
    findings.extend(_headline_vs_total(text))
    return findings


def _not_arithmetic(expression: str, *, parenthesised: bool) -> bool:
    """Things shaped like a sum that are not one: "$7,000 (2024-2025)" is a
    year range, "Form 1040 - 2026" a title. A parenthesised expression must
    carry money, a rate or a multiplication; years alone are never a sum."""
    numbers = [n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", expression)]
    if all(n.isdigit() and 1900 <= int(n) <= 2100 for n in numbers):
        return True
    return parenthesised and not re.search(r"[$%×x*]", expression)


def _digits_only(expression: str) -> str:
    """The expression with nothing but numbers and operators - no model words."""
    return " ".join(re.findall(rf"{_NUMBER}|{_OP}", expression))


def _headline_vs_total(text: str) -> list[Finding]:
    totals = [m for m in _TOTAL_LINE.finditer(text)]
    rest = totals[-1]["rest"] if totals else ""
    money = _MONEY.search(rest)
    equation = _EQUALS.search(rest)
    if equation and "%" not in equation["result"] and (money is None or equation.start() <= money.start()):
        total = _number(equation["result"])
    elif money:
        total = _number(money.group())
    else:
        # No "Total" line: the last step's result is the answer's result
        # (the 2026-10-11 eval: "... = $3,411.70 (pre-credit tax)").
        steps = [m for m in _EQUALS.finditer(text) if "%" not in m["result"]]
        if not steps:
            return []
        total = _number(steps[-1]["result"])
    lead = _lead(text)
    if total is None or total <= 0 or not lead:
        return []
    near = [
        figure for match in _MONEY.finditer(lead)
        if (figure := _number(match.group())) is not None
        and not _BASE_PLUS_RATE.match(lead[match.end():])
        and abs(figure - total) <= total * _SAME_FIGURE
    ]
    if near and all(abs(figure - total) > TOLERANCE for figure in near):
        return [Finding(
            "inconsistent_total",
            f"The first sentence gives {_fmt(near[0])} but the calculation totals {_fmt(total)}. "
            "Do the arithmetic once and give the same result in the first sentence and the total line.",
        )]
    return []


def _lead(text: str) -> str:
    for block in re.split(r"\n[ \t]*\n", text):
        block = block.strip()
        if block and not block.startswith("#"):
            return block
    return ""
