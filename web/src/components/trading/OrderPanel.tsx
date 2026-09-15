import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { postJson, tradeApi, TradeApiError } from "../../lib/tradeApi";
import { errorMessage } from "../../lib/tradeErrors";
import { estimateAmount, fmtKrw } from "../../lib/tradeMath";
import type { BuyingPower, OrderSubmitOut, PreviewOut, QuoteOut, SearchHit, Sellable } from "../../lib/tradeTypes";
import PreviewModal from "./PreviewModal";
import SymbolSearch from "./SymbolSearch";

type Side = "BUY" | "SELL"; type OrderType = "LIMIT" | "MARKET";

export default function OrderPanel() {
  const qc = useQueryClient();
  const [hit, setHit] = useState<SearchHit | null>(null);
  const [side, setSide] = useState<Side>("BUY");
  const [orderType, setOrderType] = useState<OrderType>("LIMIT");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [confirmHigh, setConfirmHigh] = useState(false);
  const [preview, setPreview] = useState<PreviewOut | null>(null);
  const [err, setErr] = useState<{ code: string; message: string } | null>(null);
  const [done, setDone] = useState<OrderSubmitOut | null>(null);
  const sym = hit?.ticker ?? null;

  const quote = useQuery<QuoteOut>({ queryKey: ["trade", "quote", sym], queryFn: () => tradeApi<QuoteOut>(`/quote/${sym}`), enabled: !!sym, refetchInterval: 5_000 });
  const bp = useQuery<BuyingPower>({ queryKey: ["trade", "buying-power"], queryFn: () => tradeApi<BuyingPower>("/buying-power"), refetchInterval: 15_000 });
  const sellable = useQuery<Sellable>({ queryKey: ["trade", "sellable", sym], queryFn: () => tradeApi<Sellable>(`/sellable/${sym}`), enabled: !!sym && side === "SELL" });

  const upper = quote.data?.limits.upperLimitPrice ?? null;
  const est = estimateAmount(orderType, orderType === "LIMIT" ? price : null, qty, upper);
  const sellOver = side === "SELL" && sellable.data && qty !== "" && /^\d+$/.test(qty) && BigInt(qty) > BigInt(sellable.data.sellableQuantity);
  const toErr = (e: unknown) => (e instanceof TradeApiError ? { code: e.code, message: e.message } : { code: "http-error", message: String(e) });

  const doPreview = useMutation({
    mutationFn: () => postJson<PreviewOut>("/orders/preview", { symbol: sym, side, orderType, quantity: qty, price: orderType === "LIMIT" ? price : null, confirmHighValueOrder: confirmHigh }),
    onSuccess: (p) => { setPreview(p); setErr(null); setDone(null); },
    onError: (e) => setErr(toErr(e)),
  });
  const doSubmit = useMutation({
    mutationFn: () => postJson<OrderSubmitOut>("/orders", { previewToken: preview!.previewToken, request: preview!.request }),
    onSuccess: (r) => { setDone(r); setPreview(null); setErr(null); qc.invalidateQueries({ queryKey: ["trade", "orders"] }); qc.invalidateQueries({ queryKey: ["trade", "holdings"] }); qc.invalidateQueries({ queryKey: ["trade", "buying-power"] }); },
    onError: (e) => setErr(toErr(e)),
  });

  const canPreview = !!sym && est !== null && !sellOver && !doPreview.isPending;
  return (
    <section className="rounded-lg border p-3">
      <h2 className="mb-2 font-semibold">주문</h2>
      <SymbolSearch onSelect={(h) => { setHit(h); setDone(null); setErr(null); }} />
      {hit && (
        <div className="mt-2 text-sm">
          <div className="font-medium"><span className="font-mono">{hit.ticker}</span> {hit.name}</div>
          {quote.data && (
            <div className="mt-1 grid grid-cols-3 gap-2 text-xs text-slate-600">
              <div>현재가 <b className="text-slate-900">{fmtKrw(quote.data.price.lastPrice)}</b></div>
              <div>상한 {fmtKrw(quote.data.limits.upperLimitPrice)}</div>
              <div>하한 {fmtKrw(quote.data.limits.lowerLimitPrice)}</div>
            </div>
          )}
          {quote.data && quote.data.warnings.length > 0 && (
            <div className="mt-1 rounded bg-red-100 px-2 py-1 text-xs text-red-800">유의사항: {quote.data.warnings.map((w) => w.warningType).join(", ")}</div>
          )}
          {quote.data && (
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
              <div><div className="text-slate-500">매도호가</div>{quote.data.orderbook.asks.slice(0, 5).reverse().map((a) => <div key={a.price} className="flex justify-between"><span className="text-blue-700">{fmtKrw(a.price)}</span><span>{fmtKrw(a.volume)}</span></div>)}</div>
              <div><div className="text-slate-500">매수호가</div>{quote.data.orderbook.bids.slice(0, 5).map((b) => <div key={b.price} className="flex justify-between"><span className="text-red-700">{fmtKrw(b.price)}</span><span>{fmtKrw(b.volume)}</span></div>)}</div>
            </div>
          )}
        </div>
      )}
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
        <div className="flex gap-1">{(["BUY", "SELL"] as Side[]).map((s) => <button key={s} className={`flex-1 rounded px-2 py-1 ${side === s ? (s === "BUY" ? "bg-red-600 text-white" : "bg-blue-600 text-white") : "border"}`} onClick={() => setSide(s)}>{s === "BUY" ? "매수" : "매도"}</button>)}</div>
        <div className="flex gap-1">{(["LIMIT", "MARKET"] as OrderType[]).map((t) => <button key={t} className={`flex-1 rounded px-2 py-1 ${orderType === t ? "bg-slate-800 text-white" : "border"}`} onClick={() => setOrderType(t)}>{t === "LIMIT" ? "지정가" : "시장가"}</button>)}</div>
        <label className="text-xs text-slate-600">수량<input className="mt-0.5 w-full rounded border px-2 py-1" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))} /></label>
        <label className="text-xs text-slate-600">가격(원){orderType === "MARKET" && <span className="ml-1 text-slate-400">시장가 — 입력 안 함</span>}
          <input className="mt-0.5 w-full rounded border px-2 py-1" inputMode="numeric" disabled={orderType === "MARKET"} value={orderType === "MARKET" ? "" : price} onChange={(e) => setPrice(e.target.value.replace(/\D/g, ""))} /></label>
      </div>
      <div className="mt-2 text-sm">
        예상 주문금액 <b>{est ? `${fmtKrw(est.amount)}원` : "—"}</b>{est?.basis === "upper_limit" && <span className="ml-1 text-xs text-slate-500">(상한가 기준 최대)</span>}
        <span className="ml-3 text-xs text-slate-500">매수가능 {bp.data ? `${fmtKrw(bp.data.cashBuyingPower)}원` : "—"}</span>
        {side === "SELL" && <span className={`ml-3 text-xs ${sellOver ? "text-red-600" : "text-slate-500"}`}>판매가능 {sellable.data ? sellable.data.sellableQuantity : "—"}주{sellOver && " — 초과"}</span>}
      </div>
      {est && BigInt(est.amount) >= 100_000_000n && (
        <label className="mt-1 flex items-center gap-1 text-xs text-orange-800"><input type="checkbox" checked={confirmHigh} onChange={(e) => setConfirmHigh(e.target.checked)} /> 1억원 이상 고액 주문임을 확인합니다</label>
      )}
      {err && !preview && <div className="mt-2 rounded bg-red-100 px-2 py-1 text-sm text-red-800">{errorMessage(err.code, err.message)}</div>}
      {done && <div className="mt-2 rounded bg-emerald-100 px-2 py-1 text-sm text-emerald-900">{done.dryRun ? "연습 모드 — 감사로그 기록만" : `주문 접수 orderId ${done.orderId}`} (audit #{done.auditId})</div>}
      <button className="mt-3 w-full rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-40" disabled={!canPreview} onClick={() => doPreview.mutate()}>{doPreview.isPending ? "검증 중…" : "미리보기"}</button>
      {preview && <PreviewModal preview={preview} title={`${hit?.name ?? sym} ${side === "BUY" ? "매수" : "매도"}`} submitting={doSubmit.isPending} error={err} onConfirm={() => doSubmit.mutate()} onClose={() => { setPreview(null); setErr(null); }} />}
    </section>
  );
}
