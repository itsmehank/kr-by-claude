// Reasoning 용어 사전 타입 — spec docs/superpowers/specs/2026-11-09-reasoning-glossary-design.md D1

export type GlossaryCategory =
  | "시장 상황"
  | "베이스·패턴"
  | "진입 신호"
  | "위험 플래그"
  | "추세 템플릿"
  | "게이트·규칙"
  | "분류 결과"
  | "참고 문헌·절 번호";

export const GLOSSARY_CATEGORIES: GlossaryCategory[] = [
  "시장 상황",
  "추세 템플릿",
  "베이스·패턴",
  "진입 신호",
  "위험 플래그",
  "게이트·규칙",
  "분류 결과",
  "참고 문헌·절 번호",
];

export interface GlossaryThreshold {
  label: string;
  value: number | string;
  unit?: string;
  /** thresholds.py 상수 이름, 또는 'prompts/analyze_chart_v3.md §x' */
  source: string;
}

export interface GlossaryEntry {
  id: string;
  title: string;
  /** reasoning 에 실제로 나오는 표기들(대소문자 무시 매칭) */
  aliases: string[];
  category: GlossaryCategory;
  /** 마우스 오버용 쉬운 설명 2~3문장 */
  short: string;
  thresholds?: GlossaryThreshold[];
  /** 분석에서의 의미 한 줄 */
  meaning?: string;
  /** 실제 숫자가 든 예시(검색 창에서만) */
  example?: string;
  related?: string[];
}

export type Segment =
  | { kind: "text"; text: string }
  | { kind: "term"; text: string; id: string };
