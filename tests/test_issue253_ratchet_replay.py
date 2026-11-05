"""(#253) 049430 하향 재판독 체인 재현 — 래칫 후 돌파 발화 0.

#129 §3 실측: 같은 베이스에서 pivot 23,650 → 22,050(08-29) 뒤 09-04(종가 22,450)·09-09(22,650)·
09-15(22,500) breakout_from_watch 3회, 세 종가 모두 옛 pivot 아래. 래칫 적용 후에는 트리거가
effective_pivot 23,650 을 보므로 breakout 계열이 나오지 않아야 한다(promotion 또는 None).
대조 테스트는 래칫을 "항상 새 값" 으로 패치해 같은 fixture 가 래칫 없이는 발화함을 증명한다.
"""
from datetime import date, datetime, timezone

import pytest

SYMBOL = "RAT049"
BASE_START = "2026-06-01"
# (prev_day, prev_close, trigger_day, close) — prev_close ≤ 22,050 로 fresh_cross 성립
DAYS = [
    (date(2026, 9, 3), 22000, date(2026, 9, 4), 22450),
    (date(2026, 9, 8), 22000, date(2026, 9, 9), 22650),
    (date(2026, 9, 14), 22000, date(2026, 9, 15), 22500),
]


def _result(pivot, base_high):
    return {
        "classification": "watch", "pattern": "cup_with_handle", "confidence": 0.6,
        "reasoning": "t", "risk_flags": [], "pivot_price": pivot, "pivot_basis": "handle_high",
        "base_high": base_high, "base_low": 21000.0, "base_depth_pct": 11.2,
        "base_start_date": BASE_START, "watch_reason": "valid_base_awaiting_breakout",
    }


def _seed_prices(cur):
    cur.execute(
        "INSERT INTO stocks (ticker, name, market) VALUES (%s, 'R', 'KOSPI') ON CONFLICT DO NOTHING",
        (SYMBOL,),
    )
    cur.execute("DELETE FROM weekly_classification WHERE symbol = %s", (SYMBOL,))
    cur.execute("DELETE FROM daily_indicators WHERE ticker = %s", (SYMBOL,))
    for prev_d, prev_c, d, c in DAYS:
        for dd, cc, vol in ((prev_d, prev_c, 1000000), (d, c, 2000000)):
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, volume, sma_50, avg_volume_50d, w52_high, w52_low)
                   VALUES (%s, %s, %s, %s, 21000, 1000000, 24000, 18000)
                   ON CONFLICT (ticker, date) DO UPDATE
                      SET adj_close = EXCLUDED.adj_close, volume = EXCLUDED.volume""",
                (SYMBOL, dd, cc, vol),
            )


def _classify_chain(db, mocker):
    from kr_pipeline.llm_runner.store import insert_classification
    mocker.patch(
        "kr_pipeline.llm_runner.store.apply_phase1_gates",
        side_effect=lambda conn, s, t, r: (r, None),
    )
    t0 = datetime(2026, 8, 22, 3, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc)
    insert_classification(db, symbol=SYMBOL, classified_at=t0, market="KOSPI",
                          result=_result(23650.1, 23650.0), source="weekend", llm_meta={},
                          analyzed_for_date=date(2026, 8, 22))
    insert_classification(db, symbol=SYMBOL, classified_at=t1, market="KOSPI",
                          result=_result(22050.1, 22050.0), source="weekend", llm_meta={},
                          analyzed_for_date=date(2026, 8, 29))
    db.commit()


def _gate_results(db):
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as evaluate_gate
    from kr_pipeline.llm_runner.load import get_active_with_current
    out = {}
    for _, _, d, _ in DAYS:
        row = {r["symbol"]: r for r in get_active_with_current(db, as_of=d)}[SYMBOL]
        out[d] = (row["pivot_price"], evaluate_gate(
            close=row["close"], pivot_price=row["pivot_price"], volume=row["volume"],
            avg_volume_50d=row["avg_volume_50d"], stop_loss=row["stop_loss"],
            sma_50=row["sma_50"], classification=row["classification"],
            prev_close=row["prev_close"], watch_reason=row["watch_reason"],
        ))
    return out


def test_049430_chain_no_breakout_after_lowered_reread(db, mocker):
    with db.cursor() as cur:
        _seed_prices(cur)
    db.commit()
    _classify_chain(db, mocker)
    results = _gate_results(db)
    for d, (pivot, trig) in results.items():
        assert pivot == 23650.1, (d, pivot)
        assert trig not in ("breakout", "breakout_from_watch"), (d, trig)
    # 22,450/23,650.1 = 0.9493 < 0.95 → None / 22,650/23,650.1 = 0.9577 ≥ 0.95 → promotion 잔존
    # (go_now 불가 경로) — #129 §6 "돌파 3 중 일부는 promotion 으로 남는다" 와 일치
    assert results[date(2026, 9, 4)][1] is None
    assert results[date(2026, 9, 9)][1] == "promotion"
    assert results[date(2026, 9, 15)][1] == "promotion"


def test_contrast_without_ratchet_fires_breakout_from_watch(db, mocker):
    """같은 fixture 에서 래칫을 '항상 새 값' 으로 패치하면 3일 전부 breakout_from_watch — RED 증빙."""
    mocker.patch("kr_pipeline.llm_runner.store.ratchet_pivot",
                 side_effect=lambda new, prev, cont, pat: (new, "accepted"))
    with db.cursor() as cur:
        _seed_prices(cur)
    db.commit()
    _classify_chain(db, mocker)
    results = _gate_results(db)
    assert all(p == 22050.1 and t == "breakout_from_watch" for p, t in results.values()), results
