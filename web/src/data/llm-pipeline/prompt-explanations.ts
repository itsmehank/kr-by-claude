// 3 prompt 의 고등학생 수준 친절 풀이.
// 근거: prompts/analyze_chart_v3.md, evaluate_pivot_trigger_v1.md, calculate_entry_params_v2_0.md
// 사용자가 *"이 prompt 가 정확히 뭐 하는지"* 알고 싶을 때 StageCard 의 LLM 섹션 fold 에서 펼침.

export interface PromptExplanation {
  filename: string;       // prompts/ 안의 파일명
  role: string;            // 한 문장 — 이 prompt 가 하는 일
  input: string[];         // AI 가 받는 자료 (목록)
  output: string[];        // AI 가 만드는 것 (목록)
  keyRules: string[];      // 핵심 룰 — 책 근거와 함께 (고등학생 수준 풀이)
}

export const PROMPT_EXPLANATIONS: Record<string, PromptExplanation> = {
  analyze_chart_v3: {
    filename: "analyze_chart_v3.md",
    role:
      "한 종목의 차트와 데이터를 보고 '지금 사기 좋은 종목인지, 베이스 형성 중인지, 부적합한지' 를 판정해 분류 라벨을 붙입니다.",
    input: [
      "차트 PNG 이미지 — 일봉/주봉 (시각 판독용)",
      "일봉·주봉 OHLCV CSV (시·고·저·종가 + 거래량)",
      "시장 컨텍스트 (오늘의 시장 상태 + FTD + distribution day 카운트)",
      "Minervini Trend Template 8 조건 통과 여부 + 각 조건의 margin",
      "corporate actions (분할·합병·배당 — 차트 왜곡 보정)",
      "종목 메타 (이름·시장·섹터)",
    ],
    output: [
      "classification: entry / watch / ignore 중 하나",
      "pattern: 10 종 base 패턴 (flat_base, cup_with_handle, cup_without_handle, vcp 등) 중 하나 또는 none",
      "pivot_price: 책 정의 매수 기준가 (패턴별 정의 다름)",
      "base_depth_pct: base 깊이 (peak 대비 trough)",
      "risk_flags: 13 종 위험 신호 중 부분집합 (climax_run·late_stage_base·faulty_pivot 등)",
      "confidence: 0.0-1.0 신뢰도",
      "reasoning: 한국어로 분류 이유 설명 (5 섹션 구조)",
    ],
    keyRules: [
      "**책 정통 추세주만 entry**: Stage 2 진입 + 깨끗한 base + 시장 우호적 시점 (§3.5 의 4-enum 시장 상태가 confirmed_uptrend) — 모두 만족해야 entry. 하나라도 빠지면 watch 또는 ignore.",
      "**10 base 패턴만 허용**: flat_base / cup_with_handle / cup_without_handle / vcp / double_bottom / high_tight_flag / 3c_cheat / base_on_base / ascending_base / none. 책에 없는 패턴은 추측 금지 — none 으로 처리.",
      "**13 risk flag 분류**: 위험 신호도 고정 13 종 목록만 사용. 자유 표현 금지. UI 와 prompt 가 동일한 분류 체계 공유.",
      "**시장 컨텍스트 하드룰** (§3.5): 시장이 correction/downtrend 면 entry 불가 → watch 강제. 시장 distribution day ≥ 5 이면 confidence -0.15.",
      "**handle 품질 (cup_with_handle)**: handle 깊이 8-12% / 10주 MA 위 / wedging 금지 — O'Neil HMMS p.116. 위반 시 watch 강등.",
    ],
  },

  evaluate_pivot_trigger_v1: {
    filename: "evaluate_pivot_trigger_v1.md",
    role:
      "결정론 게이트가 오늘 잡은 트리거가 *진짜 신호* 인지 *가짜 신호* 인지 판정해서 '지금 사라 / 기다려 / 무시' 결정을 내립니다.",
    input: [
      "종목 정보 (이름·현재 분류·이전 분석 reasoning)",
      "오늘의 트리거 유형 (breakout / promotion / invalidation)",
      "최근 60일 일봉 + 보조 지표 (SMA-21, SMA-50, 거래량, volume_ratio 등)",
      "오늘 시장 상태 (4-enum)",
      "직전 weekend 또는 daily_delta 의 분석 결과 (pivot_price, base_depth_pct, risk_flags 등)",
    ],
    output: [
      "decision: go_now (지금 사라) / wait (기다려) / abort (가짜·무효) 중 하나",
      "reasoning: 결정 이유 한국어 설명",
    ],
    keyRules: [
      "**분류 변경 금지**: 이 prompt 는 *trigger 평가* 만 함. classification 자체는 절대 변경하지 않음 — entry 가 그대로 entry, watch 가 그대로 watch. abort 가 나와도 다음 토 weekend 의 재분석에서 비로소 ignore 강등.",
      "**breakout 거래량 표준**: 종가가 pivot 위로 올라간 날의 거래량이 50일 평균의 1.4-1.5× 이상이어야 진짜 돌파. 미만이면 wait (약한 신호). O'Neil HMMS Ch.2.",
      "**pocket pivot 예외**: 표준 1.4× 안 채워도, 직전 10일 중 하락일 최대 거래량을 초과 + 종가 SMA-50 위면 valid (Morales/Kacher TLOND Ch.5).",
      "**promotion 트리거 = staging only**: 종가가 pivot 의 95% 까지 도달한 watch 종목은 매수 신호 *아님*. 분류는 watch 유지, decision 은 wait — 진짜 돌파는 pivot 위로 올라간 별도 breakout 트리거가 처리.",
      "**SMA-20 (20일선) 보조 가드**: 단독 sma_21 이탈은 wait (단기 잡음 가능성 있음). sma_50 이탈은 abort.",
    ],
  },

  calculate_entry_params_v2_0: {
    // RETIRED (#21): 결정론 함수 kr_pipeline/llm_runner/compute/entry_params_calc.py 로 대체.
    // 아래 프롬프트 본문은 아카이브 표시용.
    filename: "calculate_entry_params_v2_0.md",
    role:
      "go_now 결정을 받은 *진짜 매수 시그널* 종목에 대해 매수 계획 18 필드를 계산합니다 — '얼마에 사고, 얼마에 손절하고, 얼마까지 목표로 잡을지'. ⚠️ 이 프롬프트는 #21 로 은퇴 — 지금은 같은 규칙을 결정론 함수 (entry_params_calc.py) 가 AI 호출 없이 계산하며, 아래 설명은 그 규칙의 출처 문서로 보존된 것입니다.",
    input: [
      "오늘의 trigger 평가 결과 (decision='go_now' + trigger_type='breakout')",
      "직전 weekend/daily_delta 의 분석 결과 (pattern, pivot_price, base_high/low, risk_flags 등)",
      "최근 60일 일봉 + 보조 지표",
      "시장 컨텍스트",
    ],
    output: [
      "entry_mode: pivot_breakout (표준) 또는 pocket_pivot 중 하나",
      "trigger_price: 매수 발동 가격 (pivot 보다 약간 위, 1.001×)",
      "entry_price + stop_loss_price + expected_target_price (3 가격)",
      "stop_loss_pct_from_pivot + stop_loss_pct_from_current_price (2 손절 %)",
      "expected_target_pct (목표 %)",
      "suggested_weight_pct (포지션 사이즈 %)",
      "entry_window_days + max_chase_pct_from_pivot (매수 가드)",
      "breakout_volume_requirement + observed_breakout_volume_ratio",
      "notes + known_warnings + other_warnings (사람이 읽는 설명·경고)",
    ],
    keyRules: [
      "**O'Neil 7-8% 손절 절대 한계**: stop_loss_pct_from_pivot 의 *최대 하한* 은 -10% (= 손실 한도). 단, pocket_pivot 모드면 -8% 까지만. *Always, without exception* — O'Neil HMMS Ch.10.",
      "**Minervini 1-3% per trade**: suggested_weight_pct 는 포트폴리오의 1-3% *위험* 한도 안에서 산출. 손절 폭이 크면 포지션 작게, 손절 폭이 좁으면 포지션 크게.",
      "**5% chase 한계**: max_chase_pct_from_pivot ≤ 5% — pivot 위로 5% 넘게 올라간 종목은 추격 매수 금지 (O'Neil HMMS Ch.10). 현행 결정론 함수는 VCP 를 일괄 3% 로 더 보수화 (#21 D3a).",
      "**entry_mode 별 다른 룰**: pivot_breakout 은 표준 손절·사이징·거래량 1.4-1.5×. pocket_pivot 은 더 타이트 (손절 -5.5%~-4.5%, 거래량 1.0× 가능).",
      "**책 표준 거래량**: standard pivot_breakout 의 breakout_volume_requirement 디폴트 = ge_1.5x_50day_avg (책 선호치 50%+). 관측값 1.4×~1.5% 면 known_warning emit + 진입 허용.",
      "**known_warnings 화이트리스트**: 16 종 정의된 경고 코드만 사용. 자유 텍스트 경고는 other_warnings 로. 현행 결정론 함수는 이 중 11 종만 발행 가능 (나머지 4+1 종은 #21 결정으로 발행 지점 소멸).",
    ],
  },
};

// stage.id 에서 prompt key 로의 매핑
export const STAGE_TO_PROMPT: Record<string, string | null> = {
  weekend: "analyze_chart_v3",
  daily_delta: "analyze_chart_v3",
  evaluate_pivot: "evaluate_pivot_trigger_v1",
  entry_params: "calculate_entry_params_v2_0",
  performance: null,  // AI 호출 없음
};
