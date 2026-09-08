// entry_params 필드 풀이 — 카테고리별 그룹화
// 근거: kr_pipeline/llm_runner/compute/entry_params_calc.py (결정론, #21) + (#153 2026-09-08)
// 리스크 역산 사이징 — 구 프롬프트 calculate_entry_params_v2_0.md 의 티어·배수 사이징은 폐기.

export interface EntryParamField {
  name: string;
  category: "entry" | "stop" | "target" | "sizing" | "guard" | "meta";
  what: string;       // 한 줄 친절 설명 (이 필드가 무엇인지)
  constraint: string; // validation 룰 요약 (전문가 참고)
}

export const ENTRY_PARAMS_FIELDS: EntryParamField[] = [
  // Entry 진입 (4)
  { name: "entry_mode", category: "entry", what: "표준 돌파 매수(pivot_breakout) 또는 포켓 피벗(pocket_pivot) 중 하나.", constraint: "exactly one of: pivot_breakout, pocket_pivot" },
  { name: "pivot_price", category: "entry", what: "책에서 권하는 매수 기준가 — base 의 핵심 돌파선.", constraint: "> 0" },
  { name: "trigger_price", category: "entry", what: "실제 매수가 활성화되는 정확한 가격 — pivot 보다 약간 위 (1.001×).", constraint: "> pivot_price; ≤ pivot_price × 1.005" },
  { name: "current_price", category: "entry", what: "시그널 발생 시점의 종가 — pivot 까지 거리 비교용.", constraint: "> 0" },

  // Stop 손절 (3)
  { name: "stop_loss_price", category: "stop", what: "손절선 절대 가격 — 이 가격 닿으면 즉시 매도.", constraint: "> 0; strictly < pivot_price × 0.999" },
  { name: "stop_loss_pct_from_pivot", category: "stop", what: "pivot(예상 매입가) 대비 손절 % — O'Neil 7-8% 룰의 상단 8% 고정(TRADE_STOP_INITIAL_PCT, 관리 단계의 평균매입가 기준 8% 와 같은 규칙). entry_mode·flag 무관 (#153).", constraint: "= −8.0% (pivot × 0.92)" },
  { name: "stop_loss_pct_from_current_price", category: "stop", what: "현재가 대비 손절 % — 추격 매수 위험 평가용.", constraint: "−15.0 ~ −3.0%" },

  // Target 목표 (2)
  { name: "expected_target_price", category: "target", what: "1차 목표가 — 부분 익절 후보 가격.", constraint: "strictly > pivot_price × 1.001" },
  { name: "expected_target_pct", category: "target", what: "pivot 대비 목표 % — O'Neil 20-30% 1차 익절 룰 적용.", constraint: "15.0 ~ 50.0%" },

  // Sizing 포지션 (4) — (#153) Minervini TTLC Ch.8 리스크 역산: full = min(R / |stop|, 25%), 출력 = 파일럿(full × 0.5)
  { name: "suggested_weight_pct", category: "sizing", what: "포트폴리오 내 권장 비중 % = 파일럿 사이즈 7.8125% (full 15.625% × 0.5). 거래당 최대 리스크 R=1.25% ÷ 스탑 8% 로 역산. risk flag·confidence·패턴·entry_mode 는 사이징에 관여하지 않는다(플래그는 진입 게이트 전용 — #80 superseded).", constraint: "= 7.8125% (DB 저장 7.81)" },
  { name: "suggested_weight_full_pct", category: "sizing", what: "정상(full) 사이즈 % = min(R / |stop|, 25%) = 15.625%. 파일럿 이후 증액 시 목표.", constraint: "= 15.625% (DB 저장 15.63)" },
  { name: "sizing_method", category: "sizing", what: "사이징 방법 표지 — 'risk_backed'(리스크 역산).", constraint: "= risk_backed" },
  { name: "sizing_risk_pct", category: "sizing", what: "거래당 최대 리스크 % of equity (SIZING_RISK_PER_TRADE). Minervini TTLC Ch.8 1.25~2.5% 의 하한.", constraint: "= 1.25" },

  // Guard 매수 가드 + 거래량 요건 (5, 모두 category: "guard")
  { name: "pattern_basis", category: "guard", what: "이 매수가 어떤 base 패턴에 기반했는지 (flat_base / cup_with_handle / cup_without_handle / vcp / double_bottom / 3c_cheat).", constraint: "exactly one of: flat_base, cup_with_handle, cup_without_handle, vcp, double_bottom, 3c_cheat" },
  { name: "entry_window_days", category: "guard", what: "트리거 발생 후 며칠 안에 진입해야 유효한가 (1~5 일).", constraint: "integer, 1 ~ 5" },
  { name: "max_chase_pct_from_pivot", category: "guard", what: "pivot 위로 최대 몇 %까지 추격 매수 허용 (O'Neil: ≤5%).", constraint: "0.0 ~ 5.0%" },
  { name: "breakout_volume_requirement", category: "guard", what: "돌파일 거래량 요건 (1.4× / 1.5× 50일평균 / strict 1.5×(#74 cup_without_handle) / pocket pivot signature).", constraint: "exactly one of: ge_1.3x_50day_avg, ge_1.4x_50day_avg, ge_1.5x_50day_avg, ge_1.5x_strict, pocket_pivot_signature" },
  { name: "observed_breakout_volume_ratio", category: "guard", what: "실제 관측된 거래량 비율 — null 또는 0.0-20.0× 사이.", constraint: "null OR 0.0 ~ 20.0" },

  // Meta 메타 (3)
  { name: "notes", category: "meta", what: "사람이 읽는 매수 노트 — entry_mode, 손절 기준, 사이징 산식(R/stop→full×pilot, 미적용 flag 목록), 경고 등 종합 설명.", constraint: "50~600 글자, 필수 항목 (entry_mode, stop binding, sizing 산식, both stop_pct, warnings) 모두 언급" },
  { name: "known_warnings", category: "meta", what: "정의된 경고 코드 목록 — 예: 'breakout_volume_below_preferred_50pct'. (#153) 사이징·스탑 후보 경고 6종은 발행 지점 소멸 → 현행 발행 가능 5종.", constraint: "array from whitelist; no duplicates" },
  { name: "other_warnings", category: "meta", what: "정의 외 자유 텍스트 경고 — LLM 의 추가 관찰 사항.", constraint: "array of free-text strings; each 5~200 chars" },
];

export const FIELD_CATEGORIES: Record<EntryParamField["category"], { label: string; emoji: string }> = {
  entry: { label: "진입 가격", emoji: "🎯" },
  stop: { label: "손절", emoji: "🛑" },
  target: { label: "목표가", emoji: "🏁" },
  sizing: { label: "포지션 사이즈", emoji: "📏" },
  guard: { label: "매수 가드", emoji: "🛡️" },
  meta: { label: "기록·경고", emoji: "📝" },
};
