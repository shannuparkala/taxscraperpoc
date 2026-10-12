/**
 * The tax and audit assistant.
 *
 * Three panes: conversations on the left, the conversation in the middle,
 * jurisdiction (the state map) on the right. The middle one is the product.
 *
 * The state clicked on the map is sent as `selected_state` with every
 * question - structured input, never something inferred from the text. The
 * server checks it against its allow-list, carries it across turns, and says
 * so in the answer when it changes mid-conversation.
 *
 * The server streams the answer as the model writes it: `step` events as each
 * stage really starts, `delta` events with answer text, then one `final` event
 * holding the checked answer with its sources. Sources are known only when the
 * stream ends, so the streamed draft is marked as being checked; if it fails a
 * check the server sends `replace`, the draft is withdrawn from the screen and
 * a new one streams in its place.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ArrowUpRight, Check, Copy, Download, LoaderCircle, Menu, RotateCcw, Scale } from 'lucide-react';

import {
  api,
  type AssistantAnswer,
  type Attachment,
  type ChatSession,
  type StateProfile,
} from '../api/client';
import AnswerCard from '../components/assistant/AnswerCard';
import Composer from '../components/assistant/Composer';
import ConversationList from '../components/assistant/ConversationList';
import Markdown from '../components/assistant/Markdown';
import StatePanel from '../components/assistant/StatePanel';
import { useTaxContext } from '../context/TaxContext';

const STATE_KEY = 'taxscraper_assistant_state';
const PANEL_KEY = 'taxscraper_assistant_panel';

interface Turn {
  id: string;
  question: string;
  /** The checked answer. Null while the server is still working. */
  answer: AssistantAnswer | null;
  /** Progress lines from the server, oldest first; the last is current. */
  steps: string[];
  /** Answer text streamed so far, before it has been checked. */
  draft: string;
  /** Why the last draft was withdrawn, if one was. */
  withdrawn: string;
  error: string;
  done: boolean;
}

const blankTurn = (id: string, question: string): Turn => ({
  id, question, answer: null, steps: [], draft: '', withdrawn: '', error: '', done: false,
});

export default function AssistantPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);

  const [profiles, setProfiles] = useState<StateProfile[]>([]);
  const [selectedState, setSelectedState] = useState<string | null>(() => read(STATE_KEY));
  // The shared year (sidebar TY chip): context for a question that names no year.
  const { taxYear } = useTaxContext();
  const [panelOpen, setPanelOpen] = useState(() => read(PANEL_KEY) !== 'closed');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Other sections open the assistant as /assistant?q=...&state=XX. The
  // question is only placed in the composer - never sent without the user -
  // and the state goes through the same allow-list check as a map click.
  const [searchParams, setSearchParams] = useSearchParams();
  const [draft, setDraft] = useState(() => searchParams.get('q') ?? '');
  const [working, setWorking] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attaching, setAttaching] = useState(false);
  const [attachError, setAttachError] = useState('');
  const [copied, setCopied] = useState('');

  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);

  const stateProfile = profiles.find((profile) => profile.code === selectedState) ?? null;

  // --- Loading ----------------------------------------------------------

  useEffect(() => {
    void api.chat
      .states()
      .then((loaded) => {
        setProfiles(loaded);
        const linked = searchParams.get('state')?.toUpperCase();
        if (linked && loaded.some((profile) => profile.code === linked)) setSelectedState(linked);
        if (searchParams.has('q') || searchParams.has('state')) setSearchParams({}, { replace: true });
        // A remembered state the server no longer accepts is dropped rather
        // than sent and rejected on the first question.
        setSelectedState((current) =>
          current && !loaded.some((profile) => profile.code === current) ? null : current,
        );
      })
      .catch(() => setProfiles([]));
    // Read the link parameters once, on arrival.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      setSessions(await api.chat.sessions());
    } catch {
      setSessions([]);
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  useEffect(() => {
    let cancelled = false;
    void api.chat
      .suggestions({ state: selectedState, session: sessionId })
      .then((result) => {
        if (!cancelled) setSuggestions(result.suggestions);
      })
      .catch(() => {
        if (!cancelled) setSuggestions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedState, sessionId, attachments.length]);

  useEffect(() => write(STATE_KEY, selectedState), [selectedState]);
  useEffect(() => write(PANEL_KEY, panelOpen ? 'open' : 'closed'), [panelOpen]);

  // --- Scrolling --------------------------------------------------------

  useEffect(() => {
    const node = scroller.current;
    if (!node) return;
    const onScroll = () => {
      const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
      pinnedToBottom.current = distance < 120;
    };
    node.addEventListener('scroll', onScroll, { passive: true });
    return () => node.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    if (!pinnedToBottom.current) return;
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' });
  }, [turns]);

  // --- Asking -----------------------------------------------------------

  const ask = useCallback(
    async (question: string, options: { replaceTurnId?: string } = {}) => {
      const trimmed = question.trim();
      if (!trimmed || working) return;

      const id = options.replaceTurnId ?? `${Date.now()}`;
      const blank = blankTurn(id, trimmed);
      setTurns((prior) =>
        options.replaceTurnId
          ? prior.map((turn) => (turn.id === id ? blank : turn))
          : [...prior, blank],
      );
      setDraft('');
      setWorking(true);
      pinnedToBottom.current = true;

      const controller = new AbortController();
      abort.current = controller;
      const patch = (change: (turn: Turn) => Turn) =>
        setTurns((prior) => prior.map((turn) => (turn.id === id ? change(turn) : turn)));

      try {
        await api.chat.stream(
          { question: trimmed, session_id: sessionId, selected_state: selectedState, selected_tax_year: taxYear },
          {
            onStep: (step) =>
              patch((turn) => ({ ...turn, steps: [...turn.steps, step.message] })),
            onDelta: (text) => patch((turn) => ({ ...turn, draft: turn.draft + text })),
            onReplace: (message) => patch((turn) => ({ ...turn, draft: '', withdrawn: message })),
            onFinal: (answer) => {
              setSessionId(answer.session_id);
              patch((turn) => ({ ...turn, answer, draft: '', done: true }));
            },
            onError: (message) => patch((turn) => ({ ...turn, error: message, done: true })),
          },
          controller.signal,
        );
      } catch (caught) {
        if (!controller.signal.aborted) {
          patch((turn) => ({
            ...turn,
            error: caught instanceof Error ? caught.message : String(caught),
            done: true,
          }));
        }
      } finally {
        abort.current = null;
        setWorking(false);
        patch((turn) => ({ ...turn, done: true }));
        void refreshSessions();
      }
    },
    [refreshSessions, selectedState, sessionId, taxYear, working],
  );

  const stop = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    setWorking(false);
  }, []);

  // --- Conversations ----------------------------------------------------

  const startNew = useCallback(() => {
    stop();
    setSessionId(null);
    setTurns([]);
    setAttachments([]);
    setAttachError('');
    setDraft('');
    setSidebarOpen(false);
  }, [stop]);

  const openConversation = useCallback(
    async (id: string) => {
      stop();
      setSidebarOpen(false);
      try {
        const conversation = await api.chat.conversation(id);
        setSessionId(conversation.session.id);
        setSelectedState(conversation.session.state_code ?? null);
        setAttachments(conversation.attachments);
        setTurns(
          conversation.turns.map((turn) => ({
            ...blankTurn(turn.id, turn.question),
            answer: turn.answer,
            error: turn.answer ? '' : 'No answer was stored for this question.',
            done: true,
          })),
        );
        pinnedToBottom.current = true;
      } catch {
        setTurns([]);
      }
    },
    [stop],
  );

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await api.chat.deleteConversation(id);
      } catch {
        /* the list refresh below shows whether it went */
      }
      if (id === sessionId) startNew();
      void refreshSessions();
    },
    [refreshSessions, sessionId, startNew],
  );

  // --- Attachments ------------------------------------------------------

  const attach = useCallback(
    async (file: File) => {
      setAttachError('');
      setAttaching(true);
      try {
        // An attachment belongs to a conversation, so make an empty one first.
        let target = sessionId;
        if (!target) {
          target = (await api.chat.createSession(selectedState)).id;
          setSessionId(target);
          void refreshSessions();
        }
        const attachment = await api.chat.attach(target, file);
        setAttachments((prior) => [...prior, attachment]);
      } catch (caught) {
        setAttachError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setAttaching(false);
      }
    },
    [refreshSessions, selectedState, sessionId],
  );

  const detach = useCallback(
    async (documentId: string) => {
      if (!sessionId) return;
      try {
        await api.chat.detach(sessionId, documentId);
        setAttachments((prior) => prior.filter((item) => item.document_id !== documentId));
      } catch (caught) {
        setAttachError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [sessionId],
  );

  // --- Copy and export --------------------------------------------------

  const copy = useCallback(async (turn: Turn) => {
    if (!turn.answer) return;
    try {
      await navigator.clipboard.writeText(answerToMarkdown(turn.question, turn.answer));
      setCopied(turn.id);
      window.setTimeout(() => setCopied(''), 1600);
    } catch {
      /* clipboard blocked */
    }
  }, []);

  const exportConversation = useCallback(() => {
    const title =
      sessions.find((session) => session.id === sessionId)?.title ?? 'Tax research conversation';
    const markdown = [
      `# ${title}`,
      ...turns.filter((turn) => turn.answer).map((turn) => answerToMarkdown(turn.question, turn.answer!)),
    ].join('\n\n---\n\n');
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${slug(title)}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }, [sessionId, sessions, turns]);

  // --- Keyboard ---------------------------------------------------------

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        startNew();
        document.querySelector<HTMLTextAreaElement>('.composer textarea')?.focus();
      } else if (meta && event.key.toLowerCase() === 'j') {
        event.preventDefault();
        setPanelOpen((open) => !open);
      } else if (event.key === 'Escape' && working) {
        stop();
      } else if (
        event.key === '/' &&
        !(event.target instanceof HTMLInputElement) &&
        !(event.target instanceof HTMLTextAreaElement)
      ) {
        event.preventDefault();
        document.querySelector<HTMLTextAreaElement>('.composer textarea')?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [startNew, stop, working]);

  const empty = turns.length === 0;

  return (
    <div className="assistant-workspace">
      <div className={`assistant-sidebar ${sidebarOpen ? 'open' : ''}`}>
        <ConversationList
          sessions={sessions}
          activeId={sessionId}
          onOpen={(id) => void openConversation(id)}
          onNew={startNew}
          onDelete={(id) => void deleteConversation(id)}
          loading={sessionsLoading}
        />
      </div>

      <main className="assistant-main">
        <header className="assistant-bar">
          <button
            type="button"
            className="assistant-bar-toggle"
            onClick={() => setSidebarOpen((open) => !open)}
            aria-label="Toggle conversations"
          >
            <Menu size={18} />
          </button>
          <div className="assistant-bar-title">
            <strong>{stateProfile ? `${stateProfile.name} tax research` : 'Federal tax research'}</strong>
          </div>
          <div className="assistant-bar-actions">
            {turns.length > 0 && (
              <button
                type="button"
                className="btn ghost sm"
                onClick={exportConversation}
                title="Download this conversation as Markdown"
                aria-label="Export conversation"
              >
                <Download size={17} />
              </button>
            )}
          </div>
        </header>

        <div className="assistant-scroll" ref={scroller}>
          {empty ? (
            <Welcome state={stateProfile} suggestions={suggestions} onAsk={(q) => void ask(q)} />
          ) : (
            <div className="thread">
              {turns.map((turn) => (
                <TurnView
                  key={turn.id}
                  turn={turn}
                  working={working && !turn.done}
                  copied={copied === turn.id}
                  onCopy={() => void copy(turn)}
                  onRegenerate={() => void ask(turn.question, { replaceTurnId: turn.id })}
                />
              ))}
            </div>
          )}
        </div>

        <div className="assistant-composer">
          <Composer
            value={draft}
            onChange={setDraft}
            onSend={() => void ask(draft)}
            onStop={stop}
            streaming={working}
            suggestions={[]}
            onSuggestion={(question) => void ask(question)}
            attachments={attachments}
            onAttach={(file) => void attach(file)}
            onDetach={(id) => void detach(id)}
            attaching={attaching}
            attachError={attachError}
            state={stateProfile}
            onClearState={() => setSelectedState(null)}
          />
        </div>
      </main>

      <StatePanel
        profiles={profiles}
        selected={selectedState}
        onSelect={setSelectedState}
        open={panelOpen}
        onToggle={() => setPanelOpen((open) => !open)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------

function TurnView({
  turn, working, copied, onCopy, onRegenerate,
}: {
  turn: Turn;
  working: boolean;
  copied: boolean;
  onCopy: () => void;
  onRegenerate: () => void;
}) {
  const steps = turn.steps.length ? turn.steps : ['Working…'];
  return (
    <article className="turn">
      <div className="turn-question">
        <p>{turn.question}</p>
      </div>

      {working && !turn.answer && (
        <ol className="turn-steps" aria-live="polite">
          {steps.map((step, index) => {
            const current = index === steps.length - 1;
            return (
              <li key={index} className={current ? 'current' : 'done'}>
                {current ? (
                  <LoaderCircle size={13} className="turn-step-spinner" aria-hidden="true" />
                ) : (
                  <Check size={13} aria-hidden="true" />
                )}
                {step}
              </li>
            );
          })}
        </ol>
      )}

      {!turn.answer && turn.withdrawn && (
        <p className="turn-withdrawn">{turn.withdrawn}</p>
      )}

      {(turn.answer || turn.draft) && (
        <div className="turn-answer-head" aria-hidden="true">
          <span className="ai-chip"><Scale size={14} /></span>
          <span className="turn-answer-title">TaxScraper assistant</span>
          {!turn.answer && working && <span className="badge info">Checking sources</span>}
        </div>
      )}

      {!turn.answer && turn.draft && (
        <div className="answer answer-draft" aria-busy={working}>
          <div className="answer-body answer-markdown">
            <Markdown text={turn.draft} stripCitations />
          </div>
          {working && <span className="answer-draft-note">Checking sources…</span>}
        </div>
      )}

      {turn.error && <p className="turn-error">{turn.error}</p>}

      {turn.answer && (
        <>
          <AnswerCard answer={turn.answer} />
          {turn.done && (
            <div className="turn-actions">
              <button type="button" onClick={onCopy} title={copied ? 'Copied' : 'Copy answer'} aria-label={copied ? 'Copied' : 'Copy answer'}>
                {copied ? <Check size={15} /> : <Copy size={15} />}
              </button>
              <button type="button" onClick={onRegenerate} title="Ask again" aria-label="Ask again">
                <RotateCcw size={15} />
              </button>
            </div>
          )}
        </>
      )}
    </article>
  );
}

function Welcome({
  state, suggestions, onAsk,
}: {
  state: StateProfile | null;
  suggestions: string[];
  onAsk: (question: string) => void;
}) {
  return (
    <div className="assistant-welcome">
      <Scale size={30} className="welcome-mark" aria-hidden="true" />
      <h2>What are you working on?</h2>
      <p className="assistant-welcome-state">
        {state ? (
          <>State and local questions are answered for <strong>{state.name}</strong>; federal questions get the federal answer.</>
        ) : (
          <>No state selected — click a state on the map for state answers.</>
        )}
      </p>
      <div className="assistant-welcome-suggestions">
        {suggestions.slice(0, 4).map((suggestion) => (
          <button key={suggestion} type="button" onClick={() => onAsk(suggestion)}>
            <span>{suggestion}</span><ArrowUpRight size={16} aria-hidden="true" />
          </button>
        ))}
      </div>
    </div>
  );
}

function answerToMarkdown(question: string, answer: AssistantAnswer): string {
  const lines: string[] = [`## ${question}`];
  const meta = [
    answer.states.map((s) => s.name).join(', ') || 'Federal',
    answer.tax_year ? `Tax year ${answer.tax_year}${answer.tax_year_assumed ? ' (assumed)' : ''}` : '',
  ].filter(Boolean);
  lines.push(`_${meta.join(' · ')}_`);
  if (answer.state_change_notice) lines.push(`> ${answer.state_change_notice}`);
  if (answer.answer_markdown) {
    lines.push(answer.answer_markdown);
    if (answer.follow_up_questions.length) {
      lines.push('**To tailor this answer**\n' + answer.follow_up_questions.map((q) => `- ${q}`).join('\n'));
    }
    if (answer.citations.length) {
      lines.push('**Sources**\n' + answer.citations.map((c) => `${c.index}. [${c.title}](${c.url})`).join('\n'));
    }
    lines.push(`_${answer.disclaimer}_`);
    return lines.join('\n\n');
  }
  lines.push(`**Quick answer.** ${answer.quick_answer}`);
  if (answer.why) lines.push(`**Why.** ${answer.why}`);
  for (const section of answer.state_sections) lines.push(`**${section.heading}.** ${section.content}`);
  if (answer.example) lines.push(`**Example.** ${answer.example}`);
  if (answer.next_steps.length) {
    lines.push('**Next steps**\n' + answer.next_steps
      .map((s, i) => `${i + 1}. ${s.action}${s.deadline ? ` (${s.deadline})` : ''}`).join('\n'));
  }
  if (answer.considerations.length) {
    lines.push('**Important considerations**\n' + answer.considerations.map((c) => `- ${c}`).join('\n'));
  }
  if (answer.unverified_points.length) {
    lines.push('**Could not confirm**\n' + answer.unverified_points.map((c) => `- ${c}`).join('\n'));
  }
  if (answer.citations.length) {
    lines.push('**Sources**\n' + answer.citations.map((c) => `${c.index}. [${c.title}](${c.url})`).join('\n'));
  }
  lines.push(`_${answer.disclaimer}_`);
  return lines.join('\n\n');
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* private mode; the preference will not survive a reload */
  }
}

function slug(value: string): string {
  return (
    value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) ||
    'conversation'
  );
}
