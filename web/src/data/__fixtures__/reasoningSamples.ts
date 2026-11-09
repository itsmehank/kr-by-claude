// 실제 weekly_classification.reasoning 표본(로컬 DB 에서 복사, 2026-11-09) — 용어 사전 매칭 회귀 테스트용.

export const REASONING_SAMPLES: string[] = [
  `**시장 컨텍스트**
KOSDAQ 지수는 현재 downtrend 상태이며 최근 25세션 distribution day가 7건으로 정상 상한(3건)을 크게 초과합니다. 마지막 follow-through day는 2026-08-10, 이후 11일 경과했으나 상태는 여전히 downtrend — market_direction_gate.force_watch=true로 신규 진입이 하드룰로 차단됩니다(O'Neil HMMS Ch.9 'M' 원칙: FTD 확인 없이 신규 매수 금지). 종목 진입에 명백히 불리한 국면입니다.

**Base 구조**
2025-11 저점(3600) 대비 2026-02 고점(5990)까지 +66% 선행상승은 Gate0(30%) 통과하나, 이후 6월 저점(3525)까지 -41.2% 급락해 Gate1 정상 상한(33%)을 초과합니다. 현재 시장이 downtrend→confirmed_uptrend 전환 국면이 아니라 50% 예외도 적용 불가 → cup 계열 구조 불인정(pattern=none, rejected_gate=gate1). RS Line은 최근 6주 하락 반전(rs_line_uptrend_6w=FALSE), RS Rating도 91→88로 둔화 중입니다.

**진입 시그널**
돌파/pocket pivot 미확인. 08-21 daily.csv상 pocket_pivot_flag=TRUE가 뜨지만 시장이 confirmed_uptrend가 아니고(§4.5 요건 미충족) 유효 base(≥6주)도 부재해 근거로 사용할 수 없습니다.

**핵심 위험**
unfavorable_market_context — 시장 downtrend + distribution 7건, §3.5 하드룰로 entry 원천 차단. wide_and_loose — 41%대 급락 후 단주 폭등/재하락이 반복되는 등 자체 정상 변동성 대비 주간 스프레드가 과도해 아직 다듬어지지 않은 상태(O'Neil HMMS pp.140-143).

**결론**
Trend Template 자체는 통과했지만 marginal 조건이 4개(c1,c3,c4,c5)로 §2 강등 기준(3개↑)에 해당하고, 시장이 downtrend라 §3.5 하드룰로 entry 상한이 watch로 고정됩니다.`,

  `**Base 구조**
Trend Template 8개 조건 모두 marginal 없이 통과(RS Rating 97, Stage 2 정배열·200일선 22일 8.82% 상승)로 추세 자체는 견고합니다. 다만 base 구조는 확인 안 됨 — 7월 초 164,200원 고점 후 3주 만에 61,500원까지 -62.6% 급락(과거 climax성 급등의 흔적, history)했다가 8주 만에 131,200원까지 V자 반등했습니다. Cup 판정 시도 시 depth 62.6%가 정상 상한(33%)·베어마켓 회복 예외(50%) 모두 초과해 Gate1 탈락(pattern=none). RS Line은 8/31·9/10 52주 신고가 갱신 — leadership은 살아있으나 base 자체가 wide-and-loose 상태입니다.

**핵심 위험**
- extended_from_ma: 종가가 50일선 대비 +20.03%로 추격매수 구간, 신규 매수 부적합.
- late_stage_base: anchor(2025-02-28) 이후 80주째 진행 중인 장기 상승으로 이미 여러 베이스를 거쳐 4번째 이상 베이스로 추정.

**결론**
watch(base_forming) — 시장이 confirmed_uptrend로 전환되고 5주 이상 손잡이/평평한 조임이 형성돼 pivot이 확정되면 entry 재검토, 10주선 이탈+분배 지속 시 §6.2 topping 게이트 재평가가 필요합니다.`,

  `**Base 구조**
5월 말부터 약 19주간 고점 533,000원, 저점 461,500원 사이에서 횡보하는 flat base(평평한 기반)입니다. depth 13.4%로 15% 이내라 매물 소화는 양호합니다. pivot(돌파 매수점)은 533,000.1원입니다. 현재가 527,000원은 pivot의 98.9% 위치로 매수 구간(0.95~1.05) 안입니다.

**핵심 위험**
unfavorable_market_context — 시장이 조정 구간이고 분배일이 6일이라, 종목 셋업이 좋아도 진입을 보류해야 합니다. 또 Trend Template 8개 조건 중 4개(c1~c4)가 3% 미만의 근소한 마진으로 통과했습니다(Minervini Trend Template). 신뢰도는 0.6 이하로 제한됩니다.`,

  `**결론**
watch — TT 통과 Stage 2 주도주이나 base 형성중·시장 분배·약한 수요로 매수점 아님. climax(P2 가속이 초기 2월 돌파 대비 비-최대로 미충족)·topping(주봉 종가 58,400 > 10주선 55,220, G0 미충족) 게이트 모두 불충족이라 ignore 아님. base 조여지고 거래량 동반 돌파 + 시장 분배 해소 시 entry 승격 가능.`,
];

/** 사용자가 2026-11-09 대화에서 예로 든 용어들(그대로) */
export const USER_EXAMPLE_PHRASES: [string, string][] = [
  ["follow-through day", "follow_through_day"],
  ["downtrend", "downtrend"],
  ["flat base", "flat_base"],
  ["pocket pivot 플래그", "pocket_pivot"],
  ["confirmed_uptrend", "confirmed_uptrend"],
  ["unfavorable_market_context", "unfavorable_market_context"],
  ["climax·topping 게이트", "climax"],
  ["climax·topping 게이트", "topping"],
  ["추세 템플릿 마진", "tt_marginal"],
  ["최근 25거래일 분배일", "distribution_day"],
  ["베어장 회복 예외", "bear_recovery_exception"],
  ["선행 상승률", "prior_uptrend"],
  ["리더십", "leadership"],
  ["extended_from_ma", "extended_from_ma"],
  ["wide_and_loose", "wide_and_loose"],
  ["G0 미충족", "g0_below_10w"],
  ["조여질 여지", "tightening"],
  ["종목 셋업", "setup"],
  ["Gate0", "gate0"],
  ["pattern=none", "pattern_none"],
  ["Stage 2 확인", "stage2"],
  ["신뢰도", "confidence"],
  ["base_forming", "base_forming"],
  ["Trend Template 3개 조건(c1·c2·c4)", "trend_template"],
  ["Trend Template 3개 조건(c1·c2·c4)", "tt_conditions"],
];
