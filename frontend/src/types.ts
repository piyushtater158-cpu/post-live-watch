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

export interface Reliability {
  score: number;
  on_time_rate: number;
  avg_performance_ratio: number;
  avg_flags_per_campaign: number;
  campaigns_considered: number;
  book_again_hint: string;
  history: HistoryRow[];
}

export interface CampaignRollup extends PostResult {
  delivered: number;
  total_deliverables: number;
}

export interface CreatorSummary {
  id: number;
  handle: string;
  tier: string;
  niche: string;
  reliability: Reliability;
  current_campaign: CampaignRollup | null;
}

export interface Deliverable extends PostResult {
  deliverable_label: string;
}

export interface CreatorProfile {
  creator: { id: number; handle: string; tier: string; niche: string };
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
}

export interface DecisionIn {
  action: "approve" | "edit" | "dismiss";
  message_text: string;
  original_message: string;
  flag_rule_id: number;
}
