import type { ReviewTrigger } from "./types";

/** 타임라인 입력의 구조적 최소 인터페이스(Task 6 — #127 `StockTimeline` 을 종목 행 뷰의
 *  묶음별 펼침에서도 재사용하기 위해 `ReviewRow` 대신 이 구조 타입으로 완화한다).
 *  `ReviewRow`·`StreakAnalysis` 모두 이 필드를 전부 가지고 있어 구조적으로 충족한다.
 *  ⚠️ `classified_at` 필수 — `StockTimeline.tsx` 가 React key 로 사용한다. */
export interface TimelineRow {
  symbol: string;
  key_date: string;
  classified_at: string;
  source: string;
  classification: string;
  pattern: string | null;
  pivot_price: number | null;
  triggers: ReviewTrigger[];
}

/** 병합 타임라인의 분석 이벤트 (issue #127 DC-5/DC-10).
 *  pivotChanged/classificationChanged 는 "직전 분석 이벤트"(병합된 타임라인 내에서
 *  날짜순으로 바로 앞선 분석 이벤트, 트리거 아님) 대비 변경 여부다. */
export interface TimelineAnalysisEvent {
  kind: "analysis";
  date: string; // row.key_date
  row: TimelineRow;
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
  | { kind: "analysis"; date: string; row: TimelineRow }
  | { kind: "trigger"; date: string; symbol: string; trigger: ReviewTrigger };

/**
 * `TimelineRow[]`(분석 행 + 각 행의 `triggers[]`)를 날짜 오름차순 단일 타임라인으로 병합한다
 * (issue #127 — /review 종목 타임라인 뷰. `ReviewRow[]`·`StreakAnalysis[]` 모두 구조적으로
 * `TimelineRow[]` 를 충족해 그대로 넘길 수 있다).
 *
 * - 분석 이벤트 날짜 = `row.key_date`, 트리거 이벤트 날짜 = `trigger.d`.
 * - 동일 날짜에서는 분석 이벤트가 트리거 이벤트보다 먼저 온다.
 * - 그 외 동일 날짜·동일 종류 이벤트 간 순서는 입력 배열 순서를 유지한다(안정 정렬).
 * - 각 분석 이벤트에는 직전 분석 이벤트 대비 pivot_price/classification 변경 여부를 계산해 부여한다.
 */
export function buildStockTimeline(rows: TimelineRow[]): TimelineEvent[] {
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
