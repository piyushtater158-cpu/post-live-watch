export type Status = "Act now" | "Needs a look" | "OK";

export type ClockMode = "live" | "simulated";
export type MetricsProvider = "seeded" | "manual" | "instagram";

export interface CampaignSummary {
  id: number;
  name: string;
  brand_name: string;
  duration_days: number;
  current_day: number;
  clock_mode: ClockMode;
  status: string;
  metrics_provider: MetricsProvider;
}

/** campaign_id is null only when no campaign exists yet. */
export interface AppState {
  campaign_id: number | null;
  campaign_name: string | null;
  brand_name: string | null;
  current_day: number;
  ai_enabled: boolean;
  duration_days: number;
  clock_mode: ClockMode;
  campaigns: CampaignSummary[];
}

/** A campaigns table row, as GET /api/campaigns/{id} returns it. */
export interface CampaignRow {
  id: number;
  brand_id: number;
  name: string;
  start_date: string;
  duration_days: number;
  required_disclosure: string;
  required_tag: string;
  required_hashtag: string;
  requires_link_sticker: number;
  banned_claims: string | null;
  metrics_provider: MetricsProvider;
}

export interface CampaignEditIn {
  name: string;
  required_disclosure: string;
  required_tag: string;
  required_hashtag: string;
  requires_link_sticker: boolean;
  duration_days: number;
  banned_claims: string[];
  metrics_provider: MetricsProvider;
}

export interface CampaignFormDefaults {
  brands: { id: number; name: string; product: string }[];
  default_duration_days: number;
  max_duration_days: number;
  default_required_disclosure: string;
}

export interface CampaignFieldsIn {
  name: string;
  existing_brand_id: number | null;
  brand_name: string;
  product: string;
  duration_days: number | null;
  days_running: number | null;
  required_disclosure: string;
  required_tag: string;
  required_hashtag: string;
  requires_link_sticker: boolean;
  banned_claims: string[];
}

export interface CampaignDraft {
  source: string;
  brief_text: string;
  campaign: CampaignFieldsIn & { start_date: string };
  creators: (Omit<IntakeDraft, "source" | "brief_text"> & { source: string; brief_text: string })[];
  warnings: FieldMessage[];
}

export interface CampaignIntakeResponse {
  draft: CampaignDraft;
  blocking_errors: FieldMessage[];
  result: { campaign_id: number; brand_id: number; creators: { creator_id: number }[] } | null;
}

export interface SyncResult {
  campaign_id: number;
  provider: string;
  status: "ok" | "partial" | "error" | "not_configured" | "not_applicable";
  posts_attempted: number;
  posts_updated: number;
  errors: ({ message: string; creator_handle?: string; ig_media_id?: string } | string)[];
}

export interface FetchRun extends Omit<SyncResult, "campaign_id"> {
  id: number;
  campaign_id: number;
  campaign_name: string;
  started_at: string;
  finished_at: string | null;
}

export interface InstagramStatus {
  configured: boolean;
  missing_env: string[];
  required_env: string[];
  graph_version: string;
  instagram_campaigns: CampaignSummary[];
  recent_runs: FetchRun[];
}

export interface InstagramTest {
  ok: boolean;
  error: string | null;
  account: { ig_business_id: string; username: string; name: string | null; followers: number | null; media_count: number | null } | null;
}

export interface CreatorResearch {
  handle: string;
  followers: number;
  media_count: number | null;
  avg_engagement_rate: number | null;
  recent_captions: string[];
}

export interface ContractNote {
  requirement: string;
  note: string;
}

export interface Flag {
  rule_id: number;
  rule_name: string;
  severity: number;
  reason: string;
  ai_note?: string | null;
}

export interface PostResult {
  post_id: number;
  creator_id: number;
  handle: string;
  format: string;
  status: Status;
  max_severity: number;
  reason: string;
  flags: Flag[];
  opportunities: Flag[];
  deal_type: string;
  min_reach: number | null;
  contract_notes: ContractNote[];
}

export interface Overview {
  current_day: number;
  duration_days: number;
  posts_live: number;
  total_due: number;
  total_reach: number;
  total_promised: number;
  guaranteed_count: number;
  posts_live_pct: number;
  by_status: Record<Status, number>;
  opportunities: number;
  rows: PostResult[];
}

export interface QueueCard extends PostResult {
  niche: string;
  suggested_message: string | null;
  opportunity_note: string | null;
  primary_rule_id: number | null;
  default_message: string | null;
}

export interface HistoryRow {
  month: string;
  campaign_name: string;
  delivered_on_time: boolean;
  performance_ratio: number;
  flags_count: number;
  fix_speed_days: number | null;
  competitor_conflict: boolean;
  outcome: string;
}

/** All numeric fields are null for a creator with no history and nothing due yet. */
export interface Reliability {
  score: number | null;
  on_time_rate: number | null;
  avg_performance_ratio: number | null;
  avg_flags_per_campaign: number | null;
  campaigns_considered: number;
  book_again_hint: string;
  history: HistoryRow[];
}

export interface CampaignRollup extends PostResult {
  delivered: number;
  total_deliverables: number;
}

export type MetricsSource = "estimated" | "am_entered" | null;

export interface CreatorSummary {
  id: number;
  handle: string;
  tier: string;
  niche: string;
  metrics_source: MetricsSource;
  reliability: Reliability;
  current_campaign: CampaignRollup | null;
}

export interface Deliverable extends PostResult {
  deliverable_label: string;
}

export interface CreatorProfile {
  creator: { id: number; handle: string; tier: string; niche: string; avg_reach: number; metrics_source: MetricsSource };
  reliability: Reliability;
  current_campaign: CampaignRollup | null;
  current_deliverables: Deliverable[];
}

export interface BrandReport {
  overview: Overview;
  highlights: string[];
  issues: string[];
  text: string;
}

export interface DecisionRow {
  id: number;
  post_id: number;
  created_at: string;
  handle: string;
  rule_name: string | null;
  action: "approve" | "edit" | "dismiss";
  message_text: string | null;
  source: "flag" | "intake" | null;
}

export interface CampaignDefaults {
  name: string;
  required_tag: string;
  required_hashtag: string;
  required_disclosure: string;
  requires_link_sticker: number;
  duration_days: number;
}

export type DealType = "paid" | "barter" | "affiliate" | "paid_plus_bonus";
export type Format = "reel" | "carousel" | "story";
export type Waivable = "required_tag" | "required_hashtag" | "requires_link_sticker";

export interface DraftDeliverable {
  format: Format;
  deal_type: DealType;
  fee: number | null;
  barter_value: number | null;
  bonus_threshold: number | null;
  bonus_amount: number | null;
  min_reach: number | null;
  min_reach_explicitly_none: boolean;
  due_day: number;
  required_tag: string | null; // null = inherit, "" = waived
  required_hashtag: string | null;
  required_disclosure: null;
  requires_link_sticker: boolean | null;
  waived_notes: Partial<Record<Waivable, string>>;
  preview_notes?: ContractNote[];
}

export interface DraftCreator {
  handle: string;
  existing_creator_id: number | null;
  existing_suggestions: { creator_id: number; handle: string; why: string }[];
  followers: number;
  tier: "mid" | "micro";
  niche: string;
  avg_reach: number;
  avg_engagement_rate: number;
  metrics_source: string;
}

export interface FieldMessage {
  field: string;
  message: string;
  blocking?: boolean;
}

export interface IntakeDraft {
  source: "ai" | "template";
  brief_text: string;
  creator: DraftCreator;
  deliverables: DraftDeliverable[];
  warnings: FieldMessage[];
}

export interface IntakeResponse {
  draft: IntakeDraft;
  blocking_errors: FieldMessage[];
  result: { creator_id: number; created_creator: boolean; deliverable_ids: number[]; post_ids: number[] } | null;
  package: { current_campaign: CampaignRollup | null; current_deliverables: Deliverable[] } | null;
}

export interface DecisionIn {
  action: "approve" | "edit" | "dismiss";
  message_text: string;
  original_message: string;
  flag_rule_id: number;
}
