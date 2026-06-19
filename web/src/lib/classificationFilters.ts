/** /classifications 페이지의 클라이언트 측 presence 필터.
 *
 * pattern/pivot "있음" 토글용 순수 술어. watch 목록에서 base 패턴이 식별된
 * 종목이나 pivot(buy point)이 계산된 종목만 추리는 데 쓴다. 백엔드 쿼리는
 * 건드리지 않고 이미 받아온 행을 화면에서 거른다.
 */

export interface PresenceFilters {
  hasPattern: boolean;
  hasPivot: boolean;
}

export interface PresenceFilterable {
  pattern: string | null;
  pivot_price: number | null;
}

/** pattern 'none'(=패턴 미식별)과 null 은 "패턴 없음"으로 본다. */
export function hasIdentifiedPattern(pattern: string | null): boolean {
  return pattern != null && pattern !== "none";
}

export function matchesPresenceFilters(
  row: PresenceFilterable,
  filters: PresenceFilters,
): boolean {
  if (filters.hasPattern && !hasIdentifiedPattern(row.pattern)) return false;
  if (filters.hasPivot && row.pivot_price == null) return false;
  return true;
}
