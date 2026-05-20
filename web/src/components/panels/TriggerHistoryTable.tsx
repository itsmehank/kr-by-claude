import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import type { Trigger, TriggerDecision } from "../../lib/types";
import { Card } from "./Card";
import {
  InfoTooltip,
  TRIGGER_TYPE_HELP,
  DECISION_HELP,
  VOLUME_RATIO_HELP,
  PIVOT_DELTA_HELP,
} from "../InfoTooltip";

interface Props {
  ticker: string;
  limit?: number;
}

const DECISION_COLOR: Record<
  TriggerDecision,
  { bg: string; text: string; dot: string }
> = {
  go_now: { bg: "bg-green-100", text: "text-green-800", dot: "bg-green-500" },
  wait: { bg: "bg-yellow-100", text: "text-yellow-800", dot: "bg-yellow-500" },
  abort: { bg: "bg-gray-200", text: "text-gray-700", dot: "bg-gray-500" },
};

export function TriggerHistoryTable({ ticker, limit = 20 }: Props) {
  const q = useQuery<Trigger[]>({
    queryKey: ["trigger-history", ticker, limit],
    queryFn: () => api<Trigger[]>(`/triggers?ticker=${ticker}&limit=${limit}`),
    enabled: !!ticker,
  });

  if (q.isLoading) return <Card title="트리거 평가 이력">불러오는 중…</Card>;
  if (q.isError || !q.data || q.data.length === 0) {
    return <Card title="트리거 평가 이력">트리거 평가 이력이 없습니다.</Card>;
  }

  return (
    <Card title={`트리거 평가 이력 (최근 ${q.data.length}건)`}>
      <table className="w-full text-data">
        <thead className="text-faint">
          <tr>
            <th className="text-left py-1.5">시각</th>
            <th className="text-left py-1.5">
              트리거
              <InfoTooltip>{TRIGGER_TYPE_HELP}</InfoTooltip>
            </th>
            <th className="text-left py-1.5">
              decision
              <InfoTooltip>{DECISION_HELP}</InfoTooltip>
            </th>
            <th className="text-right py-1.5">
              거래량비
              <InfoTooltip>{VOLUME_RATIO_HELP}</InfoTooltip>
            </th>
            <th className="text-right py-1.5">
              pivot대비
              <InfoTooltip>{PIVOT_DELTA_HELP}</InfoTooltip>
            </th>
            <th className="text-left py-1.5">reasoning</th>
          </tr>
        </thead>
        <tbody>
          {q.data.map((t) => {
            const cfg = DECISION_COLOR[t.decision];
            return (
              <tr
                key={`${t.symbol}-${t.evaluated_at}`}
                className="border-t border-hairline"
              >
                <td className="py-1.5 num text-data-xs">
                  {t.evaluated_at.slice(0, 16).replace("T", " ")}
                </td>
                <td className="py-1.5">{t.trigger_type}</td>
                <td className="py-1.5">
                  <span
                    className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded ${cfg.bg} ${cfg.text}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
                    {t.decision}
                  </span>
                </td>
                <td className="py-1.5 text-right num">
                  {t.avg_volume_50d_ratio != null
                    ? `${t.avg_volume_50d_ratio.toFixed(2)}×`
                    : "—"}
                </td>
                <td className="py-1.5 text-right num">
                  {t.pivot_delta_pct != null
                    ? `${t.pivot_delta_pct >= 0 ? "+" : ""}${t.pivot_delta_pct.toFixed(2)}%`
                    : "—"}
                </td>
                <td
                  className="py-1.5 text-muted truncate max-w-md"
                  title={t.reasoning ?? ""}
                >
                  {t.reasoning ?? ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mt-3 text-right">
        <Link
          to={`/triggers?ticker=${ticker}`}
          className="text-data text-accent hover:underline"
        >
          전체 이력 보기 →
        </Link>
      </div>
    </Card>
  );
}
