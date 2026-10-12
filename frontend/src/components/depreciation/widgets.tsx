/**
 * Building blocks for the depreciation workspace: section cards with an icon
 * tile, toggle switches, info tips, money inputs, "Why?" cards and the
 * calculation tape.
 *
 * Presentation only. The tape renders the server's lines verbatim - it adds
 * no number of its own.
 */

import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronRight, HelpCircle, Info } from 'lucide-react';

import type { HeadlineFigure, TapeSection } from '../../api/client';
import { caretAfterGrouping, groupDigits, money } from '../../lib/depreciationForm';

export function Panel({
  icon, title, subtitle, actions, children, className = '',
}: {
  icon?: ReactNode; title: string; subtitle?: string; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  // The app's card (styles.css), with this page's icon tile in the header.
  return (
    <section className={`card dw-card ${className}`}>
      <header className="card-header dw-card-head">
        {icon && <span className="dw-tile" aria-hidden="true">{icon}</span>}
        <div className="dw-card-titles">
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {actions && <div className="header-actions">{actions}</div>}
      </header>
      <div className="card-body">{children}</div>
    </section>
  );
}

export function InfoTip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="dw-info">
      <button
        type="button"
        className="dw-info-btn"
        aria-label="More information"
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setOpen(false)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <Info size={13} aria-hidden="true" />
      </button>
      {open && <span role="tooltip" id={id} className="dw-info-pop">{text}</span>}
    </span>
  );
}

export function Label({ htmlFor, children, info }: { htmlFor?: string; children: ReactNode; info?: string }) {
  return (
    <div className="dw-label">
      <label htmlFor={htmlFor}>{children}</label>
      {info && <InfoTip text={info} />}
    </div>
  );
}

export function Toggle({
  checked, onChange, label, disabled = false,
}: {
  checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={`dw-switch ${checked ? 'on' : ''}`}
      onClick={() => onChange(!checked)}
    >
      <span className="dw-switch-knob" />
    </button>
  );
}

export function ToggleSection({
  title, info, checked, onChange, children, disabled = false, hint, badge,
}: {
  title: string; info?: string; checked: boolean; onChange?: (value: boolean) => void;
  children?: ReactNode; disabled?: boolean; hint?: string;
  /** Show a status chip instead of a switch (a fact about the asset, not an election). */
  badge?: string;
}) {
  return (
    <div className={`dw-toggle-section ${checked ? 'on' : ''}`}>
      <div className="dw-toggle-head">
        <div className="dw-label">
          <strong>{title}</strong>
          {info && <InfoTip text={info} />}
        </div>
        {badge ? <span className="badge accent">{badge}</span>
          : <Toggle checked={checked} onChange={(v) => onChange?.(v)} label={title} disabled={disabled} />}
      </div>
      {hint && <p className="dw-hint">{hint}</p>}
      {checked && children && <div className="dw-inset">{children}</div>}
    </div>
  );
}

export function MoneyInput({
  id, value, onChange, placeholder, ariaDescribedBy, grouped = false,
}: {
  id: string; value: string; onChange: (value: string) => void; placeholder?: string; ariaDescribedBy?: string;
  /** Show thousands separators as the user types ("1,234,567"). Display only. */
  grouped?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);
  const shown = grouped ? groupDigits(value) : value;

  // Reformatting moves the caret to the end; put it back after the same
  // digits, so editing the middle of "1,234,567" does not jump.
  useLayoutEffect(() => {
    if (caret.current !== null && input.current && document.activeElement === input.current) {
      input.current.setSelectionRange(caret.current, caret.current);
    }
    caret.current = null;
  }, [shown]);

  const change = (raw: string, position: number | null) => {
    if (!grouped) return onChange(raw);
    const formatted = groupDigits(raw);
    const before = raw.slice(0, position ?? raw.length).replace(/[^\d.]/g, '').length;
    caret.current = caretAfterGrouping(formatted, before);
    onChange(formatted);
  };

  return (
    <div className="dw-affix">
      <span aria-hidden="true">$</span>
      <input ref={input} id={id} type="text" inputMode="decimal" value={shown} placeholder={placeholder}
        aria-describedby={ariaDescribedBy} onChange={(e) => change(e.target.value, e.target.selectionStart)} />
    </div>
  );
}

export function PercentInput({
  id, value, onChange, min = 0, max = 100,
}: {
  id: string; value: string; onChange: (value: string) => void; min?: number; max?: number;
}) {
  return (
    <div className="dw-affix suffix">
      <input id={id} type="number" min={min} max={max} step="0.01" value={value} onChange={(e) => onChange(e.target.value)} />
      <span aria-hidden="true">%</span>
    </div>
  );
}

export function KeyValue({ label, value, strong = false }: { label: string; value: ReactNode; strong?: boolean }) {
  return (
    <div className={`dw-kv ${strong ? 'strong' : ''}`}>
      <span>{label}</span>
      <span className="dw-num">{value}</span>
    </div>
  );
}

/** A headline figure with a "Why?" that reveals the formula behind it. */
export function WhyCard({ figure, tone = '' }: { figure: HeadlineFigure; tone?: '' | 'accent' }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={`dw-why-card ${tone} ${open ? 'open' : ''}`}>
      <div className="dw-why-top">
        <div>
          <div className="dw-eyebrow">{figure.label}</div>
          <div className="dw-big dw-num">{money(figure.value)}</div>
        </div>
        <button type="button" className="dw-why-btn" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
          <HelpCircle size={14} aria-hidden="true" /> Why? <ChevronRight size={14} aria-hidden="true" className="dw-chev" />
        </button>
      </div>
      {open && (
        <ol id={id} className="dw-why-list">
          {figure.why.map((line, i) => <li key={i}>{line}</li>)}
        </ol>
      )}
    </div>
  );
}

const OP_LABEL: Record<string, string> = { '+': '+', '-': '−', x: '×', '=': '=', T: 'T', '': '' };

/** The calculation tape: values with the operator that combines them. */
export function Tape({ sections }: { sections: TapeSection[] }) {
  return (
    <div className="dw-tape" role="table" aria-label="Calculation tape">
      {sections.map((section) => (
        <div key={section.title} role="rowgroup" className="dw-tape-section">
          <div role="row" className="dw-tape-title"><span role="columnheader">{section.title}</span></div>
          {section.lines.map((line, index) => (
            <div
              key={`${section.title}-${index}`}
              role="row"
              className={`dw-tape-line ${line.emphasis ? 'em' : ''} ${line.op === 'T' || line.op === '=' ? 'sub' : ''}`}
              title={line.note || undefined}
            >
              <span role="cell" className="dw-tape-label">{line.label}</span>
              <span role="cell" className="dw-tape-value dw-num">
                {line.kind === 'percent' ? `${Number(line.value).toFixed(2)}%` : money2(line.value)}
              </span>
              <span role="cell" className={`dw-tape-op op-${line.op || 'none'}`} aria-label={opName(line.op)}>
                {OP_LABEL[line.op]}
              </span>
            </div>
          ))}
        </div>
      ))}
      <div className="dw-tape-legend">
        <span><b>T</b> subtotal / total</span><span><b>+ − × =</b> arithmetic operator</span>
        <span>Hover a line for its source</span>
      </div>
    </div>
  );
}

function opName(op: string): string {
  return { '+': 'plus', '-': 'minus', x: 'times', '=': 'equals', T: 'total', '': '' }[op] ?? '';
}

/** Money with cents when the engine gave cents (the unrounded line), whole dollars otherwise. */
export function money2(value: string): string {
  if (value.includes('.')) {
    const amount = Number(value);
    const text = Math.abs(amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return amount < 0 ? `−$${text}` : `$${text}`;
  }
  return money(value);
}
