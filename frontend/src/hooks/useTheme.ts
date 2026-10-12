/**
 * Theme preference.
 *
 * `data-theme` on <html> is the one switch every token block in styles.css
 * keys off, so changing theme writes a single attribute and nothing re-renders
 * for colour. The preference lives in a module-level store rather than in a
 * component so that every switch on screen agrees.
 *
 * The design is dark-first (obsidian canvas, luminous accents), so dark is the
 * default until the user picks light; the OS preference no longer decides.
 */

import { useSyncExternalStore } from 'react';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'taxscraper_theme';
const DEFAULT_THEME: Theme = 'dark';

const listeners = new Set<() => void>();

let current: Theme = readStored() ?? DEFAULT_THEME;

apply(current);

function readStored(): Theme | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : null;
  } catch {
    return null;
  }
}

function apply(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function setTheme(theme: Theme): void {
  current = theme;
  apply(theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* private mode; the preference will not survive a reload */
  }
  listeners.forEach((notify) => notify());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useTheme(): { theme: Theme; toggle: () => void; set: (theme: Theme) => void } {
  const theme = useSyncExternalStore(
    subscribe,
    () => current,
    () => current,
  );
  return {
    theme,
    toggle: () => setTheme(theme === 'dark' ? 'light' : 'dark'),
    set: setTheme,
  };
}
