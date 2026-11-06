"""handle_quality 결정론 검출기 — (#177) 책 경계: 조건 A(깊이비) 부재 가드 · 핸들 < 5일 미평가 · 5일 경계 평가 ·
B(거래량비)·D(분배일) 발화 회귀 · Gate3(프롬프트) 무영향 · 결정론 재현 (합성 데이터)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from kr_pipeline.common import thresholds
from kr_pipeline.llm_runner.compute.handle_quality import compute_handle_quality


def _seed_ohlcv(db, ticker, start: date, bars: list[tuple], *, avg50: float | None = 1000.0):
    """bars = [(high, low, close, volume, dist_flag), ...] 연속 거래일(달력일 연속 시드).
    avg50 = daily_indicators.avg_volume_50d (전 봉 동일값, None = 결측 시나리오)."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",
            (ticker, ticker),
        )
        d = start
        for (high, low, close, vol, dist) in bars:
            cur.execute(
                """
                INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (ticker, d, close, high, low, close, close, vol, vol * close),
            )
            cur.execute(
                """
                INSERT INTO daily_indicators (ticker, date, adj_close, sma_50, distribution_day_flag, avg_volume_50d)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (ticker, d, close, close * 0.95, dist, avg50),
            )
            d += timedelta(days=1)


def _cls(pattern="cup_with_handle", pivot=100.0, basis="handle_high",
         base_high=100.0, base_low=70.0, base_depth=30.0, base_start=None, classified_at=None):
    return {
        "classified_at": classified_at, "classification": "entry", "pattern": pattern,
        "pivot_price": pivot, "pivot_basis": basis, "base_high": base_high,
        "base_low": base_low, "base_depth_pct": base_depth, "base_start_date": base_start,
    }


# 검출 규칙(불변, #175 범위): cup_bottom(low 최소) → 이후 right_rim(high>=pivot) → 이후 handle.
# CUP(vol) = 컵 6봉: 좌측 림 → 바닥(low 78, idx3) → 우측 림(high 101>=100, idx5).
#   base_rows = rows[:5] (>= BASE_MIN_DAYS 5), handle_rows = rows[5:] (우측 림봉 포함).
def _cup(vol):
    return [
        (95, 90, 92, vol, False),   # idx0 좌측 림
        (93, 85, 87, vol, False),   # idx1
        (88, 80, 82, vol, False),   # idx2
        (85, 78, 80, vol, False),   # idx3 컵 바닥 (low 78)
        (94, 88, 92, vol, False),   # idx4 회복
        (101, 96, 99, vol, False),  # idx5 우측 림 (high 101 >= 100) — 핸들 1일차
    ]


def _handle(n_after_rim: int, low: float, vol: int, dist_idx: int | None = None):
    """우측 림 다음의 핸들 봉 n개 — 지정 low 로 한 번 내려갔다 회복. 핸들 길이 = n+1(림 봉 포함)."""
    bars = []
    for i in range(n_after_rim):
        lo = low if i == 1 else 98
        bars.append((99, lo, 98, vol, dist_idx is not None and i == dist_idx))
    return bars


def _run(db, ticker, bars, start, days_after, *, pivot=100.0, as_of=None, avg50: float | None = 1000.0):
    _seed_ohlcv(db, ticker, start, bars, avg50=avg50)
    cls = _cls(pivot=pivot, base_depth=30.0, base_start=start,
               classified_at=datetime.combine(start + timedelta(days=days_after), datetime.min.time(), tzinfo=timezone.utc))
    return compute_handle_quality(db, ticker, cls["classified_at"], cls, as_of=as_of)


# ---------- (#177 변경 1) 조건 A 부재 가드 ----------

def test_deep_handle_alone_does_not_fire(db):
    """깊은 핸들(depth 18% / base 30% = 구 ratio 0.6) + 거래량 마름 + 분배 없음 → 미발화(None).
    깊이 절대치는 프롬프트 §4 Gate3 담당 — 검출기는 A 조건이 없다."""
    start = date(2026, 1, 5)
    r = _run(db, "HQDEEP", _cup(1000) + _handle(5, low=82, vol=400), start, 20)
    assert r is not None and r["fired"] is False   # (#175) 비발화도 dict(structural_low 포함)
    assert not hasattr(thresholds, "HANDLE_DEEP_RATIO") and not hasattr(thresholds, "HANDLE_MIN_DAYS")


def test_metrics_have_no_ratio_a_but_echo_depth(db):
    start = date(2026, 1, 19)
    r = _run(db, "HQECHO", _cup(1000) + _handle(5, low=82, vol=2000), start, 20)
    assert r is not None and r["reasons"] == ["volume_not_contracting"]
    assert "ratio_a" not in r["metrics"] and r["metrics"]["handle_depth_pct"] == 18.0
    assert r["metrics"]["handle_low"] == 82.0 and r["metrics"]["handle_high"] == 100.0


# ---------- (#177 변경 2) 책 최소 길이 ----------

def test_handle_shorter_than_5_days_not_evaluated(db):
    """핸들 4일(림 봉 + 3) — 거래량 폭증·분배일 있어도 미평가(None): 핸들 미형성은 결함이 아님."""
    start = date(2026, 2, 2)
    r = _run(db, "HQSHORT", _cup(1000) + _handle(3, low=90, vol=3000, dist_idx=1), start, 20)
    assert r is None


def test_handle_exactly_5_days_is_evaluated(db):
    """핸들 5일(림 봉 + 4) = HANDLE_LEGIT_MIN_DAYS 경계 → 평가됨(거래량비로 발화)."""
    start = date(2026, 2, 16)
    r = _run(db, "HQFIVE", _cup(1000) + _handle(4, low=90, vol=3000), start, 20)
    assert r is not None and r["fired"] and "volume_not_contracting" in r["reasons"]
    assert r["metrics"]["handle_start"] == (start + timedelta(days=5)).isoformat()
    assert thresholds.HANDLE_LEGIT_MIN_DAYS == 5


# ---------- B·D 발화 회귀 ----------

def test_shallow_handle_dry_volume_no_dist_not_fired(db):
    start = date(2026, 3, 2)
    r = _run(db, "HQSHAL", _cup(2000) + _handle(5, low=96, vol=400), start, 20)
    assert r is not None and r["fired"] is False


def test_volume_not_contracting_fires(db):
    start = date(2026, 3, 16)
    r = _run(db, "HQVOL", _cup(1000) + _handle(5, low=96, vol=2000), start, 20)
    assert r is not None and r["reasons"] == ["volume_not_contracting"]
    assert r["metrics"]["volume_vs_50d"] >= thresholds.HANDLE_VOLUME_VS_50D_MAX


def test_distribution_in_handle_fires(db):
    start = date(2026, 4, 1)
    r = _run(db, "HQDIST", _cup(1000) + _handle(5, low=96, vol=400, dist_idx=2), start, 20)
    assert r is not None and r["reasons"] == ["distribution_in_handle"]
    assert r["metrics"]["distribution_days"] == 1


def test_not_cup_with_handle_skipped(db):
    cls = _cls(pattern="flat_base", base_start=date(2026, 5, 1),
               classified_at=datetime(2026, 5, 13, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "NOPE", cls["classified_at"], cls) is None


def test_pivot_basis_not_handle_high_skipped(db):
    cls = _cls(basis="range_high", base_start=date(2026, 5, 1),
               classified_at=datetime(2026, 5, 13, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "NOPE2", cls["classified_at"], cls) is None


def test_right_rim_never_recovered_skipped(db):
    start = date(2026, 6, 1)
    _seed_ohlcv(db, "HQNORIM", start, [(50, 40, 45, 1000, False)] * 12)
    cls = _cls(pivot=100.0, base_start=start, classified_at=datetime(2026, 6, 18, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "HQNORIM", cls["classified_at"], cls) is None


# ---------- Gate3(LLM 프롬프트) 무영향 · 결정론 재현 ----------

def test_prompt_gate3_depth_rule_unchanged():
    """검출기 A 제거는 프롬프트 §4 Gate3 의 절대 깊이(12%) 판정을 건드리지 않는다."""
    text = (Path(__file__).resolve().parents[1] / "prompts" / "analyze_chart_v3.md").read_text(encoding="utf-8")
    assert "깊이 > HANDLE_DEPTH_BULL_MAX_PCT(12%)" in text and "handle_status=faulty" in text
    assert "Handle depth ≤ 8–12% from its own peak" in text


def test_detector_is_deterministic(db):
    start = date(2026, 7, 6)
    r1 = _run(db, "HQDET", _cup(1000) + _handle(5, low=90, vol=2000, dist_idx=3), start, 20)
    cls = _cls(base_depth=30.0, base_start=start, classified_at=r1 and datetime(2026, 7, 26, tzinfo=timezone.utc))
    r2 = compute_handle_quality(db, "HQDET", cls["classified_at"], cls)
    assert r1 == r2 and r1["reasons"] == ["volume_not_contracting", "distribution_in_handle"]


def _seed_ohlcv_adj(db, ticker, start: date, bars: list[tuple]):
    """raw = garbage(×7), adj_* = real."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",
                    (ticker, ticker))
        d = start
        for (high, low, close, vol, dist) in bars:
            cur.execute(
                """INSERT INTO daily_prices
                    (ticker,date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (ticker, d, close * 7, high * 7, low * 7, close * 7, close, close, high, low, float(vol), vol * 7, vol * close * 7))
            cur.execute(
                "INSERT INTO daily_indicators (ticker,date,adj_close,sma_50,distribution_day_flag,avg_volume_50d) "
                "VALUES (%s,%s,%s,%s,%s,1000) ON CONFLICT DO NOTHING", (ticker, d, close, close * 0.95, dist))
            d += timedelta(days=1)


def test_handle_quality_uses_adjusted(db):
    start = date(2026, 5, 4)
    _seed_ohlcv_adj(db, "HQADJ", start, _cup(1000) + _handle(5, low=82, vol=2000))
    cls = _cls(base_depth=30.0, base_start=start, classified_at=datetime(2026, 5, 24, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQADJ", cls["classified_at"], cls)
    assert r is not None and r["fired"] and r["metrics"]["handle_low"] == 82.0


# ---------- (#175 2026-11-06) S4′ 2단 매칭 · S6′ 가드 · structural_low 항상 반환 ----------

def test_not_fired_returns_dict_with_structural_low(db):
    """(#175) 비발화도 None 이 아니라 fired=False + structural_low 를 돌려준다."""
    start = date(2026, 3, 2)
    r = _run(db, "HQSL", _cup(2000) + _handle(5, low=96, vol=400), start, 20)
    assert r is not None and r["fired"] is False and r["reasons"] == []
    assert r["structural_low"] == {"kind": "handle_low", "price": 96.0,
                                  "start": (start + timedelta(days=5)).isoformat(),
                                  "end": (start + timedelta(days=10)).isoformat(), "days": 6}
    assert r["metrics"]["pivot_eff_source"] == "exact" and r["metrics"]["handle_days"] == 6


def test_two_pass_recovers_legacy_plus_point_one_pivot(db):
    """구 행 pivot = 고점+0.1 — ① 매칭 없음 → ② pivot−0.1 로 고점 당일 매칭(pivot_eff_source=minus_0_1)."""
    start = date(2026, 3, 16)
    cup_eq = _cup(1000)[:5] + [(100, 96, 99, 1000, False)]          # 최고가 100 == 고점
    r = _run(db, "HQLEG", cup_eq + _handle(5, low=90, vol=2000), start, 20, pivot=100.1)
    assert r is not None and r["metrics"]["pivot_eff"] == 100.0 and r["metrics"]["pivot_eff_source"] == "minus_0_1"
    assert r["structural_low"]["price"] == 90.0 and r["metrics"]["handle_start"] == (start + timedelta(days=5)).isoformat()


def test_two_pass_keeps_first_pass_when_a_bar_exceeds_pivot(db):
    """구 행이라도 pivot 을 넘은 봉이 있으면 ① 이 현행과 같은 봉을 잡는다(기존 검출 58행 불변 보장)."""
    start = date(2026, 3, 30)
    r = _run(db, "HQEXC", _cup(1000) + _handle(5, low=90, vol=2000), start, 20, pivot=100.1)   # idx5 high 101 > 100.1
    assert r is not None and r["metrics"]["pivot_eff_source"] == "exact"
    assert r["metrics"]["handle_start"] == (start + timedelta(days=5)).isoformat()


def test_two_pass_does_not_match_when_no_bar_reaches_pivot_minus_tick(db):
    """신규 행(pivot 정수 100)에서 최고가 99 — ①·② 모두 미매칭 → 미평가(None)."""
    start = date(2026, 4, 13)
    cup99 = _cup(1000)[:5] + [(99, 96, 98, 1000, False)]
    assert _run(db, "HQ99", cup99 + _handle(5, low=90, vol=2000), start, 20, pivot=100.0) is None


def test_handle_above_pivot_is_not_a_handle(db):
    """림 봉부터 저가가 전부 pivot 이상(갭상승 돌파 상태) → handle_above_pivot 미평가(None)."""
    start = date(2026, 4, 27)
    gap_rim_and_after = [(105, 101, 104, 1000, False)] * 7          # idx5 림 봉(low 101 ≥ pivot 100) + 6봉
    assert _run(db, "HQABV", _cup(1000)[:5] + gap_rim_and_after, start, 20) is None


def test_missing_base_depth_pct_is_not_a_skip_reason(db):
    """(spec §3 S1) base_depth_pct 전제 제거 — 깊이비 조건이 #177 로 사라져 소비처 없음."""
    start = date(2026, 5, 11)
    _seed_ohlcv(db, "HQNODEP", start, _cup(1000) + _handle(5, low=96, vol=400))
    cls = _cls(base_depth=None, base_start=start, classified_at=datetime(2026, 5, 31, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "HQNODEP", cls["classified_at"], cls) is not None


# ---------- (#175 2026-11-06) S7′ 결함 조건 — (B′) 50일 평균 · (D′) 마감 위치 · 기록 지표 ----------

def test_b_rule_fires_when_handle_volume_at_or_above_50d_avg(db):
    start = date(2026, 8, 3)
    r = _run(db, "HQB1", _cup(500) + _handle(5, low=96, vol=1100), start, 20, avg50=1000.0)   # 손잡이 6봉 평균 (500+5×1100)/6 = 1000 ≥ 1000
    assert r["fired"] and r["reasons"] == ["volume_not_contracting"]
    assert r["metrics"]["volume_vs_50d"] == pytest.approx(1.0) and "ratio_b" not in r["metrics"]


def test_b_rule_not_fired_when_handle_volume_below_50d_avg_even_if_above_cup(db):
    """컵 평균(500)보다 많아도 50일 평균(1000) 미만이면 결함 아님 — 구 0.80 컵 비교와 갈리는 지점."""
    start = date(2026, 8, 17)
    r = _run(db, "HQB2", _cup(500) + _handle(5, low=96, vol=900), start, 20, avg50=1000.0)   # (500+5×900)/6 ≈ 833
    assert r["fired"] is False and r["metrics"]["volume_vs_50d"] == pytest.approx(0.8333, abs=1e-3)


def test_b_rule_unevaluated_when_avg50_null_but_low_still_returned(db):
    start = date(2026, 8, 31)
    r = _run(db, "HQB3", _cup(500) + _handle(5, low=96, vol=5000), start, 20, avg50=None)
    assert r is not None and r["fired"] is False and r["metrics"]["b_unevaluated"] is True
    assert r["metrics"]["volume_vs_50d"] is None and r["structural_low"]["price"] == 96.0


def test_distribution_day_lower_close_fires_upper_close_is_shakeout(db):
    """같은 분배 플래그라도 하단 마감(close_pos 0.11)만 결함, 상단 마감(0.78)은 shakeout → 비결함."""
    start = date(2026, 9, 14)
    lower = _cup(1000) + [(99, 98, 98, 400, False), (99, 90, 91, 2000, True), (99, 98, 98, 400, False),
                          (99, 98, 98, 400, False), (99, 98, 98, 400, False)]      # (91−90)/(99−90)=0.11
    upper = _cup(1000) + [(99, 98, 98, 400, False), (99, 90, 97, 2000, True), (99, 98, 98, 400, False),
                          (99, 98, 98, 400, False), (99, 98, 98, 400, False)]      # (97−90)/9=0.78
    r_lo = _run(db, "HQD1", lower, start, 20)
    r_up = _run(db, "HQD2", upper, start + timedelta(days=30), 20)
    assert r_lo["fired"] and r_lo["reasons"] == ["distribution_in_handle"] and r_lo["metrics"]["distribution_days_lower_close"] == 1
    assert r_up["fired"] is False and r_up["metrics"]["distribution_days"] == 1 and r_up["metrics"]["distribution_days_lower_close"] == 0


def test_distribution_day_with_zero_range_is_not_defect(db):
    start = date(2026, 10, 12)
    flat = _cup(1000) + [(99, 98, 98, 400, False), (95, 95, 95, 2000, True), (99, 98, 98, 400, False),
                         (99, 98, 98, 400, False), (99, 98, 98, 400, False)]
    r = _run(db, "HQD0", flat, start, 20)
    assert r["fired"] is False and r["metrics"]["distribution_days"] == 1 and r["metrics"]["distribution_days_lower_close"] == 0


def test_dry_up_days_counted_from_each_days_50d_avg(db):
    start = date(2026, 10, 26)
    r = _run(db, "HQDRY", _cup(1000) + _handle(5, low=96, vol=400), start, 20, avg50=1000.0)   # 림 봉 1000 제외, 5봉 400 < 500
    assert r["metrics"]["dry_up_days"] == 5 and r["fired"] is False


# ---------- (#261/#175) S5′ 창 끝 = as_of 포함(KST 거래일) ----------

def test_as_of_window_includes_friday_bar(db):
    """토 06:00 KST(= 금 21:00 UTC) 실행, as_of=금요일 → 금요일 봉이 손잡이에 포함된다(#261)."""
    start = date(2026, 6, 1)
    bars = _cup(1000) + _handle(4, low=96, vol=400)            # 10봉: 06-01~06-10(시드는 달력일 연속)
    bars.append((99, 88, 98, 400, False))                      # 06-11 저가 88
    bars.append((99, 85, 98, 400, False))                      # 06-12(금) 저가 85 ← 포함돼야 함
    _seed_ohlcv(db, "HQFRI", start, bars)
    cls = _cls(base_start=start, classified_at=datetime(2026, 6, 12, 21, 0, tzinfo=timezone.utc))  # 토 06:00 KST
    r = compute_handle_quality(db, "HQFRI", cls["classified_at"], cls, as_of=date(2026, 6, 12))
    assert r is not None and r["structural_low"]["price"] == 85.0 and r["structural_low"]["end"] == "2026-06-12"


def test_as_of_window_excludes_bars_after_as_of(db):
    start = date(2026, 6, 15)
    bars = _cup(1000) + _handle(5, low=96, vol=400) + [(99, 50, 98, 400, False)]   # 마지막 봉(06-26) 저가 50 은 as_of 뒤
    _seed_ohlcv(db, "HQAFT", start, bars)
    cls = _cls(base_start=start, classified_at=datetime(2026, 6, 27, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQAFT", cls["classified_at"], cls, as_of=date(2026, 6, 25))
    assert r is not None and r["structural_low"]["price"] == 96.0 and r["structural_low"]["end"] == "2026-06-25"


def test_fallback_without_as_of_uses_kst_date(db):
    """as_of 생략(레거시 스크립트) — KST 날짜 폴백. 금 21:00 UTC = 토 KST → 금요일 봉 포함(구 UTC 폴백이면 제외)."""
    start = date(2026, 7, 6)
    bars = _cup(1000) + _handle(4, low=96, vol=400) + [(99, 88, 98, 400, False), (99, 85, 98, 400, False)]  # 07-16·07-17(금)
    _seed_ohlcv(db, "HQKST", start, bars)
    cls = _cls(base_start=start, classified_at=datetime(2026, 7, 17, 21, 0, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQKST", cls["classified_at"], cls)
    assert r is not None and r["structural_low"]["price"] == 85.0


def test_right_rim_matches_when_high_equals_pivot(db):
    """(2026-11-05 "+0.1" 가산 폐지) pivot = 손잡이 고점 그대로 → 고점 당일(high == pivot)이 우측 림 = 핸들 시작으로
    매칭된다. 구 관례(pivot = 고점+0.1)에서는 이 봉이 `high >= pivot` 에 안 걸려 림 미회복(#175 명세 §7-1, 124행 중 101행)."""
    start = date(2026, 3, 2)
    cup_eq = _cup(2000)[:5] + [(100, 96, 99, 2000, False)]      # idx5 high == pivot(100)
    r_eq = _run(db, "HQEQ1", cup_eq + _handle(5, low=90, vol=2000), start, 20)   # 거래량 안 마름 → 발화해 metrics 노출
    r_gt = _run(db, "HQEQ2", _cup(2000) + _handle(5, low=90, vol=2000), start, 20)  # 대조: high 101 > 100
    assert r_eq is not None and r_gt is not None
    assert r_eq["metrics"]["handle_start"] == r_gt["metrics"]["handle_start"]
    assert r_eq["metrics"]["handle_high"] == 100.0 and r_eq["metrics"]["handle_low"] == 90.0


# ---------- (#175 PR #263 코드 리뷰 반영) ----------

def test_two_pass_prefers_earliest_bar_for_legacy_rows(db):
    """리뷰 1: 구 행(pivot=H+0.1)에서 고점 당일(high == H)이 돌파 봉보다 앞서면 ② 가 잡는 **앞 봉**이 손잡이 시작이어야 한다
    (돌파 후 되돌림 저점이 handle_low 로 저장되는 것 방지)."""
    start = date(2026, 11, 2)
    bars = _cup(1000)[:5] + [(100, 96, 99, 1000, False),      # idx5 손잡이 고점 당일(high == 100)
                             (105, 101, 104, 3000, False)]    # idx6 돌파 봉(high 105 > 100.1)
    bars += [(103, 95, 98, 400, False)] + [(99, 97, 98, 400, False)] * 4   # 돌파 후 되돌림 저가 95
    r = _run(db, "HQEARLY", bars, start, 20, pivot=100.1)
    assert r is not None and r["metrics"]["pivot_eff_source"] == "minus_0_1"
    assert r["metrics"]["handle_start"] == (start + timedelta(days=5)).isoformat()
    assert r["structural_low"]["price"] == 95.0 and r["metrics"]["handle_days"] == 7


def test_cup_bottom_bar_reaching_pivot_is_scale_mismatch(db):
    """리뷰 2: 컵 바닥 봉의 고가가 이미 pivot 이상(= 모든 봉이 pivot 위에서 거래, 수정주가 재스케일 등) → 컵이 아님 → 미평가(None)."""
    start = date(2026, 11, 16)
    lows = [95, 94, 93, 92, 91, 90, 91, 92, 93, 94, 95, 96]           # 컵 바닥 idx5(low 90) — 앞 5봉이 베이스 하한을 넘김
    bars = [(110, lo, 100, 1000, False) for lo in lows]               # 전 봉 high 110 ≥ pivot 100 → 바닥 봉이 곧 "림"
    assert _run(db, "HQSCALE", bars, start, 20) is None


def test_with_reason_returns_skip_reason():
    """리뷰 4: 스킵 사유를 로그 파싱이 아니라 반환값으로."""
    from kr_pipeline.llm_runner.compute.handle_quality import compute_handle_quality_with_reason
    cls = _cls(pattern="flat_base", base_start=date(2026, 5, 1), classified_at=datetime(2026, 5, 13, tzinfo=timezone.utc))
    assert compute_handle_quality_with_reason(None, "X", cls["classified_at"], cls) == (None, "pattern=flat_base")


def test_b_rule_uses_first_non_null_avg50_in_handle(db):
    """리뷰 7: 림 봉의 avg_volume_50d 만 NULL 이면 손잡이 안 첫 non-NULL 값으로 (B′) 평가."""
    start = date(2026, 11, 30)
    bars = _cup(1000) + _handle(5, low=96, vol=2000)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('HQNUL1','HQNUL1','KOSPI') ON CONFLICT DO NOTHING")
        d = start
        for i, (high, low, close, vol, dist) in enumerate(bars):
            cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        ("HQNUL1", d, close, high, low, close, close, vol, vol * close))
            cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close, sma_50, distribution_day_flag, avg_volume_50d) "
                        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        ("HQNUL1", d, close, close * 0.95, dist, None if i == 5 else 1000.0))   # idx5 = 림 봉만 NULL
            d += timedelta(days=1)
    cls = _cls(base_start=start, classified_at=datetime(2026, 12, 20, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQNUL1", cls["classified_at"], cls)
    assert r is not None and r["metrics"]["b_unevaluated"] is False and r["fired"] and "volume_not_contracting" in r["reasons"]
