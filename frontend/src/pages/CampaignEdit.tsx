import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { Field } from "../components/Field";
import { ErrorBox, Loading } from "../components/Status";
import { useAppState, usePageData } from "../state";
import type { CampaignEditIn, CampaignRow, MetricsProvider } from "../types";

interface Form extends Omit<CampaignEditIn, "duration_days" | "banned_claims"> {
  duration_days: string;
  banned_claims_text: string;
}

function toForm(c: CampaignRow): Form {
  return {
    name: c.name,
    required_disclosure: c.required_disclosure,
    required_tag: c.required_tag ?? "",
    required_hashtag: c.required_hashtag ?? "",
    requires_link_sticker: !!c.requires_link_sticker,
    duration_days: String(c.duration_days),
    banned_claims_text: (JSON.parse(c.banned_claims || "[]") as string[]).join("\n"),
    metrics_provider: c.metrics_provider,
  };
}

export default function CampaignEdit() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { setState } = useAppState();
  const campaign = usePageData(() => api.campaign(id), [id]);
  const [form, setForm] = useState<Form | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (campaign.data) {
      setForm(toForm(campaign.data));
      document.title = `Edit ${campaign.data.name} · Post-Live Watch`;
    }
  }, [campaign.data]);

  const set = (patch: Partial<Form>) => setForm((f) => (f ? { ...f, ...patch } : f));

  const save = () => {
    if (!form) return;
    setBusy(true);
    setError(null);
    const { banned_claims_text, duration_days, ...rest } = form;
    api
      .editCampaign(id, {
        ...rest,
        duration_days: Number(duration_days),
        banned_claims: banned_claims_text
          .split("\n")
          .map((l) => l.trim())
          .filter(Boolean),
      })
      .then(() => api.state())
      .then((s) => {
        setState(s);
        navigate("/campaigns");
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <main className="wrap narrow">
      <div className="head">
        <div className="titleblock">
          <p className="eyebrow">Campaign management</p>
          <h1>Edit {campaign.data?.name ?? "campaign"}</h1>
        </div>
        <p className="meta mono">Brand and start date aren't editable — the day clock has its own switch on the Campaigns page.</p>
      </div>

      {campaign.error && <ErrorBox message={campaign.error} onRetry={campaign.reload} />}
      {!form && !campaign.error && <Loading />}
      {error && (
        <div className="vwarn" role="alert" style={{ margin: 0 }}>
          <b>FIX</b>
          <span>{error}</span>
        </div>
      )}

      {form && (
        <form
          className="panel"
          style={{ flexDirection: "column", alignItems: "stretch", gap: 16 }}
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <div className="fieldgrid">
            <Field label="Campaign name">
              <input type="text" required value={form.name} onChange={(e) => set({ name: e.target.value })} />
            </Field>
            <Field label="Duration (days)">
              <input type="number" min={1} required value={form.duration_days} onChange={(e) => set({ duration_days: e.target.value })} />
            </Field>
            <Field label="Disclosure (accepted tokens, '|'-separated)">
              <input type="text" required value={form.required_disclosure} onChange={(e) => set({ required_disclosure: e.target.value })} />
            </Field>
            <Field label="Brand tag">
              <input type="text" value={form.required_tag} onChange={(e) => set({ required_tag: e.target.value })} />
            </Field>
            <Field label="Campaign hashtag">
              <input type="text" value={form.required_hashtag} onChange={(e) => set({ required_hashtag: e.target.value })} />
            </Field>
            <Field label="Metrics source">
              <select value={form.metrics_provider} onChange={(e) => set({ metrics_provider: e.target.value as MetricsProvider })}>
                {campaign.data?.metrics_provider === "seeded" && <option value="seeded">Seeded demo data</option>}
                <option value="manual">Manual entry</option>
                <option value="instagram">Instagram (Meta API)</option>
              </select>
            </Field>
            <Field label="Stories">
              <label className="muted" style={{ textTransform: "none", letterSpacing: 0, font: "14px var(--sans)", display: "flex", gap: 8, alignItems: "center" }}>
                <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={form.requires_link_sticker} onChange={(e) => set({ requires_link_sticker: e.target.checked })} />
                Require link sticker (campaign default)
              </label>
            </Field>
            <Field label="Banned claims (one per line)" wide>
              <textarea style={{ minHeight: 70 }} value={form.banned_claims_text} onChange={(e) => set({ banned_claims_text: e.target.value })} />
            </Field>
          </div>
          {form.metrics_provider === "instagram" && (
            <div className="contractnote" style={{ margin: 0 }}>
              <b>IG</b>
              <span>
                Posts will be pulled from Instagram when you press Sync on the Campaigns page — paid-partnership posts with
                reach, other public posts without it. Check the <Link to="/instagram">Instagram</Link> screen for whether the
                connection is set up.
              </span>
            </div>
          )}
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <Link className="btn ghost" to="/campaigns">
              Cancel
            </Link>
            <button className="btn approve" type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save changes"}
            </button>
          </div>
        </form>
      )}
    </main>
  );
}
