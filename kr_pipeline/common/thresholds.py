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

# ===== Distribution Day - 종목 레벨 (kr_pipeline/indicators/compute/volume.py) =====

STOCK_DISTRIBUTION_VOL_MULT: Final[float] = 1.0
"""종목 레벨 distribution day 의 거래량 임계 (50일 평균 배수).
2026-05-22 (P0-2): 1.25 → 1.0 정렬 — prompt §6 의 정의 (close down ≥0.2%
on volume > 1.0× of 50-day average) 와 일치. 책 표준 (O'Neil HMMS Ch.9:
'전일 거래량 초과') 의 IBD 실무 근사."""

# ===== Volume Dry-up (kr_pipeline/indicators/compute/volume.py) =====

VOLUME_DRY_UP_MULT: Final[float] = 0.5
"""volume_dry_up 의 거래량 임계 (50일 평균 배수).
책 명시 아님 — community standard."""

# ===== Distribution Day - 시장 레벨 (kr_pipeline/market_context/compute/distribution_day.py) =====

MARKET_DISTRIBUTION_PCT_THRESHOLD: Final[float] = -0.2
"""시장 지수 distribution day 의 일간 하락 임계 (%).
책: IBD/O'Neil 통용 -0.2%. TLOND p.231 는 -0.1% 선호 (해석본).
원전 우선 — -0.2% 유지."""

MARKET_DISTRIBUTION_LOOKBACK_DAYS: Final[int] = 25
"""시장 distribution day 카운트 lookback (세션 수).
책: O'Neil HMMS Ch.9 — 25 세션."""

# ===== Follow-Through Day (kr_pipeline/market_context/compute/follow_through.py) =====

FTD_PCT_THRESHOLD: Final[dict[str, float]] = {
    "KOSPI": 1.4,
    "KOSDAQ": 1.4,
}
"""FTD 일간 상승 임계 (%, 시장별).
책: TLOND p.232-233 — NASDAQ 1.4% (2003) / 1.5% (2010), S&P 1.1% (2004).
'한 나라 두 지수도 다른 임계' 권장. 현재 KOSPI/KOSDAQ 동일 — P2-1a 에서
한국 시장 변동성 측정 후 시장별 보정 예정."""

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
