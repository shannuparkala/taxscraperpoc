/**
 * The state and tax year every section shares.
 *
 * Selecting California on the map filters the forms library, State
 * Intelligence, the calendar and the assistant together. The state lives
 * under the key the assistant and the depreciation calculator already read
 * (`lib/selectedState.ts`), so those pages - which keep their own copy while
 * mounted - pick it up when they open, and anything they change is read back
 * here on the next navigation. The year is kept for the browser session.
 *
 * Until somebody chooses a year, it is the server's default
 * (`DEFAULT_TAX_YEAR`, `/api/reference/dashboard`) - the one place the
 * default is set. Each section clamps it to the years it covers
 * (`lib/taxYear.yearWithin`).
 *
 * The context never validates a code: each page checks it against its own
 * list (State Intelligence covers the 50 states and DC; the assistant also
 * takes territories) and says so when it does not cover the selection.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';

import { api } from '../api/client';
import { parseISO, todayIn } from '../lib/dates';
import { SELECTED_STATE_KEY, readSelectedState, writeSelectedState } from '../lib/selectedState';

const YEAR_KEY = 'taxscraper_tax_year';

export interface TaxContextValue {
  stateCode: string | null;
  setStateCode: (code: string | null) => void;
  taxYear: number;
  setTaxYear: (year: number) => void;
}

const TaxContext = createContext<TaxContextValue | null>(null);

/**
 * Only for the moment before the server's default arrives (one request at
 * start-up): the calendar year. It is replaced as soon as
 * `/api/reference/dashboard` answers, unless the user has chosen a year.
 */
export function placeholderTaxYear(today: string = todayIn()): number {
  return parseISO(today).y;
}

function storedYear(): number | null {
  try {
    const stored = Number(sessionStorage.getItem(YEAR_KEY));
    if (Number.isInteger(stored) && stored > 2000) return stored;
  } catch {
    /* storage blocked */
  }
  return null;
}

export function TaxContextProvider({ children }: { children: ReactNode }) {
  const [stateCode, setStateCodeRaw] = useState<string | null>(() => readSelectedState());
  const [taxYear, setTaxYearRaw] = useState<number>(() => storedYear() ?? placeholderTaxYear());
  const location = useLocation();

  // The server's default year, unless a year was chosen this session.
  useEffect(() => {
    if (storedYear() !== null) return;
    let live = true;
    api.reference.dashboard()
      .then((config) => {
        if (live && storedYear() === null && Number.isInteger(config.default_tax_year)) {
          setTaxYearRaw(config.default_tax_year);
        }
      })
      .catch(() => { /* keep the placeholder; every section clamps it to its own years */ });
    return () => { live = false; };
  }, []);

  const setStateCode = useCallback((code: string | null) => {
    const normalized = code ? code.toUpperCase() : null;
    writeSelectedState(normalized);
    setStateCodeRaw(normalized);
  }, []);

  const setTaxYear = useCallback((year: number) => {
    try {
      sessionStorage.setItem(YEAR_KEY, String(year));
    } catch {
      /* the choice will not survive a reload */
    }
    setTaxYearRaw(year);
  }, []);

  // A page that keeps its own copy (the assistant) may have changed the shared
  // key; read it back whenever the route changes, and when another tab writes it.
  useEffect(() => {
    setStateCodeRaw(readSelectedState());
  }, [location.pathname]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === SELECTED_STATE_KEY) setStateCodeRaw(readSelectedState());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const value = useMemo(
    () => ({ stateCode, setStateCode, taxYear, setTaxYear }),
    [stateCode, setStateCode, taxYear, setTaxYear],
  );
  return <TaxContext.Provider value={value}>{children}</TaxContext.Provider>;
}

export function useTaxContext(): TaxContextValue {
  const value = useContext(TaxContext);
  if (!value) throw new Error('useTaxContext must be used inside TaxContextProvider');
  return value;
}

/** Link into the assistant with a question and the state pre-filled. */
export function assistantLink(question: string, state?: string | null): string {
  const params = new URLSearchParams({ q: question });
  if (state) params.set('state', state);
  return `/assistant?${params}`;
}
