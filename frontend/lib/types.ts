/** Shapes mirroring the FastAPI response models in `app/schemas/api.py`. */

export type Severity = "noise" | "low" | "medium" | "high" | "critical";

export type Category =
  | "pricing"
  | "features"
  | "product"
  | "hiring"
  | "integrations"
  | "messaging"
  | "other";

export interface TrackedURL {
  id: number;
  competitor_id: number;
  url: string;
  label: string | null;
  page_type: string;
  render_js: boolean;
  active: boolean;
  last_checked: string | null;
  last_status: string | null;
  last_error: string | null;
  created_at: string;
}

export interface Competitor {
  id: number;
  name: string;
  website_url: string;
  description: string | null;
  tracking_frequency: string;
  active: boolean;
  created_at: string;
  updated_at: string;
  tracked_urls: TrackedURL[];
  /** True for the seeded fictional demo companies. */
  is_demo: boolean;
  tracked_url_count: number;
  last_scan: string | null;
  changes_this_week: number;
  high_impact_this_week: number;
  total_changes: number;
}

export interface Intelligence {
  id: number;
  change_id: number;
  competitor_id: number;
  title: string;
  category: Category;
  summary: string;
  before: string | null;
  after: string | null;
  business_impact: string;
  recommended_action: string | null;
  relevance_score: number;
  severity: Severity;
  confidence: number;
  analysed_by: string;
  /** ok | skipped | failed | rate_limited | budget */
  llm_status: string;
  llm_model: string | null;
  tracked_url_id: number | null;
  snapshot_id: number | null;
  previous_snapshot_id: number | null;
  source_url: string;
  created_at: string;
}

export interface IntelligenceItem extends Intelligence {
  competitor_name: string;
  change_type: string;
  location: string;
}

export interface DiffSegment {
  op: "equal" | "insert" | "delete";
  before: string;
  after: string;
}

export interface Change {
  id: number;
  snapshot_id: number;
  previous_snapshot_id: number | null;
  competitor_id: number;
  competitor_name: string;
  change_type: string;
  category: Category;
  location: string;
  before: string | null;
  after: string | null;
  magnitude: number;
  is_noise: boolean;
  noise_reason: string | null;
  relevance_score: number;
  severity: Severity;
  classifier_confidence: number;
  detected_at: string;
  source_url: string;
  intelligence: Intelligence | null;
  diff_segments: DiffSegment[];
}

export interface DashboardStats {
  tracked_competitors: number;
  active_competitors: number;
  tracked_urls: number;
  total_snapshots: number;
  raw_changes: number;
  noise_changes: number;
  meaningful_changes: number;
  high_impact_changes: number;
  noise_reduction: number;
  changes_this_week: number;
  high_impact_this_week: number;
  last_scan: string | null;
  llm_provider: string;
  llm_model: string;
  llm_is_llm: boolean;
  llm_label: string;
  llm_configured: boolean;
  llm_last_status: string | null;
  demo_mode: boolean;
}

export interface CategoryCount {
  category: string;
  count: number;
}

export interface TimelinePoint {
  date: string;
  raw_changes: number;
  meaningful_changes: number;
  high_impact_changes: number;
}

export interface NoiseReasonCount {
  reason: string;
  count: number;
}

export interface Analytics {
  stats: DashboardStats;
  categories: CategoryCount[];
  timeline: TimelinePoint[];
  noise_reasons: NoiseReasonCount[];
  severity_distribution: CategoryCount[];
  top_competitors: {
    competitor_id: number;
    name: string;
    meaningful_changes: number;
    high_impact_changes: number;
  }[];
}

export interface ScanStats {
  raw_changes: number;
  noise_changes: number;
  meaningful_changes: number;
  high_impact_changes: number;
  noise_reduction: number;
}

export interface ScanURLResult {
  url: string;
  status: string;
  message: string | null;
  stats: ScanStats;
}

export interface ScanResponse {
  scan_run_id: number | null;
  competitor_id: number;
  competitor_name: string;
  status: string;
  urls_scanned: number;
  urls_failed: number;
  stats: ScanStats;
  results: ScanURLResult[];
  errors: string[];
}

export interface Digest {
  id: number;
  period_start: string;
  period_end: string;
  title: string;
  content: string;
  headline: string | null;
  raw_changes: number;
  noise_changes: number;
  meaningful_changes: number;
  high_impact_changes: number;
  noise_reduction: number;
  generated_by: string;
  created_at: string;
}

export interface Evaluation {
  id: number;
  kind: string;
  target_url: string;
  snapshot_a: string | null;
  snapshot_b: string | null;
  pages_evaluated: number;
  raw_changes: number;
  noise_changes: number;
  meaningful_changes: number;
  high_impact_changes: number;
  noise_reduction: number;
  category_breakdown: string;
  report_path: string | null;
  status: string;
  error: string | null;
  created_at: string;
}

export interface CompetitorCreatePayload {
  name: string;
  website_url: string;
  description?: string;
  tracking_frequency?: string;
  tracked_urls?: { url: string; label?: string }[];
}
