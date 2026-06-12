import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Signal } from "../../lib/types";
import { Card } from "./Card";

interface Props {
  ticker: string;
}

export function EntrySignalCard({ ticker }: Props) {
  const q = useQuery<Signal[]>({
    queryKey: ["entry-signal-card", ticker],
    queryFn: () => api<Signal[]>(`/signals?ticker=${ticker}&days=60`),
    enabled: !!ticker,
  });

  if (q.isLoading) return <Card title="매수 시그널">불러오는 중…</Card>;
  if (q.isError || !q.data || q.data.length === 0) {
    return (
      <Card title="매수 시그널">
        <div className="text-muted">아직 매수 시그널이 발생하지 않았습니다.</div>
        <div className="text-faint text-data-xs mt-2">
          트리거 이력 표에서 평가 과정을 확인하세요.
        </div>
      </Card>
    );
  }
  const s = q.data[0];

  return (
    <Card title="매수 시그널">
      <div className="space-y-2 text-data">
        <div className="text-faint text-data-xs">
          {s.signal_at.slice(0, 19).replace("T", " ")}
        </div>
        {s.entry_mode && (
          <div>
            <span className="caps text-faint">진입 모드</span> {s.entry_mode}
          </div>
        )}
        <div>
          <span className="caps text-faint">진입가</span>{" "}
          <span className="num font-semibold">
            {s.entry_price != null ? `${s.entry_price.toLocaleString()}원` : "—"}
          </span>
        </div>
        <div>
          <span className="caps text-faint">손절가</span>{" "}
          <span className="num">{s.stop_loss != null ? `${s.stop_loss.toLocaleString()}원` : "—"}</span>
          {s.stop_loss_pct_from_current_price != null && (
            <span className="text-faint">
              {" "}
              ({s.stop_loss_pct_from_current_price.toFixed(2)}%)
            </span>
          )}
        </div>
        {s.expected_target_price != null && (
          <div>
            <span className="caps text-faint">목표가</span>{" "}
            <span className="num">
              {s.expected_target_price.toLocaleString()}원
            </span>
            {s.expected_target_pct != null && (
              <span className="text-faint">
                {" "}
                ({s.expected_target_pct > 0 ? "+" : ""}{s.expected_target_pct.toFixed(2)}%)
              </span>
            )}
          </div>
        )}
        {s.risk_reward_ratio != null && (
          <div>
            <span className="caps text-faint">R/R</span>{" "}
            <span className="num">{s.risk_reward_ratio.toFixed(2)}</span>
          </div>
        )}
        {s.known_warnings.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {s.known_warnings.map((w) => (
              <span
                key={w}
                className="px-2 py-0.5 rounded bg-yellow-50 text-yellow-800 text-data-xs"
              >
                {w}
              </span>
            ))}
          </div>
        )}
        {s.notes && <div className="text-muted text-data-xs">{s.notes}</div>}
      </div>
    </Card>
  );
}
