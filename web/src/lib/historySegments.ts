import type { ClassificationHistoryRow } from "./types";

/** 분류 히스토리의 변화점 구간 (스펙 §4).
 *  - 구간 = 연속 동일 classification (미분석 갭은 끊지 않음 — 다른 분류가 끼어야 분할)
 *  - 대표값(pattern/confidence/reasoning) = 구간 첫 주("왜 전환됐나"에 답하는 값)
 *  - weeks = 실제 분석 행만 (갭 주를 세지 않음 — 백테스트 해석 왜곡 방지)
 *  - truncatedStart: 가장 오래된 구간 — 조회 창에 잘려 시작일이 전환일이라
 *    단정 불가("기간 이전부터 ~" 보수 표기용) */
export interface HistorySegment {
  classification: string;
  startDate: string;
  endDate: string;
  pattern: string | null;
  confidence: number | null;
  reasoning: string | null;
  weeks: ClassificationHistoryRow[]; // 날짜 오름차순
  truncatedStart: boolean;
}

/** 주간 분류 행(임의 순서 허용)을 변화점 구간으로 그룹핑. 반환은 최신 구간 먼저. */
export function groupHistorySegments(rows: ClassificationHistoryRow[]): HistorySegment[] {
  if (rows.length === 0) return [];
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));

  const segments: HistorySegment[] = [];
  for (const r of sorted) {
    const cur = segments[segments.length - 1];
    if (cur && cur.classification === r.classification) {
      cur.endDate = r.date;
      cur.weeks.push(r);
    } else {
      segments.push({
        classification: r.classification,
        startDate: r.date,
        endDate: r.date,
        pattern: r.pattern,
        confidence: r.confidence,
        reasoning: r.reasoning,
        weeks: [r],
        truncatedStart: false,
      });
    }
  }
  segments[0].truncatedStart = true; // 가장 오래된 구간 — 창-잘림 보수 표기
  return segments.reverse(); // 최신 구간 먼저
}
