"""The calculation report as a PDF, laid out with PyMuPDF's HTML story.

PyMuPDF is already the PDF dependency; a second rendering stack for one report
would be a second set of fonts, page sizes and failure modes. The story engine
supports a limited CSS subset, so the layout is deliberately plain: headings,
tables, and a monospace formula column.

An unsupported line prints "not computed" - never 0, which is trap 32: zero in
a money column is itself a figure.
"""

from __future__ import annotations

import io
from decimal import Decimal
from html import escape

from app.services.calculation_report import (
    CalculationReport,
    DocumentEntry,
    FormSection,
    ReportLine,
)

_CSS = """
* { font-family: sans-serif; font-size: 8.5pt; }
h1 { font-size: 16pt; margin-bottom: 2pt; }
h2 { font-size: 12pt; margin-top: 14pt; border-bottom: 1px solid #999; }
h3 { font-size: 10pt; margin-top: 10pt; }
p.meta { color: #555; }
table { width: 100%; border-collapse: collapse; margin-top: 4pt; }
th { text-align: left; background-color: #eee; padding: 2pt; }
td { padding: 2pt; vertical-align: top; border-bottom: 1px solid #ddd; }
td.num { text-align: right; }
.code { font-family: monospace; font-size: 7.5pt; }
.small { font-size: 7.5pt; color: #444; }
.warn { color: #9a4a00; }
.bad { color: #a01010; }
.good { color: #106030; }
"""


def _amount(value: Decimal | None) -> str:
    if value is None:
        return "not computed"
    body = f"{abs(value):,.2f}".removesuffix(".00")
    return f"({body})" if value < 0 else body


def _e(text: object) -> str:
    return escape(str(text))


def _line_row(line: ReportLine) -> str:
    inputs = "<br/>".join(
        f"{_e(i.label)}: {_e(_amount(i.amount))}" for i in line.inputs
    ) or "-"
    sources = "<br/>".join(
        f"{_e(s.document_type)} p.{s.page}"
        + (f" ({_e(_amount(s.amount))})" if s.amount is not None else "")
        + f", {int(s.confidence * 100)}%"
        for s in line.sources
    ) or "-"
    explained = _e(line.explanation.text)
    if line.explanation.by == "model":
        explained += ' <span class="small">(model wording, checked)</span>'
    flags = "".join(f'<br/><span class="warn">! {_e(f)}</span>' for f in line.flags)
    return (
        "<tr>"
        f"<td>{_e(line.line)}</td>"
        f"<td>{_e(line.label)}<br/><span class='small'>{explained}</span>{flags}</td>"
        f"<td class='num'>{_e(_amount(line.amount))}</td>"
        f"<td><span class='code'>{_e(line.formula)}</span></td>"
        f"<td class='small'>{inputs}</td>"
        f"<td class='small'>{sources}<br/>{_e(line.reference)}</td>"
        "</tr>"
    )


def _section(section: FormSection, *, full: bool = False) -> str:
    """One form. The -0- lines of a form are listed by number, not printed.

    The JSON export carries every line in full. On paper, thirty rows of
    "0 reported as ..." bury the eight that carry the return, so a form prints
    its non-zero and unsupported lines and then names the rest. A worksheet
    prints in full (``full``): its zeros are part of the arithmetic it shows.
    """
    head = (
        "<tr><th>Line</th><th>Description</th><th>Amount</th>"
        "<th>Formula</th><th>Inputs</th><th>Source</th></tr>"
    )
    shown = [
        line
        for line in section.lines
        if full or line.amount is None or line.amount != 0 or line.flags
    ]
    nil = [line.line for line in section.lines if line not in shown]
    rows = "".join(_line_row(line) for line in shown)
    out = f"<h3>{_e(section.form)}</h3><table>{head}{rows}</table>"
    if nil:
        out += (
            f"<p class='small'>Entered as -0- (full detail in the JSON export): "
            f"lines {_e(', '.join(nil))}.</p>"
        )
    return out


def _document(entry: DocumentEntry) -> str:
    pages = (
        f"pages {entry.page_start}-{entry.page_end}"
        if entry.page_end != entry.page_start
        else f"page {entry.page_start}"
    )
    ocr = "" if entry.ocr_confidence is None else f", read at {entry.ocr_confidence:.0%}"
    hand = ", handwriting" if entry.handwritten else ""
    rows = "".join(
        "<tr>"
        f"<td>{_e(f.field)}</td><td>{'' if f.page is None else f.page}</td>"
        f"<td class='num'>{'' if f.amount is None else _e(_amount(f.amount))}</td>"
        f"<td>{int(f.confidence * 100)}%{' - review' if f.requires_review else ''}</td>"
        f"<td>{'yes' if f.located else '-'}</td>"
        f"<td class='small'>{_e(', '.join(f.used_on)) or _e(f.note) or '-'}</td>"
        "</tr>"
        for f in entry.fields
    )
    table = (
        "<table><tr><th>Field</th><th>Page</th><th>Amount</th><th>Confidence</th>"
        f"<th>Located</th><th>Used on</th></tr>{rows}</table>"
        if rows
        else "<p class='small'>Nothing was extracted from this document.</p>"
    )
    return (
        f"<h3>{_e(entry.document_type)} ({pages}{ocr}{hand})</h3>"
        f"<p class='small'>Document {_e(entry.document_id)}</p>{table}"
    )


def render_html(report: CalculationReport) -> str:
    """The report as the HTML the story engine lays out."""
    status = (
        "<span class='good'>Fileable as computed.</span>"
        if report.fileable
        else "<span class='bad'>Not fileable as computed - see Validation.</span>"
    )
    headline = "".join(
        f"<tr><td>{_e(label)}</td><td class='small'>{_e(node_id)}</td>"
        f"<td class='num'>{_e(_amount(amount))}</td></tr>"
        for label, node_id, amount in report.headline
    )
    parts = [
        f"<h1>Calculation report - tax year {report.tax_year}</h1>",
        (
            f"<p class='meta'>Workflow {_e(report.workflow_id)} - filing status "
            f"{_e(report.filing_status.replace('_', ' '))} - generated "
            f"{_e(report.generated_at)}</p>"
        ),
        f"<p>{status}</p>",
        f"<table>{headline}</table>",
        f"<p class='small'>Explanations: {_e(report.explanations_note)}</p>",
    ]
    parts += [f"<p class='small'>{_e(note)}</p>" for note in report.notes]

    parts.append("<h2>1. Forms, line by line</h2>")
    for section in report.forms:
        if section.used:
            parts.append(_section(section))
    unused = [s.form for s in report.forms if not s.used]
    if unused:
        parts.append(
            f"<p class='small'>Not used on this return (every line -0-): {_e(', '.join(unused))}.</p>"
        )

    parts.append("<h2>2. Worksheets</h2>")
    parts += [_section(w, full=True) for w in report.worksheets] or [
        "<p class='small'>No worksheet was used.</p>"
    ]

    parts.append("<h2>3. Source documents</h2>")
    parts += [_document(d) for d in report.documents] or [
        "<p class='small'>No documents were recorded for this run.</p>"
    ]

    v = report.validation
    parts.append("<h2>4. Validation</h2><table><tr><th>Check</th><th>Result</th><th>Detail</th></tr>")
    for check in v.checks:
        result = (
            "<span class='small'>not run</span>"
            if check.passed is None
            else "<span class='good'>passed</span>"
            if check.passed
            else "<span class='bad'>failed</span>"
        )
        findings = "".join(f"<br/>- {_e(f)}" for f in check.findings[:25])
        more = (
            f"<br/>... and {len(check.findings) - 25} more" if len(check.findings) > 25 else ""
        )
        parts.append(
            f"<tr><td>{_e(check.name)}</td><td>{result}</td>"
            f"<td class='small'>{_e(check.detail)}{findings}{more}</td></tr>"
        )
    parts.append("</table>")

    parts.append("<h3>Lines not computed</h3>")
    parts.append(
        "<table>"
        + "".join(
            f"<tr><td>{_e(n)}</td><td>{_e(label)}</td><td class='small'>{_e(reason)}</td></tr>"
            for n, label, reason in v.unsupported
        )
        + "</table>"
        if v.unsupported
        else "<p class='small'>Every line was computed.</p>"
    )
    parts.append("<h3>Low-confidence extractions</h3>")
    parts.append(
        "<table><tr><th>Field</th><th>Document</th><th>Page</th><th>Confidence</th></tr>"
        + "".join(
            f"<tr><td>{_e(r.field)}</td><td>{_e(r.document_type)}</td>"
            f"<td>{'' if r.page is None else r.page}</td><td>{int(r.confidence * 100)}%</td></tr>"
            for r in v.low_confidence
        )
        + "</table>"
        if v.low_confidence
        else "<p class='small'>None.</p>"
    )
    if v.unverified_authorities:
        parts.append(
            "<h3>Constants whose authority is not yet confirmed</h3><p class='small'>"
            + _e(", ".join(v.unverified_authorities))
            + "</p>"
        )
    return f"<html><body>{''.join(parts)}</body></html>"


def render_pdf(report: CalculationReport) -> bytes:
    """Letter pages, half-inch margins, as many as the report needs."""
    import fitz  # type: ignore[import-untyped]

    story = fitz.Story(html=render_html(report), user_css=_CSS)
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    page = fitz.paper_rect("letter-l")
    where = page + (36, 36, -36, -36)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()
