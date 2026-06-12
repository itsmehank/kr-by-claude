import { useMemo } from "react";
import { nDaysAgoKstISO, todayKstISO, thisWeekMondayKstISO } from "../lib/dates";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { DailyIndicator, IndexDaily, WeeklyIndicator } from "../lib/types";

interface Props {
  ticker: string;
  market: string | null;
}

const MARKET_INDEX_CODE: Record<string, string> = {
  KOSPI: "1001",
  KOSDAQ: "2001",
};

const nDaysAgoISO = nDaysAgoKstISO;
const todayISO = todayKstISO;
const thisWeekMondayISO = thisWeekMondayKstISO;

function pctChange(curr: number, base: number): number | null {
  if (!base || base === 0) return null;
  return ((curr - base) / base) * 100;
}

function formatPct(p: number | null): string {
  if (p == null) return "—";
  const sign = p >= 0 ? "+" : "";
  return `${sign}${p.toFixed(2)}%`;
}

function pctClass(p: number | null): string {
  if (p == null) return "text-muted";
  return p > 0 ? "text-success" : p < 0 ? "text-danger" : "text-muted";
}

function formatVolume(v: number): string {
  return v.toLocaleString();
}

interface ReturnsRow {
  label: string;
  daysAgo: number; // 1주=5, 1달=22, 3달=63 거래일
}

const RETURN_PERIODS: ReturnsRow[] = [
  { label: "1주", daysAgo: 5 },
  { label: "1달", daysAgo: 22 },
  { label: "3달", daysAgo: 63 },
];

export function ChartMetaBar({ ticker, market }: Props) {
  const indexCode = market ? MARKET_INDEX_CODE[market] ?? null : null;

  const stockQ = useQuery<DailyIndicator[]>({
    queryKey: ["meta-bar-stock", ticker],
    queryFn: () =>
      api<DailyIndicator[]>(
        `/indicators/daily/${ticker}?start=${nDaysAgoISO(180)}&end=${todayISO()}`,
      ),
    enabled: !!ticker,
  });

  const weeklyQ = useQuery<WeeklyIndicator[]>({
    queryKey: ["meta-bar-weekly", ticker],
    queryFn: () =>
      api<WeeklyIndicator[]>(
        `/indicators/weekly/${ticker}?start=${nDaysAgoISO(120)}&end=${todayISO()}`,
      ),
    enabled: !!ticker,
  });

  const indexQ = useQuery<IndexDaily[]>({
    queryKey: ["meta-bar-index", indexCode],
    queryFn: () =>
      api<IndexDaily[]>(
        `/index/daily/${indexCode}?start=${nDaysAgoISO(180)}&end=${todayISO()}`,
      ),
    enabled: !!indexCode,
  });

  const returns = useMemo(() => {
    const sb = stockQ.data ?? [];
    const ib = indexQ.data ?? [];
    return RETURN_PERIODS.map(({ label, daysAgo }) => {
      const stockNow = sb[sb.length - 1]?.adj_close ?? null;
      const stockBase = sb[sb.length - 1 - daysAgo]?.adj_close ?? null;
      const stock = stockNow != null && stockBase != null
        ? pctChange(stockNow, stockBase)
        : null;

      const idxNow = ib[ib.length - 1]?.close ?? null;
      const idxBase = ib[ib.length - 1 - daysAgo]?.close ?? null;
      const idx = idxNow != null && idxBase != null
        ? pctChange(idxNow, idxBase)
        : null;

      return { label, stock, idx };
    });
  }, [stockQ.data, indexQ.data]);

  // 이번주 누적 거래량 + 진행 일수
  const weekVolume = useMemo(() => {
    const sb = stockQ.data ?? [];
    if (sb.length === 0) return { sum: null as number | null, days: 0 };
    const monday = thisWeekMondayISO();
    const week = sb.filter((d) => d.date >= monday && d.adj_volume != null);
    const sum = week.reduce((acc, d) => acc + (d.adj_volume ?? 0), 0);
    return { sum: week.length > 0 ? sum : null, days: week.length };
  }, [stockQ.data]);

  // 주봉 10주 평균 거래량 (가장 최근 유효 값)
  const weeklyAvg = useMemo<number | null>(() => {
    const wb = weeklyQ.data ?? [];
    for (let i = wb.length - 1; i >= 0; i--) {
      const v = wb[i].avg_volume_10w;
      if (v != null) return v;
    }
    return null;
  }, [weeklyQ.data]);

  // 진행도: 이번주 누적 / 주간 평균 × 100
  const weekProgress = useMemo<number | null>(() => {
    if (!weekVolume.sum || !weeklyAvg) return null;
    return (weekVolume.sum / weeklyAvg) * 100;
  }, [weekVolume.sum, weeklyAvg]);

  const loading =
    stockQ.isLoading || weeklyQ.isLoading || (!!indexCode && indexQ.isLoading);
  const error = stockQ.isError;

  return (
    <div className="bento p-4 mb-3">
      {loading ? (
        <div className="text-muted">불러오는 중…</div>
      ) : error ? (
        <div className="text-muted">정보를 불러오지 못했습니다</div>
      ) : (
        <>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-data">
            {returns.map(({ label, stock, idx }) => (
              <span key={label} className="inline-flex items-baseline gap-1.5">
                <span className="caps text-faint">{label}</span>
                <span className={`num font-semibold ${pctClass(stock)}`}>
                  {formatPct(stock)}
                </span>
                {indexCode && (
                  <span className={`num text-data-xs ${pctClass(idx)}`}>
                    (시장 {formatPct(idx)})
                  </span>
                )}
              </span>
            ))}
          </div>

          <div className="mt-1 text-data text-muted">
            <span className="caps text-faint">이번주 누적</span>{" "}
            <span className="num text-ink">
              {weekVolume.sum != null ? formatVolume(weekVolume.sum) : "—"}
            </span>{" "}
            {weekVolume.days > 0 && (
              <span className="text-faint">({weekVolume.days}/5일)</span>
            )}
            {" / "}
            <span className="caps text-faint">주간 평균 (10주)</span>{" "}
            <span className="num text-ink">
              {weeklyAvg != null ? formatVolume(weeklyAvg) : "—"}
            </span>
            {weekProgress != null && (
              <span className={`num ml-1.5 ${pctClass(weekProgress - 100)}`}>
                (진행도 {weekProgress.toFixed(0)}%)
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
