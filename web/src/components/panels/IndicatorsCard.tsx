import { useQuery } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { api } from "../../lib/api";
import type { DailyIndicator } from "../../lib/types";
import { Card } from "./Card";

interface MinerviniCondDetail {
  passed: boolean | null;
  description: string;
  values: Record<string, number | null>;
  margin_pct: number | null;
}

interface MinerviniDetailResponse {
  ticker: string;
  date: string;
  detail: Record<`c${1 | 2 | 3 | 4 | 5 | 6 | 7 | 8}`, MinerviniCondDetail>;
}

interface Props {
  ticker: string;
}

const COND_KEYS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"] as const;

function startStr(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  return d.toISOString().slice(0, 10);
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

export function IndicatorsCard({ ticker }: Props) {
  const minQ = useQuery<MinerviniDetailResponse>({
    queryKey: ["minervini-detail", ticker],
    queryFn: () =>
      api<MinerviniDetailResponse>(`/indicators/minervini-detail/${ticker}`),
    enabled: !!ticker,
    retry: false,
  });
  const dailyQ = useQuery<DailyIndicator[]>({
    queryKey: ["daily-indicator-latest", ticker],
    queryFn: () =>
      api<DailyIndicator[]>(
        `/indicators/daily/${ticker}?start=${startStr(30)}&end=${todayStr()}`,
      ),
    enabled: !!ticker,
  });

  if (minQ.isLoading || dailyQ.isLoading) {
    return <Card title="결정론 지표">불러오는 중…</Card>;
  }
  if (minQ.isError || !minQ.data) {
    return <Card title="결정론 지표">Minervini 데이터 없음</Card>;
  }

  const latestDaily =
    dailyQ.data && dailyQ.data.length > 0
      ? dailyQ.data[dailyQ.data.length - 1]
      : null;

  return (
    <Card title="결정론 지표">
      <div className="space-y-3 text-data">
        <div className="flex items-baseline gap-2">
          <span className="caps text-faint">RS Rating</span>
          <span className="text-display-sm font-bold num">
            {latestDaily?.rs_rating ?? "—"}
          </span>
        </div>
        <div>
          <span className="caps text-faint">Drawdown filter</span>{" "}
          {latestDaily?.drawdown_filter_pass == null ? (
            "—"
          ) : latestDaily.drawdown_filter_pass ? (
            <span className="text-green-700">통과</span>
          ) : (
            <span className="text-red-700">실패</span>
          )}
        </div>
        <div>
          <div className="caps text-faint mb-1">Minervini 8조건</div>
          <ul className="space-y-1">
            {COND_KEYS.map((key) => {
              const cond = minQ.data!.detail[key];
              const v = cond?.passed;
              return (
                <li key={key} className="flex items-center gap-2">
                  {v ? (
                    <Check size={14} className="text-green-600" />
                  ) : (
                    <X size={14} className="text-red-500" />
                  )}
                  <span
                    className={v ? "" : "text-muted"}
                    title={cond?.description ?? ""}
                  >
                    {cond?.description ?? key}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
        <div className="text-faint text-data-xs">기준일: {minQ.data.date}</div>
      </div>
    </Card>
  );
}
