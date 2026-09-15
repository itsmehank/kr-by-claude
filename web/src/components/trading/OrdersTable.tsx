import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { postJson, tradeApi, TradeApiError } from "../../lib/tradeApi";
import { errorMessage } from "../../lib/tradeErrors";
import { fmtKrw } from "../../lib/tradeMath";
import type { OperationOut, Order, PaginatedOrders, PreviewOut } from "../../lib/tradeTypes";
import PreviewModal from "./PreviewModal";

const STATUS_KR: Record<string, string> = {
  PENDING: "대기", PENDING_CANCEL: "취소 대기", PENDING_REPLACE: "정정 대기", PARTIAL_FILLED: "부분 체결",
  FILLED: "체결", CANCELED: "취소", REJECTED: "거부", REPLACED: "정정됨", CANCEL_REJECTED: "취소 거부", REPLACE_REJECTED: "정정 거부",
};

export default function OrdersTable() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"OPEN" | "CLOSED">("OPEN");
  const [cursor, setCursor] = useState<string | null>(null);
  const [modify, setModify] = useState<{ order: Order; qty: string; price: string } | null>(null);
  const [preview, setPreview] = useState<PreviewOut | null>(null);
  const [err, setErr] = useState<{ code: string; message: string } | null>(null);
  const toErr = (e: unknown) => (e instanceof TradeApiError ? { code: e.code, message: e.message } : { code: "http-error", message: String(e) });
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["trade", "orders"] }); qc.invalidateQueries({ queryKey: ["trade", "holdings"] }); qc.invalidateQueries({ queryKey: ["trade", "buying-power"] }); };

  const q = useQuery<PaginatedOrders>({
    queryKey: ["trade", "orders", tab, cursor],
    queryFn: () => tradeApi<PaginatedOrders>(`/orders?status=${tab}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}${tab === "CLOSED" ? "&limit=20" : ""}`),
    refetchInterval: (query) => (tab === "OPEN" && (query.state.data?.orders.length ?? 0) > 0 ? 2_000 : false),   // OPEN 주문 있을 때만 폴링
  });

  const cancel = useMutation({ mutationFn: (id: string) => postJson<OperationOut>(`/orders/${id}/cancel`, {}), onSuccess: () => { setErr(null); invalidate(); }, onError: (e) => setErr(toErr(e)) });
  const modPreview = useMutation({
    mutationFn: () => postJson<PreviewOut>("/orders/modify/preview", { orderId: modify!.order.orderId, orderType: "LIMIT", quantity: modify!.qty, price: modify!.price }),
    onSuccess: (p) => { setPreview(p); setErr(null); }, onError: (e) => setErr(toErr(e)),
  });
  const modSubmit = useMutation({
    mutationFn: () => postJson<OperationOut>(`/orders/${modify!.order.orderId}/modify`, { previewToken: preview!.previewToken, orderId: modify!.order.orderId, request: { orderType: "LIMIT", quantity: modify!.qty, price: modify!.price } }),
    onSuccess: () => { setPreview(null); setModify(null); setErr(null); invalidate(); }, onError: (e) => setErr(toErr(e)),
  });

  const rows = (q.data?.orders ?? []).filter((o) => tab === "OPEN" || o.status !== "PARTIAL_FILLED");   // PARTIAL_FILLED 는 OPEN 탭에만
  return (
    <section className="rounded-lg border p-3">
      <div className="mb-2 flex items-center gap-2">
        <h2 className="font-semibold">주문 현황</h2>
        {(["OPEN", "CLOSED"] as const).map((t) => <button key={t} className={`rounded px-2 py-0.5 text-xs ${tab === t ? "bg-slate-800 text-white" : "border"}`} onClick={() => { setTab(t); setCursor(null); }}>{t === "OPEN" ? "미체결" : "체결/종료"}</button>)}
        {tab === "OPEN" && rows.length > 0 && <span className="text-xs text-slate-400">2초 갱신</span>}
      </div>
      {err && <div className="mb-2 rounded bg-red-100 px-2 py-1 text-sm text-red-800">{errorMessage(err.code, err.message)}</div>}
      <table className="w-full text-xs">
        <thead className="text-slate-500"><tr><th className="text-left">시각</th><th className="text-left">종목</th><th>구분</th><th>상태</th><th className="text-right">가격</th><th className="text-right">수량</th><th className="text-right">체결</th><th></th></tr></thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.orderId} className="border-t">
              <td>{o.orderedAt.slice(11, 19)}</td>
              <td className="font-mono">{o.symbol}</td>
              <td className={`text-center ${o.side === "BUY" ? "text-red-700" : "text-blue-700"}`}>{o.side === "BUY" ? "매수" : "매도"} {o.orderType === "MARKET" ? "시장가" : "지정가"}</td>
              <td className="text-center">{STATUS_KR[o.status] ?? o.status}</td>
              <td className="text-right">{fmtKrw(o.price)}</td>
              <td className="text-right">{o.quantity}</td>
              <td className="text-right">{o.execution.filledQuantity}{o.execution.averageFilledPrice && ` @ ${fmtKrw(o.execution.averageFilledPrice)}`}</td>
              <td className="text-right whitespace-nowrap">
                {tab === "OPEN" && (<>
                  <button className="rounded border px-1" onClick={() => setModify({ order: o, qty: o.quantity, price: o.price ?? "" })}>정정</button>
                  <button className="ml-1 rounded border px-1 text-red-700" disabled={cancel.isPending} onClick={() => cancel.mutate(o.orderId)}>취소</button>
                </>)}
              </td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={8} className="py-3 text-center text-slate-400">{q.isLoading ? "불러오는 중…" : "주문 없음"}</td></tr>}
        </tbody>
      </table>
      {tab === "CLOSED" && q.data?.hasNext && <button className="mt-2 rounded border px-2 py-1 text-xs" onClick={() => setCursor(q.data!.nextCursor)}>다음 20건</button>}
      {modify && !preview && (
        <div className="mt-3 rounded border bg-slate-50 p-2 text-sm">
          정정 <span className="font-mono">{modify.order.symbol}</span>
          <input className="ml-2 w-20 rounded border px-1" value={modify.qty} onChange={(e) => setModify({ ...modify, qty: e.target.value.replace(/\D/g, "") })} /> 주
          <input className="ml-2 w-28 rounded border px-1" value={modify.price} onChange={(e) => setModify({ ...modify, price: e.target.value.replace(/\D/g, "") })} /> 원
          <button className="ml-2 rounded bg-slate-900 px-2 py-0.5 text-white" disabled={modPreview.isPending} onClick={() => modPreview.mutate()}>미리보기</button>
          <button className="ml-1 rounded border px-2 py-0.5" onClick={() => setModify(null)}>닫기</button>
        </div>
      )}
      {preview && modify && <PreviewModal preview={preview} title={`${modify.order.symbol} 정정`} submitting={modSubmit.isPending} error={err} onConfirm={() => modSubmit.mutate()} onClose={() => { setPreview(null); setErr(null); }} />}
    </section>
  );
}
