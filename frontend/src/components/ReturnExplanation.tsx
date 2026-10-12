/**
 * The result of a return, told so a person can check it.
 *
 * Three panels, in the order someone actually asks the questions:
 *   1. What did I end up with?          -> TaxSummary
 *   2. How did each line get its value? -> Form1040Flow
 *   3. Why is that the rule?            -> HowWeArrivedHere + Compliance
 *
 * Every figure here is expandable down to the documents it came from. Nothing
 * is presented as verified unless the backend traced it to a source page — the
 * badge distinctions are load-bearing, not decoration.
 */

import { useState } from 'react';

import type {
  Explanation, LineExplanation, Operand, Provenance, TaxRule,
} from '../api/client';
import { Badge, Card, Notice } from './ui';

/** Dollars, the way a preparer reads them. */
function money(raw: string): string {
  const value = Number(raw);
  if (!Number.isFinite(value)) return raw;
  const abs = Math.abs(value);
  const body = abs.toLocaleString('en-US', {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  });
  return value < 0 ? `(${body})` : body;
}

const PROVENANCE_LABEL: Record<Provenance, string> = {
  source_document: 'From your documents',
  computed: 'Calculated from other lines',
  prior_year: 'From last year’s return',
  election: 'Your choice',
  taxpayer_profile: 'From your details',
  assumption: 'Assumed — nothing stated it',
};

const PROVENANCE_TONE: Record<Provenance, 'success' | 'info' | 'purple' | 'warning' | 'neutral'> = {
  source_document: 'success',
  computed: 'info',
  prior_year: 'purple',
  election: 'purple',
  taxpayer_profile: 'info',
  assumption: 'warning',
};

function StatusBadge({ line }: { line: LineExplanation }) {
  if (line.status === 'needs_review') {
    return <Badge tone="warning">⚠ Review recommended</Badge>;
  }
  if (line.status === 'verified') {
    return <Badge tone="success">✓ Verified from documents</Badge>;
  }
  return <Badge tone="info">✓ Calculated</Badge>;
}

/* ------------------------------------------------------------------ summary */

export function TaxSummary({ explanation }: { explanation: Explanation }) {
  const s = explanation.summary;
  const owed = Number(s.amount_owed) > 0;
  const refund = Number(s.refund) > 0;
  const carried = Number(s.applied_to_next_year) > 0;

  const rows: { label: string; value: string; hint?: string }[] = [
    { label: 'Filing status', value: s.filing_status },
    { label: 'Total income', value: `$${money(s.total_income)}` },
    { label: 'Adjusted gross income', value: `$${money(s.adjusted_gross_income)}` },
    {
      label: 'Deductions applied',
      value: `$${money(s.deductions)}`,
      hint: `${s.deduction_method} deduction`,
    },
    { label: 'Taxable income', value: `$${money(s.taxable_income)}` },
    { label: 'Credits applied', value: `$${money(s.credits)}` },
    { label: 'Total tax', value: `$${money(s.total_tax)}` },
    { label: 'Payments', value: `$${money(s.payments)}` },
  ];

  return (
    <Card title={`${explanation.tax_year} tax summary`}>
      <div className="summary-grid">
        {rows.map((row) => (
          <div key={row.label} className="summary-cell">
            <div className="summary-label">{row.label}</div>
            <div className="summary-value">{row.value}</div>
            {row.hint && <div className="summary-hint">{row.hint}</div>}
          </div>
        ))}
      </div>

      <div className={`outcome ${owed ? 'owed' : 'refund'}`}>
        <div className="outcome-label">
          {owed ? 'Amount you owe' : refund ? 'Your refund' : 'Nothing owed, nothing refunded'}
        </div>
        <div className="outcome-value">
          ${money(owed ? s.amount_owed : s.refund)}
        </div>
        {carried && (
          <div className="outcome-note">
            ${money(s.applied_to_next_year)} was left with the IRS toward next
            year’s tax instead of being refunded.
          </div>
        )}
      </div>
    </Card>
  );
}

/* --------------------------------------------------------------- 1040 flow */

function OperandRow({ operand }: { operand: Operand }) {
  const sign = operand.role === 'subtract' ? '−' : operand.role === 'add' ? '+' : '';
  return (
    <tr>
      <td className="op-sign">{sign}</td>
      <td>
        <div className="op-label">{operand.label}</div>
        {operand.detail && <div className="op-detail">{operand.detail}</div>}
      </td>
      <td>
        <Badge tone={PROVENANCE_TONE[operand.provenance]}>
          {PROVENANCE_LABEL[operand.provenance]}
        </Badge>
      </td>
      <td className="num op-amount">
        {operand.role === 'info' && operand.amount === '0' ? '—' : money(operand.amount)}
      </td>
    </tr>
  );
}

function RuleBlock({ rule }: { rule: TaxRule }) {
  return (
    <div className="rule-block">
      <div className="rule-head">
        <strong>{rule.title}</strong>
        {rule.irc_section && <span className="rule-cite">{rule.irc_section}</span>}
        {!rule.verified && (
          <Badge tone="warning">⚠ Citation unconfirmed</Badge>
        )}
      </div>
      <p className="rule-plain">{rule.plain_english}</p>
      {rule.notes && <p className="rule-notes">{rule.notes}</p>}
      <div className="rule-links">
        {rule.citations.map((citation) => (
          <a
            key={citation.url}
            href={citation.url}
            target="_blank"
            rel="noreferrer noopener"
          >
            {citation.title}
          </a>
        ))}
      </div>
      <div className="rule-effective">
        Applies to tax years {rule.effective_from}
        {rule.effective_to ? `–${rule.effective_to}` : ' onward'}
      </div>
    </div>
  );
}

function LineRow({ line }: { line: LineExplanation }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <tr className="clickable line-row" onClick={() => setOpen((o) => !o)}>
        <td className="line-number">
          <span className="chevron">{open ? '▾' : '▸'}</span>
          {line.line}
        </td>
        <td>
          <div className="line-label">{line.label}</div>
          <div className="line-narrative-teaser">{line.narrative}</div>
        </td>
        <td><StatusBadge line={line} /></td>
        <td className="num line-amount">{money(line.amount)}</td>
      </tr>

      {open && (
        <tr className="detail-row">
          <td />
          <td colSpan={3}>
            <div className="line-detail">
              <section>
                <h4>Where these numbers came from</h4>
                {line.operands.length ? (
                  <table className="operands">
                    <tbody>
                      {line.operands.map((operand, index) => (
                        <OperandRow key={`${operand.label}-${index}`} operand={operand} />
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="subtle">This line stands on its own.</p>
                )}
              </section>

              <section>
                <h4>How it was worked out</h4>
                <code className="formula">{line.formula || '—'}</code>
                {line.arithmetic_checked && (
                  <div className="check-note">
                    ✓ Re-added from the inputs above and matched this figure.
                  </div>
                )}
                {line.confidence !== null && (
                  <div className="check-note">
                    Reading confidence on the weakest input:{' '}
                    {Math.round(line.confidence * 100)}%
                  </div>
                )}
                {line.note && <div className="check-note">{line.note}</div>}
              </section>

              <section>
                <h4>The rule behind it</h4>
                <RuleBlock rule={line.rule} />
              </section>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * A line that is zero because nothing in the return touched it.
 *
 * A blank Form 1040 has around thirty of these, and showing them all buries
 * the eight lines that actually carry this taxpayer's return. They stay
 * available behind a toggle rather than being dropped, because "line 4b is
 * zero" is occasionally the fact a reviewer needs to confirm.
 */
function isEmptyLine(line: LineExplanation): boolean {
  return Number(line.amount) === 0 && line.provenance === 'assumption';
}

export function Form1040Flow({ explanation }: { explanation: Explanation }) {
  const [showEmpty, setShowEmpty] = useState(false);

  const sections = explanation.sections
    .map((section) => ({
      ...section,
      lines: showEmpty ? section.lines : section.lines.filter((l) => !isEmptyLine(l)),
    }))
    .filter((section) => section.lines.length > 0);

  const hiddenCount = explanation.lines.filter(isEmptyLine).length;

  return (
    <Card
      title="Form 1040, line by line"
      subtitle="Select any line to see its sources, arithmetic, and the rule that requires it."
      actions={
        hiddenCount > 0 ? (
          <button className="btn sm ghost" onClick={() => setShowEmpty((v) => !v)}>
            {showEmpty ? 'Hide' : 'Show'} {hiddenCount} empty line
            {hiddenCount === 1 ? '' : 's'}
          </button>
        ) : undefined
      }
    >
      <div className="flow">
        {sections.map((section, index) => (
          <div key={section.key} className="flow-section">
            <div className="flow-head">
              <span className="flow-step">{index + 1}</span>
              <h3>{section.title}</h3>
            </div>
            <table className="lines">
              <tbody>
                {section.lines.map((line) => (
                  <LineRow key={line.line} line={line} />
                ))}
              </tbody>
            </table>
            {index < sections.length - 1 && <div className="flow-arrow">↓</div>}
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ------------------------------------------------- how we arrived here */

export function HowWeArrivedHere({ explanation }: { explanation: Explanation }) {
  // The narrative reads as a story, so it follows the form's own order rather
  // than jumping to whichever lines happen to be largest.
  const notable = explanation.lines.filter(
    (line) => line.narrative && Number(line.amount) !== 0,
  );

  return (
    <Card
      title="How we arrived here"
      subtitle="The whole return in plain English, with no tax jargon."
    >
      <ol className="story">
        {notable.map((line) => (
          <li key={line.line}>
            <div className="story-head">
              <strong>{line.label}</strong>
              <span className="story-amount">${money(line.amount)}</span>
            </div>
            <p>{line.narrative}</p>
            <div className="story-meta">
              <Badge tone={PROVENANCE_TONE[line.provenance]}>
                {PROVENANCE_LABEL[line.provenance]}
              </Badge>
              {line.source_documents.map((doc) => (
                <span key={doc} className="doc-chip">{doc.replace(/_/g, ' ')}</span>
              ))}
            </div>
          </li>
        ))}
      </ol>

      {explanation.assumptions.length > 0 && (
        <div className="assumptions">
          <h4>What we assumed</h4>
          <ul>
            {explanation.assumptions.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------- compliance */

export function CompliancePanel({ explanation }: { explanation: Explanation }) {
  return (
    <Card
      title="Rules and authorities applied"
      subtitle={`${explanation.rules_applied.length} rules in force for tax year ${explanation.tax_year}.`}
    >
      {explanation.unverified_citations.length > 0 && (
        <Notice kind="warning">
          <strong>Confirm before filing.</strong> The statutory citation for{' '}
          {explanation.unverified_citations.join(', ')} could not be verified
          against primary text. The calculation is unaffected; the reference is
          what needs checking.
        </Notice>
      )}

      <div className="rules-list">
        {explanation.rules_applied.map((rule) => (
          <RuleBlock key={rule.id} rule={rule} />
        ))}
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ root */

export default function ReturnExplanationView({
  explanation,
}: {
  explanation: Explanation;
}) {
  return (
    <div className="stack">
      {explanation.warnings.length > 0 && (
        <Notice kind="warning">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {explanation.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Notice>
      )}
      <TaxSummary explanation={explanation} />
      <Form1040Flow explanation={explanation} />
      <HowWeArrivedHere explanation={explanation} />
      <CompliancePanel explanation={explanation} />
    </div>
  );
}
