import { useEffect, useState, type CSSProperties } from "react";
import { onServerSlow } from "../api";
import { statusClass } from "../format";
import type { ContractNote } from "../types";

export function Chip({ status }: { status: string }) {
  return <span className={`chip ${statusClass(status)}`}>{status}</span>;
}

export function ContractNotes({ notes, style }: { notes: ContractNote[]; style?: CSSProperties }) {
  if (!notes?.length) return null;
  return (
    <div className="contractnote" style={style}>
      <b>DEAL</b>
      <span>{notes.map((n) => `${n.requirement}: ${n.note}`).join(" · ")}</span>
    </div>
  );
}

export function Loading() {
  return <p className="loading">Loading…</p>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="errbox" role="alert">
      <p>Couldn't load this screen: {message}</p>
      <button className="btn" type="button" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

export function WakingBanner() {
  const [slow, setSlow] = useState(false);
  useEffect(() => onServerSlow(setSlow), []);
  if (!slow) return null;
  return (
    <div className="waking" role="status">
      Waking up the server… the free-tier API sleeps when idle and can take up to a minute to respond.
    </div>
  );
}

export function SampleBanner() {
  return (
    <div className="sample" role="status">
      Sample data <span>All creators, posts and figures are synthetic</span>
    </div>
  );
}
