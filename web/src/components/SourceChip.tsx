/** #132 백필 칩·툴팁의 단일 정의 — PR #138 리뷰: ReviewPage/StockTimeline 에
 *  복붙된 칩의 문구 드리프트("→ 상태는 항상 미발동" 유무)를 공유화로 통일.
 *  StockStreakRow 의 "백필" 배지도 같은 툴팁을 쓴다. */
export const BACKFILL_TOOLTIP =
  "백필 — 현재 프롬프트로 재생성된 합성 이력(당시 실전 실행 아님·트리거 이력 없음 → 상태는 항상 미발동)";

/** backfilled ⇔ source==='backfill' — 칩 중복 대신 단일 칩을 "백필"로 치환. */
export function SourceChip({ backfilled, source }: { backfilled: boolean; source: string }) {
  return (
    <span
      className="chip bg-tint-stone text-muted text-data-xs"
      title={backfilled ? BACKFILL_TOOLTIP : undefined}
    >
      {backfilled ? "백필" : source}
    </span>
  );
}
