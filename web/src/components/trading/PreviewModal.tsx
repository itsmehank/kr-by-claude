import { errorMessage } from "../../lib/tradeErrors";
import { fmtKrw } from "../../lib/tradeMath";
import type { PreviewOut } from "../../lib/tradeTypes";

interface Props {
  preview: PreviewOut; title: string; submitting: boolean; error: { code: string; message: string } | null;
  onConfirm: () => void; onClose: () => void;
}

export default function PreviewModal({ preview, title, submitting, error, onConfirm, onClose }: Props) {
  const e = preview.estimate;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[520px] max-w-[95vw] rounded-lg bg-white p-4 shadow-xl" onClick={(ev) => ev.stopPropagation()}>
        <h3 className="mb-2 text-base font-semibold">{title} — 미리보기</h3>
        <div className={`mb-3 rounded px-2 py-1 text-xs ${preview.dryRun ? "bg-amber-100 text-amber-900" : "bg-red-600 text-white"}`}>
          {preview.dryRun ? "연습 모드: 전송되지 않습니다" : "실주문 모드: 전송하면 실제 주문이 접수됩니다"}
        </div>
        <dl className="grid grid-cols-2 gap-y-1 text-sm">
          <dt className="text-slate-500">예상 주문금액</dt><dd>{fmtKrw(e.amount)}원 {e.amountBasis === "upper_limit" && <span className="text-xs text-slate-500">(상한가 기준 최대)</span>}</dd>
          <dt className="text-slate-500">예상 수수료</dt><dd>{e.commission ? `${fmtKrw(e.commission)}원` : "—"}</dd>
          <dt className="text-slate-500">예상 총액</dt><dd className="font-semibold">{fmtKrw(e.total)}원</dd>
          {preview.clientOrderId && (<><dt className="text-slate-500">clientOrderId</dt><dd className="font-mono text-xs">{preview.clientOrderId}</dd></>)}
        </dl>
        {preview.warnings.length > 0 && <div className="mt-2 rounded bg-orange-100 px-2 py-1 text-xs text-orange-900">경고: {preview.warnings.join(", ")}</div>}
        <details className="mt-2 text-xs"><summary className="cursor-pointer text-slate-500">보낼 요청 본문</summary>
          <pre className="mt-1 overflow-auto rounded bg-slate-50 p-2">{JSON.stringify(preview.request, null, 2)}</pre></details>
        {error && <div className="mt-2 rounded bg-red-100 px-2 py-1 text-sm text-red-800">{errorMessage(error.code, error.message)}</div>}
        <div className="mt-4 flex justify-end gap-2">
          <button className="rounded border px-3 py-1 text-sm" onClick={onClose}>닫기</button>
          <button className={`rounded px-3 py-1 text-sm text-white ${preview.dryRun ? "bg-amber-600" : "bg-red-600"}`} disabled={submitting} onClick={onConfirm}>
            {submitting ? "전송 중…" : preview.dryRun ? "연습 전송" : "주문 전송"}
          </button>
        </div>
      </div>
    </div>
  );
}
