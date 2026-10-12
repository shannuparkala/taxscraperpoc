/**
 * Sign-in.
 *
 * Deliberately the whole screen and nothing else. A deployment reachable from
 * the internet returns real taxpayer documents, so there is no partial view of
 * the app to show someone who has not signed in — no dashboard skeleton, no
 * navigation, nothing that reveals what a client's workpaper looks like.
 *
 * The form reports one failure message whatever went wrong. The server already
 * refuses to distinguish an unknown username from a bad password; echoing a
 * more specific reason here would give back exactly what that costs it.
 */

import { useState, type FormEvent } from 'react';

import { ApiError, api } from '../api/client';
import ThemeSwitch from '../components/ThemeSwitch';
import { Notice } from '../components/ui';

export default function LoginPage({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;

    setBusy(true);
    setError(null);
    try {
      await api.auth.login(username, password);
      onSignedIn();
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status === 0
          ? 'Cannot reach the server. It may be waking up — try again in a moment.'
          : 'Incorrect username or password.',
      );
      setPassword('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <ThemeSwitch className="login-theme" />
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="login-brand">
          <span className="brand-mark" aria-hidden="true">TS</span>
          <div>
            <h1>TaxScraper</h1>
            <p>US Tax Automation Platform</p>
          </div>
        </div>

        {error && <Notice kind="danger">{error}</Notice>}

        <label className="login-field">
          <span>Username</span>
          <input
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            autoFocus
            required
            disabled={busy}
          />
        </label>

        <label className="login-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
            disabled={busy}
          />
        </label>

        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="login-footnote">
          Documents you upload here are encrypted at rest and are never sent to
          an AI model with real names, addresses or identifiers attached.
        </p>
      </form>
    </div>
  );
}
