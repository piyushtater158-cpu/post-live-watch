import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
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
  { to: "/intake", label: "New Deal" },
  { to: "/campaigns", label: "Campaigns" },
  { to: "/instagram", label: "Instagram" },
];

/** Screens that work with no campaign selected (or none existing yet). */
const CAMPAIGN_FREE = ["/campaigns", "/instagram", "/decisions"];

export function Layout() {
  const { state, error, setState, retry } = useAppState();
  const [busy, setBusy] = useState(false);
  const { pathname } = useLocation();

  const run = (fn: () => Promise<AppState>) => {
    setBusy(true);
    fn()
      .then(setState)
      .catch((e: Error) => alert(`That didn't go through: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const onReset = () => {
    if (confirm(`Reset ${state?.campaign_name ?? "the campaign"} to day 1? This clears today's state.`)) run(api.resetDay);
  };

  const live = state?.clock_mode === "live";
  const needsCampaign = state?.campaign_id === null && !CAMPAIGN_FREE.some((p) => pathname.startsWith(p));

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
            {state.campaigns.length > 0 && (
              <select
                className="campaign-select"
                aria-label="Active campaign"
                value={state.campaign_id ?? ""}
                disabled={busy}
                onChange={(e) => run(() => api.selectCampaign(Number(e.target.value)))}
              >
                {state.campaigns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            )}
            <button
              className="ctl ai"
              type="button"
              aria-pressed={state.ai_enabled}
              disabled={busy}
              onClick={() => run(api.toggleAi)}
            >
              AI <b>{state.ai_enabled ? "ON" : "OFF"}</b>
            </button>
            {state.campaign_id !== null && (
              <>
                <div className="day" aria-label={`Campaign day ${state.current_day} of ${state.duration_days}`}>
                  <span className="mono">
                    Day {state.current_day}/{state.duration_days}
                  </span>
                  {state.duration_days <= 31 && (
                    <span className="pips" aria-hidden="true">
                      {Array.from({ length: state.duration_days }, (_, i) => (
                        <i key={i} className={i < state.current_day ? "on" : undefined} />
                      ))}
                    </span>
                  )}
                  {live && (
                    <span className="mono" title="Day is derived from the campaign's start date, not the simulator">
                      Live clock
                    </span>
                  )}
                </div>
                <button
                  className="ctl primary"
                  type="button"
                  title={live ? "Live-clock campaigns follow the calendar — switch to simulated on the Campaigns page" : undefined}
                  disabled={busy || live || state.current_day >= state.duration_days}
                  onClick={() => run(api.advanceDay)}
                >
                  Advance day
                  <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                    <path d="M3 1.5 9 6l-6 4.5z" fill="currentColor" />
                  </svg>
                </button>
                <button className="ctl" type="button" disabled={busy || live} onClick={onReset}>
                  Reset to day 1
                </button>
              </>
            )}
          </div>
        )}
      </header>
      {error ? (
        <main className="wrap">
          <ErrorBox message={error} onRetry={retry} />
        </main>
      ) : !state ? (
        <main className="wrap">
          <Loading />
        </main>
      ) : needsCampaign ? (
        <main className="wrap">
          <div className="empty">
            <p>No campaign yet.</p>
            <small>
              <Link to="/campaigns/new">Create the first campaign</Link> — every screen is scoped to one.
            </small>
          </div>
        </main>
      ) : (
        <Outlet />
      )}
    </>
  );
}
