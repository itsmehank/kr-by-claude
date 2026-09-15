import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { tradeApi } from "../../lib/tradeApi";
import { fmtKrw } from "../../lib/tradeMath";
import type { HoldingsOut } from "../../lib/tradeTypes";

export default function HoldingsTable() {
  const q = useQuery<HoldingsOut>({ queryKey: ["trade", "holdings"], queryFn: () => tradeApi<HoldingsOut>("/holdings"), refetchInterval: 15_000 });
  if (!q.data) return <section className="rounded-lg border p-3"><h2 className="font-semibold">보유</h2><div className="text-sm text-slate-400">{q.isError ? "조회 실패" : "불러오는 중…"}</div></section>;
  const o = q.data.overview;
  const pl = (s: string) => <span className={s.startsWith("-") ? "text-blue-700" : "text-red-700"}>{fmtKrw(s)}</span>;
  return (
    <section className="rounded-lg border p-3">
      <h2 className="mb-2 font-semibold">보유</h2>
      {q.data.mismatch.length > 0 && (
        <div className="mb-2 flex items-start gap-2 rounded bg-orange-100 px-2 py-1 text-xs text-orange-900">
          <AlertTriangle size={14} className="mt-0.5" />
          <div>positions 미기입/불일치 {q.data.mismatch.length}종목 — {q.data.mismatch.map((m) => `${m.name}(${m.kind === "missing" ? "미기입" : `토스 ${m.tossQty} vs positions ${m.positionQty}`})`).join(", ")}.
            손절 러너는 <Link className="underline" to="/positions">positions</Link> 만 봅니다 (등록: <code>python -m kr_pipeline.trade_management --add</code>).</div>
        </div>
      )}
      <div className="mb-2 grid grid-cols-4 gap-2 text-xs">
        <div><div className="text-slate-500">투자원금</div>{fmtKrw(o.totalPurchaseAmount.krw)}</div>
        <div><div className="text-slate-500">평가금액</div>{fmtKrw(o.marketValue.krw)}</div>
        <div><div className="text-slate-500">손익</div>{pl(o.profitLoss.krw)}</div>
        <div><div className="text-slate-500">일간</div>{pl(o.dailyProfitLoss.krw)}</div>
      </div>
      <table className="w-full text-xs">
        <thead className="text-slate-500"><tr><th className="text-left">종목</th><th className="text-right">수량</th><th className="text-right">평단</th><th className="text-right">현재가</th><th className="text-right">평가</th><th className="text-right">손익</th></tr></thead>
        <tbody>
          {o.items.map((it) => (
            <tr key={it.symbol} className="border-t">
              <td><span className="font-mono">{it.symbol}</span> {it.name}</td>
              <td className="text-right">{it.quantity}</td><td className="text-right">{fmtKrw(it.averagePurchasePrice)}</td>
              <td className="text-right">{fmtKrw(it.lastPrice)}</td><td className="text-right">{fmtKrw(it.marketValue.krw)}</td>
              <td className="text-right">{pl(it.profitLoss.krw)}</td>
            </tr>
          ))}
          {o.items.length === 0 && <tr><td colSpan={6} className="py-3 text-center text-slate-400">보유 종목 없음</td></tr>}
        </tbody>
      </table>
    </section>
  );
}
