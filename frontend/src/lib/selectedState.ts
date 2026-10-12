/**
 * The state selected on the map, shared across pages.
 *
 * The assistant already remembers its map selection under this key; the
 * depreciation calculator reads and writes the same key, so a state clicked
 * on either page is pre-filled on the other. The value is only ever a
 * suggestion: each page validates it against its own allow-list.
 */

export const SELECTED_STATE_KEY = 'taxscraper_assistant_state';

export function readSelectedState(): string | null {
  try {
    return localStorage.getItem(SELECTED_STATE_KEY);
  } catch {
    return null;
  }
}

export function writeSelectedState(code: string | null): void {
  try {
    if (code) localStorage.setItem(SELECTED_STATE_KEY, code);
    else localStorage.removeItem(SELECTED_STATE_KEY);
  } catch {
    /* private mode; the selection will not survive a reload */
  }
}
