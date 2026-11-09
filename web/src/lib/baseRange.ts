// 베이스 구간 가로선을 그릴 날짜 범위(#275). 시작일이 차트 창보다 앞이면 창 시작부터 그린다.

/** dates(오름차순 YYYY-MM-DD) 중 start 이후(포함) 날짜. start 가 없으면 전체. */
export function baseRangeDates(dates: string[], start: string | null | undefined): string[] {
  if (!start) return dates;
  const s = start.slice(0, 10);
  return dates.filter((d) => d >= s);
}
