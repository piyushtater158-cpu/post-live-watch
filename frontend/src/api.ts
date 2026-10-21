import type {
  AppState,
  BrandReport,
  CampaignDefaults,
  CampaignEditIn,
  CampaignFieldsIn,
  CampaignFormDefaults,
  CampaignIntakeResponse,
  CampaignRow,
  CampaignSummary,
  ClockMode,
  CreatorResearch,
  InstagramStatus,
  InstagramTest,
  SyncResult,
  IntakeDraft,
  IntakeResponse,
  CreatorProfile,
  CreatorSummary,
  DecisionIn,
  DecisionRow,
  Overview,
  QueueCard,
} from "./types";

// Render's free tier takes ~1 minute to wake from sleep; anything slower than
// this is treated as a cold start and surfaced to the user.
const SLOW_MS = 3000;

let slowCount = 0;
const slowListeners = new Set<(slow: boolean) => void>();

function setSlow(delta: number) {
  slowCount += delta;
  slowListeners.forEach((fn) => fn(slowCount > 0));
}

export function onServerSlow(fn: (slow: boolean) => void): () => void {
  slowListeners.add(fn);
  return () => slowListeners.delete(fn);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let flagged = false;
  const timer = setTimeout(() => {
    flagged = true;
    setSlow(1);
  }, SLOW_MS);
  try {
    const res = await fetch(`/api${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      const detail = Array.isArray(body?.detail)
        ? body.detail.map((e: { message?: string; msg?: string }) => e.message ?? e.msg).join(" · ")
        : body?.detail;
      throw new ApiError(res.status, detail ? String(detail) : `Request failed (${res.status})`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
    if (flagged) setSlow(-1);
  }
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  state: () => request<AppState>("/state"),
  overview: () => request<Overview>("/overview"),
  queue: () => request<{ cards: QueueCard[] }>("/queue"),
  decide: (postId: number, body: DecisionIn) => post<{ cards: QueueCard[] }>(`/flags/${postId}/decide`, body),
  creators: () => request<{ creators: CreatorSummary[] }>("/creators"),
  creator: (id: number) => request<CreatorProfile>(`/creators/${id}`),
  report: () => request<BrandReport>("/report"),
  decisions: () => request<{ rows: DecisionRow[] }>("/decisions"),
  advanceDay: () => post<AppState>("/simulate/advance-day"),
  resetDay: () => post<AppState>("/simulate/reset-day"),
  toggleAi: () => post<AppState>("/settings/ai-toggle"),
  intakeDefaults: () => request<{ campaign: CampaignDefaults }>("/intake"),
  intakeParse: (brief_text: string) => post<IntakeResponse>("/intake/parse", { brief_text }),
  intakeConfirm: (body: { action: "approve" | "edit"; original_draft: IntakeDraft; draft?: unknown }) =>
    post<IntakeResponse>("/intake/confirm", body),
  intakeDismiss: () => post<{ dismissed: true }>("/intake/confirm", { action: "dismiss" }),
  campaigns: () => request<{ campaigns: CampaignSummary[] }>("/campaigns"),
  campaign: (id: number) => request<CampaignRow>(`/campaigns/${id}`),
  campaignDefaults: () => request<CampaignFormDefaults>("/campaign-defaults"),
  selectCampaign: (campaign_id: number) => post<AppState>("/campaigns/select", { campaign_id }),
  setClock: (id: number, mode: ClockMode) => post<AppState>(`/campaigns/${id}/clock`, { mode }),
  editCampaign: (id: number, body: CampaignEditIn) => post<CampaignRow>(`/campaigns/${id}/edit`, body),
  syncCampaign: (id: number) => post<SyncResult>(`/campaigns/${id}/sync`),
  campaignParse: (campaign: CampaignFieldsIn, creators_brief_text: string) =>
    post<CampaignIntakeResponse>("/campaigns/parse", { campaign, creators_brief_text }),
  campaignConfirm: (original_draft: unknown) =>
    post<CampaignIntakeResponse>("/campaigns/confirm", { action: "approve", original_draft }),
  instagramStatus: () => request<InstagramStatus>("/integrations/instagram"),
  instagramTest: () => post<InstagramTest>("/integrations/instagram/test"),
  researchCreator: (handle: string) => request<CreatorResearch>(`/creators/research/${encodeURIComponent(handle)}`),
};
