import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { SortableTable, type Column } from "../components/SortableTable";
import { Chip, ErrorBox, Loading } from "../components/Status";
import { commas, statusRank } from "../format";
import { useAppState, usePageData } from "../state";
import type { PostResult } from "../types";

const columns: Column<PostResult>[] = [
  { label: "Creator", sortValue: (r) => `@${r.handle}`, cell: (r) => <Link to={`/creators/${r.creator_id}`}>@{r.handle}</Link> },
  { label: "Format", sortValue: (r) => r.format, cell: (r) => <span className="fmt">{r.format}</span> },
  { label: "Status", sortValue: (r) => statusRank(r.status), cell: (r) => <Chip status={r.status} /> },
  {
    label: "Severity",
    sortValue: (r) => r.max_severity,
    cell: (r) => (
      <span className="sev">
        {r.max_severity}
        <span aria-hidden="true">
          {Array.from({ length: 5 }, (_, i) => (
            <i key={i} className={i < Math.min(r.max_severity, 5) ? "on" : undefined} />
          ))}
        </span>
      </span>
    ),
  },
  { label: "Reason", sortValue: (r) => r.reason, cell: (r) => r.reason, className: "reason" },
];

export default function Overview() {
  const { state } = useAppState();
  const { data, error, reload } = usePageData(api.overview);

  useEffect(() => {
    document.title = "Campaign Overview · Post-Live Watch";
  }, []);

  return (
    <main className="wrap">
      <div className="head">
        <div className="titleblock">
          <p className="eyebrow">Campaign overview</p>
          <h1>{state?.campaign_name} — Campaign Overview</h1>
        </div>
        {data && (
          <p className="meta mono">
            {data.total_due} creators · {state?.duration_days}-day window
          </p>
        )}
      </div>

      {error && <ErrorBox message={error} onRetry={reload} />}
      {!data && !error && <Loading />}
      {data && (
        <>
          <section className="kpis" aria-label="Campaign KPIs">
            <div className="kpi">
              <div className="lbl">Posts live</div>
              <div className="val">
                <span>{data.posts_live}</span>
                <small>
                  /<span>{data.total_due}</span>
                </small>
              </div>
              <div className="bar" aria-hidden="true">
                <i style={{ width: `${data.posts_live_pct}%` }} />
              </div>
            </div>
            <div className="kpi">
              <div className="lbl">Reach vs promised</div>
              <div className="val">{commas(data.total_reach)}</div>
              <div className="sub">
                of <span className="mono">{commas(data.total_promised)}</span> promised across {data.guaranteed_count}{" "}
                guaranteed deliverables
              </div>
            </div>
            <div className="kpi k-act">
              <div className="lbl">
                <i className="dot act" aria-hidden="true" />
                Act now
              </div>
              <div className="val">{data.by_status["Act now"]}</div>
              <div className="sub">posts need action today</div>
            </div>
            <div className="kpi k-look">
              <div className="lbl">
                <i className="dot look" aria-hidden="true" />
                Needs a look
              </div>
              <div className="val">{data.by_status["Needs a look"]}</div>
              <div className="sub">review when free</div>
            </div>
            <div className="kpi k-ok">
              <div className="lbl">
                <i className="dot ok" aria-hidden="true" />
                OK
              </div>
              <div className="val">{data.by_status.OK}</div>
              <div className="sub">on track</div>
            </div>
            <div className="kpi k-opp">
              <div className="lbl">
                <i className="dot opp" aria-hidden="true" />
                Opportunities
              </div>
              <div className="val">{data.opportunities}</div>
              <div className="sub">viral winners to boost</div>
            </div>
          </section>

          <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="head">
              <h2>All posts</h2>
              <p className="meta">Click a column to sort</p>
            </div>
            <div className="tablebox">
              <SortableTable columns={columns} rows={data.rows} rowKey={(r) => r.post_id} initialSort={3} />
            </div>
          </section>
        </>
      )}
    </main>
  );
}
