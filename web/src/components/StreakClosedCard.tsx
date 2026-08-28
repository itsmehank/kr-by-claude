import type { Streak } from "../lib/types";

// 실격 = 차트 밴드·ClassificationHistoryTable 의 disqualified 톤(danger/rose)과 통일.
// ignore = 기존 회색 chip 관례(bg-tint-stone text-muted, StockStreakRow CLOSED_BY_LABEL).
const CLOSED_TONE: Record<string, string> = {
  disqualify: "border-danger/25 bg-rose-50 text-danger",
  ignore: "border-hairline bg-tint-stone text-muted",
};

const CLOSED_LABEL: Record<string, string> = {
  disqualify: "실격",
  ignore: "ignore",
};

/** 닫는 행 카드(#139) — 묶음이 언제·왜 닫혔는지 타임라인 끝에 표시.
 * StockStreakRow(펼침 행)·StockDetailPanel(상세 패널) 양쪽이 이 컴포넌트를 공유해
 * 닫는 행 표시가 두 곳에서 갈라지지 않게 한다. 백필 유래 ignore 등 reasoning 이
 * 없는 경우 사유 없이 날짜+라벨만 표시(스펙 §1 "제안하는 해결 방법" 3항). */
export default function StreakClosedCard({ streak }: { streak: Streak }) {
  if (!streak.end || !streak.closed_by) return null;
  const tone = CLOSED_TONE[streak.closed_by] ?? CLOSED_TONE.ignore;
  const label = CLOSED_LABEL[streak.closed_by] ?? streak.closed_by;
  return (
    <div className={`rounded-lg border px-3 py-2 ${tone}`}>
      <div className="flex items-center gap-2 flex-wrap text-data-xs">
        <span className="num text-muted">{streak.end}</span>
        <span className="font-semibold">묶음 닫힘 · {label}</span>
      </div>
      {streak.closed_reason && (
        <div className="mt-1 text-data-xs whitespace-pre-wrap">{streak.closed_reason}</div>
      )}
    </div>
  );
}
