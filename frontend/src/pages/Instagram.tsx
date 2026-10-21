import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Loading } from "../components/Status";
import { commas } from "../format";
import { usePageData } from "../state";
import type { CreatorResearch, InstagramTest, SyncResult } from "../types";
import { SyncResultPanel } from "./Campaigns";

const STATUS_CLASS: Record<string, string> = { ok: "ok", partial: "look", not_applicable: "look", not_configured: "act", error: "act" };

export default function Instagram() {
  const status = usePageData(api.instagramStatus);
  const [test, setTest] = useState<InstagramTest | null>(null);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState<number | null>(null);
  const [sync, setSync] = useState<{ result: SyncResult; name: string } | null>(null);
  const [handle, setHandle] = useState("");
  const [research, setResearch] = useState<CreatorResearch | null>(null);
  const [researchError, setResearchError] = useState<string | null>(null);
  const [looking, setLooking] = useState(false);

  useEffect(() => {
    document.title = "Instagram · Post-Live Watch";
  }, []);

  const runTest = () => {
    setTesting(true);
    api
      .instagramTest()
      .then(setTest)
      .catch((e: Error) => setTest({ ok: false, error: e.message, account: null }))
      .finally(() => setTesting(false));
  };

  const runSync = (id: number, name: string) => {
    setSyncing(id);
    api
      .syncCampaign(id)
      .then((result) => {
        setSync({ result, name });
        status.reload();
      })
      .catch((e: Error) => alert(`That didn't go through: ${e.message}`))
      .finally(() => setSyncing(null));
  };

  const lookUp = () => {
    const h = handle.trim().replace(/^@/, "");
    if (!h) return;
    setLooking(true);
    setResearch(null);
    setResearchError(null);
    api
      .researchCreator(h)
      .then(setResearch)
      .catch((e: Error) => setResearchError(e.message))
      .finally(() => setLooking(false));
  };

  const s = status.data;

  return (
    <main className="wrap narrow">
      <div className="head">
        <div className="titleblock">
          <p className="eyebrow">Integrations</p>
          <h1>Instagram connection</h1>
        </div>
        <p className="meta mono">Pulls paid-partnership and public post data for campaigns set to Instagram</p>
      </div>

      {status.error && <ErrorBox message={status.error} onRetry={status.reload} />}
      {!s && !status.error && <Loading />}

      {s && (
        <>
          <article className="card">
            <div className={`strip ${s.configured ? (test?.ok === false ? "act" : "ok") : "look"}`} aria-hidden="true" />
            <div className="card-head">
              <span className={`chip ${s.configured ? "ok" : "look"}`}>{s.configured ? "Credentials set" : "Not connected"}</span>
              <span className="fmt">Meta Graph API {s.graph_version}</span>
            </div>
            <div style={{ padding: "0 22px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
              {s.configured ? (
                <p className="meta">
                  The server has all three Meta credentials. Test the connection to confirm the token is valid and points at the
                  brand's Instagram account.
                </p>
              ) : (
                <>
                  <p className="meta">
                    The connection uses a Meta <b>system-user token</b> stored on the server (not a login button), because
                    reading partner posts needs a Business app that has passed Meta App Review. Missing on the server:
                  </p>
                  <p className="mono">{s.missing_env.join(" · ")}</p>
                  <ol className="meta" style={{ margin: 0, paddingLeft: 20, lineHeight: 1.7 }}>
                    <li>Create a Business-type app at developers.facebook.com, inside your agency's Business Portfolio (complete Business Verification).</li>
                    <li>Have each brand add your portfolio as a Partner and share its Instagram Professional account and linked Facebook Page.</li>
                    <li>Request App Review for <span className="mono">instagram_branded_content_ads_brand</span> (partner posts, with reach) and <span className="mono">instagram_basic</span> (public posts).</li>
                    <li>Create an Admin system user, generate its token, and set the three variables above on the Render service, then redeploy.</li>
                  </ol>
                  <p className="meta">Full checklist: docs/meta-setup.md in the repo.</p>
                </>
              )}
              <div className="row">
                <button className="btn approve" type="button" disabled={testing} onClick={runTest}>
                  {testing ? "Testing…" : "Test connection"}
                </button>
              </div>
              {test &&
                (test.ok && test.account ? (
                  <div className="contractnote" style={{ margin: 0 }} role="status">
                    <b>OK</b>
                    <span>
                      Connected to @{test.account.username}
                      {test.account.name ? ` (${test.account.name})` : ""}
                      {test.account.followers != null ? ` · ${commas(test.account.followers)} followers` : ""}
                    </span>
                  </div>
                ) : (
                  <div className="vwarn" style={{ margin: 0 }} role="alert">
                    <b>FAILED</b>
                    <span>{test.error}</span>
                  </div>
                ))}
            </div>
          </article>

          <div className="panel" style={{ flexDirection: "column", alignItems: "stretch", gap: 10 }}>
            <span className="lbl">What each source can see</span>
            <dl className="kv">
              <dt>Partner posts</dt>
              <dd>Posts tagged "Paid partnership" with the brand: likes, comments, views, saves, shares and reach.</dd>
              <dt>Public posts</dt>
              <dd>Any public professional account: caption, likes, comment count, timestamp. No reach.</dd>
              <dt>Never available</dt>
              <dd>Another account's Stories and comment text — enter those manually on the creator's profile.</dd>
            </dl>
          </div>

          <div className="head">
            <h2>Campaigns using Instagram</h2>
          </div>
          {s.instagram_campaigns.length === 0 ? (
            <div className="empty">
              <p>No campaign is set to Instagram.</p>
              <small>
                Open a campaign's <Link to="/campaigns">Edit</Link> screen and set Metrics source to Instagram.
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
                    <th scope="col"></th>
                  </tr>
                </thead>
                <tbody>
                  {s.instagram_campaigns.map((c) => (
                    <tr key={c.id}>
                      <td>{c.name}</td>
                      <td className="muted">{c.brand_name}</td>
                      <td className="mono">
                        {c.current_day}/{c.duration_days}
                      </td>
                      <td>
                        <div className="td-actions">
                          <button className="btn" type="button" disabled={syncing !== null} onClick={() => runSync(c.id, c.name)}>
                            {syncing === c.id ? "Syncing…" : "Sync now"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {sync && <SyncResultPanel result={sync.result} name={sync.name} />}

          <div className="head">
            <h2>Recent syncs</h2>
          </div>
          {s.recent_runs.length === 0 ? (
            <p className="meta">No sync has run yet.</p>
          ) : (
            <div className="tablebox">
              <table>
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Campaign</th>
                    <th scope="col">Status</th>
                    <th scope="col">Posts updated</th>
                    <th scope="col">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {s.recent_runs.map((r) => (
                    <tr key={r.id}>
                      <td className="mono">{new Date(r.started_at).toLocaleString()}</td>
                      <td>{r.campaign_name}</td>
                      <td>
                        <span className={`chip ${STATUS_CLASS[r.status] ?? "look"}`}>{r.status.replace(/_/g, " ")}</span>
                      </td>
                      <td className="mono">
                        {r.posts_updated}/{r.posts_attempted}
                      </td>
                      <td className="muted">
                        {r.errors.map((e) => (typeof e === "string" ? e : e.message)).join(" · ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="head">
            <h2>Look up a creator</h2>
          </div>
          <form
            className="panel"
            onSubmit={(e) => {
              e.preventDefault();
              lookUp();
            }}
          >
            <span className="lbl">Before signing</span>
            <input type="text" style={{ flex: 1, minWidth: 200 }} value={handle} placeholder="@handle" onChange={(e) => setHandle(e.target.value)} />
            <button className="btn" type="submit" disabled={looking || !handle.trim()}>
              {looking ? "Looking up…" : "Look up on Instagram"}
            </button>
          </form>
          {researchError && (
            <div className="vwarn" style={{ margin: 0 }} role="alert">
              <b>LOOKUP</b>
              <span>{researchError}</span>
            </div>
          )}
          {research && (
            <div className="panel" style={{ flexDirection: "column", alignItems: "stretch", gap: 10 }}>
              <span className="lbl">@{research.handle}</span>
              <dl className="kv">
                <dt>Followers</dt>
                <dd>{commas(research.followers)}</dd>
                <dt>Posts</dt>
                <dd>{research.media_count ?? "—"}</dd>
                <dt>Measured engagement</dt>
                <dd>{research.avg_engagement_rate != null ? `${(research.avg_engagement_rate * 100).toFixed(2)}% (recent posts)` : "—"}</dd>
              </dl>
            </div>
          )}
        </>
      )}
    </main>
  );
}
