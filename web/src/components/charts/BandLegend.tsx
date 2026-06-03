import { BAND_SWATCH, BAND_LABELS, BAND_ORDER } from "./overlayBands";

/** 분류 밴드 범례 — 색(상태) → 의미. 분류 밴드 토글 ON 일 때만 표시. */
export function BandLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 mt-3 pt-3 border-t border-hairline">
      <span className="caps text-faint">분류 밴드</span>
      {BAND_ORDER.map((s) => (
        <span key={s} className="flex items-center gap-1.5 text-data-xs text-muted">
          <span
            className="inline-block w-3 h-3 rounded-sm"
            style={{ background: BAND_SWATCH[s] }}
          />
          {BAND_LABELS[s]}
        </span>
      ))}
    </div>
  );
}
