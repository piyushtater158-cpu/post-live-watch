import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { capitalize } from "../format";
import { useAppState } from "../state";
import type { CampaignSummary, SyncResult } from "../types";

const PROVIDER_LABEL: Record<string, string> = {
  seeded: "Seeded demo data",
  manual: "Manual entry",
  instagram: "Instagram",
};

export function SyncResultPanel({ result, name }: { result: SyncResult; name?: string }) {
  const notes = result.errors.map((e) => (typeof e === "string" ? e : e.creator_handle ? `@${e.creator_handle}: ${e.message}` : e.message));
  return (
    <div className="panel" role="status" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
      <span className="lbl">
        Sync result{name ? ` · ${name}` : ""} · {result.provider}
      </span>
      <p className="mono">
        status: <b>{result.status.replace(/_/g, " ")}</b>
        {result.posts_attempted > 0 && ` · ${result.posts_updated}/${result.posts_attempted} posts updated`}
      </p>
      {result.status === "not_configured" && (
        <p>
          Instagram isn't connected yet — see the <Link to="/instagram">Instagram</Link> screen for what's missing.
        </p>
      )}
      {notes.length > 0 && (
        <div className="estflag" style={{ margin: 0 }}>
          <b>NOTE</b>
          <span>{notes.join(" · ")}</span>
        </div>
      )}
    </div>
  );
}

export default function Campaigns() {
  const { state, setState } = useAppState();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<number | null>(null);
  const [sync, setSync] = useState<{ result: SyncResult; name: string } | null>(null);

  useEffect(() => {
    document.title = "Campaigns · Post-Live Watch";
  }, []);

  const refresh = () => api.state().then(setState);

  const act = (id: number, fn: () => Promise<unknown>) => {
    setBusy(id);
    fn()
      .catch((e: Error) => alert(`That didn't go through: ${e.message}`))
      .finally(() => setBusy(null));
  };

  const select = (c: CampaignSummary, then?: string) =>
    act(c.id, () =>
      api.selectCampaign(c.id).then((s) => {
        setState(s);
        if (then) navigate(then);
      }),
    );

  const toggleClock = (c: CampaignSummary) =>
    act(c.id, () => api.setClock(c.id, c.clock_mode === "live" ? "simulated" : "live").then(refresh));

  const runSync = (c: CampaignSummary) =>
    act(c.id, () =>
      api.syncCampaign(c.id).then((result) => {
        setSync({ result, name: c.name });
        return refresh();
      }),
    );

  const campaigns = state?.campaigns ?? [];

  return (
    <main className="wrap">
      <div className="head">
        <div className="titleblock">
          <p className="eyebrow">Campaign management</p>
          <h1>Campaigns</h1>
        </div>
        <Link className="btn approve" to="/campaigns/new">
          New campaign
        </Link>
      </div>

      <p className="meta">
        Every screen (Overview, Flag Queue, Creators, Brand Report, New Deal) shows the <b>active</b> campaign. Switch
        here or from the dropdown in the header.
      </p>

      {campaigns.length === 0 ? (
        <div className="empty">
          <p>No campaigns yet.</p>
          <small>
            <Link to="/campaigns/new">Create the first one</Link>
          </small>
        </div>
      ) : (
        <div className="tablebox">
          <table>
            <thead>
              <tr>
                <th scope="col">Campaign</th>
                <th scope="col">Brand</th>
                <th scope="col">Day</th>
                <th scope="col">Clock</th>
                <th scope="col">Metrics</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => {
                const active = c.id === state?.campaign_id;
                const disabled = busy !== null;
                return (
                  <tr key={c.id}>
                    <td>
                      {active ? <b>{c.name}</b> : c.name}{" "}
                      {active && <span className="chip ok">Active</span>}
                    </td>
                    <td className="muted">{c.brand_name}</td>
                    <td className="mono">
                      {c.current_day}/{c.duration_days}
                    </td>
                    <td>
                      <div className="td-actions" style={{ alignItems: "center" }}>
                        <span className="muted">{capitalize(c.clock_mode)}</span>
                        <button className="btn ghost" type="button" disabled={disabled} onClick={() => toggleClock(c)}>
                          Switch to {c.clock_mode === "live" ? "simulated" : "live"}
                        </button>
                      </div>
                    </td>
                    <td className="muted">{PROVIDER_LABEL[c.metrics_provider] ?? c.metrics_provider}</td>
                    <td>
                      <div className="td-actions">
                        {!active && (
                          <button className="btn approve" type="button" disabled={disabled} onClick={() => select(c)}>
                            Make active
                          </button>
                        )}
                        <Link className="btn" to={`/campaigns/${c.id}/edit`}>
                          Edit
                        </Link>
                        <button className="btn" type="button" disabled={disabled} onClick={() => select(c, "/intake")}>
                          Add creators
                        </button>
                        {c.metrics_provider === "instagram" && (
                          <button className="btn" type="button" disabled={disabled} onClick={() => runSync(c)}>
                            {busy === c.id ? "Syncing…" : "Sync from Instagram"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {sync && <SyncResultPanel result={sync.result} name={sync.name} />}
    </main>
  );
}
