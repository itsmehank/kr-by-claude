"""책 임계의 SSOT (Single Source of Truth).

모든 책-유래 임계의 단일 정의. 변경 시 영향:
- Python 코드: 자동 (이 모듈 import 참조)
- UI (TypeScript): 자동 (scripts/export_thresholds.py 가 web/src/data/thresholds.generated.ts 생성)
- Prompt (markdown): 수동 — prompts/*.md 의 텍스트 임계를 함께 갱신해야 함

본 모듈의 값은 *현재 시스템 동작* 과 일치한다 (동작 변화 0). 책 표준과
다를 수 있는 항목은 docstring 에 명시하고 별도 P0/P1 plan 에서 정합.
"""
from typing import Final

# ===== 결정론 게이트 (kr_pipeline/llm_runner/compute/trigger_gate.py) =====

GATE_BREAKOUT_VOL_MULT: Final[float] = 1.0
"""게이트의 breakout 거래량 통과 임계 (50일 평균 배수).
시스템 설계: 게이트는 '거래량 죽지 않은 정도' 만 확인, 정밀 임계 (책 표준
1.4-1.5×) 는 LLM 에 위임. TLOND p.133 BIDU 사례 (39% 거래량 돌파 = pocket
pivot) 같은 false negative 방지."""

GATE_PROMOTION_PRICE_RATIO: Final[float] = 0.95
"""watch → promotion staging 가격 임계 (pivot 비율).
시스템 자체 설계 — 책 근거 없음 (O'Neil 은 pivot 미만 매수 경고).
entry_params SQL 의 trigger_type='breakout' 필터로 매수 시그널 직행 차단."""

# ===== 신규 후보 윈도우 (kr_pipeline/llm_runner/compute/delta.py) =====

RECENT_CLASSIFICATION_WINDOW_DAYS: Final[int] = 7
"""daily_delta 의 '최근 N 일 미분류' 윈도우.
시스템 자체 설계 — 책 근거 없음."""

# ===== Minervini Trend Template (kr_pipeline/indicators/compute/minervini.py) =====

C3_SMA200_LOOKBACK_DAYS: Final[int] = 22
"""C3 의 sma_200 lookback (오늘 vs N 일 전 비교).
책: Minervini TLSMW Ch.5 / TTLC Ch.6 — '≥1 month' ≈ 22 거래일.
선호: '4-5 months minimum' — 상승 강도는 LLM 시각 판단에 위임."""

C6_W52LOW_MULT: Final[float] = 1.25
"""C6 의 52w 저점 대비 임계.
두 저작 충돌: TLSMW Ch.5 p.79 = 1.30 (30%), TTLC Ch.6 = 1.25 (25%).
최신작 (TTLC) 채택."""

C7_W52HIGH_MULT: Final[float] = 0.75
"""C7 의 52w 고점 대비 임계 (within 25% of 52w high).
책: Minervini TLSMW Ch.5 / TTLC Ch.6 공통."""

C8_RS_RATING_MIN: Final[int] = 70
"""C8 RS Rating 최소.
책: Minervini TLSMW Ch.5 'relative strength ranking ... is no less than 70'.
O'Neil HMMS 는 80+ 선호."""

# ===== RS Line 신호 윈도우 (kr_pipeline/indicators/compute/rs_line.py, modes.py) =====

RS_LINE_UPTREND_SHORT_WEEKS: Final[int] = 6
"""RS Line 단기 우상향 판정 윈도우 (주). Minervini TLSMW Ch.5 criterion 7 주석
'I like to see ... six weeks' — soft 선호 신호(게이트 아님). 일봉은 6주≈30영업일(×5)."""

RS_LINE_UPTREND_LONG_WEEKS: Final[int] = 13
"""RS Line 장기 우상향 판정 윈도우 (주). Minervini 선호 '13 weeks or more'. 일봉 13주≈65영업일(×5)."""

RS_LINE_DECLINE_GATE_WEEKS: Final[int] = 30
"""O'Neil 7개월 하락 게이트 윈도우 (주). HMMS 'L = Leader or Laggard' — RS line 7개월+ 하락 =
laggard. 7개월≈30주(설계 §9.1, 현행 28주에서 변경). 게이트는 주봉에서만 계산."""

# ===== Pocket Pivot (kr_pipeline/indicators/compute/volume.py) =====

PP_DOWN_VOL_LOOKBACK_DAYS: Final[int] = 10
"""Pocket pivot 의 직전 down-day 거래량 비교 lookback.
책: Morales & Kacher TLOND Ch.5 p.133 — 기본 10 일.
선호: 변동성 큰 종목은 11-15 일 (책 단서, 적응형 미구현)."""

# ===== Breakout Volume — 책 표준 (prompts/calculate_entry_params_v2_0.md §6.1) =====

BREAKOUT_VOL_FLOOR: Final[float] = 1.4
"""Breakout 거래량 허용 하한 (50일 평균 배수).
책: O'Neil HMMS Ch.2 p.117 — '40% to 50% above normal'. 하한 = 40% (=1.4×).
1.4×~1.5× 구간은 'preferred 미달' 경고 emit."""

BREAKOUT_VOL_PREFERRED: Final[float] = 1.5
"""Breakout 거래량 선호치 (50일 평균 배수).
책: O'Neil HMMS p.117 / p.185 — '40% to 50% above normal', 선호 50%+.
TLOND p.134 — 'standard breakout = 50% above average or more'.
2026-05-22 (P0-1): 디폴트를 1.4× → 1.5× 로 상향, 1.4× 는 허용 하한."""

# ===== Entry Params 검증 임계 (kr_pipeline/llm_runner/store.py sanity ↔
# prompts/calculate_entry_params_v2_0.md §1.3/§2/§3/§4) =====
# 2026-07-08 (P1-7): store.py 사설 상수를 SSOT 승격 — 프롬프트·검증코드가 같은
# 수치를 3중 복제하던 것을 단일화(값 변경 0, 동작 중립). 프롬프트는 SSOT 블록으로
# 수동 동기화(tests/test_prompt_threshold_drift.py 가 감시).

ENTRY_STOP_PCT_FROM_PIVOT_FLOOR: Final[float] = -10.0
"""손절 % (pivot 기준) 하한. 책: O'Neil 7-8% = 절대 상한, 프롬프트 §2 는
wide handle 케이스 흡수용 floor 를 -10 으로 클램프. store sanity SOFT 경계."""

ENTRY_TARGET_PCT_MIN: Final[float] = 15.0
ENTRY_TARGET_PCT_MAX: Final[float] = 50.0
"""기대 목표수익 % 클램프 (프롬프트 §4). 책: O'Neil 20-25% 표준 익절 ±
패턴별 가감 — 시스템 채택 범위 [15, 50]. store sanity SOFT 경계."""

ENTRY_WEIGHT_PCT_MIN: Final[float] = 3.0
ENTRY_WEIGHT_PCT_MAX: Final[float] = 25.0
"""제안 비중 % 최종 클램프 (프롬프트 §3). 책: O'Neil 집중 포트폴리오
(최대 1/4) 상한 25, 하한 3 은 시스템 채택. store sanity SOFT 경계."""

ENTRY_TRIGGER_BUFFER_MAX: Final[float] = 1.005
"""trigger_price 상한 = pivot × 이 값 (프롬프트 §1.3). IBD 운용 관행
(pivot +0.1% 산출, +0.5% 초과 = 추격) — store sanity SOFT 경계."""

# ===== (A) analyze_chart 정량 선계산·사후검증 (#23 — api/services/payload_builder.py,
# kr_pipeline/llm_runner/store.py) =====
# 앞 3종은 PR #37(#22)과 문자 단위 동일 중복 — 어느 쪽이 나중에 머지되든 충돌 해소가
# 자명하도록 정의문 일치. 의존성 맵:
# docs/superpowers/plans/2026-07-13-issue-23-a-quant-precompute.md

MARKET_DIST_DEMOTION_COUNT_25S: Final[int] = 5
"""시장 분배일(25세션) 강등/회복 co-anchor. A §3.5 강등: count >= N → entry 대신 watch
(unfavorable_market_context). B §3.5 회복: count < N 일 때만 market_recovery_ok.
책: O'Neil HMMS Ch.9 — '5~6 distribution days' 가 랠리를 꺾는다.
⚠ 양쪽이 같은 N 이어야 역류가 닫힌다(#19) — 코드는 이 상수, A 텍스트는 drift 가드."""

TT_MARGIN_MARGINAL_PCT: Final[float] = 3.0
"""Trend Template 조건의 marginal 판정 마진 % (A §2: margin < 3% = marginal pass)."""

TT_MARGINAL_DEMOTION_COUNT: Final[int] = 3
"""marginal 조건 개수 임계. A §2: 3개 이상 marginal → confidence 상한 + watch 선호
(watch_reason=marginal_tt). B tt_recovery_ok: 8조건 all pass AND marginal < 3개 (정확한 역).
marginal 계수는 A §2 정의 그대로 'PASS 하면서 margin < 3%' 인 조건만 — margin 미산출(None)·
탈락 조건은 미계수 (#37 리뷰: None 계수 시 데이터 결함이 회복을 영구 차단해 역이 깨짐).
시스템 설계 (marginal 개념은 Minervini 해설 유래, 3%/3개 수치는 시스템)."""

MARKET_DIST_NORMAL_MAX_25S: Final[int] = 3
"""A §3.5 '정상 진행' 상한 — confirmed_uptrend 이고 시장 분배일 <= N 이면 전 범위 분류 허용.
기존 프롬프트 텍스트('with ≤ 3 distribution days')의 승격 — 값 변화 0. 시스템 채택
(책은 5~6 강등만 명시). 4 개 구간(강등 임계 미만·정상 상한 초과)은 프롬프트가 원래
미규정 — 갭 보존(동작 중립)."""

PIVOT_EXTENDED_BAND_MULT: Final[float] = 1.05
"""A §8.5 entry/extended 경계 (pivot 대비 상단 밴드). current > pivot × 1.05 = extended.
O'Neil/Minervini 'pivot +5% 이내 매수' 추격 한계의 대칭 적용 (design judgment — §8.5 명시).
하단 0.95 는 GATE_PROMOTION_PRICE_RATIO 재사용 (§8.5 'promotion 임계와 정합')."""

PIVOT_PRICE_OFFSET: Final[float] = 0.1
"""A §4.7 pivot 산출 오프셋 — pivot = 기준 고점 + 0.1 (flat_base/cup_with_handle/vcp/
double_bottom). 시스템 관례 (책의 '10 cents above' 관행의 KRW 적용). store 사후검증
(sanity_pivot_offset_rule)의 기준."""

# ===== Distribution Day - 종목 레벨 (kr_pipeline/indicators/compute/volume.py) =====

STOCK_DISTRIBUTION_VOL_MULT: Final[float] = 1.0
"""종목 레벨 distribution day 의 거래량 임계 (50일 평균 배수).
2026-05-22 (P0-2): 1.25 → 1.0 정렬 — prompt §6 의 정의 (close down ≥0.2%
on volume > 1.0× of 50-day average) 와 일치. 책 표준 (O'Neil HMMS Ch.9:
'전일 거래량 초과') 의 IBD 실무 근사."""

STOCK_DISTRIBUTION_PCT_DOWN: Final[float] = -0.2
"""종목 레벨 distribution day 의 하락 컷 (% 일간 수익률, 이하 ≤).
책: O'Neil HMMS Ch.9 — 시장 레벨 DISTRIBUTION_PCT_BASE 와 같은 원전.
2026-07-10 (#20): 기존 is_down_day(0% 컷) 사용이 prompt §6 정의 (close down
≥0.2%) 와 불일치해 −0.2%~0% 하락일을 과대 집계 → 정의 정합 복원.
시장 레벨과 달리 σ 보정 미적용 (prompt §6 정의 그대로) — 보정 도입 여부는
발동률 데이터 누적 후 재검토 (B-수치). up/down volume ratio 의 is_down(0% 컷)
은 의도적으로 별개 (A/D 는 전체 하락일 대상)."""

# ===== Volume Dry-up (kr_pipeline/indicators/compute/volume.py) =====

VOLUME_DRY_UP_MULT: Final[float] = 0.5
"""volume_dry_up 의 거래량 임계 (50일 평균 배수).
책 명시 아님 — community standard."""

# ===== P2-1a: Market volatility correction (한국시장 보정) =====

NASDAQ_REFERENCE_SIGMA: Final[float] = 1.0
"""정상 시장 NASDAQ 일간 % σ (단순수익률 기준).
책 명시 없음 — TLOND p.232-233 의 FTD 1.0-1.5% 임계 밴드의 분모로 implied.
Regime shift 시 재도출. 단위 정합: 임계 비교 대상 (FTD 1.4% / distribution
-0.2%) 이 단순수익률이므로 σ 도 단순수익률 기준 (log 아님)."""

FTD_PCT_BASE: Final[float] = 1.4
"""NASDAQ 기준 FTD 임계 (% 일간 상승).
책: TLOND p.232-233 (2003 NASDAQ).
한국 임계 = FTD_PCT_BASE × ratio_applied."""

DISTRIBUTION_PCT_BASE: Final[float] = -0.2
"""NASDAQ 기준 시장 distribution day 임계 (% 일간 하락).
책: O'Neil HMMS Ch.9 + IBD/Dr.K 통용. TLOND p.231 -0.1% 선호 (해석본) —
원전 우선으로 -0.2% 채택. 거래량 조건 (전일 초과) 은 별도 인자 (보정 제외).
한국 임계 = DISTRIBUTION_PCT_BASE × ratio_applied."""

SIGMA_WINDOW_DAYS: Final[int] = 252
"""한국 σ rolling window (1년 거래일).
환경 변화 부분적 반영. EWMA 등 동적 가중은 미적용 (단순 우선)."""

SIGMA_MIN_DATA_RATIO: Final[float] = 200 / 252
"""σ 측정 최소 데이터 비율. window_days * min_data_ratio 미만이면 None 반환
→ book_default_thresholds 로 fallback. 약 0.79 (200/252 거래일)."""

KOREAN_SIGMA_RATIO_FLOOR: Final[float] = 1.0
"""ratio clamp 하한. 한국 임계 ≥ 책 임계 보장 — 책의 'explosive / institutional
selling' 강도 최소 강제."""

KOREAN_SIGMA_RATIO_CEILING: Final[float] = 2.5
"""ratio clamp 상한. TLOND FTD 임계 역사 1.0-1.7% 좁은 밴드 근거 — 패닉기
한국 σ 폭증 (예: 5-6%) 시 임계 7% 이상으로 폭주 → confirmed_uptrend 봉쇄
→ 패닉 직후 매수 구간 통째 누락 방지. 평시 한국 σ 2.3 < 2.5 → 평시 투명.
패닉기에만 안전장치."""

# ===== Distribution Day - 시장 레벨 (kr_pipeline/market_context/compute/distribution_day.py) =====

# Deprecated alias — DISTRIBUTION_PCT_BASE 로 이전 (P2-1a). 다음 사이클 cleanup.
MARKET_DISTRIBUTION_PCT_THRESHOLD: Final[float] = DISTRIBUTION_PCT_BASE

MARKET_DISTRIBUTION_LOOKBACK_DAYS: Final[int] = 25
"""시장 distribution day 카운트 lookback (세션 수).
책: O'Neil HMMS Ch.9 — 25 세션."""

# ===== Follow-Through Day (kr_pipeline/market_context/compute/follow_through.py) =====

FTD_RALLY_WINDOW_MIN_DAYS: Final[int] = 3
"""FTD 발생 가능 윈도우 최소 (저점 후 일수).
책: O'Neil HMMS Ch.9 — 최소 3 일."""

FTD_RALLY_WINDOW_MAX_DAYS: Final[int] = 15
"""FTD 발생 가능 윈도우 최대.
책: O'Neil — 4-7 최적, 11 일까지 인정 (시스템은 15 일까지 허용)."""

FTD_LOW_LOOKBACK_DAYS: Final[int] = 15
"""FTD 의 rally 시작 후보 (저점) lookback.
시스템 자체 설계."""

# ===== Market Status (kr_pipeline/market_context/compute/status.py) =====

STATUS_CORRECTION_OFF_HIGH_PCT: Final[float] = -10.0
"""correction 판정의 52주 고점 대비 하락폭 임계."""

STATUS_DOWNTREND_OFF_HIGH_PCT: Final[float] = -15.0
"""downtrend 판정의 52주 고점 대비 하락폭 임계."""

STATUS_DIST_COUNT_FOR_FTD_INVALIDATION: Final[int] = 6
"""FTD 무효화 distribution 카운트 임계 (25 세션 내)."""

STATUS_FTD_RECENT_DAYS: Final[int] = 90
"""confirmed_uptrend 진입을 위해 FTD 가 유효한 최근 일수."""

STATUS_FTD_INVALIDATION_DAYS: Final[int] = 10
"""distribution 누적 후 FTD 무효화까지 일수."""

# ===== Phase 2 (i): cup-shape 결정론화 (analyze_chart_v3.md §2 트리 / handle_quality / failed_breakout) =====
# 분류: book-anchor = 책 고정 앵커(변경 금지) / heuristic = 튜닝 가능.
# 단일 스칼라 금지 — depth 는 패턴 × 시장 2축. (i) 트리는 cup 행만 소비, 나머지는 향후 다패턴 트리용.

CUP_DEPTH_MAX_NORMAL_PCT: Final[float] = 33.0
"""[book-anchor] cup 정상장 최대 depth %. O'Neil HMMS Ch.2."""

CUP_DEPTH_MAX_BEAR_RECOVERY_PCT: Final[float] = 50.0
"""[book-anchor] cup 약세장 회복(downtrend→uptrend 60세션 내) 최대 depth %.
O'Neil 예외. F3(cup depth 50% 예외 연속화)가 여기 묶임 — market_context 전환 트리거와 동시 점검."""

FLAT_BASE_DEPTH_MAX_PCT: Final[float] = 15.0
"""[book-anchor] flat base 최대 depth %. Minervini TLSMW Ch.10. (향후 다패턴 트리용 — (i) 미소비.)"""

CUP_PRIOR_UPTREND_MIN_PCT: Final[float] = 30.0
"""[book-anchor] cup 진입 전 최소 선행상승 %. O'Neil HMMS Ch.2 — 모든 cup 패턴 전제."""

FLAT_BASE_PRIOR_UPTREND_MIN_PCT: Final[float] = 20.0
"""[book-anchor] flat base 최소 선행상승 %. Minervini. (향후 다패턴 트리용 — (i) 미소비.)"""

MIN_BASE_WEEKS: Final[dict[str, int]] = {
    "cup_with_handle": 7,
    "flat_base": 5,
    "double_bottom": 7,
    "vcp": 5,
}
"""[book-anchor] 패턴별 최소 base 주수 (narrow_base 미만 기준). 현 analyze_chart_v3.md §4 표와 동일."""

HANDLE_DEPTH_BULL_MIN_PCT: Final[float] = 8.0
HANDLE_DEPTH_BULL_MAX_PCT: Final[float] = 12.0
"""[book-anchor] 정상장 핸들 깊이 밴드(피크 대비 %). O'Neil HMMS Ch.2 p.116 '8% to 12%'."""

HANDLE_LEGIT_MIN_DAYS: Final[int] = 5
"""[book-anchor] 적법 핸들 최소 길이 (≈1주 = 5거래일). Primary: Minervini (handle ≥1주, 현 analyze
§4 표). Corroborating: O'Neil HMMS Ch.2 "more than one or two weeks" (1~2주는 변동성 큰 종목 예외 floor).
**HANDLE_MIN_DAYS(=3, heuristic 계산 윈도우)와 다름** — 이건 분류 게이트(길이). 미달 → handle_status=not_formed(형성중, faulty 아님)."""

# --- handle_quality.py 이관 (heuristic) ---
HANDLE_DEEP_RATIO: Final[float] = 0.33
"""[heuristic] 컵깊이 대비 핸들깊이 비 발화 임계. **trace 필요**: 책의 8~12% 절대치
(HANDLE_DEPTH_BULL_*)와 reconcile 미완 — 현재는 휴리스틱."""

HANDLE_VOLUME_NOT_CONTRACTING_RATIO: Final[float] = 0.80
"""[heuristic] handle/base 평균거래량 비 발화 임계 (수축 안 됨)."""

HANDLE_MIN_DAYS: Final[int] = 3
"""[heuristic] handle_quality 의 handle 구간 계산 최소 윈도우 (≠ HANDLE_LEGIT_MIN_DAYS 분류 게이트)."""
BASE_MIN_DAYS: Final[int] = 5
"""[heuristic] handle_quality 의 base 구간 계산 최소 윈도우."""

HANDLE_POSITION_LOW_RATIO: Final[float] = 0.33
"""[heuristic] 핸들 하단 위치 가중(단독 트리거 아님)."""

# --- failed_breakout.py 이관 (heuristic) ---
FAILED_BREAKOUT_K_DAYS: Final[int] = 5
"""[heuristic] 2-F 돌파(D0) 후 실패 관찰 윈도우 (거래일). 시간상수 — 비율조정 부적절, B-수치."""
FAILED_BREAKOUT_CONSECUTIVE_BELOW: Final[int] = 2
"""[heuristic] 2-F 실패 판정 연속 pivot-하회 일수. 시간상수 — B-수치(사례 누적 후 재조정)."""

# --- 허용밴드 (heuristic · calibration-target) ---
MEASUREMENT_TOLERANCE_PCT: Final[float] = 5.0
"""[heuristic · calibration-target] LLM 측정값 경계 허용밴드 %. **고정상수 아님** —
shape 가 LLM 소유라 밴드폭이 안정성의 load-bearing 변수. 재측정(plan Task 11)의 'depth read
회차간 분산'으로 보정. 5% 는 잠정 시작값(사용자 ±5% 노이즈 정책)."""

# ===== Climax run — §6.1 게이트 (prompts/analyze_chart_v3.md) =====

CLIMAX_GAIN_PCT: Final[float] = 25.0
"""[PRESERVES] climax 가속 상승률 임계 (max(1~3주) 수익률). O'Neil HMMS p.262-263,
Minervini TTLC Ch.9 ('25-50% in 1-3 weeks')."""
CLIMAX_GAIN_WINDOW_WEEKS: Final[int] = 3
"""[PRESERVES] climax 상승률 측정 창 상한(주). HMMS p.262-263 '1-2 weeks', TTLC '1-3 weeks'."""

CLIMAX_UP_DAYS_PCT: Final[float] = 70.0
"""[PRESERVES] climax T4 트리거: 윈도우 내 상승일 비율 임계. TTLC Ch.9 / HMMS p.263 (#4)."""
CLIMAX_UP_DAYS_WINDOW_MIN: Final[int] = 7
CLIMAX_UP_DAYS_WINDOW_MAX: Final[int] = 15
"""[PRESERVES] T4 상승일 측정 윈도우 (거래일 7~15). TTLC Ch.9."""

CLIMAX_MATURITY_WEEKS: Final[int] = 18
"""숫자 [PRESERVES] HMMS p.263 ('usually at least 18 weeks out of a first- or second-
stage base'); **적용은 EXTENDS** — advance-start 앵커에 묶은 hard P1 게이트는 시스템 채택.
drift 테스트 목적 = '이 값 변경 시 §6.1 climax 게이트 재검증 필요' 신호 (책 변경 감지 아님)."""
CLIMAX_LATE_MATURITY_WEEKS: Final[int] = 12
"""숫자 [PRESERVES] HMMS p.263 ('12 weeks or more if ... later-stage base'); 적용 EXTENDS (위와 동일)."""

# ===== Topping/distribution — §6.2 게이트 =====

TOPPING_BELOW_10W_WEEKS: Final[int] = 8
"""[PRESERVES] topping T-B: 10주선 아래 연속 주 임계. O'Neil HMMS p.269 ('living below
the 10-week line for 8-9 weeks')."""

STOCK_DISTRIBUTION_COUNT_25D: Final[int] = 4
"""[DESIGN-JUDGMENT] 종목 25세션 내 분배일 카운트 임계. 분배 *개념*은 책(O'Neil),
카운트 4 는 IBD/community convention — 책 literal 아님. §6 stock-distribution flag +
§6.2 T-D 가 공유 (기존 prompt 리터럴 '4+ distribution days' 를 SSOT 로 승격)."""
