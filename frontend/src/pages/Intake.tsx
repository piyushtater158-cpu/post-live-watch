import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Chip, ContractNotes, ErrorBox } from "../components/Status";
import { useAppState, usePageData } from "../state";
import type { CampaignDefaults, DealType, DraftDeliverable, Format, IntakeDraft, IntakeResponse } from "../types";

const EXAMPLES = [
  {
    label: "Example: barter + waived hashtag",
    text: "Signed Priya for 2 reels + 1 story, barter deal worth ₹5k product, no reach guarantee, skipping our campaign hashtag due to an exclusivity clause, due in 3 days",
  },
  { label: "Example: renew existing creator", text: "Renewing @glow_with_meera for one more reel, ₹55k, min reach 40k, due by day 5" },
  { label: "Example: affiliate deal", text: "Booked @casualcosmetics for 1 reel via affiliate commission, no min reach, due tomorrow" },
];

const FORMATS: Format[] = ["reel", "carousel", "story"];
const DEAL_TYPES: DealType[] = ["paid", "barter", "affiliate", "paid_plus_bonus"];

type Mode = "inherit" | "waived" | "literal";

interface DeliverableForm {
  format: Format;
  deal_type: DealType;
  fee: string;
  barter_value: string;
  bonus_threshold: string;
  bonus_amount: string;
  reach_mode: "guarantee" | "none";
  min_reach: string;
  due_day: string;
  tag_mode: Mode;
  tag_value: string;
  tag_reason: string;
  hashtag_mode: Mode;
  hashtag_value: string;
  hashtag_reason: string;
  link_mode: "inherit" | "required" | "waived";
}

interface CreatorForm {
  handle: string;
  followers: string;
  tier: "mid" | "micro";
  niche: string;
  avg_reach: string;
  avg_engagement_rate: string;
}

interface DraftForm {
  creator: CreatorForm;
  deliverables: DeliverableForm[];
}

const str = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v));
const num = (v: string) => (v.trim() === "" ? null : Number(v));
const modeOf = (v: string | null): Mode => (v === null ? "inherit" : v === "" ? "waived" : "literal");

function toForm(draft: IntakeDraft): DraftForm {
  const c = draft.creator;
  return {
    creator: {
      handle: c.handle,
      followers: c.followers ? String(c.followers) : "",
      tier: c.tier,
      niche: c.niche,
      avg_reach: c.avg_reach ? String(c.avg_reach) : "",
      avg_engagement_rate: c.avg_engagement_rate ? String(c.avg_engagement_rate) : "",
    },
    deliverables: draft.deliverables.map((d) => ({
      format: d.format,
      deal_type: d.deal_type,
      fee: str(d.fee),
      barter_value: str(d.barter_value),
      bonus_threshold: str(d.bonus_threshold),
      bonus_amount: str(d.bonus_amount),
      reach_mode: d.min_reach_explicitly_none ? "none" : "guarantee",
      min_reach: str(d.min_reach),
      due_day: str(d.due_day),
      tag_mode: modeOf(d.required_tag),
      tag_value: d.required_tag ?? "",
      tag_reason: d.waived_notes.required_tag ?? "",
      hashtag_mode: modeOf(d.required_hashtag),
      hashtag_value: d.required_hashtag ?? "",
      hashtag_reason: d.waived_notes.required_hashtag ?? "",
      link_mode: d.requires_link_sticker === null ? "inherit" : d.requires_link_sticker ? "required" : "waived",
    })),
  };
}

function toDraft(form: DraftForm, base: IntakeDraft, metricsTouched: boolean): unknown {
  const c = form.creator;
  return {
    source: base.source,
    brief_text: base.brief_text,
    creator: {
      handle: c.handle,
      followers: num(c.followers),
      tier: c.tier,
      niche: c.niche,
      // Untouched averages go back as null so the server re-estimates from (possibly
      // edited) followers and keeps labelling them as estimated rather than AM-entered.
      avg_reach: metricsTouched ? num(c.avg_reach) : null,
      avg_engagement_rate: metricsTouched ? num(c.avg_engagement_rate) : null,
    },
    deliverables: form.deliverables.map((d): Omit<DraftDeliverable, "preview_notes"> => {
      const waived_notes: DraftDeliverable["waived_notes"] = {};
      if (d.tag_mode === "waived" && d.tag_reason.trim()) waived_notes.required_tag = d.tag_reason.trim();
      if (d.hashtag_mode === "waived" && d.hashtag_reason.trim()) waived_notes.required_hashtag = d.hashtag_reason.trim();
      const pick = (mode: Mode, value: string) => (mode === "inherit" ? null : mode === "waived" ? "" : value);
      return {
        format: d.format,
        deal_type: d.deal_type,
        fee: num(d.fee),
        barter_value: num(d.barter_value),
        bonus_threshold: num(d.bonus_threshold),
        bonus_amount: num(d.bonus_amount),
        min_reach: d.reach_mode === "guarantee" ? num(d.min_reach) : null,
        min_reach_explicitly_none: d.reach_mode === "none",
        due_day: Number(d.due_day),
        required_tag: pick(d.tag_mode, d.tag_value),
        required_hashtag: pick(d.hashtag_mode, d.hashtag_value),
        required_disclosure: null,
        requires_link_sticker: d.link_mode === "inherit" ? null : d.link_mode === "required",
        waived_notes,
      };
    }),
  };
}

function Field({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className="field" style={wide ? { gridColumn: "1/-1" } : undefined}>
      <label>{label}</label>
      {children}
    </div>
  );
}

function Preview({
  response,
  durationDays,
  onDone,
  onReset,
}: {
  response: IntakeResponse;
  durationDays: number;
  onDone: (r: IntakeResponse) => void;
  onReset: () => void;
}) {
  const { draft, blocking_errors } = response;
  const initial = useMemo(() => toForm(draft), [draft]);
  const [form, setForm] = useState<DraftForm>(initial);
  const [metricsTouched, setMetricsTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  const existing = draft.creator.existing_creator_id;

  const setCreator = (patch: Partial<CreatorForm>) => setForm((f) => ({ ...f, creator: { ...f.creator, ...patch } }));
  const setDeliverable = (i: number, patch: Partial<DeliverableForm>) =>
    setForm((f) => ({ ...f, deliverables: f.deliverables.map((d, j) => (j === i ? { ...d, ...patch } : d)) }));

  const confirm = (action: "approve" | "edit") => {
    setBusy(true);
    api
      .intakeConfirm({ action, original_draft: draft, draft: action === "edit" ? toDraft(form, draft, metricsTouched) : undefined })
      .then(onDone)
      .catch((e: Error) => alert(`That didn't go through: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const dismiss = () => {
    setBusy(true);
    api.intakeDismiss().finally(() => onReset());
  };

  return (
    <article className="card">
      <div className={`strip ${blocking_errors.length ? "act" : "ok"}`} aria-hidden="true" />
      <div className="card-head">
        <span className="chip ok">Draft</span>
        <span className="fmt">{draft.deliverables.length} deliverable(s)</span>
      </div>

      <div className="ainote">
        <b>{draft.source === "ai" ? "AI" : "KEYWORD"}</b>
        <span>
          {draft.source === "ai"
            ? "AI draft — review every field before confirming."
            : "Keyword draft — AI is off (or the model's reply didn't parse). Check every field carefully."}
        </span>
      </div>

      {blocking_errors.length > 0 && (
        <div className="vwarn" role="alert">
          <b>FIX</b>
          <span>{blocking_errors.map((e) => e.message).join(" · ")}</span>
        </div>
      )}
      {draft.warnings.length > 0 && (
        <div className="estflag">
          <b>CHECK</b>
          <span>{draft.warnings.map((w) => w.message).join(" · ")}</span>
        </div>
      )}

      <form className="decide" onSubmit={(e) => e.preventDefault()}>
        <div className="decide-top">
          <label>Creator</label>
          <span className="hintline">Approve confirms the draft exactly as shown · change anything below to unlock Edit &amp; Confirm</span>
        </div>

        <div className="fieldgrid" style={{ padding: "0 22px 14px" }}>
          {existing ? (
            <div className="field" style={{ gridColumn: "1/-1" }}>
              <div className="contractnote" style={{ margin: 0 }}>
                <b>DEAL</b>
                <span>
                  Attaching to existing creator <Link to={`/creators/${existing}`}>@{draft.creator.handle}</Link> — their
                  profile and averages won't be changed.
                </span>
              </div>
            </div>
          ) : (
            <>
              <Field label="Handle">
                <input type="text" value={form.creator.handle} placeholder="handle" onChange={(e) => setCreator({ handle: e.target.value })} />
              </Field>
              <Field label="Followers">
                <input type="number" min={0} value={form.creator.followers} onChange={(e) => setCreator({ followers: e.target.value })} />
              </Field>
              <Field label="Tier">
                <select value={form.creator.tier} onChange={(e) => setCreator({ tier: e.target.value as CreatorForm["tier"] })}>
                  <option value="micro">Micro</option>
                  <option value="mid">Mid</option>
                </select>
              </Field>
              <Field label="Niche">
                <input type="text" value={form.creator.niche} onChange={(e) => setCreator({ niche: e.target.value })} />
              </Field>
              <Field label="Avg reach">
                <input
                  type="number"
                  min={0}
                  value={form.creator.avg_reach}
                  placeholder="estimated from followers"
                  onChange={(e) => {
                    setMetricsTouched(true);
                    setCreator({ avg_reach: e.target.value });
                  }}
                />
              </Field>
              <Field label="Avg engagement rate">
                <input
                  type="number"
                  step="0.001"
                  min={0}
                  value={form.creator.avg_engagement_rate}
                  onChange={(e) => {
                    setMetricsTouched(true);
                    setCreator({ avg_engagement_rate: e.target.value });
                  }}
                />
              </Field>
              {draft.creator.metrics_source === "estimated" && !metricsTouched && (
                <div className="field" style={{ gridColumn: "1/-1" }}>
                  <div className="estflag" style={{ margin: 0 }}>
                    <b>EST</b>
                    <span>
                      Reach and engagement are estimated from the follower count (config/thresholds.yaml → intake), not
                      measured. Rules 5 and 12 compare real reach against this number — replace it if you have a real figure.
                    </span>
                  </div>
                </div>
              )}
              {draft.creator.existing_suggestions.length > 0 && (
                <div className="field" style={{ gridColumn: "1/-1" }}>
                  <span className="muted">
                    Did you mean an existing creator?{" "}
                    {draft.creator.existing_suggestions.map((s) => (
                      <button key={s.creator_id} className="btn" type="button" style={{ minHeight: 32, marginRight: 6 }} onClick={() => setCreator({ handle: s.handle })}>
                        Attach to @{s.handle}
                      </button>
                    ))}
                  </span>
                </div>
              )}
            </>
          )}
        </div>

        <div className="flags">
          {form.deliverables.map((d, i) => (
            <div className="flag" key={i} style={{ gridTemplateColumns: "1fr" }}>
              <div className="rule">
                <span>Deliverable {i + 1}</span>
                <span className="mono">{d.format}</span>
              </div>
              <div className="fieldgrid">
                <Field label="Format">
                  <select value={d.format} onChange={(e) => setDeliverable(i, { format: e.target.value as Format })}>
                    {FORMATS.map((f) => (
                      <option key={f} value={f}>
                        {f[0].toUpperCase() + f.slice(1)}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Deal type">
                  <select value={d.deal_type} onChange={(e) => setDeliverable(i, { deal_type: e.target.value as DealType })}>
                    {DEAL_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t.replace(/_/g, " ")}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Fee (₹)">
                  <input type="number" min={0} value={d.fee} onChange={(e) => setDeliverable(i, { fee: e.target.value })} />
                </Field>
                <Field label="Barter value (₹)">
                  <input type="number" min={0} value={d.barter_value} onChange={(e) => setDeliverable(i, { barter_value: e.target.value })} />
                </Field>
                {d.deal_type === "paid_plus_bonus" && (
                  <>
                    <Field label="Bonus threshold (reach)">
                      <input type="number" min={0} value={d.bonus_threshold} onChange={(e) => setDeliverable(i, { bonus_threshold: e.target.value })} />
                    </Field>
                    <Field label="Bonus amount (₹)">
                      <input type="number" min={0} value={d.bonus_amount} onChange={(e) => setDeliverable(i, { bonus_amount: e.target.value })} />
                    </Field>
                  </>
                )}
                <Field label="Reach guarantee">
                  <select value={d.reach_mode} onChange={(e) => setDeliverable(i, { reach_mode: e.target.value as DeliverableForm["reach_mode"] })}>
                    <option value="guarantee">Has a minimum</option>
                    <option value="none">No guarantee (stated)</option>
                  </select>
                </Field>
                {d.reach_mode === "guarantee" && (
                  <Field label="Minimum reach">
                    <input type="number" min={0} value={d.min_reach} onChange={(e) => setDeliverable(i, { min_reach: e.target.value })} />
                  </Field>
                )}
                <Field label="Due — campaign day">
                  <input type="number" min={1} max={durationDays} value={d.due_day} onChange={(e) => setDeliverable(i, { due_day: e.target.value })} />
                </Field>
                <Field label="Brand tag">
                  <select value={d.tag_mode} onChange={(e) => setDeliverable(i, { tag_mode: e.target.value as Mode })}>
                    <option value="inherit">Inherit campaign default</option>
                    <option value="waived">Waived</option>
                    <option value="literal">Specific value</option>
                  </select>
                </Field>
                {d.tag_mode === "literal" && (
                  <Field label="Tag value">
                    <input type="text" value={d.tag_value} onChange={(e) => setDeliverable(i, { tag_value: e.target.value })} />
                  </Field>
                )}
                {d.tag_mode === "waived" && (
                  <Field label="Tag waiver reason">
                    <input type="text" value={d.tag_reason} onChange={(e) => setDeliverable(i, { tag_reason: e.target.value })} />
                  </Field>
                )}
                <Field label="Hashtag">
                  <select value={d.hashtag_mode} onChange={(e) => setDeliverable(i, { hashtag_mode: e.target.value as Mode })}>
                    <option value="inherit">Inherit campaign default</option>
                    <option value="waived">Waived</option>
                    <option value="literal">Specific value</option>
                  </select>
                </Field>
                {d.hashtag_mode === "literal" && (
                  <Field label="Hashtag value">
                    <input type="text" value={d.hashtag_value} onChange={(e) => setDeliverable(i, { hashtag_value: e.target.value })} />
                  </Field>
                )}
                {d.hashtag_mode === "waived" && (
                  <Field label="Hashtag waiver reason">
                    <input type="text" value={d.hashtag_reason} onChange={(e) => setDeliverable(i, { hashtag_reason: e.target.value })} />
                  </Field>
                )}
                <Field label="Link sticker">
                  <select value={d.link_mode} onChange={(e) => setDeliverable(i, { link_mode: e.target.value as DeliverableForm["link_mode"] })}>
                    <option value="inherit">Infer from format</option>
                    <option value="required">Required</option>
                    <option value="waived">Not required</option>
                  </select>
                </Field>
              </div>
              <ContractNotes notes={draft.deliverables[i]?.preview_notes ?? []} style={{ margin: "14px 0 0" }} />
            </div>
          ))}
        </div>

        <div className="row" style={{ padding: "16px 22px" }}>
          <button className="btn approve" type="button" disabled={busy} onClick={() => confirm("approve")}>
            Approve as drafted
          </button>
          <button className="btn" type="button" disabled={busy || !dirty} onClick={() => confirm("edit")}>
            Edit &amp; Confirm
          </button>
          <button className="btn ghost" type="button" disabled={busy} onClick={dismiss}>
            Dismiss
          </button>
        </div>
      </form>
    </article>
  );
}

function Created({ response, onReset }: { response: IntakeResponse; onReset: () => void }) {
  const { draft, result, package: pkg } = response;
  if (!result) return null;
  return (
    <article className="card">
      <div className="strip ok" aria-hidden="true" />
      <div className="card-head">
        <span className="chip ok">Created</span>
        <Link className="handle" to={`/creators/${result.creator_id}`}>
          @{draft.creator.handle}
        </Link>
        <span className="fmt">{result.deliverable_ids.length} deliverable(s)</span>
      </div>
      {pkg?.current_campaign && (
        <div className="panel" style={{ margin: "14px 22px", flexWrap: "wrap" }}>
          <span className="lbl">Rolled-up status</span>
          <Chip status={pkg.current_campaign.status} />
          <span className="muted mono">
            {pkg.current_campaign.delivered}/{pkg.current_campaign.total_deliverables} live
          </span>
        </div>
      )}
      <div className="row" style={{ padding: "16px 22px", display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Link className="btn approve" to={`/creators/${result.creator_id}`}>
          View creator profile
        </Link>
        <Link className="btn" to="/queue">
          Go to flag queue
        </Link>
        <button className="btn ghost" type="button" onClick={onReset}>
          Draft another deal
        </button>
      </div>
    </article>
  );
}

export default function Intake() {
  const { state } = useAppState();
  const defaults = usePageData(api.intakeDefaults);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<IntakeResponse | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    document.title = "New Deal · Post-Live Watch";
  }, []);

  const campaign: CampaignDefaults | undefined = defaults.data?.campaign;

  const draftIt = () => {
    setBusy(true);
    setError(null);
    setDismissed(false);
    api
      .intakeParse(brief)
      .then((r) => {
        setResponse(r);
        setVersion((v) => v + 1);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  const clear = (wasDismissed: boolean) => {
    setResponse(null);
    setDismissed(wasDismissed);
  };

  return (
    <main className="wrap narrow">
      <div className="head">
        <div className="titleblock">
          <p className="eyebrow">Deal intake</p>
          <h1>New Deal</h1>
        </div>
        <p className="meta mono">Describe what was negotiated — a human confirms before anything is created</p>
      </div>

      {defaults.error && <ErrorBox message={defaults.error} onRetry={defaults.reload} />}
      {campaign && (
        <div className="panel">
          <span className="lbl">Campaign defaults</span>
          <p>
            tag {campaign.required_tag} · hashtag {campaign.required_hashtag} · disclosure{" "}
            {campaign.required_disclosure.split("|").join(" or ")} · link sticker{" "}
            {campaign.requires_link_sticker ? "required on stories" : "not required"}
          </p>
        </div>
      )}

      <form
        className="panel"
        style={{ flexDirection: "column", alignItems: "stretch", gap: 12 }}
        onSubmit={(e) => {
          e.preventDefault();
          if (brief.trim()) draftIt();
        }}
      >
        <label htmlFor="brief_text" className="lbl">
          Deal brief
        </label>
        <textarea
          id="brief_text"
          value={brief}
          required
          maxLength={4000}
          placeholder={EXAMPLES[0].text}
          onChange={(e) => setBrief(e.target.value)}
        />
        <div className="row" style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {EXAMPLES.map((ex) => (
            <button key={ex.label} className="btn" type="button" onClick={() => setBrief(ex.text)}>
              {ex.label}
            </button>
          ))}
        </div>
        <div className="row" style={{ display: "flex", justifyContent: "flex-end" }}>
          <button className="btn approve" type="submit" disabled={busy || !brief.trim()}>
            {busy ? "Drafting…" : state?.ai_enabled ? "Draft the deal" : "Draft the deal (keyword mode)"}
          </button>
        </div>
      </form>

      {error && <ErrorBox message={error} onRetry={draftIt} />}

      <div id="intake-preview" className="list">
        {response?.result ? (
          <Created
            response={response}
            onReset={() => {
              clear(false);
              setBrief("");
            }}
          />
        ) : response ? (
          <Preview
            key={version}
            response={response}
            durationDays={campaign?.duration_days ?? state?.duration_days ?? 7}
            onDone={(r) => {
              setResponse(r);
              setVersion((v) => v + 1);
            }}
            onReset={() => clear(true)}
          />
        ) : (
          <div className="empty">
            <p>{dismissed ? "Draft dismissed — nothing was created." : "Nothing drafted yet."}</p>
            <small>Describe the deal above and draft it — nothing is created until you review and confirm.</small>
          </div>
        )}
      </div>
    </main>
  );
}
