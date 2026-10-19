import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api";
import { useAppState } from "../state";
import type { AppState } from "../types";
import { ErrorBox, Loading, SampleBanner, WakingBanner } from "./Status";

const LINKS = [
  { to: "/", label: "Overview", end: true },
  { to: "/queue", label: "Flag Queue" },
  { to: "/creators", label: "Creators" },
  { to: "/report", label: "Brand Report" },
  { to: "/decisions", label: "Decision Log" },
];

export function Layout() {
  const { state, error, setState, retry } = useAppState();
  const [busy, setBusy] = useState(false);

  const run = (fn: () => Promise<AppState>) => {
    setBusy(true);
    fn()
      .then(setState)
      .catch((e: Error) => alert(`That didn't go through: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const onReset = () => {
    if (confirm("Reset the campaign to day 1? This clears today's state.")) run(api.resetDay);
  };

  return (
    <>
      <SampleBanner />
      <WakingBanner />
      <header className="nav">
        <div className="brand">
          <i aria-hidden="true" />
          Post-Live Watch
        </div>
        <nav className="navlinks" aria-label="Screens">
          {LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end}>
              {l.label}
            </NavLink>
          ))}
        </nav>
        {state && (
          <div className="controls">
            <button
              className="ctl ai"
              type="button"
              aria-pressed={state.ai_enabled}
              disabled={busy}
              onClick={() => run(api.toggleAi)}
            >
              AI <b>{state.ai_enabled ? "ON" : "OFF"}</b>
            </button>
            <div className="day" aria-label={`Campaign day ${state.current_day} of ${state.duration_days}`}>
              <span className="mono">
                Day {state.current_day}/{state.duration_days}
              </span>
              <span className="pips" aria-hidden="true">
                {Array.from({ length: state.duration_days }, (_, i) => (
                  <i key={i} className={i < state.current_day ? "on" : undefined} />
                ))}
              </span>
            </div>
            <button
              className="ctl primary"
              type="button"
              disabled={busy || state.current_day >= state.duration_days}
              onClick={() => run(api.advanceDay)}
            >
              Advance day
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                <path d="M3 1.5 9 6l-6 4.5z" fill="currentColor" />
              </svg>
            </button>
            <button className="ctl" type="button" disabled={busy} onClick={onReset}>
              Reset to day 1
            </button>
          </div>
        )}
      </header>
      {error ? (
        <main className="wrap">
          <ErrorBox message={error} onRetry={retry} />
        </main>
      ) : state ? (
        <Outlet />
      ) : (
        <main className="wrap">
          <Loading />
        </main>
      )}
    </>
  );
}
