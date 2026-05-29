// Minervini Trend Template 8 조건 — 초보 친화 풀이
// 근거: audit minervini.ts (영문 원전 + threshold) + 고등학생 수준 한국어 풀이
// audit MINERVINI_CONDITIONS 의 num 과 일대일 대응 (drift 검증용).

import {
  C6_W52LOW_MULT,
  C7_W52HIGH_MULT,
  C8_RS_RATING_MIN,
} from "../thresholds.generated";

export interface TrendTemplateCondition {
  num: number;            // audit minervini.ts 의 num 과 일치
  shortLabel: string;     // 한 줄 친절 요약 (제목으로 사용)
  meaning: string;        // 풀어쓴 설명 (1-2 문장, 왜 이 조건이 필요한지)
  rule: string;           // 기술 표현 (audit korean 필드와 동일, raw SQL 표현)
  threshold?: string;     // 임계값 (있을 때만)
}

export const TREND_TEMPLATE_CONDITIONS: TrendTemplateCondition[] = [
  {
    num: 1,
    shortLabel: "현재가가 150일선·200일선 위에 있다",
    meaning:
      "주가가 중기 (150일) · 장기 (200일) 평균 위에 있어야 *강세 추세* 의 첫 신호. 평균 아래라면 약세 국면이라 매수 부적합.",
    rule: "close > sma_150 AND close > sma_200",
  },
  {
    num: 2,
    shortLabel: "150일선이 200일선 위에 있다",
    meaning:
      "150일 이동평균이 200일 이동평균 위 = *중기 추세가 장기 추세보다 강함*. 즉 종목이 최근 몇 달간 상승 가속 중. (Minervini 가 'Stage 2' 상승 구간 식별의 핵심 지표.)",
    rule: "sma_150 > sma_200",
  },
  {
    num: 3,
    shortLabel: "200일선이 최소 1개월 (≈22 거래일) 상승 추세",
    meaning:
      "장기 평균선이 우상향 — 일시적 반등이 아니라 *구조적 상승* 임을 확인. 책은 4-5 개월 이상이면 더 강한 신호로 보지만 최소 1 개월이 통과 기준.",
    rule: "오늘 sma_200 > 22 거래일 전 sma_200",
    threshold: "22 거래일 (lookback)",
  },
  {
    num: 4,
    shortLabel: "50일선이 150일선·200일선 위에 있다",
    meaning:
      "단기 (50일) · 중기 (150일) · 장기 (200일) 평균이 *위에서 아래로 정렬* 됨. 모멘텀이 최근일수록 강하다는 뜻 — 정통 강세 종목의 차트 모양.",
    rule: "sma_50 > sma_150 AND sma_50 > sma_200",
  },
  {
    num: 5,
    shortLabel: "현재가가 50일선 위에 있다",
    meaning:
      "단기적으로도 평균 위에서 거래 중. 50일선이 받침대 역할을 하고 있음을 의미. 50일선 아래로 떨어지면 종목이 약해진 신호.",
    rule: "close > sma_50",
  },
  {
    num: 6,
    shortLabel: "52주 저점 대비 25% 이상 상승",
    meaning:
      "1년 최저가 대비 충분히 올라온 상태 — 바닥에서 막 출발한 종목이 아니라 *이미 추세 진행 중* 인 종목만 통과. 너무 낮은 가격대 종목은 추세가 약하다는 책 룰.",
    rule: `close ≥ w52_low × ${C6_W52LOW_MULT.toFixed(2)}`,
    threshold: `+${((C6_W52LOW_MULT - 1) * 100).toFixed(0)}% (Minervini TTLC Ch.6; 구판 TLSMW 는 +30%)`,
  },
  {
    num: 7,
    shortLabel: "52주 고점에서 25% 이내 (= 신고가 근접)",
    meaning:
      "1년 최고가에서 멀리 떨어지지 않음 — *역사적 강세* 종목만 통과. 신고가 근처에서 매수하는 것이 책 룰 (역설적이지만 통계적으로 신고가 종목이 더 오른다).",
    rule: `close ≥ w52_high × ${C7_W52HIGH_MULT.toFixed(2)}`,
    threshold: `고점의 ${(C7_W52HIGH_MULT * 100).toFixed(0)}% 이상 (Minervini TLSMW Ch.5 / TTLC Ch.6)`,
  },
  {
    num: 8,
    shortLabel: `RS Rating ≥ ${C8_RS_RATING_MIN}`,
    meaning:
      `전체 종목 대비 가격 상승률 백분위가 ${C8_RS_RATING_MIN} 이상 — *시장의 상위 ${100 - C8_RS_RATING_MIN}% 강세주*. O'Neil 은 80+ 선호, Minervini 는 70 이상이면 통과. 본 시스템은 ${C8_RS_RATING_MIN} 채택.`,
    rule: `rs_rating ≥ ${C8_RS_RATING_MIN}`,
    threshold: `${C8_RS_RATING_MIN} (Minervini 'no less than 70')`,
  },
];
