// 비일관성 / 변경 이력 (spec audit §9)

export interface ChangeEntry {
  letter: string;
  date: string;
  commit: string;
  title: string;
  rationale: string;
  changes: string[];
}

export const CHANGE_LOG: ChangeEntry[] = [
  {
    letter: "A",
    date: "2026-05-21",
    commit: "59a1e82 + cca4054",
    title: "drawdown_filter 제거 (2 단계)",
    rationale:
      "(w52_high − w52_low) / w52_high 공식이 시간 순서 무시 → 정통 강세 종목 (저점 대비 100~300% 상승) false negative 80% 발생.",
    changes: [
      "1차 (59a1e82): 게이트만 제거. weekend.py / compute/delta.py 의 SQL WHERE 절에서 drawdown_filter_pass=TRUE 제거. 컬럼/계산 함수는 보존.",
      "2차 (cca4054): 컬럼/계산 완전 제거 (YAGNI). DB ALTER TABLE DROP COLUMN, compute_drawdown() 함수 삭제, API/TS 필드 제거.",
    ],
  },
  {
    letter: "B",
    date: "2026-05-21",
    commit: "fabe319",
    title: "avg_volume_20d → avg_volume_50d 전면 리네임",
    rationale:
      "전문가 자문 — Minervini TLSMW Ch.10 + O'Neil HMMS Ch.2 의 breakout 거래량 baseline 은 50일 평균. 책에 20일 거래량 평균 근거 없음. 20일은 *가격* MA (Minervini TTLC Ch.1) 로만 등장.",
    changes: [
      "DB SELECT 는 처음부터 avg_volume_50d. 변수명/dict key/함수 인자/prompt 참조만 잘못된 20d 이름이었음. 실제 값/동작 변화 없음 (단순 리네임).",
    ],
  },
  {
    letter: "C",
    date: "2026-05-21",
    commit: "5c6bf06",
    title: "trigger_gate breakout 게이트 1.5× → 1.0× 완화",
    rationale:
      "전문가 자문 — 책 표준 (1.4-1.5×) 정밀 판정 + pocket pivot 예외 (O'Neil 제자 책 Ch.5 BIDU 사례) 는 LLM 이 차트 보고 결정. 게이트가 1.5× 로 사전 배제하던 false negative 해소.",
    changes: [
      "BREAKOUT_VOLUME_MULTIPLIER = 1.5 → 1.0 (compute/trigger_gate.py:12)",
      "게이트는 '거래량 죽지 않은 정도' (avg 이상) 만 확인. LLM 이 표준/예외 판단.",
    ],
  },
  {
    letter: "D",
    date: "2026-05-21",
    commit: "5c6bf06",
    title: "promotion staging 안전장치 (이중 방어)",
    rationale:
      "promotion 트리거는 watch 분류의 'LLM 평가 시작' staging 신호일 뿐 매수 시그널 아님. 0.95× pivot 임계는 책 근거 없는 시스템 자체 설계 (O'Neil 은 pivot 도달 전 매수 경고).",
    changes: [
      "Prompt: evaluate_pivot_trigger_v1.md §3.3 신규 추가 — promotion 트리거에서 go_now 발생 금지 명시.",
      "Code: entry_params.py:34-43 SQL 에 WHERE trigger_type = 'breakout' 필터 추가. prompt 위반 시에도 promotion + go_now → entry_params 직행 차단.",
    ],
  },
  {
    letter: "E",
    date: "2026-05-22",
    commit: "a215cfa",
    title: "spec audit Part 1-7 검토 후 코드 정합성 fix",
    rationale: "spec v2 작성 과정의 line-by-line 비교에서 발견된 코드 정합성 이슈 사전 정리.",
    changes: [
      "daily_delta SQL 에 JOIN stocks WHERE s.delisted_at IS NULL 추가 (compute/delta.py). weekend 와 일관성 회복.",
      "ZIP payload 의 kospi_*.csv → market_index_*.csv 일반화 (zip_builder.py + README + 테스트). KOSDAQ 종목 분석 시 파일명 혼동 해소.",
      "LlmPipelinePage mermaid 정정. DIAGRAM_DATA_FLOW 에 weekend 노드 + trigger_type='breakout' 안전장치 반영. DIAGRAM_STATE 의 잘못된 promotion + go_now 전이 제거.",
    ],
  },
  {
    letter: "F",
    date: "2026-05-22",
    commit: "0e0976c",
    title: "전문가 자문 #2 + #3 반영 (c6 주석 + SMA-21 가드)",
    rationale:
      "spec audit 작성 후 잔존 3 항목 전문가 자문 요청 → 답변 받음 (#1 retry / #2 c6 임계 / #3 SMA-20).",
    changes: [
      "#2 c6: minervini.py:38 주석 보강 — TTLC Ch.6 +25% (최신작, 코드 일치) vs TLSMW Ch.5 +30% 두 저작 간 버전 차이 명시.",
      "#3 SMA-20 가드 (옵션 2 채택): payload_lite.py 에 current_metrics.sma_21 + prior_analysis.days_since_classification 추가. evaluate_pivot_trigger_v1.md §3.1 breakout abort + §3.2 invalidation abort 에 20일선 가드 + '단독은 wait' 단서 + squat reversal recovery 여지.",
      "#1 retry: 책 밖 (엔지니어링). 현행 합리적. 코드 변경 없음.",
    ],
  },
];

export interface ReviewItem {
  title: string;
  status: "resolved" | "open";
  detail: string;
}

export const REVIEW_ITEMS: ReviewItem[] = [
  {
    title: "Minervini c6 임계 (1.25 vs 1.30)",
    status: "resolved",
    detail:
      "두 저작 차이 — TTLC Ch.6 +25% (최신작, 현재 코드 일치) vs TLSMW Ch.5 +30%. 그대로 유지 + minervini.py:38 주석 보강 (commit 0e0976c).",
  },
  {
    title: "daily_delta SQL delisted_at 필터 누락",
    status: "resolved",
    detail: "compute/delta.py 에 JOIN stocks WHERE s.delisted_at IS NULL 추가 (commit a215cfa).",
  },
  {
    title: "retry 정책 일관성",
    status: "resolved",
    detail:
      "전문가 결론 — 책 밖 (엔지니어링). weekend 대량/평일 소량 차이라 현행 정책이 데이터 일관성 관점에서 합리적. 코드 변경 없음.",
  },
  {
    title: "kospi_*.csv 파일명 혼동",
    status: "resolved",
    detail: "market_index_*.csv 로 일반화 (commit a215cfa).",
  },
  {
    title: "기존 안내 페이지 mermaid 다이어그램 정정",
    status: "resolved",
    detail:
      "DIAGRAM_DATA_FLOW + DIAGRAM_STATE 정정 (commit a215cfa). weekend 노드 추가 + 잘못된 promotion go_now 전이 제거.",
  },
  {
    title: "invalidation 에 SMA-20 가격 MA 추가",
    status: "resolved",
    detail:
      "옵션 2 채택 (게이트는 SMA-50, SMA-21 은 LLM prompt 재료). payload_lite.py + evaluate_pivot_trigger_v1.md 갱신 (commit 0e0976c). 책 직접 인용: Minervini TTLC Ch.1 'WATCH THE 20-DAY LINE'.",
  },
];

export const FUTURE_MONITORING = [
  "1.0× 게이트 완화 후 LLM 호출 종목 수 / 비용 추이 모니터링",
  "pocket pivot 케이스 발견 시 LLM 이 정상 판정하는지 확인",
  "분류 변경 추이 (entry → ignore 강등이 정상 흐름인지)",
];
