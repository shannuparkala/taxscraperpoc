/**
 * The associate's clients and hand-added deadlines.
 *
 * Only a display name is asked for. There is no field for an SSN, EIN or bank
 * detail, and the server refuses a name shaped like one.
 */

import { useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import {
  api, ApiError, type ClientInput, type CustomDeadline, type CustomDeadlineInput, type WorkspaceClient,
} from '../../api/client';
import { currentReturnYearEnd, taxYearBegins, type EntityType, type StateGap } from '../../lib/deadlines';
import { parseISO, type ISODate } from '../../lib/dates';
import { Section } from '../workspace/common';

const ENTITY_LABELS: Record<EntityType, string> = {
  individual: 'Individual',
  c_corp: 'C corporation',
  s_corp: 'S corporation',
  partnership: 'Partnership / LLC',
  trust_estate: 'Trust or estate',
  exempt_org: 'Exempt organization',
};

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];

const BLANK: ClientInput = {
  name: '', entity_type: 'individual', fiscal_year_end_month: 12, states: [], extension_status: 'not_extended', notes: '',
};

export function ClientManager({
  clients, states, gaps, loading, error, onRetry, onChanged, defaultState, today,
}: {
  clients: WorkspaceClient[];
  states: { code: string; name: string }[];
  gaps: StateGap[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onChanged: () => void;
  defaultState: string | null;
  today: ISODate;
}) {
  const [editing, setEditing] = useState<WorkspaceClient | 'new' | null>(null);
  const [message, setMessage] = useState('');

  const remove = async (client: WorkspaceClient) => {
    if (!window.confirm(`Delete ${client.name} and their custom deadlines?`)) return;
    try {
      await api.workspace.deleteClient(client.id);
      setMessage(`${client.name} deleted.`);
      onChanged();
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : String(caught));
    }
  };

  return (
    <Section
      title="Clients"
      className="dash-clients"
      loading={loading}
      error={error}
      onRetry={onRetry}
      actions={editing === null && (
        <button type="button" className="btn accent sm" onClick={() => setEditing('new')}>Add client</button>
      )}
    >
      <p role="status" className="sr-only">{message}</p>
      {editing !== null && (
        <ClientForm
          initial={editing === 'new'
            ? { ...BLANK, states: defaultState ? [defaultState] : [] }
            : { ...editing }}
          states={states}
          onCancel={() => setEditing(null)}
          onSave={async (body) => {
            if (editing === 'new') await api.workspace.createClient(body);
            else await api.workspace.updateClient(editing.id, body);
            setMessage(`${body.name} saved.`);
            setEditing(null);
            onChanged();
          }}
        />
      )}
      {clients.length === 0 && editing === null && (
        <p className="ws-note">
          No clients yet. Add one to see their federal and state filing deadlines on the calendar.
          No real client data is seeded.
        </p>
      )}
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {clients.map((client) => {
          // Only the return being prepared now: older and future years are not the associate's question.
          const returnYear = parseISO(taxYearBegins(currentReturnYearEnd(client.fiscal_year_end_month, today))).y;
          const clientGaps = gaps.filter((g) => g.clientId === client.id && g.taxYear === returnYear);
          return (
            <li key={client.id} className="client-row">
              <span className="cr-name">{client.name}</span>
              <span className="ws-chip">{ENTITY_LABELS[client.entity_type]}</span>
              <span className="ws-chip">FYE {MONTHS[client.fiscal_year_end_month - 1].slice(0, 3)}</span>
              {client.extension_status === 'extended' && <span className="ws-chip accent">Extended</span>}
              {client.states.map((s) => <Link key={s} to={`/states/${s}`} className="ws-chip purple">{s}</Link>)}
              <button type="button" className="btn ghost sm" onClick={() => setEditing(client)} aria-label={`Edit ${client.name}`}>Edit</button>
              <button type="button" className="btn ghost sm" onClick={() => void remove(client)} aria-label={`Delete ${client.name}`}>Delete</button>
              {clientGaps.length > 0 && (
                <div className="ws-note" style={{ flexBasis: '100%' }}>
                  {uniqueStates(clientGaps).map((g) => (
                    <span key={g.state}>
                      <Link to={`/states/${g.state}`}>{g.state}</Link>: {g.message} ({g.taxYear} return). No {g.state} deadline is shown for it.{' '}
                    </span>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function uniqueStates(gaps: StateGap[]): StateGap[] {
  const seen = new Set<string>();
  return gaps.filter((g) => (seen.has(g.state) ? false : (seen.add(g.state), true)));
}

function ClientForm({
  initial, states, onCancel, onSave,
}: {
  initial: ClientInput;
  states: { code: string; name: string }[];
  onCancel: () => void;
  onSave: (body: ClientInput) => Promise<void>;
}) {
  const [form, setForm] = useState<ClientInput>(initial);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const id = useId();
  const set = <K extends keyof ClientInput>(key: K, value: ClientInput[K]) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      await onSave({ ...form, name: form.name.trim() });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="ws-form" onSubmit={(e) => void submit(e)} aria-label="Client details" style={{ marginBottom: 14 }}>
      <div className="field full">
        <label htmlFor={`${id}-name`}>Client name</label>
        <input id={`${id}-name`} type="text" required maxLength={200} value={form.name}
          onChange={(e) => set('name', e.target.value)} autoComplete="off" />
      </div>
      <div className="field">
        <label htmlFor={`${id}-entity`}>Entity type</label>
        <select id={`${id}-entity`} value={form.entity_type} onChange={(e) => set('entity_type', e.target.value as EntityType)}>
          {(Object.keys(ENTITY_LABELS) as EntityType[]).map((k) => <option key={k} value={k}>{ENTITY_LABELS[k]}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${id}-fye`}>Tax year ends</label>
        <select id={`${id}-fye`} value={form.fiscal_year_end_month}
          onChange={(e) => set('fiscal_year_end_month', Number(e.target.value))}>
          {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}{i === 11 ? ' (calendar year)' : ''}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${id}-states`}>Add a state</label>
        <select id={`${id}-states`} value="" onChange={(e) => {
          const code = e.target.value;
          if (code && !form.states.includes(code)) set('states', [...form.states, code]);
        }}>
          <option value="">Choose a state…</option>
          {[...states].sort((a, b) => a.name.localeCompare(b.name))
            .filter((s) => !form.states.includes(s.code))
            .map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
        </select>
        <div className="ws-btn-row" style={{ marginTop: 6 }} aria-label="Selected states">
          {form.states.length === 0 && <span className="ws-note">No states yet.</span>}
          {form.states.map((code) => (
            <button key={code} type="button" className="ws-chip purple" style={{ border: 'none', cursor: 'pointer' }}
              onClick={() => set('states', form.states.filter((s) => s !== code))} aria-label={`Remove ${code}`}>
              {code} <span aria-hidden="true">×</span>
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor={`${id}-ext`}>Extension (current return)</label>
        <select id={`${id}-ext`} value={form.extension_status}
          onChange={(e) => set('extension_status', e.target.value as ClientInput['extension_status'])}>
          <option value="not_extended">Not extended</option>
          <option value="extended">Extended</option>
        </select>
      </div>
      <div className="field full">
        <label htmlFor={`${id}-notes`}>Notes (optional — no SSNs or account numbers)</label>
        <textarea id={`${id}-notes`} rows={2} maxLength={2000} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
      </div>
      {error && <div className="full notice danger" role="alert"><span className="notice-icon">✕</span><div>{error}</div></div>}
      <div className="full ws-btn-row">
        <button type="submit" className="btn accent sm" disabled={saving}>{saving ? 'Saving…' : 'Save client'}</button>
        <button type="button" className="btn ghost sm" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

export function CustomDeadlineForm({
  clients, onSaved, today,
}: { clients: WorkspaceClient[]; onSaved: () => void; today: ISODate }) {
  const id = useId();
  const [form, setForm] = useState<CustomDeadlineInput>({ title: '', due_date: today, client_id: null, kind: 'deadline', done: false });
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    try {
      await api.workspace.createDeadline({ ...form, title: form.title.trim() });
      setSaved(`Added "${form.title.trim()}".`);
      setForm((f) => ({ ...f, title: '' }));
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  return (
    <form className="ws-form" onSubmit={(e) => void submit(e)} aria-label="Add a custom deadline or task">
      <div className="field full">
        <label htmlFor={`${id}-title`}>Deadline or task</label>
        <input id={`${id}-title`} type="text" required maxLength={200} value={form.title}
          onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-date`}>Date</label>
        <input id={`${id}-date`} type="date" required value={form.due_date}
          onChange={(e) => setForm((f) => ({ ...f, due_date: e.target.value }))} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-kind`}>Kind</label>
        <select id={`${id}-kind`} value={form.kind} onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value as CustomDeadline['kind'] }))}>
          <option value="deadline">Deadline</option>
          <option value="task">Task</option>
        </select>
      </div>
      <div className="field full">
        <label htmlFor={`${id}-client`}>Client (optional)</label>
        <select id={`${id}-client`} value={form.client_id ?? ''} onChange={(e) => setForm((f) => ({ ...f, client_id: e.target.value || null }))}>
          <option value="">No client</option>
          {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      {error && <div className="full notice danger" role="alert"><span className="notice-icon">✕</span><div>{error}</div></div>}
      <div className="full ws-btn-row">
        <button type="submit" className="btn sm">Add to calendar</button>
        <span role="status" className="ws-note">{saved}</span>
      </div>
    </form>
  );
}
