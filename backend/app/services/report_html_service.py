"""Self-contained HTML rendering of one computed return's explanation.

A single file with no external assets and no script: it can be archived beside
the client's workpaper, mailed to a reviewer, or opened years later without
this application running. It carries what the results screen shows — every
Form 1040 line, the operands behind it, the arithmetic check, the sources, and
the authority — so a question about a figure can be answered from the file
instead of by re-running the pipeline.

Rendered from ``ReturnExplanation.to_dict()``, the same payload the UI
consumes, so the document and the screen cannot drift apart.

SECURITY: the report contains real taxpayer figures. It belongs to the output
zone's audience and is never sent outbound. Every interpolated value is
HTML-escaped — the text being escaped includes model-extracted document
content — and citation links are restricted to http(s) so a malformed rule
entry cannot become a ``javascript:`` link in an archived file.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.explanation_service import ReturnExplanation

#: Mirrors PROVENANCE_LABEL in frontend/src/components/ReturnExplanation.tsx.
_PROVENANCE_LABEL: dict[str, str] = {
    "source_document": "From your documents",
    "computed": "Calculated from other lines",
    "prior_year": "From last year's return",
    "election": "Your choice",
    "taxpayer_profile": "From your details",
    "assumption": "Assumed — nothing stated it",
}

_PROVENANCE_TONE: dict[str, str] = {
    "source_document": "success",
    "computed": "info",
    "prior_year": "purple",
    "election": "purple",
    "taxpayer_profile": "info",
    "assumption": "warning",
}

_STATUS_LABEL: dict[str, str] = {
    "verified": "✓ Verified from documents",
    "computed": "✓ Calculated",
    "needs_review": "⚠ Review recommended",
}

_STATUS_TONE: dict[str, str] = {
    "verified": "success",
    "computed": "info",
    "needs_review": "warning",
}

_OPERAND_SIGN: dict[str, str] = {"add": "+", "subtract": "−", "info": ""}

_SAFE_URL = re.compile(r"^https?://", re.IGNORECASE)

#: Anything else is replaced, so the name cannot inject a Content-Disposition
#: header or carry path syntax onto the reviewer's machine. Dots go too: the
#: extension is appended here, and ".." in a saved filename helps nobody.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_]+")


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _money(raw: str) -> str:
    """Format a serialized engine amount the way the results screen does."""
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return str(raw)
    magnitude = abs(value)
    body = (
        f"{magnitude:,.0f}"
        if magnitude == magnitude.to_integral_value()
        else f"{magnitude:,.2f}"
    )
    return f"(${body})" if value < 0 else f"${body}"


def _is_zero(raw: str) -> bool:
    try:
        return Decimal(str(raw)) == 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _is_empty_line(line: dict[str, Any]) -> bool:
    """A line the form carries but this return never touched."""
    return _is_zero(line["amount"]) and line["provenance"] == "assumption"


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip()


def _badge(text: str, tone: str) -> str:
    return f'<span class="badge {_e(tone)}">{_e(text)}</span>'


def _provenance_badge(provenance: str) -> str:
    return _badge(
        _PROVENANCE_LABEL.get(provenance, _humanize(provenance)),
        _PROVENANCE_TONE.get(provenance, "neutral"),
    )


def _rule_block(rule: dict[str, Any]) -> str:
    links = "".join(
        f'<a href="{_e(c["url"])}" target="_blank" rel="noreferrer noopener">'
        f"{_e(c['title'])}</a>"
        for c in rule.get("citations", [])
        if _SAFE_URL.match(str(c.get("url", "")))
    )
    effective = (
        f"{rule['effective_from']}–{rule['effective_to']}"
        if rule.get("effective_to")
        else f"{rule['effective_from']} onward"
    )
    parts = [
        '<div class="rule">',
        '<div class="rule-head">',
        f"<strong>{_e(rule['title'])}</strong>",
    ]
    if rule.get("irc_section"):
        parts.append(f'<span class="cite">{_e(rule["irc_section"])}</span>')
    if not rule.get("verified", True):
        parts.append(_badge("⚠ Citation unconfirmed", "warning"))
    parts.append("</div>")
    parts.append(f"<p>{_e(rule['plain_english'])}</p>")
    if rule.get("notes"):
        parts.append(f'<p class="subtle">{_e(rule["notes"])}</p>')
    if links:
        parts.append(f'<div class="rule-links">{links}</div>')
    parts.append(f'<div class="subtle">Applies to tax years {_e(effective)}</div>')
    parts.append("</div>")
    return "".join(parts)


def _operands_table(operands: list[dict[str, Any]]) -> str:
    if not operands:
        return '<p class="subtle">This line stands on its own.</p>'
    rows = []
    for operand in operands:
        amount = (
            "—"
            if operand["role"] == "info" and _is_zero(operand["amount"])
            else _money(operand["amount"])
        )
        detail = (
            f'<div class="subtle">{_e(operand["detail"])}</div>'
            if operand.get("detail")
            else ""
        )
        rows.append(
            "<tr>"
            f'<td class="sign">{_e(_OPERAND_SIGN.get(operand["role"], ""))}</td>'
            f"<td><div>{_e(operand['label'])}</div>{detail}</td>"
            f"<td>{_provenance_badge(operand['provenance'])}</td>"
            f'<td class="num">{_e(amount)}</td>'
            "</tr>"
        )
    return f'<table class="operands"><tbody>{"".join(rows)}</tbody></table>'


def _line_block(line: dict[str, Any]) -> str:
    checks = []
    if line.get("arithmetic_checked"):
        checks.append(
            "<div>✓ Re-added from the inputs above and matched this figure.</div>"
        )
    if line.get("confidence") is not None:
        pct = round(float(line["confidence"]) * 100)
        checks.append(
            f"<div>Reading confidence on the weakest input: {pct}%</div>"
        )
    if line.get("note"):
        checks.append(f"<div>{_e(line['note'])}</div>")

    checks_html = (
        '<div class="checks">' + "".join(checks) + "</div>" if checks else ""
    )

    docs = "".join(
        f'<span class="chip">{_e(_humanize(doc))}</span>'
        for doc in line.get("source_documents", [])
    )
    docs_html = f'<div class="chips">{docs}</div>' if docs else ""

    status_badge = _badge(
        _STATUS_LABEL.get(line["status"], line["status"]),
        _STATUS_TONE.get(line["status"], "neutral"),
    )

    return (
        '<details class="line" open>'
        "<summary>"
        f'<span class="line-no">{_e(line["line"])}</span>'
        f'<span class="line-main"><span class="line-label">{_e(line["label"])}'
        f'</span><span class="subtle">{_e(line["narrative"])}</span></span>'
        f'<span class="line-status">{status_badge}</span>'
        f'<span class="num line-amount">{_e(_money(line["amount"]))}</span>'
        "</summary>"
        '<div class="line-body">'
        "<section><h4>Where these numbers came from</h4>"
        f"{_operands_table(line.get('operands', []))}{docs_html}"
        "</section>"
        "<section><h4>How it was worked out</h4>"
        f'<code class="formula">{_e(line.get("formula") or "—")}</code>'
        f"{checks_html}"
        "</section>"
        "<section><h4>The rule behind it</h4>"
        f"{_rule_block(line['rule'])}"
        "</section>"
        "</div>"
        "</details>"
    )


def _summary_section(data: dict[str, Any]) -> str:
    s = data["summary"]
    cells = [
        ("Filing status", _e(s.get("filing_status", "")), ""),
        ("Total income", _e(_money(s.get("total_income", "0"))), ""),
        (
            "Adjusted gross income",
            _e(_money(s.get("adjusted_gross_income", "0"))),
            "",
        ),
        (
            "Deductions applied",
            _e(_money(s.get("deductions", "0"))),
            _e(f"{s.get('deduction_method', '')} deduction"),
        ),
        ("Taxable income", _e(_money(s.get("taxable_income", "0"))), ""),
        ("Credits applied", _e(_money(s.get("credits", "0"))), ""),
        ("Total tax", _e(_money(s.get("total_tax", "0"))), ""),
        ("Payments", _e(_money(s.get("payments", "0"))), ""),
    ]
    grid = "".join(
        f'<div class="cell"><div class="subtle">{_e(label)}</div>'
        f'<div class="value">{value}</div>'
        + (f'<div class="subtle">{hint}</div>' if hint else "")
        + "</div>"
        for label, value, hint in cells
    )

    owed = not _is_zero(s.get("amount_owed", "0"))
    refund = not _is_zero(s.get("refund", "0"))
    carried = not _is_zero(s.get("applied_to_next_year", "0"))
    outcome_label = (
        "Amount you owe"
        if owed
        else "Your refund"
        if refund
        else "Nothing owed, nothing refunded"
    )
    outcome_value = _money(s.get("amount_owed" if owed else "refund", "0"))
    outcome_tone = "owed" if owed else "refund"
    carry_note = (
        f'<div class="subtle">{_e(_money(s["applied_to_next_year"]))} was left '
        "with the IRS toward next year's tax instead of being refunded.</div>"
        if carried
        else ""
    )

    return (
        '<section id="summary" class="card">'
        f"<h2>{_e(data['tax_year'])} tax summary</h2>"
        f'<div class="grid">{grid}</div>'
        f'<div class="outcome {outcome_tone}">'
        f'<div class="subtle">{_e(outcome_label)}</div>'
        f'<div class="outcome-value">{_e(outcome_value)}</div>'
        f"{carry_note}"
        "</div>"
        "</section>"
    )


def _flow_section(data: dict[str, Any]) -> str:
    blocks = []
    step = 0
    for section in data["sections"]:
        lines = [ln for ln in section["lines"] if not _is_empty_line(ln)]
        if not lines:
            continue
        step += 1
        rendered = "".join(_line_block(line) for line in lines)
        blocks.append(
            '<div class="flow-section">'
            f'<h3><span class="step">{step}</span>{_e(section["title"])}</h3>'
            f"{rendered}</div>"
        )

    hidden = [ln for ln in data["lines"] if _is_empty_line(ln)]
    if hidden:
        rows = "".join(
            f"<tr><td>{_e(ln['line'])}</td><td>{_e(ln['label'])}</td>"
            f'<td class="num">{_e(_money(ln["amount"]))}</td></tr>'
            for ln in hidden
        )
        blocks.append(
            '<details class="empty-lines"><summary>'
            f"{len(hidden)} form line(s) this return did not use"
            f"</summary><table><tbody>{rows}</tbody></table></details>"
        )

    return (
        '<section id="flow" class="card">'
        "<h2>Form 1040, line by line</h2>"
        '<p class="subtle">Every line with its sources, arithmetic, and the '
        "rule that requires it.</p>"
        f"{''.join(blocks)}"
        "</section>"
    )


def _narrative_section(data: dict[str, Any]) -> str:
    items = []
    for line in data["lines"]:
        if not line["narrative"] or _is_zero(line["amount"]):
            continue
        chips = "".join(
            f'<span class="chip">{_e(_humanize(doc))}</span>'
            for doc in line.get("source_documents", [])
        )
        items.append(
            "<li>"
            f'<div class="story-head"><strong>{_e(line["label"])}</strong>'
            f'<span class="num">{_e(_money(line["amount"]))}</span></div>'
            f"<p>{_e(line['narrative'])}</p>"
            f'<div class="chips">{_provenance_badge(line["provenance"])}{chips}</div>'
            "</li>"
        )

    assumptions = ""
    if data["assumptions"]:
        listed = "".join(f"<li>{_e(note)}</li>" for note in data["assumptions"])
        assumptions = f"<h3>What we assumed</h3><ul>{listed}</ul>"

    return (
        '<section id="narrative" class="card">'
        "<h2>How we arrived here</h2>"
        '<p class="subtle">The whole return in plain English, with no tax '
        "jargon.</p>"
        f'<ol class="story">{"".join(items)}</ol>'
        f"{assumptions}"
        "</section>"
    )


def _compliance_section(data: dict[str, Any]) -> str:
    unverified = ""
    if data["unverified_citations"]:
        names = ", ".join(data["unverified_citations"])
        unverified = (
            '<div class="notice warning"><strong>Confirm before filing.</strong> '
            f"The statutory citation for {_e(names)} could not be verified "
            "against primary text. The calculation is unaffected; the reference "
            "is what needs checking.</div>"
        )
    rules = "".join(_rule_block(rule) for rule in data["rules_applied"])
    return (
        '<section id="rules" class="card">'
        "<h2>Rules and authorities applied</h2>"
        f'<p class="subtle">{len(data["rules_applied"])} rules in force for tax '
        f"year {_e(data['tax_year'])}.</p>"
        f"{unverified}{rules}"
        "</section>"
    )


_STYLE = """
:root {
  --ink: #1b2230; --muted: #64707f; --line: #e2e7ee; --bg: #f6f8fb;
  --accent: #1f5fd0;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 20px 64px; background: var(--bg); color: var(--ink);
  font: 15px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.page { max-width: 980px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 0 0 4px; }
h3 { font-size: 15px; margin: 24px 0 8px; display: flex; align-items: center; gap: 8px; }
h4 { font-size: 13px; text-transform: uppercase; letter-spacing: .04em;
     color: var(--muted); margin: 0 0 6px; }
p { margin: 0 0 10px; }
a { color: var(--accent); }
.subtle { color: var(--muted); font-size: 13px; }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.card { background: #fff; border: 1px solid var(--line); border-radius: 10px;
        padding: 20px 22px; margin: 0 0 18px; }
.masthead { background: #fff; border: 1px solid var(--line); border-radius: 10px;
            padding: 22px; margin-bottom: 18px; }
.meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px; margin-top: 14px; }
.toc { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 14px; font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 14px; margin: 14px 0; }
.cell { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
.value { font-size: 19px; font-weight: 600; margin-top: 2px; }
.outcome { border-radius: 8px; padding: 16px 18px; margin-top: 8px;
           border: 1px solid var(--line); }
.outcome.owed { background: #fdf2f2; border-color: #f2c5c5; }
.outcome.refund { background: #f0f8f2; border-color: #bfe0c8; }
.outcome-value { font-size: 28px; font-weight: 700; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px;
         font-size: 12px; border: 1px solid var(--line); background: #f2f4f8;
         color: var(--muted); white-space: nowrap; }
.badge.success { background: #eaf6ee; border-color: #bfe0c8; color: #216c37; }
.badge.info { background: #eaf1fc; border-color: #c3d6f5; color: #1b4c9e; }
.badge.warning { background: #fdf4e6; border-color: #f0d8ab; color: #8a5a10; }
.badge.purple { background: #f3eefb; border-color: #d8c9f0; color: #5b3a95; }
.chip { display: inline-block; padding: 1px 8px; border-radius: 4px; font-size: 12px;
        background: #f2f4f8; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.step { display: inline-flex; width: 22px; height: 22px; border-radius: 50%;
        background: var(--accent); color: #fff; font-size: 12px;
        align-items: center; justify-content: center; }
details.line { border: 1px solid var(--line); border-radius: 8px; margin-bottom: 6px;
               background: #fff; page-break-inside: avoid; }
details.line > summary { list-style: none; cursor: pointer; padding: 10px 12px;
  display: grid; grid-template-columns: 18px 46px 1fr 190px 120px; gap: 10px;
  align-items: center; }
details.line > summary::-webkit-details-marker { display: none; }
/* The generated marker is itself a grid item, hence the leading column. */
details.line > summary::before { content: "▸"; color: var(--muted); }
details.line[open] > summary::before { content: "▾"; }
.line-no { font-weight: 600; }
.line-main { display: flex; flex-direction: column; }
.line-label { font-weight: 550; }
.line-amount { font-weight: 600; }
.line-body { padding: 4px 14px 16px 86px; border-top: 1px solid var(--line); }
.line-body section { margin-top: 14px; }
table { width: 100%; border-collapse: collapse; }
td, th { padding: 6px 8px; border-bottom: 1px solid var(--line);
         text-align: left; vertical-align: top; }
.sign { width: 22px; color: var(--muted); }
.formula { display: inline-block; background: #f2f4f8; border-radius: 4px;
           padding: 3px 8px; font-size: 13px; }
.checks { margin-top: 8px; color: var(--muted); font-size: 13px; }
.rule { border-left: 3px solid var(--accent); padding: 2px 0 2px 12px; margin: 10px 0; }
.rule-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.cite { color: var(--muted); font-size: 13px; }
.rule-links { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; }
.notice { border-radius: 8px; padding: 12px 14px; margin: 0 0 14px;
          border: 1px solid var(--line); background: #f2f4f8; }
.notice.warning { background: #fdf4e6; border-color: #f0d8ab; }
.story { padding-left: 18px; }
.story li { margin-bottom: 14px; }
.story-head { display: flex; justify-content: space-between; gap: 16px; }
.empty-lines { margin-top: 18px; }
.empty-lines summary { cursor: pointer; color: var(--muted); font-size: 13px; }
footer { color: var(--muted); font-size: 12px; text-align: center; margin-top: 24px; }
@media print {
  body { background: #fff; padding: 0; }
  .card, .masthead { border: none; padding: 0; margin-bottom: 20px; }
  details.line > summary { cursor: default; }
  .toc { display: none; }
}
"""


def report_filename(explanation: ReturnExplanation, source_filename: str) -> str:
    """A filename that identifies the return without needing the workflow id."""
    stem = _UNSAFE_FILENAME_CHARS.sub("-", source_filename.rsplit(".", 1)[0])
    stem = stem.strip("-")[:60].strip("-") or "return"
    return f"tax-report-{stem}-{explanation.tax_year}.html"


def render_return_report(
    explanation: ReturnExplanation,
    *,
    source_filename: str,
    workflow_id: str,
    generated_at: datetime,
) -> str:
    """Render the full explanation as one standalone HTML document."""
    data = explanation.to_dict()
    title = f"{data['tax_year']} Form 1040 — calculation report"

    warnings = ""
    if data["warnings"]:
        listed = "".join(f"<li>{_e(w)}</li>" for w in data["warnings"])
        warnings = f'<div class="notice warning"><ul>{listed}</ul></div>'

    meta_items = [
        ("Tax year", str(data["tax_year"])),
        ("Filing status", data["summary"].get("filing_status", "")),
        ("Deduction method", f"{data['deduction_method']} deduction"),
        ("Source document", source_filename),
        ("Workflow", workflow_id),
        ("Generated", generated_at.strftime("%d %b %Y %H:%M UTC")),
    ]
    meta = "".join(
        f'<div><div class="subtle">{_e(label)}</div><div>{_e(value)}</div></div>'
        for label, value in meta_items
    )

    return (
        "<!doctype html>\n"
        '<html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title>"
        f"<style>{_STYLE}</style>"
        "</head><body><div class=\"page\">"
        '<header class="masthead">'
        f"<h1>{_e(title)}</h1>"
        '<p class="subtle">Every figure below was computed by the deterministic '
        "tax engine and traced to the document, prior-year return, or stated "
        "assumption it came from.</p>"
        f'<div class="meta">{meta}</div>'
        '<nav class="toc">'
        '<a href="#summary">Summary</a>'
        '<a href="#flow">Form 1040 line by line</a>'
        '<a href="#narrative">How we arrived here</a>'
        '<a href="#rules">Rules and authorities</a>'
        "</nav>"
        "</header>"
        f"{warnings}"
        f"{_summary_section(data)}"
        f"{_flow_section(data)}"
        f"{_narrative_section(data)}"
        f"{_compliance_section(data)}"
        "<footer>This report contains taxpayer information. Store and share it "
        "accordingly.</footer>"
        "</div></body></html>"
    )
