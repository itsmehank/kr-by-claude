import { useQuery } from "@tanstack/react-query";
import { Briefcase, AlertTriangle } from "lucide-react";
import { api } from "../lib/api";
import { Skeleton } from "../components/ui/Skeleton";

// (#47) 보유 포지션 + 일일 손절 평가 — 수동 기록 모델 (등록/종료는 CLI:
// python -m kr_pipeline.trade_management --add/--close-id)

interface LastEval {
  eval_date: string;
  close: number | null;
  sma_50: number | null;
  effective_stop: number | null;
  binding: string;
  triggered: boolean;
  warnings: string[];
}

interface Position {
  id: number;
  symbol: string;
  name: string | null;
  entry_date: string;
  entry_price: number | null;
  quantity: number | null;
  breakeven_armed: boolean;
  status: string;
  note: string | null;
  last_eval: LastEval | null;
}

function fmtPrice(n: number | null | undefined): string {
  if (n == null) return "—";
  return `₩${n.toLocaleString("ko-KR")}`;
}

const BINDING_LABEL: Record<string, string> = {
  initial_stop: "초기 -8%",
  breakeven: "본전 바닥",
  sma50_trail: "50일선 추적",
};

export default function PositionsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["positions"],
    queryFn: () => api<Position[]>("/positions?status=open"),
  });

  if (isLoading) return <Skeleton className="h-64" />;
  if (isError)
    return (
      <p className="text-sm text-red-600">
        포지션 조회 실패 — API 서버 상태를 확인하세요.
      </p>
    );
  const rows = data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Briefcase className="h-5 w-5" />
        <h1 className="text-xl font-semibold">보유 포지션</h1>
        <span className="text-sm text-muted-foreground">
          {rows.length}건 · 일일 손절 평가(3층 스택)
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          open 포지션이 없습니다. 등록:{" "}
          <code>python -m kr_pipeline.trade_management --add SYMBOL --price P</code>
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3">종목</th>
                <th className="py-2 pr-3">매수일</th>
                <th className="py-2 pr-3">평균매입가</th>
                <th className="py-2 pr-3">평가일</th>
                <th className="py-2 pr-3">종가</th>
                <th className="py-2 pr-3">유효 손절선</th>
                <th className="py-2 pr-3">바인딩</th>
                <th className="py-2 pr-3">상태</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className="border-b">
                  <td className="py-2 pr-3 font-medium">
                    {p.symbol}
                    {p.name ? <span className="ml-1 text-muted-foreground">{p.name}</span> : null}
                  </td>
                  <td className="py-2 pr-3">{p.entry_date}</td>
                  <td className="py-2 pr-3">{fmtPrice(p.entry_price)}</td>
                  <td className="py-2 pr-3">{p.last_eval?.eval_date ?? "—"}</td>
                  <td className="py-2 pr-3">{fmtPrice(p.last_eval?.close)}</td>
                  <td className="py-2 pr-3">{fmtPrice(p.last_eval?.effective_stop)}</td>
                  <td className="py-2 pr-3">
                    {p.last_eval ? BINDING_LABEL[p.last_eval.binding] ?? p.last_eval.binding : "—"}
                    {p.breakeven_armed ? (
                      <span className="ml-1 rounded bg-emerald-100 px-1 text-xs text-emerald-700 dark:bg-emerald-900 dark:text-emerald-200">
                        장전
                      </span>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3">
                    {p.last_eval?.triggered ? (
                      <span className="inline-flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-900 dark:text-red-200">
                        <AlertTriangle className="h-3 w-3" /> 매도 신호
                      </span>
                    ) : (
                      <span className="text-muted-foreground">보유</span>
                    )}
                    {p.last_eval?.warnings?.length ? (
                      <span className="ml-1 text-xs text-amber-600" title={p.last_eval.warnings.join("; ")}>
                        ⚠
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
