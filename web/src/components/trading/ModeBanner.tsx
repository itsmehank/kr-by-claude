import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { tradeApi } from "../../lib/tradeApi";
import type { Health } from "../../lib/tradeTypes";
import { fmtKrw } from "../../lib/tradeMath";

function useHealth() {
  return useQuery<Health>({ queryKey: ["trade", "health"], queryFn: () => tradeApi<Health>("/health"), refetchInterval: 30_000 });
}

export default function ModeBanner() {
  const q = useHealth();
  if (q.isError) return <div className="rounded-md bg-slate-800 text-slate-100 px-3 py-2 text-sm">매매 서버(:8001)에 연결할 수 없습니다 — `uv run uvicorn trade_api.main:app --port 8001`</div>;
  if (!q.data) return null;
  const h = q.data;
  return h.dryRun ? (
    <div className="flex items-center gap-2 rounded-md bg-amber-100 text-amber-900 px-3 py-2 text-sm">
      <ShieldCheck size={16} /> <b>연습 모드 (DRY_RUN)</b> — 주문은 토스에 전송되지 않고 감사로그에만 기록됩니다. 상한 1건 {fmtKrw(h.maxOrderKrw)} / 1일 {fmtKrw(h.maxDailyKrw)}원
    </div>
  ) : (
    <div className="flex items-center gap-2 rounded-md bg-red-600 text-white px-3 py-2 text-sm">
      <AlertTriangle size={16} /> <b>실주문 모드</b> — 주문 전송 시 실제 계좌에 주문이 접수됩니다. 상한 1건 {fmtKrw(h.maxOrderKrw)} / 1일 {fmtKrw(h.maxDailyKrw)}원 · 계좌 #{h.accountSeq ?? "미설정"}
    </div>
  );
}
