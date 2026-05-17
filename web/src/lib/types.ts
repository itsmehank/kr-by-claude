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
