# kr_pipeline/llm_runner/compute/handle_quality.py
"""handle_quality 결정론적 계산 — 후처리 (prompt 갱신 X).

spec §3. 핵심 잣대 = 거래량 마름·핸들 내 분배 (위치 아님). low cheat 보호.
경계 불명확 → 적용 안 함 + log (silent false-negative 방지).

(#177 2026-09-10, book-fidelity — governance 1-1·1-3) 책 경계 강제 2건:
- 조건 (A) 깊이비(handle_depth/base_depth > HANDLE_DEEP_RATIO 0.33) **제거** — 책은 고점 대비 절대 8~12%
  (HANDLE_DEPTH_BULL_*, 프롬프트 §4 Gate3 담당). 비율 방식은 깊은 컵의 정상 핸들(20% 컵의 7% 핸들 = 0.35)을
  불량 처리해 책과 충돌. 정의 원문은 plans/2026-09-10-issue177-handle-quality-book-bounds.md 보존.
- 검출 핸들 창 < HANDLE_LEGIT_MIN_DAYS(5, book-anchor — HMMS "핸들은 대개 1~2주 이상") → 핸들 미형성 → 미평가
  (None). 구 HANDLE_MIN_DAYS 3 [heuristic] 삭제. 5일은 평가(경계 포함).

(#175 2026-11-06, specs/2026-11-06-issue175-handle-low-design.md §3) 구조 저점 산출 재설계:
- S4′ 손잡이 시작 = 컵 바닥 이후 `high ≥ pivot` 첫 봉, **2단 매칭**(① pivot 그대로, ② pivot−0.1: 2026-11-05 이전
  저장 행의 "+0.1" 관례 역산) — 두 기준 중 **더 이른 봉**을 쓴다(PR #263 리뷰 1: 고점 당일이 돌파 봉보다 앞서면 고점 당일).
  신규 행(pivot 정수)은 ①·② 가 같은 봉.
- S5′ 입력 창 끝 = `as_of`(= analyzed_for_date) **포함**. as_of 가 없으면 classified_at 의 KST 날짜 − 1(= KST 당일 제외, #261).
- S6′ 저점은 발화 여부와 무관하게 **항상** 산출해 `structural_low` 로 반환(저장은 store). `handle_low ≥ pivot_eff` 면 손잡이가
  아니다(손잡이는 고점 아래 형성 — HMMS p.116) → 미평가(`handle_above_pivot`). 컵 바닥 봉의 고가가 이미 pivot 이상이면 컵이 아니다
  (수정주가 재스케일 등) → 미평가(`pivot_below_cup_bottom`, 리뷰 2).
- S1 전제에서 `base_depth_pct` 제거(깊이비 조건 소멸로 소비처 없음).
- S7′ 결함 조건 교체(전문가 사실 확인 2026-11-06 Q-C): (B′) 손잡이 일평균 거래량 ≥ 손잡이 구간 첫 non-NULL 50일 평균
  (`HANDLE_VOLUME_VS_50D_MAX`, TLSMW p.226 — 구 0.80 컵 평균 비교는 책에 없음) / (D′) 분배일 ∧ 하단 마감
  (`HANDLE_SHAKEOUT_CLOSE_POS_MIN`, 상단 마감 = shakeout 긍정 — 구 "분배일 1일 = 결함" 은 책과 불일치). 극저 거래량일 수는 기록만.
반환 계약: 미평가 = None(사유 log + `compute_handle_quality_with_reason` 으로 사유 반환) / 식별 = dict(fired·reasons·weights·metrics·
structural_low) — fired=False 도 dict.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from psycopg import Connection

from kr_pipeline.common import thresholds

log = logging.getLogger(__name__)
_KST = ZoneInfo("Asia/Seoul")

# 구 "+0.1" 관례(2026-11-05 폐지 전 저장 행) 역산 폭 — KRX 정수 호가에서 유일한 비정수 가산.
_LEGACY_PIVOT_OFFSET = 0.1
_EPS = 1e-6


def _to_date(d) -> date:
    return d.date() if isinstance(d, datetime) else d


def kst_fallback_as_of(classified_at) -> date:
    """as_of(analyzed_for_date) 가 없는 호출(레거시 스크립트)의 데이터 날짜 = classified_at 의 **KST** 날짜 − 1일(그 봉까지 포함).
    (#261) 구 코드는 UTC 날짜를 썼고, 토 06:00 KST 주말 분류 = 금 21:00 UTC 라 금요일 봉이 항상 빠졌다."""
    if isinstance(classified_at, datetime) and classified_at.tzinfo is not None:
        return classified_at.astimezone(_KST).date() - timedelta(days=1)
    return _to_date(classified_at) - timedelta(days=1)


def close_position(high: float, low: float, close: float) -> float:
    """일중 범위 안 마감 위치 (close − low)/(high − low). 범위 0(high == low)이면 0.5 — 상·하단 어느 쪽도 아님(비결함)."""
    rng = high - low
    if rng <= 0:
        return 0.5
    return (close - low) / rng


def find_handle_start(rows, cup_bottom_idx: int, pivot_price: float) -> tuple[Optional[int], float, str]:
    """S4′ 2단 매칭. rows[i][1] = high. 반환 (idx | None, pivot_eff, source) — source ∈ {"exact", "minus_0_1"}.

    ① pivot 그대로 / ② pivot−0.1(구 관례 역산) 로 각각 컵 바닥 이후 첫 매칭 봉을 찾고 **더 이른 봉**을 택한다.
    ② 는 ① 보다 느슨하므로 idx② ≤ idx①; 같은 봉이면 ①(exact). 신규 행(pivot 정수)은 정수 고가에서 둘이 항상 같다.
    """
    pv = float(pivot_price)
    idx_exact = next((i for i in range(cup_bottom_idx, len(rows)) if float(rows[i][1]) >= pv - _EPS), None)
    idx_legacy = next((i for i in range(cup_bottom_idx, len(rows)) if float(rows[i][1]) >= pv - _LEGACY_PIVOT_OFFSET - _EPS), None)
    if idx_legacy is None:
        return None, pv, "exact"
    if idx_exact is not None and idx_exact <= idx_legacy:
        return idx_exact, pv, "exact"
    return idx_legacy, pv - _LEGACY_PIVOT_OFFSET, "minus_0_1"


def compute_handle_quality_with_reason(
    conn: Connection, symbol: str, classified_at, cls: dict, *, as_of: date | None = None,
) -> tuple[Optional[dict], Optional[str]]:
    """compute_handle_quality 본체 — (결과 | None, 미평가 사유 | None). 사유 문자열은 로그와 동일(readout·소급 스크립트가 소비)."""
    if cls.get("pattern") != "cup_with_handle":
        return None, f"pattern={cls.get('pattern')}"
    if cls.get("pivot_basis") != "handle_high":
        return None, f"pivot_basis={cls.get('pivot_basis')}"
    if cls.get("base_start_date") is None:
        return None, "base_start_date is None"
    if cls.get("pivot_price") is None:
        return None, "pivot_price missing"

    pivot_price = float(cls["pivot_price"])
    base_start = _to_date(cls["base_start_date"])
    end_date = _to_date(as_of) if as_of is not None else kst_fallback_as_of(classified_at)

    # daily_prices + daily_indicators 조인해 base_start ~ as_of(포함) 범위(S5′).
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.date,
                   COALESCE(p.adj_high,   p.high)   AS high,
                   COALESCE(p.adj_low,    p.low)    AS low,
                   COALESCE(p.adj_close,  p.close)  AS close,
                   COALESCE(p.adj_volume, p.volume) AS volume,
                   i.sma_50, COALESCE(i.distribution_day_flag, FALSE), i.avg_volume_50d
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %s AND p.date >= %s AND p.date <= %s
             ORDER BY p.date
            """,
            (symbol, base_start, end_date),
        )
        rows = cur.fetchall()

    if len(rows) < thresholds.BASE_MIN_DAYS + thresholds.HANDLE_LEGIT_MIN_DAYS:
        return None, f"window too short ({len(rows)} rows)"

    # S3 컵 바닥 (low 최소) → S4′ 그 이후 오른쪽 림 (high >= pivot_eff 첫 거래일, 2단 매칭).
    # 단순 "첫 high>=pivot" 는 컵 왼쪽 림을 잡으므로 cup_bottom 이후로 탐색.
    cup_bottom_idx = min(range(len(rows)), key=lambda i: float(rows[i][2]))  # rows[i][2] = low
    right_rim_idx, handle_high, pivot_eff_source = find_handle_start(rows, cup_bottom_idx, pivot_price)
    if right_rim_idx is None:
        return None, "right rim not recovered after cup bottom"
    if right_rim_idx == cup_bottom_idx:
        # 컵 바닥 봉의 고가가 이미 pivot 이상 — 바닥이 고점 아래 있지 않으니 컵이 아니다(수정주가 재스케일 vs 저장 pivot 등, 리뷰 2)
        return None, "pivot_below_cup_bottom"

    base_rows = rows[:right_rim_idx]
    handle_rows = rows[right_rim_idx:]  # right_rim 봉 포함 — 그 low 도 handle 바닥 계산에 들어감
    if len(handle_rows) < thresholds.HANDLE_LEGIT_MIN_DAYS:
        # (#177) 책 하한 미달 = 핸들 미형성(형성중) — 결함이 아니므로 미평가
        return None, f"handle not formed ({len(handle_rows)} days < HANDLE_LEGIT_MIN_DAYS)"
    if len(base_rows) < thresholds.BASE_MIN_DAYS:
        return None, f"base window too short ({len(base_rows)} days)"

    handle_low = min(float(r[2]) for r in handle_rows)
    if handle_low >= handle_high - _EPS:
        # S6′ 가드: pivot 위의 구간은 손잡이가 아니다(돌파 후 상태) — #161 이 "손절가 ≥ 트리거" 를 읽는 사고 차단
        return None, "handle_above_pivot"
    base_low = float(cls["base_low"]) if cls.get("base_low") is not None else \
        min(float(r[2]) for r in base_rows)
    base_high = float(cls["base_high"]) if cls.get("base_high") is not None else \
        max(float(r[1]) for r in base_rows)

    # (A) deep handle 깊이비 판정은 #177 로 제거 — 깊이 절대치(8~12%)는 프롬프트 §4 Gate3 담당.
    #     handle_depth_pct 는 감사 echo 로만 남긴다(장중 high/low 기준, 판정 비관여).
    handle_depth_pct = (handle_high - handle_low) / handle_high * 100.0

    # (B′) 거래량 안 마름 — 손잡이 일평균 vs 50일 평균(TLSMW p.226, HANDLE_VOLUME_VS_50D_MAX).
    #      기준 50일 평균 = 손잡이 구간 첫 non-NULL avg_volume_50d(림 봉이 지표 지연으로 NULL 이어도 평가 — 리뷰 7).
    #      전부 NULL(신규 상장 등)이면 (B′) 만 미평가(결함 아님) — 저점·(D′) 는 정상 산출.
    avg_handle_vol = sum(float(r[4]) for r in handle_rows) / len(handle_rows)
    avg50 = next((float(r[7]) for r in handle_rows if r[7] is not None and float(r[7]) > 0), None)
    if avg50 is None:
        volume_vs_50d, fired_b, b_unevaluated = None, False, True
    else:
        volume_vs_50d = avg_handle_vol / avg50
        fired_b, b_unevaluated = volume_vs_50d >= thresholds.HANDLE_VOLUME_VS_50D_MAX, False
    # 극저 거래량일(책 "one or two days when volume is extremely low" — 수치 없음) — 봉별 50일 평균 × 0.5, 기록만
    dry_up_days = sum(
        1 for r in handle_rows
        if r[7] is not None and float(r[4]) < float(r[7]) * thresholds.VOLUME_DRY_UP_MULT
    )

    # (D′) 손잡이 안 분배일 — 하단 마감(마감 위치 < HANDLE_SHAKEOUT_CLOSE_POS_MIN)만 결함, 상단 마감 = shakeout(비결함)
    dist_days = sum(1 for r in handle_rows if r[6])
    dist_days_lower = sum(
        1 for r in handle_rows
        if r[6] and close_position(float(r[1]), float(r[2]), float(r[3])) < thresholds.HANDLE_SHAKEOUT_CLOSE_POS_MIN
    )
    fired_dist = dist_days_lower >= 1

    fired = fired_b or fired_dist

    # 가중치 (E) 위치 / (F) MA50 — 단독 트리거 아님, reasons 와 함께 기록만.
    denom = (base_high - base_low)
    handle_position_low = denom > 0 and ((handle_low - base_low) / denom) < thresholds.HANDLE_POSITION_LOW_RATIO
    last = handle_rows[-1]
    last_close, last_ma50 = float(last[3]), last[5]
    handle_below_ma50 = last_ma50 is not None and last_close < float(last_ma50)

    reasons = []
    if fired_b: reasons.append("volume_not_contracting")
    if fired_dist: reasons.append("distribution_in_handle")
    weights = []
    if handle_position_low: weights.append("handle_position_low")
    if handle_below_ma50: weights.append("handle_below_ma50")

    handle_start = _to_date(handle_rows[0][0]).isoformat()
    handle_end = _to_date(handle_rows[-1][0]).isoformat()
    if not fired:
        log.info(
            "[handle_quality] checked-not-fired symbol=%s depth=%.1f%% vol_vs_50d=%s dist=%d dist_lower=%d",
            symbol, handle_depth_pct,
            None if volume_vs_50d is None else round(volume_vs_50d, 3), dist_days, dist_days_lower,
        )

    return {
        "fired": fired,
        "reasons": reasons,
        "weights": weights,
        "metrics": {
            "handle_depth_pct": round(handle_depth_pct, 2),  # (#177) echo — 판정 비관여
            "avg_volume_50d": avg50,
            "handle_avg_volume": round(avg_handle_vol, 2),
            "volume_vs_50d": None if volume_vs_50d is None else round(volume_vs_50d, 3),
            "b_unevaluated": b_unevaluated,
            "dry_up_days": dry_up_days,
            "distribution_days": dist_days,
            "distribution_days_lower_close": dist_days_lower,
            "handle_start": handle_start,
            "handle_end": handle_end,
            "handle_days": len(handle_rows),
            "handle_high": round(handle_high, 2),
            "handle_low": round(handle_low, 2),
            "pivot_eff": round(handle_high, 4),
            "pivot_eff_source": pivot_eff_source,
        },
        # (#175) 구조 저점 — 발화 여부와 무관. 저장은 store.insert_* (handle_low·handle_start·handle_end).
        "structural_low": {
            "kind": "handle_low",
            "price": round(handle_low, 4),
            "start": handle_start,
            "end": handle_end,
            "days": len(handle_rows),
        },
    }, None


def compute_handle_quality(
    conn: Connection, symbol: str, classified_at, cls: dict, *, as_of: date | None = None,
) -> Optional[dict]:
    """handle_quality 결정론적 계산.

    Returns dict(fired, reasons, weights, metrics, structural_low) 또는 None(미평가 — 적용 불가, 사유는 log.info).
    """
    result, reason = compute_handle_quality_with_reason(conn, symbol, classified_at, cls, as_of=as_of)
    if result is None:
        log.info("[handle_quality] skipped symbol=%s reason=%s", symbol, reason)
    return result
