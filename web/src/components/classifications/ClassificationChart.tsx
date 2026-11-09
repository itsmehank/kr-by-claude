import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Classification, DailyIndicator } from "../../lib/types";
import { nDaysAgoKstISO, todayKstISO } from "../../lib/dates";
import { PriceChart } from "../charts/PriceChart";
import { dailyToBar } from "../charts/barAdapters";

const CHART_DAYS = 180; // 6개월 일봉

/** 분류 상세 영역의 6개월 일봉 차트 — pivot 선 + 베이스 상·하단 선(#275) */
export function ClassificationChart({ row }: { row: Classification }) {
  const start = nDaysAgoKstISO(CHART_DAYS);
  const end = todayKstISO();
  const q = useQuery<DailyIndicator[]>({
    queryKey: ["daily-indicators", row.symbol, "6M-classifications", start, end],
    queryFn: () => api<DailyIndicator[]>(`/indicators/daily/${row.symbol}?start=${start}&end=${end}`),
    staleTime: 5 * 60 * 1000,
  });
  const bars = useMemo(() => (q.data ?? []).map(dailyToBar), [q.data]);
  const baseRange = useMemo(
    () =>
      row.base_high != null && row.base_low != null
        ? { high: row.base_high, low: row.base_low, start: row.base_start_date ?? null }
        : null,
    [row.base_high, row.base_low, row.base_start_date],
  );

  if (q.isLoading) return <div className="h-[380px] flex items-center justify-center text-data-xs text-faint">차트 로딩 중…</div>;
  if (q.isError) return <div className="h-[380px] flex items-center justify-center text-data-xs text-danger">차트 데이터를 불러오지 못했습니다.</div>;
  if (bars.length === 0) return <div className="h-[380px] flex items-center justify-center text-data-xs text-faint">최근 6개월 일봉 데이터가 없습니다.</div>;

  return (
    <div>
      <PriceChart
        data={bars}
        height={380}
        showSMAMid={false}
        pivotPrice={row.pivot_price}
        baseRange={baseRange}
        showTriggerMarkers={false}
      />
      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1 text-data-xs text-faint">
        <span>6개월 일봉</span>
        <span><span className="text-[#ea580c]">━</span> 50일선</span>
        <span><span className="text-[#dc2626]">━</span> 200일선</span>
        {row.pivot_price != null && <span><span className="text-[#2563eb]">┅</span> pivot</span>}
        {baseRange && <span><span className="text-[#7c3aed]">┈</span> 베이스 상·하단{row.base_start_date ? ` (${row.base_start_date}~)` : ""}</span>}
      </div>
    </div>
  );
}
