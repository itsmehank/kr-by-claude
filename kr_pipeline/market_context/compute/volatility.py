# kr_pipeline/market_context/compute/volatility.py
"""한국시장 변동성 보정 — σ 측정 + 임계 derive.

3 순수 함수 (DB 캐시 안 함):
- compute_korean_sigma_pct: index_daily 의 1년 rolling 단순수익률 σ
- derive_market_thresholds: σ → ratio → clamp → 보정 임계
- book_default_thresholds: fallback (σ 측정 실패 시 책 기본값)

Spec: docs/superpowers/specs/2026-05-25-p2-1a-korean-market-volatility-design.md
"""
from datetime import date

import pandas as pd
from psycopg import Connection

from kr_pipeline.common.thresholds import (
    SIGMA_WINDOW_DAYS,
    SIGMA_MIN_DATA_RATIO,
)


def compute_korean_sigma_pct(
    conn: Connection,
    index_code: str,
    *,
    as_of: date,
    window_days: int = SIGMA_WINDOW_DAYS,
    min_data_ratio: float = SIGMA_MIN_DATA_RATIO,
) -> float | None:
    """한국 지수 일간 % 변화율 (단순수익률) 의 rolling 표준편차.

    단순수익률: pct_change = (close_t / close_{t-1}) - 1.
    log 수익률 (log(p_t / p_{t-1})) 아님 — 임계 비교 대상 (FTD 1.4% / dist
    -0.2%) 이 모두 단순수익률이라 단위 정합 위해.

    Look-ahead 방지: WHERE date <= as_of (당일 포함). as_of 이후 데이터는
    절대 안 봄. 백테스트 / 과거 status 재계산 안전.

    Args:
        conn: psycopg connection
        index_code: 지수 코드 (예: "1001" KOSPI, "2001" KOSDAQ)
        as_of: 측정 기준일 (당일 포함)
        window_days: 윈도우 거래일 수 (default SIGMA_WINDOW_DAYS=252)
        min_data_ratio: 최소 데이터 비율 (default SIGMA_MIN_DATA_RATIO≈0.79)

    Returns:
        float: rolling σ (% 단위, 예: 2.34 = 2.34%)
        None: 가용 row 수 < window_days * min_data_ratio → 호출단 fallback
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT close FROM index_daily
             WHERE index_code = %s AND date <= %s
             ORDER BY date DESC LIMIT %s
            """,
            (index_code, as_of, window_days),
        )
        rows = cur.fetchall()

    if len(rows) < window_days * min_data_ratio:
        return None

    # rows 는 최신 → 과거 순. pct_change 계산을 위해 reverse (오래된 → 최신).
    closes = pd.Series([float(r[0]) for r in reversed(rows)])
    returns_pct = closes.pct_change().dropna() * 100  # % 단위 단순수익률
    return float(returns_pct.std())


def derive_market_thresholds(
    sigma_pct: float,
    *,
    anchor_sigma: float,
    ftd_base: float,
    dist_base: float,
    clamp_floor: float,
    clamp_ceiling: float,
) -> dict:
    """σ → ratio → clamp → base × ratio.

    Clamp 적용 지점: ratio 에만. % 임계에 직접 clamp 금지 (SSOT 원칙 — floor/
    ceiling 값이 FTD·distribution 두 곳에 중복 정의 방지).

    절차:
        raw_ratio = sigma_pct / anchor_sigma
        ratio_applied = clamp(raw_ratio, floor=clamp_floor, ceiling=clamp_ceiling)
        ftd_pct = ftd_base * ratio_applied
        distribution_pct = dist_base * ratio_applied

    Returns:
        {
            "ftd_pct": float,             # ftd_base * ratio_applied
            "distribution_pct": float,    # dist_base * ratio_applied
            "raw_ratio": float,           # 측정값 그대로 (디버깅)
            "ratio_applied": float,       # clamp 적용 후
            "clamped": bool,              # raw_ratio != ratio_applied
            "source": "sigma_derived",
        }
    """
    raw_ratio = sigma_pct / anchor_sigma
    ratio_applied = max(clamp_floor, min(clamp_ceiling, raw_ratio))
    return {
        "ftd_pct": ftd_base * ratio_applied,
        "distribution_pct": dist_base * ratio_applied,
        "raw_ratio": raw_ratio,
        "ratio_applied": ratio_applied,
        "clamped": raw_ratio != ratio_applied,
        "source": "sigma_derived",
    }


def book_default_thresholds(*, ftd_base: float, dist_base: float) -> dict:
    """Fallback — σ 측정 실패 시 책 기본값. derive 와 동일 스키마.

    회귀 보장: 이 경로의 결과 == pre-P2-1a behavior (보정 비활성 시 결과).

    Returns:
        {
            "ftd_pct": ftd_base,          # = pre-P2-1a 값 (예: 1.4)
            "distribution_pct": dist_base, # = pre-P2-1a 값 (예: -0.2)
            "raw_ratio": None,
            "ratio_applied": 1.0,
            "clamped": False,
            "source": "book_default",
        }
    """
    return {
        "ftd_pct": ftd_base,
        "distribution_pct": dist_base,
        "raw_ratio": None,
        "ratio_applied": 1.0,
        "clamped": False,
        "source": "book_default",
    }
