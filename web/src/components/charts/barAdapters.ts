// API 지표 행 → PriceChartBar 변환(ChartPage 에서 추출 — #275, 분류 페이지 상세 차트와 공유)
import type { DailyIndicator, WeeklyIndicator } from "../../lib/types";
import type { PriceChartBar } from "./PriceChart";

export function dailyToBar(d: DailyIndicator): PriceChartBar {
  return {
    date: d.date,
    open: d.adj_open,
    high: d.adj_high,
    low: d.adj_low,
    close: d.adj_close,
    adj_close: d.adj_close,
    volume: d.adj_volume,
    avg_volume_50d: d.avg_volume_50d,
    sma_short: d.sma_50,
    sma_mid: d.sma_150,
    sma_long: d.sma_200,
    sma_extra: d.sma_10,
    w52_high: d.w52_high,
    w52_low: d.w52_low,
    pocket_pivot_flag: d.pocket_pivot_flag,
    distribution_day_flag: d.distribution_day_flag,
    minervini_pass: d.minervini_pass,
  };
}

export function weeklyToBar(w: WeeklyIndicator): PriceChartBar {
  return {
    date: w.date,
    open: w.adj_open,
    high: w.adj_high,
    low: w.adj_low,
    close: w.adj_close,
    adj_close: w.adj_close,
    volume: w.adj_volume,
    avg_volume_50d: null, // weekly indicators 에는 avg_volume_50d 없음
    sma_short: w.sma_10w,
    sma_mid: w.sma_30w,
    sma_long: w.sma_40w,
    sma_extra: null,
    w52_high: w.w52_high,
    w52_low: w.w52_low,
    pocket_pivot_flag: null,
    distribution_day_flag: null,
    minervini_pass: null,
  };
}
