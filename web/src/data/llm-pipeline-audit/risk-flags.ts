// Risk Flags 13개 (spec audit §6) — analyze_chart_v3.md §6 line 176-188 표 그대로

export interface RiskFlag {
  id: string;
  definition: string;
}

export const RISK_FLAGS: RiskFlag[] = [
  {
    id: "climax_run",
    definition:
      "Price up ≥25% in 1–3 weeks; largest weekly price spread and heaviest volume of current move (Minervini Stage 3 warning)",
  },
  {
    id: "late_stage_base",
    definition: "3rd or later base in current Stage 2 advance",
  },
  {
    id: "extended_from_ma",
    definition: "Price > SMA-50 by more than 15%",
  },
  {
    id: "faulty_pivot",
    definition: "Pivot is at a prior resistance level that has failed 2+ times",
  },
  {
    id: "low_volume_breakout",
    definition:
      "Breakout volume < 1.4× the 50-day average (O'Neil: 40-50% above normal at minimum)",
  },
  {
    id: "narrow_base",
    definition: "Base duration below pattern-specific minimum (see §5)",
  },
  {
    id: "wide_and_loose",
    definition:
      "Weekly price swings > 10–15% during base; erratic, difficult to trade (O'Neil: 1.5–2.5× general market correction)",
  },
  {
    id: "thin_liquidity_us_only",
    definition:
      "US individual stock only: avg daily dollar volume (volume_ma20 × current_price) < $5M",
  },
  {
    id: "prior_uptrend_insufficient",
    definition:
      "Less than 20% run from prior base before current consolidation (flat_base requirement)",
  },
  {
    id: "volume_contraction_on_advance",
    definition: "Price advancing on declining volume — distribution warning or weak demand",
  },
  {
    id: "reverse_split_distortion",
    definition: "Reverse split within past ~12 weeks confirmed in price_data_notes",
  },
  {
    id: "unfavorable_market_context",
    definition:
      "Market direction is downtrend/correction/unconfirmed rally_attempt, OR distribution day count ≥ 5 over last 25 sessions",
  },
  {
    id: "etf_methodology_mismatch",
    definition: "Instrument is an ETF/fund (handled in Pre-Check)",
  },
];

export interface AutoRule {
  flag: string;
  trigger: string;
}

export const AUTO_RULES: AutoRule[] = [
  {
    flag: "reverse_split_distortion",
    trigger: "corporate_actions 에 최근 12주 내 reverse split 있음 (prompt line 45)",
  },
  {
    flag: "unfavorable_market_context",
    trigger:
      "market_context.current_status == 'downtrend' | 'correction' (line 75) → 분류 강제 watch",
  },
  {
    flag: "unfavorable_market_context",
    trigger:
      "current_status == 'rally_attempt' AND follow-through day 없음 (line 76)",
  },
  {
    flag: "unfavorable_market_context",
    trigger:
      "distribution_day_count_last_25_sessions ≥ 5 (line 77) → confidence -0.15, prefer watch",
  },
  {
    flag: "volume_contraction_on_advance",
    trigger: "종목 자체 최근 25일 distribution day ≥ 4 (line 201)",
  },
];

export const KR_NOTE =
  "thin_liquidity_us_only 는 KR 종목 (KOSPI/KOSDAQ) 에 적용 안 됨 (prompt line 194).";
