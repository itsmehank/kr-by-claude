// LLM 분류 화면 공용 라벨·설명(#275 — ClassificationsPage 에서 추출, 목록 행과 상세 영역이 공유)
import {
  BREAKOUT_VOL_PREFERRED,
  MARKET_DISTRIBUTION_LOOKBACK_DAYS,
} from "../../data/thresholds.generated";

export const CLASSIFICATION_LABELS: Record<string, string> = {
  watch: "Watch",
  entry: "Entry",
  ignore: "Ignore",
  disqualified: "자격 상실",
  excluded_by_universe: "유니버스 배제",
};

export const CLASSIFICATION_TONES: Record<string, string> = {
  watch: "bg-tint-blue text-accent",
  entry: "bg-success-soft text-success",
  ignore: "bg-tint-stone text-muted",
  disqualified: "bg-tint-stone text-faint",
  excluded_by_universe: "bg-tint-stone text-faint",
};

export const PATTERN_DESCRIPTIONS: Record<string, string> = {
  flat_base:
    "5~7주 횡보 통합, depth ≤15% — Cup-with-handle 이후 자주 등장하는 2차 base (Box 형태).",
  cup_with_handle:
    "U자 컵 (12~33% 조정, 깊으면 50%까지) + cup 상반부에 형성된 짧은 손잡이 (8~12% pullback), 7주~수개월. O'Neil 의 가장 흔한 정통 패턴.",
  cup_without_handle:
    "U자 컵 (기준은 cup_with_handle 과 동일) — 손잡이 없이 컵 고점 돌파를 노리는 패턴 (O'Neil 5대 모델). 우측이 고점의 90%까지 회복돼야 인정. 보수 장치: 돌파 거래량 strict 1.5× + 사이징 감액 (#74).",
  vcp:
    "Volatility Contraction Pattern — 변동성과 거래량이 단계적으로 줄어드는 통합 (Minervini).",
  double_bottom:
    "W 형태 이중 바닥. 두 번째 저점이 첫 저점을 살짝 undercut(shakeout). Buy point 는 W 중앙 peak (top of middle peak, 우측). 두 번째 바닥에서 매수는 너무 이름.",
  none:
    "Base 패턴 식별되지 않음.",
  high_tight_flag:
    "4~8주에 가격 100~120%+ 상승(깃대) 후 3~6주간 25% 이내 횡보(깃발) — 매우 강한 매수 신호 (드문 패턴, O'Neil HMM 'High Tight Flag' / Minervini Power Play).",
  "3c_cheat":
    "Cup이 완성되기 전 중·하반부에서 형성되는 cheat 영역의 early entry pivot (Minervini Trade Like a Stock Market Wizard ch.10 / Think & Trade Like a Champion ch.7).",
  base_on_base:
    "1차 base 돌파 후 20~30% 상승 못 하고 위쪽에 2차 base 형성. Bear market 막판 강세 신호 (O'Neil HMM 'Base on Top of a Base').",
  ascending_base:
    "3번의 10~20% pullback이 점점 더 높은 저점에서 발생. 시장 약세기에 강한 종목 (O'Neil HMM 'Ascending Base').",
};

export const RISK_FLAG_DESCRIPTIONS: Record<string, string> = {
  climax_run:
    "1~3주에 가격 25%+ 상승 + 가장 큰 주봉/거래량 — Minervini Stage 3 climax 경고.",
  late_stage_base:
    "현재 Stage 2 advance 의 3번째 이상 base. O'Neil: base 3~4는 경계, Minervini: base 4+ 위험.",
  extended_from_ma:
    "50일 이평선 위 15%+ — 추격 진입 위험 (실무 휴리스틱; O'Neil 원전은 pivot 에서 5~10%+ 추격 시 늦은 매수).",
  faulty_pivot:
    "Pivot 의 형태적 결함 (wedging handle, handle이 base 하반부, V자 즉시 신고가, 거래량 없는 돌파 등).",
  low_volume_breakout:
    `돌파 거래량이 50일 평균의 ${BREAKOUT_VOL_PREFERRED.toFixed(1)}배 미만 (O'Neil: 50% above average 가 최소).`,
  narrow_base:
    "패턴별 최소 기간보다 짧은 base.",
  wide_and_loose:
    "주봉 변동폭이 erratic / 시장 조정 대비 2.5배 초과 — 거래 어려운 base (O'Neil).",
  prior_uptrend_insufficient:
    "직전 base 대비 20% 미만 상승 — flat_base 패턴의 prior uptrend 요건 미달 (prompt §5). C6 (52주 저점 ×1.25) 와 다른 개념.",
  volume_contraction_on_advance:
    "상승 중 거래량 감소 — 수요 약화 / 기관 매수 부족 신호 (O'Neil: lost appetite).",
  reverse_split_distortion:
    "최근 12주 내 reverse split — 가격 왜곡 가능 (실무 휴리스틱, 책 원전 아님).",
  unfavorable_market_context:
    `시장 downtrend/correction 또는 distribution day 5개 이상 (${MARKET_DISTRIBUTION_LOOKBACK_DAYS} sessions). O'Neil HMMS Ch.9 의 표준.`,
  etf_methodology_mismatch:
    "ETF/fund — Minervini/O'Neil 개별 leadership 종목 방법론 적용 안 됨.",
  security_group_not_equity:
    "증권구분이 주권·외국주권·주식예탁증권이 아님(투자회사·투융자회사·리츠·UNRESOLVED) — 방법론 대상 자산 아님(Pre-Check).",
  thin_liquidity_us_only:
    "(US only) 일평균 거래대금 $5M 미만 (실무 변형; O'Neil disciple 원전은 35~50만 주 최소).",
};

export const FIELD_TOOLTIPS = {
  pivot:
    "베이스 안에서 거래량 동반으로 이 가격을 돌파하면 buy point (Minervini/O'Neil 진입 기준).",
  base:
    "가격 통합 구간 (low~high, 형성 시작일~현재). depth = 고점 대비 저점 하락률. 매물 소화 후 새 추세 시작.",
  confidence:
    "LLM 의 분류 자신감 (0~1). 데이터 부족 / 모호한 패턴 / 시장 컨텍스트 불리 시 낮아짐.",
};
