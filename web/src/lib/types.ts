export interface Stock {
  ticker: string;
  name: string;
  market: string;
  sector: string | null;
  delisted_at: string | null;
}

export interface DailyIndicator {
  date: string;
  adj_close: number;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  avg_volume_50d: number | null;
  sma_10: number | null;
  sma_21: number | null;
  sma_50: number | null;
  sma_150: number | null;
  sma_200: number | null;
  w52_high: number | null;
  w52_low: number | null;
  rs_line: number | null;
  rs_rating: number | null;
  minervini_pass: boolean | null;
  volume_ratio_50d: number | null;
  pocket_pivot_flag: boolean | null;
  distribution_day_flag: boolean | null;
}

export interface MinerviniPassed {
  ticker: string;
  name: string;
  sector: string | null;
  rs_rating: number;
  adj_close: number;
  volume_ratio_50d: number | null;
  pocket_pivot_flag: boolean | null;
}

export interface SectorHeatmap {
  sector: string;
  stock_count: number;
  avg_rs_rating: number | null;
  minervini_pass_count: number;
  minervini_pass_rate: number;
  avg_return_pct: number | null;
}

export interface SectorTimeseriesPoint {
  date: string;
  value: number;
}

export interface SectorTimeseries {
  sector: string;
  points: SectorTimeseriesPoint[];
}

export interface SectorTimeseriesResponse {
  lookback_days: number;
  series: SectorTimeseries[];
}

export interface WeeklyIndicator {
  date: string;
  adj_close: number;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  sma_10w: number | null;
  sma_30w: number | null;
  sma_40w: number | null;
  w52_high: number | null;
  w52_low: number | null;
  rs_line: number | null;
  rs_rating: number | null;
  minervini_pass: boolean | null;
}

export interface MarketContext {
  date: string;
  index_code: string;
  current_status: string;
  distribution_day_count_last_25_sessions: number;
  last_follow_through_day: string | null;
  days_since_follow_through: number | null;
  pct_stocks_above_200d_ma: number | null;
}

export interface PipelineRun {
  id: number;
  pipeline: string;
  mode: string;
  status: string;
  rows_affected: number | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface Signal {
  symbol: string;
  name: string | null;
  sector: string | null;
  market: string | null;
  signal_at: string;
  entry_mode: string | null;
  trigger_price: number | null;
  entry_price: number;
  stop_loss: number;
  stop_loss_pct_from_pivot: number | null;
  stop_loss_pct_from_current_price: number | null;
  expected_target_price: number | null;
  expected_target_pct: number | null;
  risk_reward_ratio: number | null;
  position_size_pct: number | null;
  known_warnings: string[];
  notes: string | null;
}

export interface PipelineMode {
  id: string;
  label: string;
  args: string[];
  is_heavy: boolean;
}

export interface PipelineSpec {
  id: string;
  group: string;
  label: string;
  description: string;
  module: string;
  pipeline_db_name: string;
  modes: PipelineMode[];
  default_cron: string;
  schedule_label: string;
}

export interface PipelineSummary {
  pipeline_id: string;
  group: string;
  label: string;
  description: string;
  module: string;
  cron_expression: string;
  schedule_label: string;
  last_run: {
    id: number;
    status: string;
    rows_affected: number | null;
    error: string | null;
    started_at: string | null;
    finished_at: string | null;
    duration_seconds: number | null;
  } | null;
  next_scheduled: string | null;
  modes: PipelineMode[];
}

export interface RunSummaryResponse {
  pipelines: PipelineSummary[];
}

export interface CronStatus {
  registered: boolean;
  lines: string[];
  default_lines: string[];
  marker_begin: string;
  marker_end: string;
}

export interface CronPreview {
  action: "register" | "unregister";
  current_lines: string[];
  new_lines: string[];
  diff: string[];
  new_crontab_preview: string;
}

export interface RunResponse {
  pipeline_id: string;
  mode_id: string;
  pid: number;
  command: string;
}

export interface RunConflict {
  reason: string;
  existing_run_id: number | null;
  existing_run_summary: Record<string, unknown> | null;
  message: string;
}

export interface PipelineRef {
  id: string;
  label: string;
}

export interface PipelineRecentRun {
  id: number;
  mode: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  rows_affected: number | null;
  duration_seconds: number | null;
  error: string | null;
}

export interface PipelineDetail {
  id: string;
  group: string;
  label: string;
  description: string;
  long_description: string;
  module: string;
  schedule_label: string;
  default_cron: string;
  inputs: string[];
  outputs: string[];
  depends_on: PipelineRef[];
  consumed_by: PipelineRef[];
  modes: PipelineMode[];
  recent_runs: PipelineRecentRun[];
}
