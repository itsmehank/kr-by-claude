// (#207 회신 21 Q-5c 3) 판정 행 volume_regime_flag 배지 — 문구·값 SSOT(2차 리뷰: Signals·EntrySignalCard 복붙 통합).
// 경계 날짜는 Python data_regimes.VOLUME_REGIME_BOUNDARY 와 수동 동기(변경 시 함께 갱신).
import { AlertTriangle } from "lucide-react";

export const VOLUME_REGIME_FLAG_MIXED = "mixed";
export const VOLUME_REGIME_BOUNDARY = "2026-09-28";
export const VOLUME_REGIME_MIXED_LABEL = "거래량 혼재 창";
export const VOLUME_REGIME_MIXED_DESC =
  `${VOLUME_REGIME_BOUNDARY} 부터 KRX 일별 거래량에 애프터마켓이 합산됨. 이 판정의 거래량 창이 경계에 걸쳐 비율이 위로 편향될 수 있음(#207)`;

export function VolumeRegimeBadge({ flag, variant = "chip" }: { flag: string | null | undefined; variant?: "chip" | "inline" }) {
  if (flag !== VOLUME_REGIME_FLAG_MIXED) return null;
  if (variant === "inline") {
    return (
      <span className="px-2 py-0.5 rounded bg-amber-50 text-amber-800 text-data-xs" title={VOLUME_REGIME_MIXED_DESC}>
        {VOLUME_REGIME_MIXED_LABEL}
      </span>
    );
  }
  return (
    <div className="flex items-center gap-1.5">
      <AlertTriangle size={13} className="text-amber shrink-0" />
      <span className="chip bg-amber-soft text-amber text-data-xs" title={VOLUME_REGIME_MIXED_DESC}>
        {VOLUME_REGIME_MIXED_LABEL}
      </span>
    </div>
  );
}
