export type Status = "Act now" | "Needs a look" | "OK";

export interface AppState {
  current_day: number;
  ai_enabled: boolean;
  duration_days: number;
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
