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
  {
    letter: "G",
    date: "2026-05-25",
    commit: "e8458f4 외 (P2-1a chain)",
    title: "P2-1a 한국시장 σ 보정 구현 (FTD / 시장 distribution 임계)",
    rationale:
      "TLOND p.232-233 'Adjusting threshold levels for index volatility is correct' + 시기별 손조정 이력(1.0→1.7→1.4→1.5%) 책-강제. 한국 일간 σ ≈ NASDAQ × 2.3 → US 절대임계(FTD 1.4% / dist -0.2%) 그대로 적용 시 한국 약 반등 FTD 오인. 등급 3층 (필요성=책-강제 / 자동 공식화=책-허용 / σ 도구 선택=설계-판단; TLOND p.117 ATR 권고이나 σ 채택, 의도적 deviation).",
    changes: [
      "신규 kr_pipeline/market_context/compute/volatility.py — compute_korean_sigma_pct / derive_market_thresholds / book_default_thresholds 3 순수 함수.",
      "thresholds.py SSOT 상수 7개 추가 — NASDAQ_REFERENCE_SIGMA, FTD_PCT_BASE, DISTRIBUTION_PCT_BASE, SIGMA_WINDOW_DAYS, SIGMA_MIN_DATA_RATIO, KOREAN_SIGMA_RATIO_FLOOR/CEILING.",
      "modes.py:_process_one_date 에 σ 측정 → 임계 도출 → detect_last_ftd / count_distribution_days 시장별 임계 주입.",
      "검증 아티팩트: docs/superpowers/verification/2026-05-25-p2-1a-replay.csv + p2-1a-ftd-invalidation-entry-impact.md (§3.5 co-fire 분석으로 status flip 의 entry/watch 영향 bounded 입증).",
    ],
  },
  {
    letter: "H",
    date: "2026-05-27",
    commit: "a97a61e (P2-1b cup depth)",
    title: "P2-1b cup depth 측정·종결 — 33%/50% 유지, 규칙 무변경",
    rationale:
      "책 'cups correct 1.5-2.5× the market averages' (HMMS p.190 단일조정 직접인용) 의 분모 = 단일 중간조정 크기. KR 46/30yr + US 46yr 외부 캐시로 3 탐지 정의 측정. 가장 책-정본 분모인 Def C (zigzag swing) 에서 KR ≈ US (KOSPI/SP500=1.13, KOSDAQ/Nasdaq=0.94) → 33%/50% 이전 정당. 등급: 책-강제 (Minervini/O'Neil 1순위 + 측정).",
    changes: [
      "신규 measure_drawdowns.py (read-only) + data/ 캐시 (KOSPI/KOSDAQ/SP500/Nasdaq).",
      "FINDINGS.md 작성 — Def C canonical denominator, KR≈US 측정, 33%/50% 유지 판정.",
      "F3 (P2-1c, 50% 예외 연속화) backlog 등록 — 식: clamp(2.5 × 동시점 지수 drawdown, floor=33%, cap=50%), >60% reject. Wake trigger: cron 으로 base_depth ∈ [33,50] AND status='correction' 누적 후.",
      "F4 (handle very-large-cup 예외 복원) backlog 등록 — HMMS p.116-117 의 ②unless very large cup 조건 operationalize. ①during bull markets 는 prompt 가 이미 'in a normal market' 으로 반영.",
      "prompt §4 / thresholds.py 무수정.",
    ],
  },
  {
    letter: "I",
    date: "2026-05-27~28",
    commit: "f43191c, 4f310bd (P2-1d wide_and_loose)",
    title: "P2-1d wide_and_loose 주간 봉폭 측정 + prompt §5 주석 정합",
    rationale:
      "wide_and_loose 의 operative 임계가 'Weekly price swings 10–15%' = 주간 봉폭(bar-volatility)이고 괄호 주석 '1.5-2.5× general market correction' 은 non-operative size-relative 정당화 → 차원 혼용. P2-1a σ-ratio 재사용 금지 (분모 다름). KR/US 주간 봉폭 직접 측정 → 비율 KOSPI/SP500=1.30, KOSDAQ/Nasdaq=1.06 (일간 σ 2.3× 와 차이 큼 = 주간 집계 효과). 성장주 페어 1.06 → 10-15% 유지 primary, KOSPI 분기는 F5 조건부 backlog.",
    changes: [
      "신규 measure_weekly_swings.py — 주간 (high-low)/close 및 |close ret| 두 metric.",
      "analyze_chart_v3.md §5 L189 wide_and_loose 주석 정정: 'O'Neil: 1.5-2.5× general market correction' 제거 → bar-volatility flag 임을 명시 + 'base-depth 는 cup_with_handle 룰(§4) 소관, 중복 금지'. operative 10-15% 불변, 동작 중립. threshold-change-checklist 적용(축2 영향 NONE).",
      "F5 (P2-1d-KOSPI 분기) 조건부 backlog 등록 — KOSPI 종목 한정 10-15% × 1.3 (≈13-19%). Wake trigger: cron 으로 KOSPI 종목 wide_and_loose false-flag 빈도 누적 후.",
    ],
  },
  {
    letter: "J",
    date: "2026-05-28",
    commit: "94d7894, 5eb9293 (prompt 잔재 정리)",
    title: "PP 2008 예외 인용 강화 + blue dot dead reference 정리",
    rationale:
      "(P2-5) §4.5 의 PP 2008 예외 주석이 의역으로만 있어 책 원문 직접 인용 누락. (P3-5) is_blue_dot 필드가 사전 사이클에 payload 에서 제거됐으나 prompt 본문 두 곳에 positive trait 예시로 'blue dot' 잔존 → LLM 이 받지 못하는 입력 거론하던 dead reference.",
    changes: [
      "analyze_chart_v3.md §4.5 L130: 'Except in very rare cases, such as in the aftermath of the crash of late 2008' (TLOND p.132 토씨까지) 직접 인용 + 'Conservative-by-design, not a book deviation' 명시 (책은 예외 허용, 우리는 §3.5 게이트 중첩이라 억제). 등급: 책-허용.",
      "analyze_chart_v3.md §5 L199 + L324 의 positive trait 예시 목록에서 'blue dot' 제거. 남은 예시: high RS Rating · price above MAs · MA alignment · RS Line leadership.",
      "동작 무관 (dead reference 청소 + 주석 강화).",
    ],
  },
  {
    letter: "K",
    date: "2026-05-25~28",
    commit: "1baa640, 5d63b74, 7edae41, 2e65489 + 본 commit",
    title: "방법론 인프라 + 거시 계획서 격상 + audit 메타 drift 정리",
    rationale:
      "P2-1a chain 에서 'FTD 임계 상향이 status.py FTD 무효화 룰(10일 상수)과 상호작용해 회복을 correction 으로 오판' 발견. 임계 변경 시 의존 룰 정합 점검을 일회성으로 두지 말고 재사용 방법론으로 흡수. 등급/Wake trigger/거시 계획서/audit 메타까지 거버넌스 인프라 일괄 정착.",
    changes: [
      "threshold-change-checklist.md 신설 — 2축 의존성 맵 + 합격 조건 게이트 + P2-1a 소급 예시.",
      "3층 등급 의미 명문화 (필요성 / 공식화 / 도구) — 통일 등급 압축 금지, 변경 우선순위 보존.",
      "Wake trigger 모든 backlog 항목에 명시 — F3 (P2-1c 50% 연속화), F4 (handle), F5 (P2-1d KOSPI 분기), F6 (ATR 전환).",
      "F6 ATR 전환 검토 backlog 등록 — 1순위 위반 아닌 2순위 권고 채택 선택건이라 시급성 LOW. P2-1a σ 선택 사유 (의도적 deviation) 기록 인용.",
      "PROJECT_ROADMAP.md 신설 — 원안 5단계 청사진(첫 spec 임베드)을 거시 단일 문서로 격상. 원안 vs 현 구현 매핑 + 운영 상태 + backlog Wake trigger + authoritative sources.",
      "audit 메타 drift 정리 (본 commit): risk-flags.ts 의 wide_and_loose / faulty_pivot / narrow_base 정의를 prompt 와 동기화. stages.ts PP 영문 인용에 책 원문 'aftermath of the crash of late 2008' 추가. change-log.ts 에 본 chain G-K 5건 백필. prompt 본문 표시는 ?raw import 라 이미 자동 동기화돼 있음, 잔존은 메타-설명 4 파일 수동 작성 영역.",
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
