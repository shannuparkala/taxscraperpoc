/**
 * The conversation sidebar: new chat, and everything asked before.
 *
 * A stored title is the first question the user typed, so it may contain a
 * client's name — it is shown only to the authenticated user whose session it
 * is, which is the same rule the backend applies when it stores it.
 */

import { Plus } from 'lucide-react';

import type { ChatSession } from '../../api/client';

interface Props {
  sessions: ChatSession[];
  activeId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  loading: boolean;
}

export default function ConversationList({
  sessions, activeId, onOpen, onNew, onDelete, loading,
}: Props) {
  return (
    <div className="conversation-list">
      <button type="button" className="new-chat" onClick={onNew}>
        <Plus size={17} aria-hidden="true" /> New chat
      </button>
      <div className="conversation-heading">Research log</div>

      <div className="conversation-scroll">
        {loading && sessions.length === 0 && (
          <p className="muted small">Loading…</p>
        )}

        {!loading && sessions.length === 0 && (
          <p className="muted small">
            Nothing yet. Ask a question and it will appear here.
          </p>
        )}

        {sessions.map((session) => (
          <div
            key={session.id}
            className={`conversation-item ${session.id === activeId ? 'active' : ''}`}
          >
            <button
              type="button"
              className="conversation-open"
              onClick={() => onOpen(session.id)}
              title={session.title}
            >
              <span className="conversation-title">{session.title}</span>
              <span className="conversation-meta">
                {session.state_code && (
                  <span className="badge accent sm">{session.state_code}</span>
                )}
                <span>{relativeTime(session.last_message_at ?? session.created_at)}</span>
              </span>
            </button>
            <button
              type="button"
              className="conversation-delete"
              aria-label={`Delete “${session.title}”`}
              title="Delete this conversation"
              onClick={() => onDelete(session.id)}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

/** "3 min ago" beats a timestamp in a list scanned for the recent one. */
function relativeTime(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return '';
  const seconds = Math.max(0, (Date.now() - then) / 1000);

  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 604_800) return `${Math.floor(seconds / 86_400)} d ago`;
  return new Date(then).toLocaleDateString();
}
