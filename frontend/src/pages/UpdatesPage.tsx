/**
 * Industry Updates: IRS and Treasury news, plus licensed sources once connected.
 *
 * Each item is the agency's headline, date, a short excerpt of the agency's
 * own summary and the link - the reader goes to the original for the text.
 * Bloomberg Tax and Thomson Reuters appear only through the owner's licensed
 * API; until then their tab says how to connect, and the rest of the page
 * works. An AI summary is only ever shown labelled, short, and beside the link.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Bookmark, BookmarkCheck, MessageSquare, RefreshCw, Sparkles } from 'lucide-react';

import { api, type NewsItem, type NewsSourceStatus, type NewsSummary } from '../api/client';
import { ExternalLink, Section, TabPanel, Tabs } from '../components/workspace/common';
import { assistantLink } from '../context/TaxContext';
import { useAsync } from '../hooks/useApi';
import { formatInstant, formatShort } from '../lib/dates';
import '../styles/workspace.css';

const SOURCE_TABS = [
  { key: '', label: 'All' },
  { key: 'irs', label: 'IRS' },
  { key: 'treasury', label: 'Treasury' },
  { key: 'bloomberg_tax', label: 'Bloomberg Tax' },
  { key: 'thomson_reuters', label: 'Thomson Reuters' },
];

const STATE_LABEL: Record<NewsSourceStatus['state'], string> = {
  ok: 'Up to date', error: 'Could not be reached', not_connected: 'Not connected', disabled: 'Fetching off', pending: 'Waiting for first fetch',
};

export default function UpdatesPage() {
  const [source, setSource] = useState('');
  const [topic, setTopic] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const feed = useAsync(() => api.updates.feed({ source, topic, start, end }), [source, topic, start, end]);
  const bookmarks = useAsync(() => api.updates.bookmarks(), []);
  const [summaries, setSummaries] = useState<Record<string, NewsSummary | 'loading'>>({});
  const [refreshing, setRefreshing] = useState(false);

  const status = feed.data?.sources.find((s) => s.key === source);
  const bookmarkFor = (id: string) => bookmarks.data?.find((b) => b.item_id === id);

  const toggleBookmark = async (item: NewsItem) => {
    const existing = bookmarkFor(item.id);
    try {
      if (existing) await api.updates.removeBookmark(existing.id);
      else await api.updates.bookmark(item.id);
    } finally {
      bookmarks.reload();
    }
  };

  const summarize = async (item: NewsItem) => {
    setSummaries((s) => ({ ...s, [item.id]: 'loading' }));
    try {
      const result = await api.updates.summary(item.id);
      setSummaries((s) => ({ ...s, [item.id]: result }));
    } catch (caught) {
      setSummaries((s) => ({ ...s, [item.id]: {
        available: false, text: '', reason: caught instanceof Error ? caught.message : String(caught),
        label: 'AI-generated summary', source_url: item.url, source_name: item.source_name,
      } }));
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    try {
      await api.updates.refresh();
      window.setTimeout(() => { feed.reload(); setRefreshing(false); }, 2500);
    } catch {
      setRefreshing(false);
    }
  };

  return (
    <div className="ws">
      <div className="updates-layout">
        <Section
          title="Industry Updates"
          actions={(
            <>
              {feed.data?.last_updated && (
                <span className="ws-note">Last updated {formatInstant(feed.data.last_updated)}</span>
              )}
              <button type="button" className="btn ghost sm" onClick={() => void refresh()} disabled={refreshing}>
                <RefreshCw size={14} aria-hidden="true" /> {refreshing ? 'Refreshing…' : 'Refresh'}
              </button>
            </>
          )}
        >
          <Tabs tabs={SOURCE_TABS} value={source} onChange={setSource} label="Sources" idPrefix="updates" />
          <TabPanel idPrefix="updates" active={source || ''}>
            <div className="ws-filters" style={{ margin: '12px 0' }}>
              <div className="field">
                <label htmlFor="updates-topic">Topic</label>
                <select id="updates-topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
                  <option value="">All topics</option>
                  {(feed.data?.topics ?? []).map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="updates-from">From</label>
                <input id="updates-from" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="updates-to">To</label>
                <input id="updates-to" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
              </div>
            </div>

            {status && status.state !== 'ok' && (
              <div className={`notice ${status.state === 'error' ? 'danger' : 'info'}`} role="status" style={{ marginBottom: 12 }}>
                <span className="notice-icon" aria-hidden="true">ℹ</span>
                <div>
                  <strong>{status.name}: {STATE_LABEL[status.state]}.</strong> {status.message}{' '}
                  <ExternalLink href={status.homepage}>Visit {status.name}</ExternalLink>
                </div>
              </div>
            )}

            {feed.loading ? (
              <p className="ws-note">Loading updates…</p>
            ) : feed.error ? (
              <div className="notice danger" role="alert"><span className="notice-icon">✕</span>
                <div>{feed.error} <button type="button" className="btn sm" onClick={feed.reload}>Try again</button></div></div>
            ) : (feed.data?.items.length ?? 0) === 0 ? (
              <p className="ws-note">
                No updates match. {feed.data?.sources.some((s) => s.state === 'pending')
                  ? 'Sources are still being fetched in the background - try again in a moment.' : 'Try a wider date range or another topic.'}
              </p>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {feed.data!.items.map((item) => (
                  <UpdateItem
                    key={item.id}
                    item={item}
                    topics={feed.data!.topics}
                    bookmarked={!!bookmarkFor(item.id)}
                    onBookmark={() => void toggleBookmark(item)}
                    summary={summaries[item.id]}
                    onSummarize={() => void summarize(item)}
                  />
                ))}
              </ul>
            )}
          </TabPanel>
        </Section>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Section title="Sources" loading={feed.loading && !feed.data} error={null}>
            <ul className="source-status">
              {(feed.data?.sources ?? []).map((s) => (
                <li key={s.key}>
                  <strong>{s.name}</strong>{' '}
                  <span className={`ws-chip ${s.state === 'ok' ? 'success' : s.state === 'error' ? 'danger' : ''}`}>{STATE_LABEL[s.state]}</span>
                  <div className="ws-note">
                    {s.state === 'not_connected' ? s.message : s.last_updated ? `Fetched ${formatInstant(s.last_updated)} · ${s.item_count} items` : s.message}
                  </div>
                </li>
              ))}
            </ul>
            <p className="ws-note" style={{ marginTop: 10 }}>
              Headlines link to the original. Bloomberg Tax and Thomson Reuters are copyrighted and are shown only
              through a licensed connection set up by your administrator.
            </p>
          </Section>
          <Section title="Bookmarks" loading={bookmarks.loading} error={bookmarks.error} onRetry={bookmarks.reload}
            empty={!bookmarks.data?.length} emptyText="Bookmark an update to keep it here.">
            <ul className="news-list">
              {(bookmarks.data ?? []).map((b) => (
                <li key={b.id}>
                  <ExternalLink href={b.url}>{b.title}</ExternalLink>
                  <div className="news-meta">{b.published && formatShort(b.published)}</div>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      </div>
    </div>
  );
}

function UpdateItem({
  item, topics, bookmarked, onBookmark, summary, onSummarize,
}: {
  item: NewsItem;
  topics: { key: string; label: string }[];
  bookmarked: boolean;
  onBookmark: () => void;
  summary: NewsSummary | 'loading' | undefined;
  onSummarize: () => void;
}) {
  const question = `Explain this ${item.source_name} update for a tax associate: "${item.title}" (${item.url})`;
  return (
    <li className="upd-item">
      <div className="news-meta">
        <span className="ws-chip">{item.source_name}</span>
        {item.published && <span>{formatShort(item.published)}</span>}
        {item.reference && <span>{item.reference}</span>}
        {item.topics.map((t) => <span key={t} className="ws-chip info">{topics.find((x) => x.key === t)?.label ?? t}</span>)}
      </div>
      <h3 id={`upd-${item.id}`}><ExternalLink href={item.url}>{item.title}</ExternalLink></h3>
      {item.excerpt && <p>{item.excerpt}</p>}
      <div className="ws-btn-row">
        <button type="button" className="btn ghost sm" onClick={onBookmark} aria-pressed={bookmarked} aria-describedby={`upd-${item.id}`}>
          {bookmarked ? <BookmarkCheck size={14} aria-hidden="true" /> : <Bookmark size={14} aria-hidden="true" />}
          {bookmarked ? 'Bookmarked' : 'Bookmark'}
        </button>
        <Link to={assistantLink(question)} className="btn ghost sm" aria-describedby={`upd-${item.id}`}>
          <MessageSquare size={14} aria-hidden="true" /> Ask the chatbot about this update
        </Link>
        {(item.source === 'irs' || item.source === 'treasury') && summary === undefined && (
          <button type="button" className="btn ghost sm" onClick={onSummarize} aria-describedby={`upd-${item.id}`}>
            <Sparkles size={14} aria-hidden="true" /> AI summary
          </button>
        )}
      </div>
      {summary === 'loading' && <p className="ws-note" role="status">Writing a summary…</p>}
      {summary && summary !== 'loading' && (
        <div className="ai-summary" role="note" aria-label={summary.label}>
          <div className="ai-label">{summary.label}</div>
          {summary.available ? <div>{summary.text}</div> : <div className="ws-note">{summary.reason}</div>}
          <div className="ws-note">Original: <ExternalLink href={summary.source_url}>{summary.source_name}</ExternalLink></div>
        </div>
      )}
    </li>
  );
}
