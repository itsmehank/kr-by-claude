import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { PerformanceSignal } from "../../lib/types";
import { Card } from "./Card";

interface Props {
  ticker: string;
}

const PERIODS = [
  { label: "1주", returnKey: "return_1w_pct", marketKey: "market_return_1w_pct" },
  { label: "2주", returnKey: "return_2w_pct", marketKey: "market_return_2w_pct" },
  { label: "4주", returnKey: "return_4w_pct", marketKey: "market_return_4w_pct" },
  { label: "8주", returnKey: "return_8w_pct", marketKey: "market_return_8w_pct" },
] as const satisfies ReadonlyArray<{
  label: string;
  returnKey: keyof PerformanceSignal;
  marketKey: keyof PerformanceSignal;
}>;

export function PerformanceCard({ ticker }: Props) {
  const q = useQuery<PerformanceSignal[]>({
    queryKey: ["performance-card", ticker],
    queryFn: () =>
      api<PerformanceSignal[]>(`/performance/signals?ticker=${ticker}&limit=1`),
    enabled: !!ticker,
  });

  if (q.isLoading) return <Card title="성과">불러오는 중…</Card>;
  if (q.isError || !q.data || q.data.length === 0) {
    return <Card title="성과">성과 기록 없음</Card>;
  }
  const p = q.data[0];

  return (
    <Card title="성과">
      <div className="space-y-2 text-data">
        <div className="text-faint text-data-xs">
          진입 {p.signal_at.slice(0, 10)} @ {p.entry_price.toLocaleString()}원
        </div>
        <table className="w-full text-data-xs">
          <thead className="text-faint">
            <tr>
              <th className="text-left">기간</th>
              <th className="text-right">종목</th>
              <th className="text-right">시장</th>
              <th className="text-right">α</th>
            </tr>
          </thead>
          <tbody>
            {PERIODS.map(({ label, returnKey, marketKey }) => {
              const r = p[returnKey] as number | null;
              const m = p[marketKey] as number | null;
              const alpha = r != null && m != null ? r - m : null;
              return (
                <tr key={returnKey} className="border-t border-hairline">
                  <td className="py-1">{label}</td>
                  <td
                    className={`py-1 text-right num ${
                      r != null && r >= 0
                        ? "text-green-700"
                        : r != null
                          ? "text-red-700"
                          : ""
                    }`}
                  >
                    {r != null ? `${r >= 0 ? "+" : ""}${r.toFixed(2)}%` : "—"}
                  </td>
                  <td className="py-1 text-right num text-muted">
                    {m != null ? `${m >= 0 ? "+" : ""}${m.toFixed(2)}%` : "—"}
                  </td>
                  <td
                    className={`py-1 text-right num ${
                      alpha != null && alpha >= 0
                        ? "text-green-700"
                        : alpha != null
                          ? "text-red-700"
                          : ""
                    }`}
                  >
                    {alpha != null
                      ? `${alpha >= 0 ? "+" : ""}${alpha.toFixed(2)}`
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
