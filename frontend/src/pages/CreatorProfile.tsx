import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Chip, ContractNotes, ErrorBox, Loading } from "../components/Status";
import { capitalize, commas, hintClass } from "../format";
import { usePageData } from "../state";

export default function CreatorProfile() {
  const id = Number(useParams().id);
  const { data, error, reload } = usePageData(() => api.creator(id), [id]);

  useEffect(() => {
    if (data) document.title = `@${data.creator.handle} · Post-Live Watch`;
  }, [data]);

  const crumb = (
    <Link className="crumb" to="/creators">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M8.5 3 4.5 7l4 4" />
      </svg>
      All creators
    </Link>
  );

  if (error || !data)
    return (
      <main className="wrap">
        {crumb}
        {error ? <ErrorBox message={error} onRetry={reload} /> : <Loading />}
      </main>
    );

  const { creator, reliability, current_deliverables } = data;
  const verdict = hintClass(reliability.book_again_hint);

  return (
    <main className="wrap">
      {crumb}

      <div className="titleblock" style={{ gap: 12 }}>
        <h1 className="handle-title">@{creator.handle}</h1>
        <div className="tags">
          <span className="tag">{capitalize(creator.tier)} tier</span>
          <span className="tag">{creator.niche}</span>
          {creator.metrics_source === "estimated" && (
            <span className="tag est" title="Rules 5 and 12 compare real reach against this estimate">
              Estimated reach · {commas(Math.round(creator.avg_reach))} from follower count
            </span>
          )}
          {creator.metrics_source === "am_entered" && (
            <span className="tag">Avg reach {commas(Math.round(creator.avg_reach))} · entered at intake</span>
          )}
        </div>
      </div>

      <section className="kpis wide" aria-label="Reliability">
        <div className="kpi">
          <div className="lbl">Reliability score</div>
          {reliability.score === null ? (
            <>
              <div className="val">—</div>
              <div className="sub">no campaign due yet</div>
            </>
          ) : (
            <>
              <div className="val">
                <span>{Math.round(reliability.score)}</span>
                <small>/100</small>
              </div>
              <div className="bar" aria-hidden="true">
                <i style={{ width: `${reliability.score}%` }} />
              </div>
            </>
          )}
        </div>
        <div className="kpi">
          <div className="lbl">On-time rate</div>
          <div className="val">{reliability.on_time_rate === null ? "—" : `${Math.round(reliability.on_time_rate * 100)}%`}</div>
          <div className="sub">across {reliability.campaigns_considered} campaigns</div>
        </div>
        <div className="kpi">
          <div className="lbl">Avg performance</div>
          <div className="val">{reliability.avg_performance_ratio === null ? "—" : `${reliability.avg_performance_ratio.toFixed(2)}x`}</div>
          <div className="sub">actual ÷ promised reach</div>
        </div>
        <div className="kpi">
          <div className="lbl">Avg flags / campaign</div>
          <div className="val">{reliability.avg_flags_per_campaign === null ? "—" : reliability.avg_flags_per_campaign.toFixed(1)}</div>
        </div>
      </section>

      <div className={`verdict ${verdict}`}>
        <div className="ico" aria-hidden="true">
          {verdict === "yes" ? (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 8.5 6.5 12 13 4.5" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M8 4v5" />
              <path d="M8 12h.01" />
            </svg>
          )}
        </div>
        <span>{reliability.book_again_hint}</span>
      </div>

      {current_deliverables.length > 0 && (
        <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="head">
            <h2>Current campaign · GlowLeaf</h2>
          </div>
          {current_deliverables.map((d) => (
            <div className="panel" key={d.post_id}>
              <span className="lbl">
                {d.deliverable_label} · {capitalize(d.deal_type)}
                {d.deal_type !== "paid" && " deal"}
              </span>
              <Chip status={d.status} />
              <p>{d.reason}</p>
              <ContractNotes notes={d.contract_notes} style={{ margin: "10px 0 0" }} />
            </div>
          ))}
        </section>
      )}

      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="head" style={{ alignItems: "center" }}>
          <h2>12-month history</h2>
          <div className="legend">
            <span>
              <i className="l-conflict" aria-hidden="true" />
              Competitor conflict
            </span>
            <span>
              <i className="l-incomplete" aria-hidden="true" />
              Not completed
            </span>
          </div>
        </div>
        <div className="tablebox">
          <table className="nowrap">
            <thead>
              <tr>
                <th scope="col">Month</th>
                <th scope="col">Campaign</th>
                <th scope="col">On time</th>
                <th scope="col">Performance</th>
                <th scope="col">Flags</th>
                <th scope="col">Fix speed</th>
                <th scope="col">Competitor conflict</th>
                <th scope="col">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {[...reliability.history].reverse().map((h, i) => {
                const classes = [h.competitor_conflict && "conflict", h.outcome !== "completed" && "incomplete"].filter(Boolean);
                return (
                  <tr key={`${h.month}-${i}`} className={classes.length ? classes.join(" ") : undefined}>
                    <td className="mono">{h.month}</td>
                    <td>{h.campaign_name}</td>
                    <td>{h.delivered_on_time ? <span className="yes-t">Yes</span> : <span className="no-t">No</span>}</td>
                    <td className="mono">{h.performance_ratio.toFixed(2)}x</td>
                    <td className="mono">{h.flags_count}</td>
                    <td className="mono">{h.fix_speed_days !== null ? `${h.fix_speed_days} d` : "—"}</td>
                    <td>{h.competitor_conflict ? <span className="flagtag">Conflict</span> : "—"}</td>
                    <td>
                      <span className={`outcome${h.outcome !== "completed" ? " bad" : ""}`}>{h.outcome}</span>
                    </td>
                  </tr>
                );
              })}
              {reliability.history.length === 0 && (
                <tr>
                  <td colSpan={8} className="muted">
                    No campaign history on record.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
