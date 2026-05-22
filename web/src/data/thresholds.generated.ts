/* eslint-disable */
// AUTO-GENERATED — DO NOT EDIT BY HAND.
// Source: kr_pipeline/common/thresholds.py
// Regenerate: `uv run python scripts/export_thresholds.py`

export const GATE_BREAKOUT_VOL_MULT: number = 1.0;
export const GATE_PROMOTION_PRICE_RATIO: number = 0.95;
export const RECENT_CLASSIFICATION_WINDOW_DAYS: number = 7;
export const C3_SMA200_LOOKBACK_DAYS: number = 22;
export const C6_W52LOW_MULT: number = 1.25;
export const C7_W52HIGH_MULT: number = 0.75;
export const C8_RS_RATING_MIN: number = 70;
export const PP_DOWN_VOL_LOOKBACK_DAYS: number = 10;
export const STOCK_DISTRIBUTION_VOL_MULT: number = 1.25;
export const VOLUME_DRY_UP_MULT: number = 0.5;
export const MARKET_DISTRIBUTION_PCT_THRESHOLD: number = -0.2;
export const MARKET_DISTRIBUTION_LOOKBACK_DAYS: number = 25;
export const FTD_PCT_THRESHOLD: Record<string, number> = { "KOSPI": 1.4, "KOSDAQ": 1.4 };
export const FTD_RALLY_WINDOW_MIN_DAYS: number = 3;
export const FTD_RALLY_WINDOW_MAX_DAYS: number = 15;
export const FTD_LOW_LOOKBACK_DAYS: number = 15;
export const STATUS_CORRECTION_OFF_HIGH_PCT: number = -10.0;
export const STATUS_DOWNTREND_OFF_HIGH_PCT: number = -15.0;
export const STATUS_DIST_COUNT_FOR_FTD_INVALIDATION: number = 6;
export const STATUS_FTD_RECENT_DAYS: number = 90;
export const STATUS_FTD_INVALIDATION_DAYS: number = 10;
