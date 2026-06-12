/**
 * KST(Asia/Seoul) 기준 날짜 헬퍼.
 *
 * `new Date().toISOString().slice(0, 10)` 은 UTC 날짜라, KST 자정~오전 9시
 * 사이엔 "어제"를 반환한다 — 트리거 목록 기본 to, 차트 기간 끝단 등이
 * 하루 밀리는 버그의 원인. 화면의 "오늘/기간" 계산은 전부 이 모듈을 쓴다.
 */

const KST_DATE_FMT = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}); // en-CA → "YYYY-MM-DD"

const DAY_MS = 86_400_000;

/** 주어진 시각의 KST 날짜를 YYYY-MM-DD 로. */
export function kstDateISO(d: Date = new Date()): string {
  return KST_DATE_FMT.format(d);
}

/** 오늘(KST) YYYY-MM-DD. */
export function todayKstISO(): string {
  return kstDateISO();
}

/** KST 기준 n일 전 YYYY-MM-DD. */
export function nDaysAgoKstISO(n: number, from: Date = new Date()): string {
  return kstDateISO(new Date(from.getTime() - n * DAY_MS));
}

/** from 이 속한 주(KST 기준)의 월요일 YYYY-MM-DD.
 *  요일 계산과 날짜 문자열을 같은 기준(KST)으로 — 로컬 getDay() 와
 *  toISOString() 을 섞으면 월요일 오전 9시 전에 일요일로 계산된다. */
export function thisWeekMondayKstISO(from: Date = new Date()): string {
  const utcMidnight = new Date(`${kstDateISO(from)}T00:00:00Z`);
  const day = utcMidnight.getUTCDay(); // 0=일 1=월 ... 6=토 (KST 날짜의 요일)
  const back = day === 0 ? 6 : day - 1;
  return new Date(utcMidnight.getTime() - back * DAY_MS).toISOString().slice(0, 10);
}
