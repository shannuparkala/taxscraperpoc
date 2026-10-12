import { useCallback, useEffect, useState } from 'react';
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { Activity, LogOut, Menu, ShieldCheck } from 'lucide-react';

import { api, type PrincipalInfo } from './api/client';
import { useAsync } from './hooks/useApi';
import ThemeSwitch from './components/ThemeSwitch';
import { LoadingBlock } from './components/ui';
import AssistantPage from './pages/AssistantPage';
import DashboardPage from './pages/DashboardPage';
import DepreciationPage from './pages/DepreciationPage';
import FormsPage from './pages/FormsPage';
import HomeDashboardPage from './pages/HomeDashboardPage';
import LoginPage from './pages/LoginPage';
import SettingsPage from './pages/SettingsPage';
import StateIntelPage from './pages/StateIntelPage';
import UpdatesPage from './pages/UpdatesPage';
import { TaxContextProvider, useTaxContext } from './context/TaxContext';

interface NavEntry {
  to: string;
  label: string;
  icon: IconName;
  subtitle: string;
  /** Listed in the sidebar but not navigable yet. */
  disabled?: boolean;
}

const PRIMARY_NAV: NavEntry[] = [
  { to: '/', label: 'Dashboard', icon: 'home', subtitle: 'Your deadlines, clients and what changed' },
  { to: '/assistant', label: 'Tax & audit assistant', icon: 'sparkle', subtitle: 'Ask anything about US tax, state rules, cases and audits' },
  { to: '/depreciation', label: 'Depreciation calculator', icon: 'calculator', subtitle: 'Federal and state depreciation, year by year, from published rules' },
  { to: '/forms', label: 'IRS Forms', icon: 'document', subtitle: 'Federal, business and state forms from the agencies themselves' },
  { to: '/updates', label: 'Industry Updates', icon: 'news', subtitle: 'IRS and Treasury news, with links to the originals' },
  { to: '/states', label: 'State Intelligence', icon: 'landmark', subtitle: 'Apportionment, nexus, conformity, rates and filing, with sources' },
  // Return preparation is still being built: shown, but not reachable.
  { to: '/prepare', label: 'Coming soon', icon: 'grid', subtitle: 'Return preparation from workpapers is in development', disabled: true },
  { to: '/workload', label: 'Workload', icon: 'grid', subtitle: 'Filing status and workload overview' },
];

const SECONDARY_NAV: NavEntry[] = [
  { to: '/settings', label: 'Settings', icon: 'gear', subtitle: 'Configuration and system health' },
];

const ALL_NAV = [...PRIMARY_NAV, ...SECONDARY_NAV];

/** Nothing renders until the server has said who the caller is. */
type Gate =
  | { state: 'checking' }
  | { state: 'in'; principal: PrincipalInfo }
  | { state: 'out' };

export default function App() {
  const [gate, setGate] = useState<Gate>({ state: 'checking' });

  /**
   * Ask the server who we are.
   *
   * This is the whole access check, and it needs no build-time flag: with
   * AUTH_DISABLED the endpoint answers with the dev principal and the app
   * opens as it always has, and with auth enabled it answers 401 until a token
   * is held. A frontend that decided for itself whether login was required
   * would be a second copy of that decision, free to disagree with the server.
   */
  const identify = useCallback(async () => {
    try {
      setGate({ state: 'in', principal: await api.auth.me() });
    } catch {
      api.auth.logout(); // a stale or expired token is worse than none
      setGate({ state: 'out' });
    }
  }, []);

  useEffect(() => {
    void identify();
  }, [identify]);

  if (gate.state === 'checking') {
    return (
      <div className="login-screen">
        <LoadingBlock label="Starting up…" />
      </div>
    );
  }

  if (gate.state === 'out') {
    return <LoginPage onSignedIn={identify} />;
  }

  return (
    <TaxContextProvider>
      <Shell principal={gate.principal} onSignOut={() => {
        api.auth.logout();
        setGate({ state: 'out' });
      }} />
    </TaxContextProvider>
  );
}

function Shell({
  principal, onSignOut,
}: {
  principal: PrincipalInfo; onSignOut: () => void;
}) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  const { taxYear, stateCode } = useTaxContext();

  // Health drives the sidebar status card and the topbar AI pill.
  const health = useAsync(() => api.settings.health(), []);
  // Only checks the server actually ran; nothing here is a made-up metric.
  const checks = health.data
    ? [
      { key: 'database', label: 'DB', ok: health.data.database, title: 'Database' },
      { key: 'llm', label: 'AI', ok: health.data.llm, title: 'AI model (Gemini)' },
      { key: 'ocr', label: 'OCR', ok: health.data.ocr, title: 'OCR (Tesseract)' },
      { key: 'ner', label: 'NER', ok: health.data.ner, title: 'Name detection for masking (spaCy)' },
    ]
    : [];
  const online = checks.filter((c) => c.ok).length;

  const current = ALL_NAV.find((entry) =>
    entry.to === '/' ? location.pathname === '/' : location.pathname.startsWith(entry.to));
  // The assistant is a full-height three-pane app, not a document in a
  // padded column, so the shell hands it the whole pane.
  const onAssistant = location.pathname.startsWith('/assistant');
  const displayName = principal.first_name || principal.username;

  return (
    <div className="app">
      {sidebarOpen && (
        <div className="sidebar-scrim" onClick={() => setSidebarOpen(false)} aria-hidden="true" />
      )}
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true"><Activity size={19} strokeWidth={2.2} /></span>
          <div>
            <h1>Tax<span className="brand-accent">Scraper</span></h1>
            <div className="tagline">Tax intelligence</div>
          </div>
        </div>
        <div className="sidebar-context" title="Tax year and state shared across the workspace">
          <span className="pulse-dot" aria-hidden="true" />
          TY{taxYear}{stateCode ? ` / ${stateCode}` : ' / Federal'}
        </div>

        <nav className="sidebar-nav">
          <div className="nav-section-label">Modules</div>
          {PRIMARY_NAV.map((entry) => (
            <NavItem key={entry.to} entry={entry} onNavigate={() => setSidebarOpen(false)} />
          ))}

          <div className="nav-section-label">System</div>
          {SECONDARY_NAV.map((entry) => (
            <NavItem
              key={entry.to}
              entry={entry}
              onNavigate={() => setSidebarOpen(false)}
            />
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-status">
            <div className="sidebar-status-head">
              <span>Services</span>
              <span className={`sidebar-status-count ${health.data?.status ?? 'degraded'}`}>
                {health.data ? `${online}/${checks.length} online` : 'Checking…'}
              </span>
            </div>
            <div className="sidebar-status-track" aria-hidden="true">
              <span style={{ width: checks.length ? `${(online / checks.length) * 100}%` : '0%' }} />
            </div>
            <ul className="sidebar-status-checks">
              {checks.map((check) => (
                <li key={check.key} className={check.ok ? 'ok' : 'down'} title={`${check.title}: ${check.ok ? 'available' : 'unavailable'}`}>
                  {check.label}
                </li>
              ))}
            </ul>
            <div className="status-line">
              <span className={`status-dot ${health.data?.status ?? 'degraded'}`} />
              <span>{health.data ? `System ${health.data.status}` : 'Checking…'}</span>
              <span className="sidebar-version">v{health.data?.version ?? '—'}</span>
            </div>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button
            className="btn ghost icon-only sidebar-toggle"
            onClick={() => setSidebarOpen((open) => !open)}
            aria-label="Toggle navigation"
          >
            <Menu size={18} aria-hidden="true" />
          </button>
          <div className="topbar-heading">
            <h1>{current?.label ?? 'TaxScraper'}</h1>
            <div className="subtitle">{current?.subtitle ?? ''}</div>
          </div>
          <div className="topbar-actions">
            {health.data && (
              <span
                className={`badge ${health.data.llm ? 'live' : 'warning'}`}
                title={health.data.llm ? 'The AI model is reachable' : 'Set GEMINI_API_KEY to enable AI generation'}
              >
                {health.data.llm && <span className="pulse-dot" aria-hidden="true" />}
                {health.data.llm ? 'AI online' : 'AI offline'}
              </span>
            )}
            {health.data && !health.data.ocr && (
              <span className="badge warning" title="Install Tesseract to read scanned documents">
                OCR unavailable
              </span>
            )}
            {onAssistant ? (
              // Chat questions are masked only on request (owner's decision,
              // 2026-10-09); workpapers and attachments are always masked.
              <span
                className="badge neutral"
                title="Questions are sent as typed. Start a message with /mask to replace names and identifiers first. Attached documents are always masked."
              >
                <ShieldCheck size={12} aria-hidden="true" /> Masking on request
              </span>
            ) : (
              <span className="badge accent" title="Workpaper documents reach the AI model only after masking">
                <ShieldCheck size={12} aria-hidden="true" /> PII masking
              </span>
            )}
            <ThemeSwitch />
            <div className="topbar-divider" />
            <div className="topbar-user" title={`Signed in as ${principal.username} (${principal.role})`}>
              <span className="topbar-who">
                <span className="topbar-username">{displayName}</span>
                <span className="topbar-role">{principal.role}</span>
              </span>
              <span className="avatar" aria-hidden="true">
                {displayName.slice(0, 1).toUpperCase()}
              </span>
            </div>
            <button className="btn ghost sm topbar-signout" onClick={onSignOut} aria-label="Sign out" title="Sign out">
              <LogOut size={15} aria-hidden="true" />
            </button>
          </div>
        </header>

        <main className={`content ${onAssistant ? "flush" : ""}`}>
          <Routes>
            <Route path="/" element={<HomeDashboardPage principal={principal} />} />
            <Route path="/assistant" element={<AssistantPage />} />
            <Route path="/depreciation" element={<DepreciationPage />} />
            <Route path="/forms" element={<FormsPage />} />
            <Route path="/updates" element={<UpdatesPage />} />
            <Route path="/states" element={<StateIntelPage />} />
            <Route path="/states/:code" element={<StateIntelPage />} />
            <Route path="/map" element={<Navigate to="/states" replace />} />
            <Route path="/prepare" element={<ComingSoon />} />
            <Route path="/workload" element={<DashboardPage />} />
            <Route path="/dashboard" element={<Navigate to="/workload" replace />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

/** Return preparation is in development; a bookmarked /prepare lands here. */
function ComingSoon() {
  return (
    <div className="empty" style={{ paddingTop: 60 }}>
      <div className="empty-title">Coming soon</div>
      <div className="empty-hint">Return preparation from workpapers is still in development.</div>
    </div>
  );
}

function NavItem({
  entry, badge, onNavigate,
}: {
  entry: NavEntry; badge?: number; onNavigate: () => void;
}) {
  if (entry.disabled) {
    return (
      <span className="nav-item disabled" aria-disabled="true" title={entry.subtitle}>
        <span className="icon" aria-hidden="true"><NavIcon name={entry.icon} /></span>
        <span className="nav-label">{entry.label}</span>
      </span>
    );
  }
  return (
    <NavLink
      to={entry.to}
      end={entry.to === '/'}
      className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
      onClick={onNavigate}
    >
      <span className="icon" aria-hidden="true"><NavIcon name={entry.icon} /></span>
      <span className="nav-label">{entry.label}</span>
      {badge !== undefined && <span className="badge-count">{badge}</span>}
    </NavLink>
  );
}

type IconName = 'sparkle' | 'document' | 'grid' | 'gear' | 'calculator' | 'home' | 'news' | 'landmark';

/** Stroked 24px icons on a shared grid, so they sit at one optical weight. */
function NavIcon({ name }: { name: IconName }) {
  const paths: Record<IconName, JSX.Element> = {
    sparkle: (
      <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3zM18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z" />
    ),
    document: (
      <>
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" />
        <path d="M14 3v5h5M9 13h6M9 17h4" />
      </>
    ),
    grid: (
      <>
        <rect x="3" y="3" width="7" height="8" rx="1.5" />
        <rect x="14" y="3" width="7" height="5" rx="1.5" />
        <rect x="3" y="15" width="7" height="6" rx="1.5" />
        <rect x="14" y="12" width="7" height="9" rx="1.5" />
      </>
    ),
    home: <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1v-9.5z" />,
    news: (
      <>
        <rect x="3" y="4" width="15" height="16" rx="2" />
        <path d="M18 8h2a1 1 0 0 1 1 1v9a2 2 0 0 1-2 2M7 8h7M7 12h7M7 16h4" />
      </>
    ),
    landmark: (
      <>
        <path d="M3 21h18M4 10h16M12 3 3 8h18l-9-5z" />
        <path d="M6 10v8M10 10v8M14 10v8M18 10v8" />
      </>
    ),
    calculator: (
      <>
        <rect x="5" y="3" width="14" height="18" rx="2" />
        <path d="M8 7h8M8 11h2M12 11h2M16 11v6M8 15h2M12 15h2M8 18.5h2M12 18.5h2" />
      </>
    ),
    gear: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z" />
      </>
    ),
  };
  return (
    <svg
      viewBox="0 0 24 24"
      width="17"
      height="17"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  );
}
