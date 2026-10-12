/**
 * The whole product in one screen: drop a file, get a return.
 *
 * There is deliberately nothing else here. The previous page led with an upload
 * box and then two tables — every file ever uploaded, and every run ever made —
 * which meant the first thing a user saw was other people's history rather than
 * the thing they came to do. Those lists answered an operator's question, not a
 * preparer's, and they are gone.
 *
 * The screen has exactly three states, and only ever shows one:
 *   idle       -> the dropzone
 *   working    -> what is happening right now, and nothing else
 *   done       -> the result, its explanation, and the files to download
 */

import { useRef, useState } from 'react';

import {
  api, type Explanation, type OutputPackage, type PipelineProgress,
  type ReviewItem, type Workflow,
} from '../api/client';
import CostMeter from '../components/CostMeter';
import FigureTrace from '../components/FigureTrace';
import ReturnExplanationView from '../components/ReturnExplanation';
import { Card, Empty, Notice, formatBytes } from '../components/ui';

type Phase = 'idle' | 'working' | 'done' | 'failed';

const STAGE_COPY: Record<string, string> = {
  upload: 'Securing your file',
  classification: 'Identifying the documents',
  ocr: 'Reading the pages',
  masking: 'Replacing personal details',
  llm_processing: 'Pulling out the tax figures',
  validation: 'Checking the maths',
  review: 'Flagging anything unclear',
  rehydration: 'Restoring your real details',
  output: 'Building your documents',
};

const STAGE_ORDER = Object.keys(STAGE_COPY);

export default function HomePage() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [fileName, setFileName] = useState('');
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<PipelineProgress | null>(null);
  const [completed, setCompleted] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [outputs, setOutputs] = useState<OutputPackage[]>([]);
  // Why there is no return, when there is no return. The card here used to
  // assert "no tax figures could be read", which was the wrong reason far more
  // often than the right one: a workpaper whose figures read perfectly but
  // whose filing status could not be established lands in exactly the same
  // branch, and the screen told the preparer to go and fix the OCR.
  const [blockers, setBlockers] = useState<ReviewItem[]>([]);
  const [tracing, setTracing] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

  function reset() {
    setPhase('idle');
    setFileName('');
    setProgress(null);
    setCompleted([]);
    setError(null);
    setWorkflow(null);
    setExplanation(null);
    setOutputs([]);
    setBlockers([]);
    setTracing(false);
  }

  async function handleFile(file: File | undefined) {
    if (!file) return;

    reset();
    setPhase('working');
    setFileName(file.name);

    try {
      const uploaded = await api.files.upload(file);

      let workflowId: string | null = null;
      let streamError: string | null = null;

      await api.workflows.processStream(uploaded.id, undefined, {
        onProgress: (event) => {
          setProgress(event);
          if (event.status === 'completed') {
            setCompleted((prior) =>
              prior.includes(event.stage) ? prior : [...prior, event.stage],
            );
          }
        },
        onDone: (result) => { workflowId = result.workflow_id; },
        onError: (message) => { streamError = message; },
      });

      if (streamError || !workflowId) {
        setError(streamError ?? 'Processing did not finish.');
        setPhase('failed');
        return;
      }

      // The return and its explanation are fetched together: a result with no
      // account of how it was reached is the thing this product exists to
      // avoid showing.
      const [detail, packages, explained, queued] = await Promise.all([
        api.workflows.get(workflowId),
        api.workflows.outputs(workflowId).catch(() => [] as OutputPackage[]),
        api.workflows.explanation(workflowId).catch(() => null),
        api.review
          .queue('pending', workflowId)
          .then((r) => r.items)
          .catch(() => [] as ReviewItem[]),
      ]);

      setWorkflow(detail);
      setOutputs(packages);
      setExplanation(explained);
      setBlockers(queued.filter((item) => item.workflow_id === workflowId));
      setPhase('done');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setPhase('failed');
    }
  }

  if (phase === 'working') {
    return (
      <Working
        fileName={fileName}
        progress={progress}
        completed={completed}
      />
    );
  }

  if (phase === 'failed') {
    return (
      <Card title="We could not finish this file">
        <Notice kind="danger">{error}</Notice>
        <button className="btn primary" style={{ marginTop: 14 }} onClick={reset}>
          Try another file
        </button>
      </Card>
    );
  }

  if (phase === 'done') {
    return (
      <div className="stack">
        <div className="result-bar">
          <div>
            <div className="result-file">{fileName}</div>
            <div className="subtle">Finished — everything below came from this file.</div>
          </div>
          <button className="btn" onClick={reset}>Process another file</button>
        </div>

        {workflow && workflow.review_items_open > 0 && (
          <Notice kind="warning">
            <strong>
              {workflow.review_items_open} item
              {workflow.review_items_open === 1 ? '' : 's'} need a person to look.
            </strong>{' '}
            The figures below are computed, but something in the documents was
            unclear or missing. Each one is listed under “What we assumed”.
          </Notice>
        )}

        {explanation
          ? <ReturnExplanationView explanation={explanation} />
          : <NoReturn blockers={blockers} />}

        {explanation && workflow && (
          tracing
            ? <FigureTrace workflowId={workflow.id} />
            : (
              <Card
                title="Trace any figure to its page"
                subtitle="Every line of every form, each one walked back to the document and page it was read from."
                actions={
                  <button className="btn sm primary" onClick={() => setTracing(true)}>
                    Trace a figure
                  </button>
                }
              >
                <p className="subtle">
                  Computed by the calculation engine from the same extracted
                  figures, with the provenance of every line.
                </p>
              </Card>
            )
        )}

        <Downloads outputs={outputs} workflowId={workflow?.id ?? ''} />

        {workflow && <CostMeter workflowId={workflow.id} />}
      </div>
    );
  }

  return (
    <div className="landing">
      <div className="landing-head">
        <h2>Drop your tax documents in</h2>
        <p>
          W-2s, 1099s, K-1s, brokerage statements, prior returns — one file or a
          whole scanned workpaper. We read them, compute the return, and show you
          how every figure was reached.
        </p>
      </div>

      <div
        className={`dropzone big ${dragging ? 'dragging' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFile(e.dataTransfer.files?.[0]);
        }}
      >
        <div className="dz-icon">⬆</div>
        <div className="dz-title">Drop a file here, or click to browse</div>
        <div className="dz-hint">PDF, Word, Excel, CSV, text, or a scanned image</div>
        <input
          ref={inputRef}
          type="file"
          style={{ display: 'none' }}
          onChange={(e) => handleFile(e.target.files?.[0] ?? undefined)}
        />
      </div>

      <Notice kind="privacy">
        Your file is encrypted the moment it arrives. Names and ID numbers are
        replaced with stand-ins before anything is sent for AI processing — your
        real details never leave this machine.
      </Notice>
    </div>
  );
}

/**
 * Why no return was produced — using the reasons the pipeline actually gave.
 *
 * The pipeline refuses in more than one place and each refusal writes a review
 * item saying which one: no monetary field was read, or the filing status could
 * not be established, or last year's return is needed. Showing those beats
 * guessing at one of them, and a preparer who is told the real reason can
 * usually clear it in a minute.
 */
function NoReturn({ blockers }: { blockers: ReviewItem[] }) {
  // Every refusal in the pipeline titles its item "… not computed" or
  // "… could not …". Anything else in the queue is a figure to verify on a
  // return that did compute, and listing sixty of those here would bury the
  // one line that matters.
  const blocking = blockers.filter((item) => /not computed|could not/i.test(item.title));

  if (blocking.length === 0) {
    return (
      <Card title="No return could be computed">
        <Empty
          title="No reason was recorded"
          hint="Processing finished without a return and without saying which check
                stopped it. That is a defect rather than something missing from your
                documents — the review queue for this run has the detail."
        />
      </Card>
    );
  }

  return (
    <Card
      title="No return could be computed"
      subtitle="Nothing was guessed. This is what stopped it."
    >
      <div className="stack">
        {blocking.map((item) => (
          <Notice kind="warning" key={item.id}>
            <strong>{item.title}</strong>
            {item.description && <div style={{ marginTop: 6 }}>{item.description}</div>}
          </Notice>
        ))}
      </div>
    </Card>
  );
}

function Working({
  fileName, progress, completed,
}: {
  fileName: string;
  progress: PipelineProgress | null;
  completed: string[];
}) {
  const currentIndex = progress ? STAGE_ORDER.indexOf(progress.stage) : 0;

  return (
    <div className="landing">
      <div className="landing-head">
        <h2>Working through {fileName}</h2>
        <p>
          Reading a scanned workpaper takes a few minutes. You can leave this
          open — nothing is lost if you look away.
        </p>
      </div>

      <Card>
        <ol className="progress-list">
          {STAGE_ORDER.map((stage, index) => {
            const done = completed.includes(stage);
            const active = !done && index === currentIndex;
            return (
              <li
                key={stage}
                className={done ? 'done' : active ? 'active' : 'pending'}
              >
                <span className="progress-mark">
                  {done ? '✓' : active ? <span className="spinner" /> : ''}
                </span>
                <span>{STAGE_COPY[stage]}</span>
              </li>
            );
          })}
        </ol>
      </Card>
    </div>
  );
}

function Downloads({
  outputs, workflowId,
}: {
  outputs: OutputPackage[]; workflowId: string;
}) {
  // Downloads go through an authenticated fetch rather than a plain link, so
  // unlike an <a href> they can fail in a way the user needs to be told about.
  const [failed, setFailed] = useState<string | null>(null);

  if (!outputs.length) return null;

  return (
    <Card
      title="Your documents"
      subtitle="Every file below has your real details restored. Downloads are recorded."
    >
      {failed && <Notice kind="danger">{failed}</Notice>}
      <div className="downloads">
        {outputs.map((pkg) => (
          <button
            key={pkg.id}
            type="button"
            className="download-card"
            onClick={() => {
              void api.workflows
                .download(workflowId, pkg.artifact_type, pkg.filename)
                .catch((caught) =>
                  setFailed(
                    caught instanceof Error ? caught.message : String(caught),
                  ),
                );
            }}
          >
            <span className="download-icon">⬇</span>
            <span className="download-body">
              <span className="download-name">{pkg.filename}</span>
              <span className="download-meta">{formatBytes(pkg.size_bytes)}</span>
            </span>
          </button>
        ))}
      </div>
    </Card>
  );
}
