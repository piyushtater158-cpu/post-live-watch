import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { SortableTable, type Column } from "../components/SortableTable";
import { Chip, ErrorBox, Loading } from "../components/Status";
import { capitalize, hintClass, hintRank, statusRank } from "../format";
import { usePageData } from "../state";
import type { CreatorSummary } from "../types";

const columns: Column<CreatorSummary>[] = [
  { label: "Creator", sortValue: (c) => `@${c.handle}`, cell: (c) => <Link to={`/creators/${c.id}`}>@{c.handle}</Link> },
  {
    label: "Tier · niche",
    sortValue: (c) => `${c.tier} · ${c.niche}`,
    className: "muted",
    cell: (c) => (
      <>
        <span>{capitalize(c.tier)}</span> · <span>{c.niche}</span>
        {c.metrics_source === "estimated" && (
          <span className="tag est" title="Average reach estimated from follower count at deal intake, not measured">
            Estimated reach
          </span>
        )}
      </>
    ),
  },
  {
    label: "Reliability",
    sortValue: (c) => c.reliability.score ?? -1,
    cell: (c) =>
      c.reliability.score === null ? (
        <span className="muted">—</span>
      ) : (
        <div className="score">
          <span>{Math.round(c.reliability.score)}</span>
          <span className="bar" aria-hidden="true">
            <i style={{ width: `${c.reliability.score}%` }} />
          </span>
        </div>
      ),
  },
  {
    label: "Book again?",
    sortValue: (c) => hintRank(c.reliability.book_again_hint),
    cell: (c) => <span className={`hint ${hintClass(c.reliability.book_again_hint)}`}>{c.reliability.book_again_hint}</span>,
  },
  {
    label: "This campaign",
    sortValue: (c) => (c.current_campaign ? statusRank(c.current_campaign.status) : 0),
    cell: (c) =>
      c.current_campaign ? (
        <>
          <Chip status={c.current_campaign.status} />
          {c.current_campaign.total_deliverables > 1 && (
            <span className="muted mono" style={{ marginLeft: 6 }}>
              {c.current_campaign.delivered}/{c.current_campaign.total_deliverables} live
            </span>
          )}
        </>
      ) : (
        <span className="muted">—</span>
      ),
  },
];

export default function Creators() {
  const { data, error, reload } = usePageData(api.creators);

  useEffect(() => {
    document.title = "Creators · Post-Live Watch";
  }, []);

  return (
    <main className="wrap">
      <div className="head">
        <div className="titleblock">
          <p className="eyebrow">Roster</p>
          <h1>Creators</h1>
        </div>
        {data && <p className="meta mono">{data.creators.length} creators on GlowLeaf</p>}
      </div>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!data && !error && <Loading />}
      {data && (
        <div className="tablebox">
          <SortableTable columns={columns} rows={data.creators} rowKey={(c) => c.id} initialSort={2} />
        </div>
      )}
    </main>
  );
}
