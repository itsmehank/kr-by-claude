import type { ReviewRow, ReviewTrigger } from "./types";

/** 병합 타임라인의 분석 이벤트 (issue #127 DC-5/DC-10).
 *  pivotChanged/classificationChanged 는 "직전 분석 이벤트"(병합된 타임라인 내에서
 *  날짜순으로 바로 앞선 분석 이벤트, 트리거 아님) 대비 변경 여부다. */
export interface TimelineAnalysisEvent {
  kind: "analysis";
  date: string; // row.key_date
  row: ReviewRow;
  previousPivotPrice: number | null; // 직전 분석 이벤트의 pivot_price (없으면 null)
  pivotChanged: boolean; // 직전 분석 이벤트 대비 pivot_price 변경 여부(직전 없으면 false)
  classificationChanged: boolean; // 직전 분석 이벤트 대비 classification 변경 여부(직전 없으면 false)
}

/** 병합 타임라인의 트리거 이벤트. */
export interface TimelineTriggerEvent {
  kind: "trigger";
  date: string; // trigger.d
  symbol: string;
  trigger: ReviewTrigger;
}

export type TimelineEvent = TimelineAnalysisEvent | TimelineTriggerEvent;

const KIND_ORDER: Record<"analysis" | "trigger", number> = { analysis: 0, trigger: 1 };

type RawEvent =
  | { kind: "analysis"; date: string; row: ReviewRow }
  | { kind: "trigger"; date: string; symbol: string; trigger: ReviewTrigger };

/**
 * `ReviewRow[]`(분석 행 + 각 행의 `triggers[]`)를 날짜 오름차순 단일 타임라인으로 병합한다
 * (issue #127 — /review 종목 타임라인 뷰).
 *
 * - 분석 이벤트 날짜 = `row.key_date`, 트리거 이벤트 날짜 = `trigger.d`.
 * - 동일 날짜에서는 분석 이벤트가 트리거 이벤트보다 먼저 온다.
 * - 그 외 동일 날짜·동일 종류 이벤트 간 순서는 입력 배열 순서를 유지한다(안정 정렬).
 * - 각 분석 이벤트에는 직전 분석 이벤트 대비 pivot_price/classification 변경 여부를 계산해 부여한다.
 */
export function buildStockTimeline(rows: ReviewRow[]): TimelineEvent[] {
  const rawEvents: RawEvent[] = [];

  for (const row of rows) {
    rawEvents.push({ kind: "analysis", date: row.key_date, row });
    for (const trigger of row.triggers) {
      rawEvents.push({ kind: "trigger", date: trigger.d, symbol: row.symbol, trigger });
    }
  }

  const sorted = [...rawEvents].sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? -1 : 1;
    return KIND_ORDER[a.kind] - KIND_ORDER[b.kind];
  });

  const result: TimelineEvent[] = [];
  let lastPivot: number | null = null;
  let lastClassification: string | null = null;
  let hasPrevious = false;

  for (const ev of sorted) {
    if (ev.kind === "trigger") {
      result.push(ev);
      continue;
    }
    const pivotChanged = hasPrevious && ev.row.pivot_price !== lastPivot;
    const classificationChanged = hasPrevious && ev.row.classification !== lastClassification;
    result.push({
      kind: "analysis",
      date: ev.date,
      row: ev.row,
      previousPivotPrice: hasPrevious ? lastPivot : null,
      pivotChanged,
      classificationChanged,
    });
    lastPivot = ev.row.pivot_price;
    lastClassification = ev.row.classification;
    hasPrevious = true;
  }

  return result;
}
