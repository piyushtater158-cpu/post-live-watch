import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import type { AppState } from "./types";

interface Ctx {
  state: AppState | null;
  error: string | null;
  setState: (s: AppState) => void;
  retry: () => void;
}

const AppStateContext = createContext<Ctx | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api.state().then(setState, (e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  return (
    <AppStateContext.Provider value={{ state, error, setState, retry: load }}>{children}</AppStateContext.Provider>
  );
}

export function useAppState(): Ctx {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error("useAppState outside AppStateProvider");
  return ctx;
}

/** Loads page data once global state is known, and reloads whenever the day
 *  or the AI toggle changes — those two controls affect every screen. */
export function usePageData<T>(load: () => Promise<T>, extraDeps: unknown[] = []) {
  const { state } = useAppState();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!state) return;
    let live = true;
    setError(null);
    load().then(
      (d) => live && setData(d),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [state?.current_day, state?.ai_enabled, nonce, ...extraDeps]);

  return { data, setData, error, reload: () => setNonce((n) => n + 1) };
}
