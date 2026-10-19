import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Chip, ContractNotes, ErrorBox, Loading } from "../components/Status";
import { statusClass } from "../format";
import { useAppState, usePageData } from "../state";
import type { DecisionIn, QueueCard } from "../types";

async function copyText(text: string, fallbackEl: HTMLTextAreaElement | null) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    fallbackEl?.select();
    document.execCommand("copy");
  }
}

function DecisionForm({
  card,
  isOppOnly,
  onDecide,
}: {
  card: QueueCard;
  isOppOnly: boolean;
  onDecide: (body: DecisionIn) => Promise<void>;
}) {
  const original = card.default_message ?? "";
  const [text, setText] = useState(original);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [textarea, setTextarea] = useState<HTMLTextAreaElement | null>(null);

  const submit = (action: DecisionIn["action"]) => {
    // Approve sends the suggestion exactly as written, whatever is in the box.
    if (action === "approve") setText(original);
    setBusy(true);
    onDecide({ action, message_text: text, original_message: original, flag_rule_id: card.primary_rule_id ?? 0 })
      .catch((e: Error) => alert(`That didn't go through: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const onCopy = () =>
    copyText(text, textarea).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });

  return (
    <form className="decide" onSubmit={(e) => e.preventDefault()}>
      <div className="decide-top">
        <label htmlFor={`msg-${card.post_id}`}>{isOppOnly ? "Boost suggestion" : "Message to creator"}</label>
        <span className="hintline">Approve sends the suggestion as written · edit it to unlock Edit &amp; Approve</span>
      </div>
      <textarea
        id={`msg-${card.post_id}`}
        name="message_text"
        ref={setTextarea}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="row">
        <button className={`btn ${isOppOnly ? "boost" : "approve"}`} type="button" disabled={busy} onClick={() => submit("approve")}>
          {isOppOnly ? "Approve boost" : "Approve"}
        </button>
        <button className="btn" type="button" disabled={busy || text.trim() === original.trim()} onClick={() => submit("edit")}>
          Edit &amp; Approve
        </button>
        <button className="btn ghost" type="button" disabled={busy} onClick={() => submit("dismiss")}>
          Dismiss
        </button>
        <span className="spacer" />
        <button className="btn" type="button" aria-label="Copy message to clipboard" onClick={onCopy}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <rect x="5" y="5" width="8.5" height="8.5" rx="1.5" />
            <path d="M10.5 5V3.5A1.5 1.5 0 0 0 9 2H3.5A1.5 1.5 0 0 0 2 3.5V9A1.5 1.5 0 0 0 3.5 10.5H5" />
          </svg>
          <span className="copy-label">{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
    </form>
  );
}

function Card({ card, onDecide }: { card: QueueCard; onDecide: (body: DecisionIn) => Promise<void> }) {
  const isOppOnly = !card.flags.length && !!card.opportunity_note;
  return (
    <article className={`card${isOppOnly ? " is-opp" : ""}`}>
      <div className={`strip ${isOppOnly ? "opp" : statusClass(card.status)}`} aria-hidden="true" />
      <div className="card-head">
        <Chip status={card.status} />
        <Link className="handle" to={`/creators/${card.creator_id}`}>
          @{card.handle}
        </Link>
        <span className="fmt">{card.format}</span>
        {card.flags.length > 0 && (
          <span className="sevtag">
            MAX SEVERITY <span>{card.max_severity}</span>
          </span>
        )}
        {card.opportunity_note && <span className="chip opp">Opportunity</span>}
      </div>

      {card.flags.length > 0 && (
        <div className="flags">
          {card.flags.map((f) => (
            <div className="flag" key={f.rule_id}>
              <div className={`sevbox sev${Math.min(f.severity, 5)}`}>
                <span>{f.severity}</span>
                <small>SEV</small>
              </div>
              <div className="rule">
                <span>{f.rule_name}</span>
                <span className="mono">rule {f.rule_id}</span>
              </div>
              <p className="why">{f.reason}</p>
              {f.ai_note && (
                <div className="ainote">
                  <b>AI</b>
                  <span>{f.ai_note}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <ContractNotes notes={card.contract_notes} />

      {card.opportunity_note && (
        <div className="oppbox">
          <div className="t">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M2.5 13.5 7 9l3 3 5.5-6.5" />
              <path d="M11.5 5.5h4v4" />
            </svg>
            Viral winner <span className="mono">rule {card.opportunities[0]?.rule_id}</span>
          </div>
          <p>{card.opportunity_note}</p>
        </div>
      )}

      {card.primary_rule_id !== null && <DecisionForm card={card} isOppOnly={isOppOnly} onDecide={onDecide} />}
    </article>
  );
}

export default function Queue() {
  const { state } = useAppState();
  const { data, setData, error, reload } = usePageData(api.queue);
  // Bumped after every decision so each card's form remounts with its fresh default
  // message, the same way the server-rendered queue swaps in new markup.
  const [version, setVersion] = useState(0);

  useEffect(() => {
    document.title = "Flag Queue · Post-Live Watch";
  }, []);

  const decide = (postId: number) => async (body: DecisionIn) => {
    const res = await api.decide(postId, body);
    setData(res);
    setVersion((v) => v + 1);
  };

  return (
    <main className="wrap narrow">
      <div className="head">
        <div className="titleblock">
          <p className="eyebrow">Account manager queue</p>
          <h1>Flag Queue (Act now first)</h1>
        </div>
      </div>

      {error && <ErrorBox message={error} onRetry={reload} />}
      {!data && !error && <Loading />}
      {data && (
        <div id="queue-list" className="list">
          {data.cards.map((card) => (
            <Card key={`${card.post_id}-${version}`} card={card} onDecide={decide(card.post_id)} />
          ))}
          {data.cards.length === 0 && (
            <div className="empty">
              <div className="ring" aria-hidden="true">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 12.5 10 17.5 19 7" />
                </svg>
              </div>
              <p>No flags right now — everything's clean as of day {state?.current_day}.</p>
              <small>New flags appear here when you advance the day.</small>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
