/**
 * Trace a figure: every line the calculation graph computed, each one
 * clickable down to the page it was read from.
 *
 *   form line  ->  explain(node_id) tree  ->  source page, figure highlighted
 *
 * The page is the masked zone's copy: masked text plus the boxes of the dollar
 * figures on it. There is deliberately no image of the original - that would
 * be the unmasked document in the browser, and no route serves one.
 */

import { useMemo, useState } from 'react';

import {
  api,
  type ExplainNode, type GraphLine, type GraphReturn, type LeafKind,
  type SourceFact, type SourcePage,
} from '../api/client';
import { useAsync } from '../hooks/useApi';
import {
  Badge, Card, Empty, ErrorBlock, LoadingBlock, Notice, humanize, type Tone,
} from './ui';

/** Dollars, the way a preparer reads them. None is "not computed", never 0. */
function money(raw: string | null): string {
  if (raw === null) return 'not computed';
  const value = Number(raw);
  if (!Number.isFinite(value)) return raw;
  const body = Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  });
  return value < 0 ? `(${body})` : body;
}

const LEAF: Record<LeafKind, { label: string; tone: Tone }> = {
  source: { label: 'Read from a document', tone: 'success' },
  statutory: { label: 'Set by law', tone: 'info' },
  not_reported: { label: 'Nothing reported, entered 0', tone: 'neutral' },
  nil: { label: 'Not used on this return', tone: 'neutral' },
  supplied: { label: 'No document named', tone: 'warning' },
  unsupported: { label: 'Not computed', tone: 'danger' },
  standalone: { label: 'No inputs recorded', tone: 'warning' },
};

/* ------------------------------------------------------------ source page */

/** The figure as the page might print it: 52,340.00 / 52,340 / 52340.00. */
function spellings(amount: string | null): string[] {
  const value = Math.abs(Number(amount));
  if (!amount || !Number.isFinite(value) || value === 0) return [];
  const grouped = value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const plain = value.toFixed(2);
  const whole = Number.isInteger(value)
    ? [value.toLocaleString('en-US'), String(value)]
    : [];
  return [...new Set([grouped, plain, ...whole])];
}

function sameFigure(text: string, amount: string | null): boolean {
  const parsed = Number(text.replace(/[$,()]/g, ''));
  return amount !== null && Number.isFinite(parsed) && Math.abs(parsed) === Math.abs(Number(amount));
}

function sameBox(a: number[], b: string[] | null): boolean {
  return !!b && a.length === 4 && a.every((v, i) => Math.abs(v - Number(b[i])) < 0.5);
}

function HighlightedText({ text, marks }: { text: string; marks: string[] }) {
  if (!marks.length) return <>{text}</>;
  const escaped = marks.map((m) => m.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`(${escaped.join('|')})`, 'g');
  return (
    <>
      {text.split(pattern).map((part, i) => (
        marks.includes(part) ? <mark key={i}>{part}</mark> : <span key={i}>{part}</span>
      ))}
    </>
  );
}

function PageMap({ page, source }: { page: SourcePage; source: SourceFact }) {
  if (!page.width || !page.height || !page.figures.length) return null;
  return (
    <div
      className="page-map"
      style={{ aspectRatio: `${page.width} / ${page.height}` }}
      aria-label={`Page ${page.page}, figure positions`}
    >
      {page.figures.map((figure, index) => {
        const [x0, y0, x1, y1] = figure.bbox;
        const primary = sameBox(figure.bbox, source.bbox);
        const match = !primary && sameFigure(figure.text, source.amount);
        return (
          <span
            key={index}
            className={`page-figure${primary ? ' primary' : match ? ' match' : ''}`}
            style={{
              left: `${(x0 / page.width) * 100}%`,
              top: `${(y0 / page.height) * 100}%`,
              width: `${((x1 - x0) / page.width) * 100}%`,
              height: `${((y1 - y0) / page.height) * 100}%`,
            }}
            title={figure.text}
          >
            {figure.text}
          </span>
        );
      })}
    </div>
  );
}

function SourcePageView({
  workflowId, source, onClose,
}: { workflowId: string; source: SourceFact; onClose: () => void }) {
  const page = useAsync(
    () => api.workflows.sourcePage(workflowId, source.document_id, source.page),
    [workflowId, source.document_id, source.page],
  );

  const marks = useMemo(() => {
    const onPage = (page.data?.figures ?? [])
      .filter((f) => sameFigure(f.text, source.amount))
      .map((f) => f.text);
    return [...new Set([...onPage, ...spellings(source.amount)])];
  }, [page.data, source.amount]);

  return (
    <Card
      title={`${humanize(source.document_type)} · page ${source.page}`}
      subtitle={`Where ${source.field.replace(/_/g, ' ')} was read`}
      actions={<button className="btn sm ghost" onClick={onClose}>✕</button>}
    >
      <div className="source-meta">
        {source.amount !== null && <span>This document: <strong>{money(source.amount)}</strong></span>}
        <span>Reading confidence: {Math.round(Number(source.confidence) * 100)}%</span>
        {source.bbox
          ? <Badge tone="success">Located on the page</Badge>
          : <Badge tone="neutral">Position not pinned - every match is marked</Badge>}
      </div>

      {page.loading && <LoadingBlock label="Opening the page…" />}
      {page.error && <ErrorBlock message={page.error} onRetry={page.reload} />}
      {page.data && (
        <div className="source-page">
          <PageMap page={page.data} source={source} />
          {page.data.whole_document && (
            <Notice kind="info">
              This run did not record page breaks, so the whole document
              (pages {page.data.page_start}-{page.data.page_end}) is shown.
            </Notice>
          )}
          <pre className="masked-page">
            {page.data.masked_text
              ? <HighlightedText text={page.data.masked_text} marks={marks} />
              : 'No text was read from this page.'}
          </pre>
          <p className="subtle">
            Personal details are shown as tokens - this is the masked copy the
            model saw, not the original scan.
          </p>
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------ explain tree */

function SourceChips({
  sources, onOpen,
}: { sources: SourceFact[]; onOpen: (s: SourceFact) => void }) {
  return (
    <div className="source-chips">
      {sources.map((source, index) => (
        <button
          key={`${source.document_id}-${source.page}-${index}`}
          type="button"
          className="doc-chip clickable"
          disabled={!source.document_id}
          onClick={() => onOpen(source)}
          title={source.document_id ? 'Open the page' : 'No document was recorded for this figure'}
        >
          {humanize(source.document_type || 'unknown document')} · p.{source.page}
          {source.amount !== null && ` · ${money(source.amount)}`}
        </button>
      ))}
    </div>
  );
}

function TreeNode({
  node, depth, onOpen,
}: { node: ExplainNode; depth: number; onOpen: (s: SourceFact) => void }) {
  const [open, setOpen] = useState(depth < 1);
  const expandable = node.children.length > 0 || !!node.leaf;
  const leaf = node.leaf ? LEAF[node.leaf] : null;

  return (
    <li className="tree-node">
      <button
        type="button"
        className="tree-row"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="chevron">{expandable ? (open ? '▾' : '▸') : ''}</span>
        <span className="tree-label">
          {node.label}
          <code className="tree-id">{node.node_id}</code>
        </span>
        {leaf && <Badge tone={leaf.tone}>{leaf.label}</Badge>}
        {node.repeated && <Badge tone="neutral">shown above</Badge>}
        <span className="num tree-amount">{money(node.amount)}</span>
      </button>

      {open && (
        <div className="tree-detail">
          <code className="formula">{node.formula}</code>
          <div className="tree-ref">
            {node.authority
              ? <a href={node.authority.url} target="_blank" rel="noreferrer noopener">{node.reference}</a>
              : <span>{node.reference}</span>}
          </div>
          {node.flags.length > 0 && (
            <ul className="tree-flags">
              {node.flags.map((flag) => <li key={flag}>⚠ {flag}</li>)}
            </ul>
          )}
          {node.leaf === 'source' && <SourceChips sources={node.sources} onOpen={onOpen} />}
          {node.children.length > 0 && (
            <ul className="tree">
              {node.children.map((child) => (
                <TreeNode key={child.node_id} node={child} depth={depth + 1} onOpen={onOpen} />
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

function ExplainPanel({
  workflowId, nodeId, onOpen,
}: { workflowId: string; nodeId: string; onOpen: (s: SourceFact) => void }) {
  const tree = useAsync(() => api.workflows.explain(workflowId, nodeId), [workflowId, nodeId]);
  if (tree.loading) return <LoadingBlock label="Tracing the figure…" />;
  if (tree.error) return <ErrorBlock message={tree.error} onRetry={tree.reload} />;
  if (!tree.data) return null;
  return (
    <div className="trace-tree">
      {tree.data.sources.length > 0 && (
        <section>
          <h4>Documents behind this figure</h4>
          <SourceChips sources={tree.data.sources} onOpen={onOpen} />
        </section>
      )}
      <section>
        <h4>How it was computed</h4>
        <ul className="tree root">
          <TreeNode node={tree.data} depth={0} onOpen={onOpen} />
        </ul>
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ lines */

function FormLines({
  form, lines, showAll, selected, onSelect,
}: {
  form: string; lines: GraphLine[]; showAll: boolean;
  selected: string | null; onSelect: (id: string) => void;
}) {
  const shown = showAll
    ? lines
    : lines.filter((l) => l.amount === null || Number(l.amount) !== 0);
  if (!shown.length) return null;
  return (
    <div className="flow-section">
      <h3>{form}</h3>
      <table className="lines">
        <tbody>
          {shown.map((line) => (
            <tr
              key={line.node_id}
              className={`clickable line-row${selected === line.node_id ? ' selected' : ''}`}
              onClick={() => onSelect(line.node_id)}
            >
              <td className="line-number">{line.line}</td>
              <td><div className="line-label">{line.label}</div></td>
              <td>
                {line.amount === null && <Badge tone="danger">Not computed</Badge>}
                {line.amount !== null && line.sources.length > 0 && (
                  <Badge tone="success">{line.sources.length} source{line.sources.length === 1 ? '' : 's'}</Badge>
                )}
              </td>
              <td className="num line-amount">
                <button type="button" className="link-button" onClick={() => onSelect(line.node_id)}>
                  {money(line.amount)}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Warnings({ graph }: { graph: GraphReturn }) {
  const missing = graph.unplaced.filter((u) => u.blocks_filing);
  const aside = graph.unplaced.filter((u) => !u.blocks_filing);
  return (
    <>
      {!graph.fileable && (
        <Notice kind="warning">
          <strong>Not fileable as computed.</strong>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {graph.unsupported.length > 0 && (
              <li>
                {graph.unsupported.length} line{graph.unsupported.length === 1 ? '' : 's'} could
                not be computed: {graph.unsupported.join(', ')}. Every line that depends
                on them is marked too.
              </li>
            )}
            {missing.map((u) => (
              <li key={u.field}>
                {humanize(u.field)} of {money(u.amount)} was read but is on no line
                here - {u.reason}.
              </li>
            ))}
          </ul>
        </Notice>
      )}
      {aside.length > 0 && (
        <Notice kind="info">
          Read, and not a Form 1040 input:{' '}
          {aside.map((u) => `${humanize(u.field)} (${u.reason})`).join('; ')}.
        </Notice>
      )}
      {graph.notes.map((note) => <Notice key={note} kind="info">{note}</Notice>)}
    </>
  );
}

export default function FigureTrace({ workflowId }: { workflowId: string }) {
  const graph = useAsync(() => api.workflows.graph(workflowId), [workflowId]);
  const [selected, setSelected] = useState<string | null>(null);
  const [source, setSource] = useState<SourceFact | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [exporting, setExporting] = useState<'pdf' | 'json' | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const exportReport = async (format: 'pdf' | 'json') => {
    setExportError(null);
    setExporting(format);
    try {
      await api.workflows.downloadCalculationReport(workflowId, format);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : 'The report could not be saved.');
    } finally {
      setExporting(null);
    }
  };

  if (graph.loading) return <LoadingBlock label="Computing every line…" />;
  if (graph.error) {
    return (
      <Empty
        title="Nothing to trace yet"
        hint={graph.error}
      />
    );
  }
  if (!graph.data) return null;

  const byForm = graph.data.forms.map((form) => ({
    form,
    lines: graph.data!.lines.filter((l) => l.form === form),
  }));

  return (
    <div className="stack">
      <div className="toolbar">
        <button
          type="button"
          className="btn sm primary"
          disabled={exporting !== null}
          onClick={() => { void exportReport('pdf'); }}
        >
          {exporting === 'pdf' ? 'Preparing…' : '⬇ Calculation report (PDF)'}
        </button>
        <button
          type="button"
          className="btn sm ghost"
          disabled={exporting !== null}
          onClick={() => { void exportReport('json'); }}
        >
          {exporting === 'json' ? 'Preparing…' : '⬇ JSON'}
        </button>
      </div>
      {exportError && <Notice kind="danger">{exportError}</Notice>}
      <Warnings graph={graph.data} />
      <div className="trace-grid">
        <Card
          title="Every line, with its sources"
          subtitle="Select a figure to see what it was computed from, down to the page."
          actions={
            <button className="btn sm ghost" onClick={() => setShowAll((v) => !v)}>
              {showAll ? 'Hide' : 'Show'} empty lines
            </button>
          }
        >
          {byForm.map(({ form, lines }) => (
            <FormLines
              key={form}
              form={form}
              lines={lines}
              showAll={showAll}
              selected={selected}
              onSelect={(id) => { setSelected(id); setSource(null); }}
            />
          ))}
        </Card>

        <div className="stack trace-side">
          {selected ? (
            <Card title="Where this figure came from" subtitle={selected}>
              <ExplainPanel workflowId={workflowId} nodeId={selected} onOpen={setSource} />
            </Card>
          ) : (
            <Card title="Where this figure came from">
              <p className="subtle">Select any figure on the left.</p>
            </Card>
          )}
          {source && (
            <SourcePageView
              key={`${source.document_id}-${source.page}-${source.field}`}
              workflowId={workflowId}
              source={source}
              onClose={() => setSource(null)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
