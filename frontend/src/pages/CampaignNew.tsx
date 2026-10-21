import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Field } from "../components/Field";
import { ContractNotes, ErrorBox } from "../components/Status";
import { commas } from "../format";
import { useAppState, usePageData } from "../state";
import type { CampaignFieldsIn, CampaignFormDefaults, CampaignIntakeResponse } from "../types";

const EXAMPLE =
  "@glowgirlpriya for 1 reel, ₹20k, min reach 15k, due in 3 days. @riya.unfiltered for 2 stories, barter worth ₹6k, no reach guarantee, due day 8.";

interface Form {
  name: string;
  brand_name: string;
  product: string;
  duration_days: string;
  days_running: string;
  required_disclosure: string;
  required_tag: string;
  required_hashtag: string;
  requires_link_sticker: boolean;
  banned_claims_text: string;
}

function toFields(form: Form, defaults: CampaignFormDefaults): CampaignFieldsIn {
  const existing = defaults.brands.find((b) => b.name.toLowerCase() === form.brand_name.trim().toLowerCase());
  return {
    name: form.name.trim(),
    existing_brand_id: existing?.id ?? null,
    brand_name: form.brand_name.trim(),
    product: form.product.trim(),
    duration_days: form.duration_days ? Number(form.duration_days) : null,
    days_running: form.days_running ? Number(form.days_running) : null,
    required_disclosure: form.required_disclosure,
    required_tag: form.required_tag.trim(),
    required_hashtag: form.required_hashtag.trim(),
    requires_link_sticker: form.requires_link_sticker,
    banned_claims: form.banned_claims_text
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean),
  };
}

function Preview({
  response,
  busy,
  onConfirm,
  onDiscard,
}: {
  response: CampaignIntakeResponse;
  busy: boolean;
  onConfirm: () => void;
  onDiscard: () => void;
}) {
  const { draft, blocking_errors } = response;
  const c = draft.campaign;
  return (
    <article className="card">
      <div className={`strip ${blocking_errors.length ? "act" : "ok"}`} aria-hidden="true" />
      <div className="card-head">
        <span className="chip ok">Draft</span>
        <span className="handle">{c.name || "(name not set)"}</span>
        <span className="fmt">{draft.creators.length} creator(s)</span>
      </div>
      <div className="ainote" style={{ margin: "0 22px" }}>
        <b>{draft.source === "ai" ? "AI" : "KEYWORD"}</b>
        <span>
          {draft.source === "ai"
            ? "AI drafted the creator deals — review every line before confirming."
            : "Keyword draft of the creator deals — check every line carefully."}
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

      <div className="panel" style={{ margin: "10px 22px", flexDirection: "column", alignItems: "stretch", gap: 4 }}>
        <span className="lbl">Campaign · {c.brand_name}</span>
        <p className="mono">
          {c.duration_days} days · {c.days_running ? `already running ${c.days_running} days` : "starts today"} · disclosure{" "}
          {c.required_disclosure.split("|").join(" or ")}
          {c.required_tag && ` · tag ${c.required_tag}`}
          {c.required_hashtag && ` · hashtag ${c.required_hashtag}`}
          {c.banned_claims.length > 0 && ` · banned: ${c.banned_claims.join(", ")}`}
        </p>
      </div>

      <div className="flags">
        {draft.creators.map((cd, i) => (
          <div className="flag" key={i} style={{ gridTemplateColumns: "1fr" }}>
            <div className="rule">
              <span>Creator {i + 1}</span>
              <span className="mono">
                @{cd.creator.handle || "(handle not set)"} {cd.creator.existing_creator_id ? "(existing)" : "(new)"}
              </span>
            </div>
            {cd.warnings.length > 0 && (
              <div className="estflag" style={{ margin: "6px 0" }}>
                <b>CHECK</b>
                <span>{cd.warnings.map((w) => w.message).join(" · ")}</span>
              </div>
            )}
            {cd.deliverables.map((d, j) => (
              <div key={j}>
                <p className="muted" style={{ margin: "4px 0" }}>
                  {d.format} · {d.deal_type.replace(/_/g, " ")}
                  {d.fee ? ` · ₹${commas(d.fee)}` : ""}
                  {d.barter_value ? ` · barter ₹${commas(d.barter_value)}` : ""}
                  {d.min_reach ? ` · min reach ${commas(d.min_reach)}` : d.min_reach_explicitly_none ? " · no reach guarantee" : ""}
                  {` · due day ${d.due_day}`}
                </p>
                <ContractNotes notes={d.preview_notes ?? []} style={{ margin: "6px 0" }} />
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="row" style={{ padding: "16px 22px" }}>
        <button className="btn approve" type="button" disabled={busy || blocking_errors.length > 0} onClick={onConfirm}>
          {busy ? "Creating…" : "Confirm & create campaign"}
        </button>
        <button className="btn ghost" type="button" disabled={busy} onClick={onDiscard}>
          Discard draft
        </button>
      </div>
    </article>
  );
}

export default function CampaignNew() {
  const { state, setState } = useAppState();
  const defaults = usePageData(api.campaignDefaults);
  const [form, setForm] = useState<Form | null>(null);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<CampaignIntakeResponse | null>(null);
  const [created, setCreated] = useState<{ id: number; name: string; creators: number } | null>(null);

  useEffect(() => {
    document.title = "New Campaign · Post-Live Watch";
  }, []);

  useEffect(() => {
    if (defaults.data && !form)
      setForm({
        name: "",
        brand_name: "",
        product: "",
        duration_days: String(defaults.data.default_duration_days),
        days_running: "",
        required_disclosure: defaults.data.default_required_disclosure,
        required_tag: "",
        required_hashtag: "",
        requires_link_sticker: true,
        banned_claims_text: "",
      });
  }, [defaults.data, form]);

  const set = (patch: Partial<Form>) => setForm((f) => (f ? { ...f, ...patch } : f));

  const draftIt = () => {
    if (!form || !defaults.data) return;
    setBusy(true);
    setError(null);
    api
      .campaignParse(toFields(form, defaults.data), brief)
      .then(setResponse)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  const confirm = () => {
    if (!response) return;
    setBusy(true);
    api
      .campaignConfirm(response.draft)
      .then(async (r) => {
        if (r.result) {
          setState(await api.selectCampaign(r.result.campaign_id));
          setCreated({ id: r.result.campaign_id, name: r.draft.campaign.name, creators: r.result.creators.length });
          setResponse(null);
        } else {
          setResponse(r);
        }
      })
      .catch((e: Error) => alert(`That didn't go through: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const startOver = () => {
    setCreated(null);
    setResponse(null);
    setBrief("");
    setForm(null);
  };

  if (created)
    return (
      <main className="wrap narrow">
        <article className="card">
          <div className="strip ok" aria-hidden="true" />
          <div className="card-head">
            <span className="chip ok">Created</span>
            <span className="handle">{created.name}</span>
            <span className="fmt">{created.creators} creator(s)</span>
          </div>
          <p className="meta" style={{ padding: "0 22px" }}>
            It's now the active campaign — every screen shows it. Switch back any time from the header dropdown.
          </p>
          <div className="row" style={{ padding: "16px 22px" }}>
            <Link className="btn approve" to="/">
              Open its overview
            </Link>
            <Link className="btn" to="/intake">
              Add another creator
            </Link>
            <Link className="btn" to={`/campaigns/${created.id}/edit`}>
              Edit / connect Instagram
            </Link>
            <button className="btn ghost" type="button" onClick={startOver}>
              Create another campaign
            </button>
          </div>
        </article>
      </main>
    );

  return (
    <main className="wrap narrow">
      <div className="head">
        <div className="titleblock">
          <p className="eyebrow">Campaign intake</p>
          <h1>New Campaign</h1>
        </div>
        <p className="meta mono">Brand-new or already running — you review the draft before anything is created</p>
      </div>

      {defaults.error && <ErrorBox message={defaults.error} onRetry={defaults.reload} />}

      {form && defaults.data && (
        <form
          className="panel"
          style={{ flexDirection: "column", alignItems: "stretch", gap: 16 }}
          onSubmit={(e) => {
            e.preventDefault();
            draftIt();
          }}
        >
          <div className="fieldgrid">
            <Field label="Campaign name">
              <input type="text" required value={form.name} placeholder="e.g. Summer Sunscreen Launch" onChange={(e) => set({ name: e.target.value })} />
            </Field>
            <Field label="Brand (pick existing or type a new one)">
              <input type="text" required list="brand-list" value={form.brand_name} onChange={(e) => set({ brand_name: e.target.value })} />
              <datalist id="brand-list">
                {defaults.data.brands.map((b) => (
                  <option key={b.id} value={b.name} />
                ))}
              </datalist>
            </Field>
            <Field label="Product">
              <input type="text" value={form.product} onChange={(e) => set({ product: e.target.value })} />
            </Field>
            <Field label="Duration (days)">
              <input type="number" min={1} max={defaults.data.max_duration_days} value={form.duration_days} onChange={(e) => set({ duration_days: e.target.value })} />
            </Field>
            <Field label="Already running for (days)">
              <input type="number" min={1} value={form.days_running} placeholder="blank = starts today" onChange={(e) => set({ days_running: e.target.value })} />
            </Field>
            <Field label="Disclosure (accepted tokens, '|'-separated)">
              <input type="text" required value={form.required_disclosure} onChange={(e) => set({ required_disclosure: e.target.value })} />
            </Field>
            <Field label="Brand tag">
              <input type="text" value={form.required_tag} placeholder="@brandhandle" onChange={(e) => set({ required_tag: e.target.value })} />
            </Field>
            <Field label="Campaign hashtag">
              <input type="text" value={form.required_hashtag} placeholder="#CampaignHashtag" onChange={(e) => set({ required_hashtag: e.target.value })} />
            </Field>
            <Field label="Stories">
              <label className="muted" style={{ textTransform: "none", letterSpacing: 0, font: "14px var(--sans)", display: "flex", gap: 8, alignItems: "center" }}>
                <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={form.requires_link_sticker} onChange={(e) => set({ requires_link_sticker: e.target.checked })} />
                Require link sticker
              </label>
            </Field>
            <Field label="Banned claims (one per line)" wide>
              <textarea style={{ minHeight: 70 }} value={form.banned_claims_text} placeholder={"cures acne\n100% natural"} onChange={(e) => set({ banned_claims_text: e.target.value })} />
            </Field>
          </div>

          <label htmlFor="creators_brief_text" className="lbl">
            Creators &amp; deals — paste a brief, or one line per creator
          </label>
          <textarea id="creators_brief_text" required maxLength={8000} value={brief} placeholder={EXAMPLE} onChange={(e) => setBrief(e.target.value)} />
          <div className="row">
            <button className="btn" type="button" onClick={() => setBrief(EXAMPLE)}>
              Example: two creators, mixed deal types
            </button>
          </div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn approve" type="submit" disabled={busy || !form.name.trim() || !brief.trim()}>
              {busy && !response ? "Drafting…" : state?.ai_enabled ? "Draft the campaign" : "Draft the campaign (keyword mode)"}
            </button>
          </div>
        </form>
      )}

      {error && <ErrorBox message={error} onRetry={draftIt} />}

      <div className="list">
        {response ? (
          <Preview response={response} busy={busy} onConfirm={confirm} onDiscard={() => setResponse(null)} />
        ) : (
          <div className="empty">
            <p>Nothing drafted yet.</p>
            <small>Fill in the campaign and its creator deals above, then draft — nothing is created until you confirm.</small>
          </div>
        )}
      </div>
    </main>
  );
}
