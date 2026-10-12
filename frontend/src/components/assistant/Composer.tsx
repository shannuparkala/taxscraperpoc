/**
 * The message box: suggestions, attachments, the state badge, and send.
 *
 * Three behaviours that are easy to get wrong and very obvious when they are:
 *
 * * **Enter sends, Shift+Enter breaks the line.** A tax question is often two
 *   sentences and a list of figures, so the multi-line case is normal.
 * * **The box grows with the text**, to a ceiling. A fixed two-line box hides
 *   the middle of a scenario question while it is being written.
 * * **Stop is where Send was.** While an answer is being researched the same
 *   button stops it, because that is where the pointer already is.
 */

import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Paperclip, ShieldCheck, Square, X } from 'lucide-react';

import type { Attachment, StateProfile } from '../../api/client';

const MAX_ROWS_PX = 200;

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  suggestions: string[];
  onSuggestion: (question: string) => void;
  attachments: Attachment[];
  onAttach: (file: File) => void;
  onDetach: (documentId: string) => void;
  attaching: boolean;
  attachError: string;
  state: StateProfile | null;
  onClearState: () => void;
}

export default function Composer({
  value, onChange, onSend, onStop, streaming,
  suggestions, onSuggestion,
  attachments, onAttach, onDetach, attaching, attachError,
  state, onClearState,
}: Props) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  // Grow to fit, up to a ceiling. Reset to auto first or the box can only
  // ever get taller.
  useEffect(() => {
    const node = textarea.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${Math.min(node.scrollHeight, MAX_ROWS_PX)}px`;
  }, [value]);

  const submit = () => {
    if (streaming) return;
    if (!value.trim()) return;
    onSend();
  };

  return (
    <div
      className={`composer ${dragging ? 'dragging' : ''}`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        const file = event.dataTransfer.files?.[0];
        if (file) onAttach(file);
      }}
    >
      {suggestions.length > 0 && !streaming && (
        <div className="composer-suggestions">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => onSuggestion(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {(attachments.length > 0 || attaching || attachError) && (
        <div className="composer-attachments">
          {attachments.map((attachment) => (
            <span key={attachment.document_id} className="attachment-chip">
              <span className="attachment-name" title={attachment.filename}>
                {attachment.filename}
              </span>
              {attachment.page_count > 0 && (
                <span className="attachment-meta">
                  {attachment.page_count}p
                </span>
              )}
              {attachment.masked_value_count > 0 && (
                <span
                  className="attachment-meta"
                  title={`${attachment.masked_value_count} personal details replaced with placeholders before anything was sent`}
                >
                  <ShieldCheck size={12} /> {attachment.masked_value_count}
                </span>
              )}
              {attachment.needs_review && (
                <span
                  className="attachment-meta warn"
                  title="Only part of this document could be read; check anything quoted from it"
                >
                  partial
                </span>
              )}
              <button
                type="button"
                aria-label={`Remove ${attachment.filename}`}
                onClick={() => onDetach(attachment.document_id)}
              >
                <X size={12} />
              </button>
            </span>
          ))}
          {attaching && <span className="attachment-chip pending">Reading…</span>}
          {attachError && (
            <span className="attachment-chip error">{attachError}</span>
          )}
        </div>
      )}

      <div className="composer-box">
        <button
          type="button"
          className="composer-icon"
          title="Attach a PDF, Word document, spreadsheet, CSV or text file"
          aria-label="Attach a document"
          onClick={() => fileInput.current?.click()}
          disabled={attaching}
        >
          <Paperclip size={18} />
        </button>
        <input
          ref={fileInput}
          type="file"
          hidden
          accept=".pdf,.docx,.txt,.xlsx,.xls,.csv"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onAttach(file);
            // Clear it, or picking the same file twice does nothing.
            event.target.value = '';
          }}
        />

        <textarea
          ref={textarea}
          rows={1}
          value={value}
          placeholder={
            state
              ? `Ask a federal or ${state.name} tax or audit question…`
              : 'Ask a US tax or audit question…'
          }
          aria-label="Your question"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
        />

        <button
          type="button"
          className={`composer-send ${streaming ? 'stop' : ''}`}
          onClick={streaming ? onStop : submit}
          disabled={!streaming && !value.trim()}
          title={streaming ? 'Stop generating' : 'Send (Enter)'}
          aria-label={streaming ? 'Stop generating' : 'Send question'}
        >
          {streaming ? <Square size={15} fill="currentColor" /> : <ArrowUp size={19} />}
        </button>
      </div>

      <div className="composer-foot">
        {state ? (
          <button
            type="button"
            className="state-badge"
            onClick={onClearState}
            title="Clear the state context"
          >
            <span className="dot" />
            {state.name}
            <X size={12} className="state-badge-clear" />
          </button>
        ) : (
          <span className="muted">Federal — no state selected</span>
        )}
        {/^\s*\/mask(?![\w-])/i.test(value) ? (
          <span className="composer-mask on" title="Names and identifiers in this message are replaced with placeholders before it is sent">
            <ShieldCheck size={12} /> Masking on
          </span>
        ) : (
          <span className="composer-mask muted" title="Questions are sent as typed. Start a message with /mask to replace names and identifiers with placeholders first.">
            Start with /mask to hide names and identifiers
          </span>
        )}
      </div>
    </div>
  );
}
