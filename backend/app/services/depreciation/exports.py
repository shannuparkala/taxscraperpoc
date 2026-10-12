"""CSV and PDF exports of a calculator result.

Both read the same result dict the screen renders, so an export cannot show
a number the screen did not. The PDF uses PyMuPDF's HTML story, as the
calculation report does - one PDF stack for the whole application.
"""

from __future__ import annotations

import csv
import io
from html import escape
from typing import Any

_CSS = """
* { font-family: sans-serif; font-size: 8.5pt; }
h1 { font-size: 15pt; margin-bottom: 2pt; }
h2 { font-size: 11pt; margin-top: 12pt; border-bottom: 1px solid #999; }
p.meta { color: #555; }
table { width: 100%; border-collapse: collapse; margin-top: 4pt; }
th { text-align: left; background-color: #eee; padding: 2pt; }
td { padding: 2pt; vertical-align: top; border-bottom: 1px solid #ddd; }
td.num, th.num { text-align: right; }
.small { font-size: 7.5pt; color: #444; }
.warn { color: #9a4a00; }
"""


def _money(value: Any) -> str:
    if value is None or value == "":
        return ""
    amount = float(value)
    return f"-${-amount:,.0f}" if amount < 0 else f"${amount:,.0f}"


def schedule_rows(result: dict[str, Any]) -> list[dict[str, str]]:
    """The federal-and-state schedule, one row per year, as displayed."""
    state = result.get("state") or {}
    state_rows = {row["year"]: row for row in state.get("rows", [])} if state.get("rows") else {}
    rows = []
    for row in result["federal"]["schedule"]:
        s = state_rows.get(row["year"], {})
        rows.append({
            "year": str(row["year"]),
            "section_179": row["section_179"],
            "bonus": row["bonus"],
            "special": row["special"],
            "macrs": row["macrs"],
            "federal_total": row["total"],
            "state_total": s.get("state", ""),
            "state_adjustment": s.get("adjustment", ""),
        })
    return rows


def to_csv(result: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    state = result.get("state")
    writer.writerow([f"Depreciation schedule - tax year {result['tax_year']}", result["primary_label"]])
    if state:
        writer.writerow([f"State: {state['name']} ({state['status']})", state["message"]])
    writer.writerow([])
    writer.writerow([
        "Year", "Section 179", "Bonus", "Special allowance (168(n))", "MACRS",
        "Federal total", "State total", "State adjustment (+add back / -subtract)",
    ])
    for row in schedule_rows(result):
        writer.writerow([
            row["year"], row["section_179"], row["bonus"], row["special"], row["macrs"],
            row["federal_total"], row["state_total"], row["state_adjustment"],
        ])
    federal = result["federal"]
    writer.writerow(["Total", "", "", "", "", federal["total"], (state or {}).get("total") or "", ""])
    writer.writerow(["Section 179 carryforward", "", "", "", "", federal["carryforward"], "", ""])
    writer.writerow([])
    writer.writerow(["Asset", "Class", "Placed in service", "Depreciable basis", "Recovery", "Convention",
                     "Section 179", "Bonus rate %", "Bonus", f"{result['tax_year']} deduction"])
    for asset in result["assets"]:
        writer.writerow([
            asset["description"] or asset["id"], asset["class_label"], asset["placed_in_service"],
            asset["business_basis"], f"{asset['recovery_years']} yr {asset['system']} {asset['method']}",
            asset["convention"], asset["section_179_allowed"], asset["bonus_rate"], asset["bonus"],
            asset["tax_year_deduction"],
        ])
    writer.writerow([])
    writer.writerow(["Method comparison", f"Federal {result['tax_year']} deduction", "State deduction",
                     "Federal tax effect", "State tax effect"])
    for c in result["comparison"]:
        writer.writerow([c["label"], c["federal_tax_year_deduction"], c["state_tax_year_deduction"] or "",
                         c["federal_tax_effect"] or "", c["state_tax_effect"] or ""])
    writer.writerow([])
    writer.writerow(["Form 4562 line", "Description", "Amount"])
    for line in result["form_4562"]:
        writer.writerow([line["line"], line["label"], line["amount"]])
    writer.writerow([])
    for warning in result["warnings"]:
        writer.writerow(["Warning", warning])
    for assumption in result["assumptions"]:
        writer.writerow(["Assumption", assumption])
    writer.writerow([])
    writer.writerow(["Source", "Citation", "URL", "Last verified", "Verified"])
    for source in result["sources"]:
        writer.writerow([source["label"], source["source_citation"], source["source_url"],
                         source["last_verified"] or "", "yes" if source["verified"] else "no"])
    writer.writerow([])
    writer.writerow([result["disclaimer"]])
    return buffer.getvalue()


def render_html(result: dict[str, Any]) -> str:
    e = escape
    state = result.get("state")
    first = result["federal"]["first_year"]
    parts = [
        f"<h1>Depreciation schedule - tax year {result['tax_year']}</h1>",
        f"<p class='meta'>{e(result['primary_label'])}"
        + (f" - {e(state['name'])}: {e(state['message'])}" if state else " - federal only")
        + "</p>",
        "<h2>First-year deduction</h2><table>",
        f"<tr><td>Section 179</td><td class='num'>{_money(first['section_179'])}</td></tr>",
        f"<tr><td>Bonus depreciation</td><td class='num'>{_money(first['bonus'])}</td></tr>",
        f"<tr><td>Section 168(n) allowance</td><td class='num'>{_money(first['special'])}</td></tr>",
        f"<tr><td>Regular MACRS</td><td class='num'>{_money(first['macrs'])}</td></tr>",
        f"<tr><th>Federal total, {result['tax_year']}</th><th class='num'>{_money(first['total'])}</th></tr>",
    ]
    if state and state.get("tax_year_deduction") is not None:
        parts.append(f"<tr><th>{e(state['name'])} total, {result['tax_year']}</th>"
                     f"<th class='num'>{_money(state['tax_year_deduction'])}</th></tr>")
    parts.append("</table>")

    parts.append("<h2>Year-by-year schedule</h2><table><tr><th>Year</th><th class='num'>Section 179</th>"
                 "<th class='num'>Bonus</th><th class='num'>168(n)</th><th class='num'>MACRS</th>"
                 "<th class='num'>Federal</th><th class='num'>State</th><th class='num'>State adj.</th></tr>")
    for row in schedule_rows(result):
        parts.append(
            f"<tr><td>{row['year']}</td><td class='num'>{_money(row['section_179'])}</td>"
            f"<td class='num'>{_money(row['bonus'])}</td><td class='num'>{_money(row['special'])}</td>"
            f"<td class='num'>{_money(row['macrs'])}</td><td class='num'>{_money(row['federal_total'])}</td>"
            f"<td class='num'>{_money(row['state_total'])}</td><td class='num'>{_money(row['state_adjustment'])}</td></tr>"
        )
    fed = result["federal"]
    parts.append(f"<tr><th>Total</th><th></th><th></th><th></th><th></th><th class='num'>{_money(fed['total'])}</th>"
                 f"<th class='num'>{_money((state or {}).get('total'))}</th><th></th></tr></table>")
    parts.append(f"<p class='small'>{e(fed['check']['statement'])} Depreciable basis {_money(fed['basis'])}; "
                 f"Section 179 carryforward {_money(fed['carryforward'])}.</p>")

    parts.append("<h2>Assets</h2><table><tr><th>Asset</th><th>Class</th><th>In service</th>"
                 "<th class='num'>Basis</th><th>Recovery</th><th class='num'>Sec. 179</th>"
                 "<th class='num'>Bonus</th></tr>")
    for a in result["assets"]:
        parts.append(
            f"<tr><td>{e(a['description'] or a['id'])}</td><td>{e(a['class_label'])}</td>"
            f"<td>{a['placed_in_service']}</td><td class='num'>{_money(a['business_basis'])}</td>"
            f"<td>{a['recovery_years']} yr {a['system']} {a['method']} {a['convention']}</td>"
            f"<td class='num'>{_money(a['section_179_allowed'])}</td>"
            f"<td class='num'>{_money(a['bonus'])} ({e(a['bonus_rate'])}%)</td></tr>"
        )
    parts.append("</table>")

    parts.append(f"<h2>Method comparison</h2><table><tr><th>Method</th><th class='num'>Federal {result['tax_year']}</th>"
                 "<th class='num'>State</th><th class='num'>Fed. tax effect</th><th class='num'>State tax effect</th></tr>")
    for c in result["comparison"]:
        parts.append(f"<tr><td>{e(c['label'])}</td><td class='num'>{_money(c['federal_tax_year_deduction'])}</td>"
                     f"<td class='num'>{_money(c['state_tax_year_deduction'])}</td>"
                     f"<td class='num'>{_money(c['federal_tax_effect'])}</td><td class='num'>{_money(c['state_tax_effect'])}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>Form 4562 reference</h2><table><tr><th>Line</th><th>Description</th><th class='num'>Amount</th></tr>")
    for line in result["form_4562"]:
        parts.append(f"<tr><td>{e(line['line'])}</td><td>{e(line['label'])}</td><td class='num'>{_money(line['amount'])}</td></tr>")
    parts.append("</table>")

    if result["warnings"]:
        parts.append("<h2>Warnings</h2>" + "".join(f"<p class='warn'>{e(w)}</p>" for w in result["warnings"]))
    parts.append("<h2>Assumptions</h2>" + "".join(f"<p class='small'>{e(a)}</p>" for a in result["assumptions"]))
    parts.append("<h2>Sources</h2><table><tr><th>Rule</th><th>Citation</th><th>Verified</th></tr>")
    for s in result["sources"]:
        parts.append(f"<tr><td>{e(s['label'])}</td><td class='small'>{e(s['source_citation'])}<br/>{e(s['source_url'])}</td>"
                     f"<td>{'yes, ' + e(s['last_verified']) if s['verified'] and s['last_verified'] else 'no'}</td></tr>")
    parts.append("</table>")
    parts.append(f"<p class='small'>{e(result['disclaimer'])}</p>")
    return "".join(parts)


def to_pdf(result: dict[str, Any]) -> bytes:
    import fitz  # type: ignore[import-untyped]

    story = fitz.Story(html=render_html(result), user_css=_CSS)
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    page = fitz.paper_rect("letter")
    where = page + (36, 36, -36, -36)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()
