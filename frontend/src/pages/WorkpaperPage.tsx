import { useRef, useState } from 'react';

import {
  api, type PipelineProgress, type Workflow,
} from '../api/client';
import { useAction, useAsync } from '../hooks/useApi';
import ReturnExplanationView from '../components/ReturnExplanation';
import {
  Badge, Card, ConfidenceMeter, Empty, ErrorBlock, LoadingBlock, Notice,
  PipelineTimeline, Spinner, formatBytes, formatDate, formatRelative,
  humanize, statusTone,
} from '../components/ui';

type Tab = 'results' | 'status' | 'outputs';

export default function WorkpaperPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('results');

  const files = useAsync(() => api.files.list(), []);
  const workflows = useAsync(() => api.workflows.list(), []);

  const upload = useAction(api.files.upload);

  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busyFileId, setBusyFileId] = useState<string | null>(null);

  // Live pipeline progress. Reading a scanned workpaper takes minutes, and a
  // spinner with nothing behind it is indistinguishable from a hang.
  const [progress, setProgress] = useState<PipelineProgress | null>(null);
  const [donePhases, setDonePhases] = useState<PipelineProgress[]>([]);
  const [runError, setRunError] = useState<string | null>(null);

  async function handleFiles(list: FileList | null) {
    if (!list?.length) return;
    for (const file of Array.from(list)) {
      await upload.run(file);
    }
    files.reload();
  }

  async function runPipeline(fileId: string) {
    setBusyFileId(fileId);
    setDonePhases([]);
    setProgress(null);
    setRunError(null);

    let workflowId: string | null = null;
    await api.workflows.processStream(fileId, undefined, {
      onProgress: (event) => {
        setProgress(event);
        if (event.status === 'completed') {
          setDonePhases((prior) => [...prior, event]);
        }
      },
      onDone: (result) => { workflowId = result.workflow_id; },
      onError: (message) => setRunError(message),
    });

    setBusyFileId(null);
    setProgress(null);
    files.reload();
    workflows.reload();
    if (workflowId) { setSelectedId(workflowId); setTab('results'); }
  }

  return (
    <div className="stack">
      {/* Upload panel */}
      <Card title="Upload workpapers">
        <div
          className={`dropzone ${dragging ? 'dragging' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            handleFiles(e.dataTransfer.files);
          }}
        >
          <div className="dz-icon">⬆</div>
          <div className="dz-title">
            {upload.pending ? 'Uploading…' : 'Drop files here, or click to browse'}
          </div>
          <div className="dz-hint">
            PDF, Word, Excel, CSV, text, and scanned images
          </div>
          <input
            ref={inputRef}
            type="file"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => handleFiles(e.target.files)}
          />
        </div>

        {upload.error && (
          <div style={{ marginTop: 12 }}>
            <Notice kind="danger">{upload.error}</Notice>
          </div>
        )}

        {/* The claim worth making once, not twice: the dropzone hint above
            used to repeat the encryption line verbatim. */}
        <div style={{ marginTop: 12 }}>
          <Notice kind="privacy">
            Files are encrypted the moment they arrive. Names and ID numbers are
            replaced with stand-ins before anything is sent for AI processing —
            your real details never leave this machine.
          </Notice>
        </div>
      </Card>

      {/* Files */}
      <Card
        title="Uploaded files"
        actions={<button className="btn sm ghost" onClick={files.reload}>↻</button>}
        bodyClass="tight"
      >
        {files.loading ? <LoadingBlock />
          : files.error ? <ErrorBlock message={files.error} onRetry={files.reload} />
          : !files.data?.items.length ? (
            <Empty title="No files uploaded yet" hint="Upload a workpaper to start the pipeline." />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Status</th>
                  <th>Uploaded</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {dedupeFiles(files.data.items).map(({ file, copies }) => (
                  <tr key={file.id}>
                    <td>
                      <div className="truncate" style={{ maxWidth: 380, fontWeight: 550 }}>
                        {file.original_filename}
                      </div>
                      {copies > 1 && (
                        <div className="subtle">
                          {copies} identical copies uploaded — newest shown
                        </div>
                      )}
                    </td>
                    <td>
                      <Badge tone={statusTone(file.status)}>{humanize(file.status)}</Badge>
                      {file.validation_notes && (
                        <div className="subtle" style={{ maxWidth: 300, marginTop: 3 }}>
                          {file.validation_notes}
                        </div>
                      )}
                    </td>
                    <td className="subtle">{formatRelative(file.created_at)}</td>
                    <td style={{ width: 1 }}>
                      <button
                        className="btn sm accent"
                        onClick={() => runPipeline(file.id)}
                        // A quarantined file cannot be decrypted; retrying can
                        // never succeed, so the action is disabled rather than
                        // inviting an endless retry loop.
                        disabled={
                          busyFileId !== null
                          || file.status === 'quarantined'
                        }
                        title={
                          file.status === 'quarantined'
                            ? 'This file cannot be read. Re-upload it to process it.'
                            : undefined
                        }
                      >
                        {busyFileId === file.id ? <Spinner /> : '▶ Process'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

        {/* Live progress. Replaces a silent multi-minute wait. */}
        {busyFileId && (
          <div className="progress-panel">
            <div className="progress-head">
              <strong>{progress?.label ?? 'Starting…'}</strong>
              <span className="subtle">
                Step {progress?.step ?? 1} of {progress?.steps ?? 9}
              </span>
            </div>
            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${progress?.percent ?? 0}%` }}
              />
            </div>
            {donePhases.length > 0 && (
              <ul className="progress-log">
                {donePhases.map((phase) => (
                  <li key={phase.stage}>
                    <span className="tick">✓</span>
                    <span>{phase.label}</span>
                    {phase.note && <span className="subtle"> — {phase.note}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {runError && (
          <div style={{ padding: 14 }}>
            <Notice kind="danger">{runError}</Notice>
          </div>
        )}
      </Card>

      {/* Workflows */}
      <Card
        title="Processing workflows"
        actions={<button className="btn sm ghost" onClick={workflows.reload}>↻</button>}
        bodyClass="tight"
      >
        {workflows.loading ? <LoadingBlock />
          : !workflows.data?.length ? (
            <Empty title="No workflows yet" hint="Process an uploaded file to create one." />
          ) : (
            /* Dropped from this table: the workflow's hex id, the internal
               stage name, the masked-value count, and a confidence meter that
               read 100% on every row. None of them told a preparer whether a
               run needed their attention, which is the only question this list
               has to answer. */
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Result</th>
                  <th className="num">Documents</th>
                  <th>Needs review</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {workflows.data.map((workflow) => (
                  <tr
                    key={workflow.id}
                    className="clickable"
                    onClick={() => { setSelectedId(workflow.id); setTab('results'); }}
                  >
                    <td style={{ fontWeight: 550 }}>
                      {workflow.source_filename ?? 'Workpaper'}
                    </td>
                    <td>
                      <Badge tone={statusTone(workflow.status)}>
                        {humanize(workflow.status)}
                      </Badge>
                    </td>
                    <td className="num">{workflow.documents_detected}</td>
                    <td>
                      {workflow.review_items_open > 0
                        ? (
                          <Badge tone="warning">
                            {workflow.review_items_open} item
                            {workflow.review_items_open === 1 ? '' : 's'}
                          </Badge>
                        )
                        : <span className="subtle">Nothing flagged</span>}
                    </td>
                    <td className="subtle">{formatRelative(workflow.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </Card>

      {selectedId && (
        <WorkflowDetail
          workflowId={selectedId}
          tab={tab}
          onTab={setTab}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}

function WorkflowDetail({
  workflowId, tab, onTab, onClose,
}: {
  workflowId: string; tab: Tab; onTab: (t: Tab) => void; onClose: () => void;
}) {
  const detail = useAsync(() => api.workflows.get(workflowId), [workflowId]);
  const explanation = useAsync(
    () => api.workflows.explanation(workflowId),
    [workflowId],
  );
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  if (detail.loading) return <Card title="Workflow"><LoadingBlock /></Card>;
  if (detail.error) return <Card title="Workflow"><ErrorBlock message={detail.error} onRetry={detail.reload} /></Card>;
  const workflow = detail.data;
  if (!workflow) return null;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'results', label: 'Tax result' },
    { key: 'status', label: 'Processing status' },
    {
      key: 'outputs',
      label: `Supporting documents (${workflow.output_packages?.length ?? 0})`,
    },
  ];

  const saveReport = async () => {
    setDownloadError(null);
    setDownloading(true);
    try {
      await api.workflows.downloadReport(
        workflow.id,
        `tax-report-${explanation.data?.tax_year ?? 'return'}.html`,
      );
    } catch (error) {
      setDownloadError(
        error instanceof Error ? error.message : 'The report could not be saved.',
      );
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Card
      title={workflow.source_filename ?? 'Tax return'}
      actions={
        <>
          {explanation.data && (
            <button
              type="button"
              className="btn sm primary"
              disabled={downloading}
              onClick={() => { void saveReport(); }}
            >
              {downloading ? 'Preparing…' : '⬇ Download report (HTML)'}
            </button>
          )}
          <button className="btn sm ghost" onClick={detail.reload}>↻</button>
          <button className="btn sm ghost" onClick={onClose}>✕ Close</button>
        </>
      }
    >
      {downloadError && <Notice kind="danger">{downloadError}</Notice>}

      <div className="toolbar">
        {tabs.map((t) => (
          <button
            key={t.key}
            className={`btn sm ${tab === t.key ? 'primary' : 'ghost'}`}
            onClick={() => onTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'results' && (
        explanation.loading ? <LoadingBlock label="Preparing your result…" />
          : explanation.data ? <ReturnExplanationView explanation={explanation.data} />
          : (
            <Empty
              title="No tax result yet"
              hint={
                'This run did not produce a computed return. Check the '
                + 'processing status for what stopped it.'
              }
            />
          )
      )}
      {tab === 'status' && <StatusTab workflow={workflow} />}
      {tab === 'outputs' && <OutputsTab workflow={workflow} />}
    </Card>
  );
}

/**
 * What the pipeline did, for someone who wants to know it ran cleanly.
 *
 * Deliberately not a debug view. The masked-text preview, token maps, model
 * tier and token counts that used to live here answered questions a preparer
 * never asks; they now live in the audit log, where an engineer or a compliance
 * reviewer can go looking for them on purpose.
 */
function StatusTab({ workflow }: { workflow: Workflow }) {
  const docs = workflow.documents ?? [];
  const unreadable = docs.filter((d) => d.requires_ocr && !d.ocr_performed);

  return (
    <div className="stack">
      <PipelineTimeline stages={workflow.stages ?? []} />

      {workflow.error_summary && <Notice kind="danger">{workflow.error_summary}</Notice>}

      {unreadable.length > 0 && (
        <Notice kind="warning">
          {unreadable.length} scanned page group(s) could not be read, so any
          figures on them are missing from the result. They have been routed to
          review rather than guessed at.
        </Notice>
      )}

      <div className="grid cols-3">
        <div>
          <div className="subtle">Documents found</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>{docs.length}</div>
        </div>
        <div>
          <div className="subtle">Items needing review</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>
            {workflow.review_items_open}
          </div>
        </div>
        <div>
          <div className="subtle">Reading confidence</div>
          <div style={{ marginTop: 6 }}>
            <ConfidenceMeter value={workflow.overall_confidence} />
          </div>
        </div>
      </div>

      {docs.length > 0 && (
        <div>
          <h3 style={{ marginBottom: 8 }}>Documents we read</h3>
          <table>
            <thead>
              <tr><th>Document</th><th>Pages</th><th>How it was read</th></tr>
            </thead>
            <tbody>
              {docs.map((doc) => (
                <tr key={doc.id}>
                  <td><Badge tone="info">{humanize(doc.document_type)}</Badge></td>
                  <td>{doc.page_start}–{doc.page_end}</td>
                  <td className="subtle">
                    {doc.ocr_performed
                      ? 'Scanned image, read by OCR'
                      : doc.requires_ocr
                        ? <Badge tone="warning">Could not be read</Badge>
                        : 'Digital text'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function OutputsTab({ workflow }: { workflow: Workflow }) {
  const packages = workflow.output_packages ?? [];
  if (!packages.length) return <Empty title="No output artifacts yet" />;

  return (
    <div className="stack">
      <Notice kind="warning">
        <strong>These files contain real taxpayer data.</strong> Real values were
        restored locally after AI processing finished. Every download is recorded
        in the audit log.
      </Notice>

      <table>
        <thead>
          <tr>
            <th>Artifact</th><th>Type</th><th className="num">Size</th>
            <th>Rehydrated</th><th>Created</th><th />
          </tr>
        </thead>
        <tbody>
          {packages.map((pkg) => (
            <tr key={pkg.id}>
              <td style={{ fontWeight: 550 }}>{pkg.filename}</td>
              <td><Badge tone="neutral">{humanize(pkg.artifact_type)}</Badge></td>
              <td className="num">{formatBytes(pkg.size_bytes)}</td>
              <td>
                {pkg.is_rehydrated
                  ? <Badge tone="warning">{pkg.tokens_rehydrated} value(s)</Badge>
                  : <Badge tone="neutral">No PII</Badge>}
              </td>
              <td className="subtle">{formatDate(pkg.created_at)}</td>
              <td style={{ width: 1 }}>
                <button
                  type="button"
                  className="btn sm"
                  onClick={() => {
                    void api.workflows.download(
                      workflow.id, pkg.artifact_type, pkg.filename,
                    );
                  }}
                >
                  ⬇ Download
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Collapse repeated uploads of the same file into one row.
 *
 * Re-uploading a workpaper while iterating is normal, and every upload is a
 * separate record with its own id. Listing all of them buries the file you
 * actually want behind four identical rows. Identity is the content hash, not
 * the name: two different files that happen to share a name stay separate.
 */
function dedupeFiles<T extends { id: string; content_hash: string; created_at: string }>(
  items: T[],
): { file: T; copies: number }[] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const group = groups.get(item.content_hash);
    if (group) group.push(item);
    else groups.set(item.content_hash, [item]);
  }

  return [...groups.values()]
    .map((group) => {
      const newest = group.reduce((a, b) =>
        a.created_at >= b.created_at ? a : b,
      );
      return { file: newest, copies: group.length };
    })
    .sort((a, b) => b.file.created_at.localeCompare(a.file.created_at));
}
