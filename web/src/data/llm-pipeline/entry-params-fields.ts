// entry_params 18 필드 풀이 — 카테고리별 그룹화
// 근거: prompts/calculate_entry_params_v2_0.md §10 validation 표
// 사용자 지적 "17 필드" 는 stale — 실제 18 필드.

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
  { name: "stop_loss_pct_from_pivot", category: "stop", what: "pivot 대비 손절 % — O'Neil 의 7-8% 룰 적용.", constraint: "standard: −10.0 ~ −5.0%; pocket_pivot: −8.0 ~ −4.0%" },
  { name: "stop_loss_pct_from_current_price", category: "stop", what: "현재가 대비 손절 % — 추격 매수 위험 평가용.", constraint: "−15.0 ~ −3.0%" },

  // Target 목표 (2)
  { name: "expected_target_price", category: "target", what: "1차 목표가 — 부분 익절 후보 가격.", constraint: "strictly > pivot_price × 1.001" },
  { name: "expected_target_pct", category: "target", what: "pivot 대비 목표 % — O'Neil 20-30% 1차 익절 룰 적용.", constraint: "15.0 ~ 50.0%" },

  // Sizing 포지션 (1)
  { name: "suggested_weight_pct", category: "sizing", what: "포트폴리오 내 권장 비중 % — Minervini 의 거래당 1-3% 위험 룰 적용.", constraint: "3.0 ~ 25.0%" },

  // Guard 매수 가드 (3)
  { name: "pattern_basis", category: "guard", what: "이 매수가 어떤 base 패턴에 기반했는지 (flat_base / cup_with_handle / vcp / double_bottom / 3c_cheat).", constraint: "exactly one of: flat_base, cup_with_handle, vcp, double_bottom, 3c_cheat" },
  { name: "entry_window_days", category: "guard", what: "트리거 발생 후 며칠 안에 진입해야 유효한가 (1~5 일).", constraint: "integer, 1 ~ 5" },
  { name: "max_chase_pct_from_pivot", category: "guard", what: "pivot 위로 최대 몇 %까지 추격 매수 허용 (O'Neil: ≤5%).", constraint: "0.0 ~ 5.0%" },

  // Volume 거래량 (2)
  { name: "breakout_volume_requirement", category: "guard", what: "돌파일 거래량 요건 (1.4× / 1.5× 50일평균 / pocket pivot signature).", constraint: "exactly one of: ge_1.3x_50day_avg, ge_1.4x_50day_avg, ge_1.5x_50day_avg, pocket_pivot_signature" },
  { name: "observed_breakout_volume_ratio", category: "guard", what: "실제 관측된 거래량 비율 — null 또는 0.0-20.0× 사이.", constraint: "null OR 0.0 ~ 20.0" },

  // Meta 메타 (3)
  { name: "notes", category: "meta", what: "사람이 읽는 매수 노트 — entry_mode, 손절 기준, 사이징, 경고 등 종합 설명.", constraint: "50~600 글자, 필수 항목 (entry_mode, stop binding rule, sizing tier, both stop_pct, warnings) 모두 언급" },
  { name: "known_warnings", category: "meta", what: "정의된 경고 코드 목록 (whitelist 16종) — 예: 'breakout_volume_below_preferred_50pct'.", constraint: "array from §8.1 whitelist (16 codes); no duplicates" },
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
