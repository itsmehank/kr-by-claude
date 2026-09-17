"""(#181 P0-② 배관) B1 adj OHLV 유도 · B2 주봉 · B3 지표 · B4 리졸버/분기 · B5 강제청산 · B6 prompt_version."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest

from kr_pipeline.common.price_source import DELISTED, LIVE, price_source
from kr_pipeline.ohlcv.delisted_ohlv import AdjOHLV, apply_delisted_adj_ohlv, derive_adj_ohlv, is_zero_bar

D0 = date(2020, 1, 6)  # 월요일


# ---------- B1 순수 함수 ----------

def test_derive_adj_ohlv_single_factor():
    r = derive_adj_ohlv(100.0, 110.0, 90.0, 100.0, 1000.0, adj_close=50.0)   # factor 0.5
    assert r == AdjOHLV(50.0, 55.0, 45.0, 50.0, 2000.0)


def test_derive_adj_ohlv_zero_bar_keeps_adj_close_only():
    # (PR #183 Q-1 (B)) nullify_halt_adj 동형: OHLV·volume None, adj_close(체인값) 유지
    assert is_zero_bar(0, 0, 0, 0)
    assert derive_adj_ohlv(0, 0, 0, 100.0, 0, adj_close=50.0) == AdjOHLV(None, None, None, 50.0, None)
    assert derive_adj_ohlv(100, 110, 90, 100.0, 10, adj_close=None) == AdjOHLV(None, None, None, None, None)


# ---------- 시드 헬퍼: 격리 상폐 종목 1개(600거래일) ----------

def _seed_delisted(db, ticker, n_days=600, halt_days=(300, 301), split_at=200):
    """delisted_daily_prices(raw) + delisted_adj_prices(adj_close only, 체인 결과 흉내: split_at 이전 factor 0.5)."""
    with db.cursor() as cur:
        for tbl in ("delisted_daily_indicators", "delisted_weekly_prices", "delisted_adj_prices", "delisted_daily_prices"):
            cur.execute(f"DELETE FROM {tbl} WHERE ticker=%s", (ticker,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (ticker,))
        cur.execute("DELETE FROM stocks WHERE ticker=%s", (ticker,))
        cur.execute("INSERT INTO stocks (ticker, name, market, delisted_at) VALUES (%s,%s,'KOSPI',%s)",
                    (ticker, ticker, D0 + timedelta(days=n_days + 1)))
        d = D0
        dates = []
        while len(dates) < n_days:
            if d.weekday() < 5:
                dates.append(d)
            d += timedelta(days=1)
        for i, dd in enumerate(dates):
            raw = 200.0 if i < split_at else 100.0   # 1:2 분할 흉내
            close = raw + (i % 7)
            if i in halt_days:
                cur.execute("INSERT INTO delisted_daily_prices (ticker,date,open,high,low,close,volume,value) VALUES (%s,%s,0,0,0,%s,0,0)",
                            (ticker, dd, close))
                cur.execute("INSERT INTO delisted_adj_prices (ticker,date,adj_close,liq_window) VALUES (%s,%s,%s,%s)",
                            (ticker, dd, close * (0.5 if i < split_at else 1.0), i >= n_days - 10))
            else:
                cur.execute("INSERT INTO delisted_daily_prices (ticker,date,open,high,low,close,volume,value) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (ticker, dd, close, close * 1.02, close * 0.98, close, 1000 + i, (1000 + i) * close))
                cur.execute("INSERT INTO delisted_adj_prices (ticker,date,adj_close,liq_window) VALUES (%s,%s,%s,%s)",
                            (ticker, dd, close * (0.5 if i < split_at else 1.0), i >= n_days - 10))
    db.commit()
    return dates


def _cleanup(db, ticker):
    with db.cursor() as cur:
        for tbl in ("delisted_daily_indicators", "delisted_weekly_prices", "delisted_adj_prices", "delisted_daily_prices"):
            cur.execute(f"DELETE FROM {tbl} WHERE ticker=%s", (ticker,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (ticker,))
        cur.execute("DELETE FROM stocks WHERE ticker=%s", (ticker,))
    db.commit()


def test_b1_apply_derives_ohlv_and_nulls_zero_bar(db):
    dates = _seed_delisted(db, "DLST1")
    st = apply_delisted_adj_ohlv(db, ["DLST1"])
    assert st["tickers"] == 1 and st["rows"] == 600 and st["zero_bar_nulled"] == 2 and st["derived"] == 598
    with db.cursor() as cur:
        cur.execute("SELECT adj_open, adj_high, adj_low, adj_close, adj_volume FROM delisted_adj_prices WHERE ticker=%s AND date=%s",
                    ("DLST1", dates[10]))
        o, h, l, c, v = [float(x) for x in cur.fetchone()]
        raw = 200.0 + 10 % 7
        assert c == pytest.approx(raw * 0.5) and o == pytest.approx(raw * 0.5) and h == pytest.approx(raw * 1.02 * 0.5)
        assert l == pytest.approx(raw * 0.98 * 0.5) and v == pytest.approx(1010 / 0.5)
        cur.execute("SELECT adj_open, adj_close, adj_volume FROM delisted_adj_prices WHERE ticker=%s AND date=%s", ("DLST1", dates[300]))
        o, c, v = cur.fetchone()
        assert o is None and v is None and float(c) == pytest.approx((100.0 + 300 % 7) * 1.0)  # adj_close 유지
        cur.execute("SELECT count(*) FROM delisted_daily_prices_adj WHERE ticker=%s AND adj_close IS NULL", ("DLST1",))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM delisted_daily_prices_adj WHERE ticker=%s AND adj_open IS NULL", ("DLST1",))
        assert cur.fetchone()[0] == 2
    _cleanup(db, "DLST1")


# ---------- B4 리졸버 ----------

def test_price_source_live_vs_delisted(db):
    assert price_source(db, "NOSUCH") == LIVE
    assert price_source(db, "NOSUCH", rs_source="bt").rs == "bt_rs_daily"
    with pytest.raises(ValueError):
        price_source(db, "NOSUCH", rs_source="x")
    _seed_delisted(db, "DLST2", n_days=60)
    assert price_source(db, "DLST2") == DELISTED and price_source(db, "DLST2").delisted
    _cleanup(db, "DLST2")


# ---------- B2 · B3 · B4 payload 경로 (격리 종목 end-to-end) ----------

def test_b2_b3_b4_delisted_end_to_end(db):
    from api.services.payload_builder import (
        _build_current_metrics, _fetch_daily_ohlcv, _fetch_daily_since, _fetch_indicators_recent,
        _fetch_minervini_pass_series, _fetch_weekly_full, _fetch_weekly_ohlcv,
    )
    from kr_pipeline.backtest.trigger_sim import load_daily_series
    from kr_pipeline.indicators.delisted import build_delisted_indicators
    from kr_pipeline.trade_management.held_climax import fetch_daily_flagged
    from kr_pipeline.weekly.delisted import build_delisted_weekly
    dates = _seed_delisted(db, "DLST3")
    apply_delisted_adj_ohlv(db, ["DLST3"])
    w = build_delisted_weekly(db, ["DLST3"])
    assert w["tickers"] == 1 and 110 <= w["rows"] <= 125
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM weekly_prices WHERE ticker=%s", ("DLST3",))
        assert cur.fetchone()[0] == 0   # 라이브 주봉 무접촉
        cur.execute("SELECT count(*) FROM delisted_weekly_prices WHERE ticker=%s AND adj_high IS NOT NULL", ("DLST3",))
        assert cur.fetchone()[0] >= 110
    # B3 — 지표: KOSPI index_daily 는 conftest 시드 여부에 따라 비어 있을 수 있음 → rs_line NULL 허용, 나머지 수치 존재
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM index_daily WHERE index_code='1001' AND date BETWEEN %s AND %s", (dates[0], dates[-1]))
        has_idx = cur.fetchone()[0] > 0
    if not has_idx:
        with db.cursor() as cur:
            for dd in dates:
                cur.execute("INSERT INTO index_daily (index_code, date, open, high, low, close, volume) VALUES ('1001',%s,100,100,100,100,0) ON CONFLICT DO NOTHING", (dd,))
        db.commit()
    st = build_delisted_indicators(db, ["DLST3"])
    assert st["tickers"] == 1 and st["rows"] == 600   # zero-bar 행도 adj_close(체인값) 보유 → 포함(라이브 동형)
    with db.cursor() as cur:
        cur.execute("SELECT sma_50, w52_high, minervini_c1, rs_rating, minervini_pass FROM delisted_daily_indicators WHERE ticker=%s AND date=%s",
                    ("DLST3", dates[-1]))
        sma50, w52h, c1, rs, mp = cur.fetchone()
        assert sma50 is not None and w52h is not None and c1 is not None
        assert rs is None and mp is None   # bt_rs_daily 없음 → c8/pass 미정의(null=보수)
        cur.execute("SELECT count(*) FROM daily_indicators WHERE ticker=%s", ("DLST3",))
        assert cur.fetchone()[0] == 0    # 라이브 지표 무접촉
    # B4 — payload 헬퍼 8개가 격리 테이블을 읽고 라이브와 같은 스키마를 낸다
    on = dates[-1]
    d60 = _fetch_daily_ohlcv(db, "DLST3", on, days=60)
    assert len(d60) == 60 and set(d60[0]) == {"date", "open", "high", "low", "close", "volume"}
    assert d60[-1]["close"] == pytest.approx(100.0 + 599 % 7)   # adj(=raw, factor 1.0 구간)
    ds = _fetch_daily_since(db, "DLST3", dates[290], on)
    assert any(r["zero_bar"] for r in ds) and set(ds[0]) >= {"zero_bar", "adj_hl"}
    wk = _fetch_weekly_full(db, "DLST3", on)
    assert len(wk) >= 110 and set(wk[0]) == {"week_end", "open", "high", "low", "close", "volume", "gap_before", "adj_hl"}
    assert len(_fetch_weekly_ohlcv(db, "DLST3", on)) == 104
    ind = _fetch_indicators_recent(db, "DLST3", on, days=60)
    assert len(ind) == 60 and ind[-1]["sma_50"] is not None and "minervini_pass" in ind[-1]
    assert len(_fetch_minervini_pass_series(db, "DLST3", on)) == 64
    cm = _build_current_metrics(db, "DLST3", on)
    assert cm["close"] is not None and cm["w52_high"] is not None
    flagged = fetch_daily_flagged(db, "DLST3", on)
    assert len(flagged) == 600 and sum(r["zero_bar"] for r in flagged) == 2
    bars = load_daily_series(db, "DLST3", dates[0], on)
    assert len(bars) == 600 and bars[-1].sma_50 is not None   # zero-bar 도 adj_close 보유(라이브 동형)
    _cleanup(db, "DLST3")


def test_get_qualifying_tickers_include_delisted_default_off(db):
    from kr_pipeline.llm_runner.load import get_qualifying_tickers
    _seed_delisted(db, "DLST4", n_days=60)
    on = date(2020, 3, 27)
    with db.cursor() as cur:
        cur.execute("INSERT INTO delisted_daily_indicators (ticker, date, adj_close, minervini_pass, rs_line_not_declining_7m) "
                    "VALUES (%s,%s,100,TRUE,TRUE)", ("DLST4", on))
        cur.execute("INSERT INTO delisted_adj_prices (ticker,date,adj_close,adj_low,liq_window) VALUES (%s,%s,100,99,FALSE) "
                    "ON CONFLICT (ticker,date) DO UPDATE SET adj_low=99", ("DLST4", on))
        cur.execute("INSERT INTO delisted_daily_prices (ticker,date,open,high,low,close,volume,value) VALUES (%s,%s,100,101,99,100,10,1000) "
                    "ON CONFLICT DO NOTHING", ("DLST4", on))
        cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close) VALUES ('DLST4', %s, 100) ON CONFLICT DO NOTHING", (on,))
    db.commit()
    live = {r["symbol"] for r in get_qualifying_tickers(db, as_of=on)}
    assert "DLST4" not in live
    both = {r["symbol"] for r in get_qualifying_tickers(db, as_of=on, include_delisted=True)}
    assert "DLST4" in both
    only = get_qualifying_tickers(db, as_of=on, tickers=["DLST4"], include_delisted=True)
    assert [r["symbol"] for r in only] == ["DLST4"]
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_indicators WHERE ticker='DLST4'")
    db.commit()
    _cleanup(db, "DLST4")


# ---------- B5 백테스트 강제청산 ----------

from tests.test_trade_held_climax import _bars, _tdata  # noqa: E402


def _delisted_td(bars, last_bar, liq_days=14):
    td = _tdata(bars)
    td.delisted, td.last_bar, td.liq_start = True, last_bar, last_bar - timedelta(days=liq_days)
    return td


def test_backtest_delisted_forced_exit_on_last_bar(mocker):
    import kr_pipeline.backtest.portfolio as pf
    start = date(2024, 1, 8)
    seq = [(98, 200, 96), (104, 200, 97)] + [(104 + i * 0.5, 200, 97) for i in range(1, 30)]
    bars = _bars(start, seq)
    last = bars[-1].d
    r = pf.run_portfolio({"T": _delisted_td(bars, last)}, pf.PortfolioConfig())
    assert r["stats"]["exit_reasons"] == {"delisted": 1}
    ex = r["stats"]["exits"][0]
    assert ex["date"] == last.isoformat() and ex["also"] == []
    assert r["stats"]["n_entries_in_liq_window"] == 0   # 진입(2일차)은 창 밖


def test_backtest_stop_precedes_delisted_and_delisted_precedes_decline(mocker):
    import kr_pipeline.backtest.portfolio as pf
    from tests.test_trade_held_decline import _hd
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (104, 200, 97), (90, 200, 97)])
    mocker.patch.object(pf, "evaluate_held_decline", return_value=_hd())
    r = pf.run_portfolio({"T": _delisted_td(bars, bars[-1].d)}, pf.PortfolioConfig())
    assert r["stats"]["exit_reasons"] == {"stop8": 1}   # 같은 날 스탑이면 stop
    bars2 = _bars(start, [(98, 200, 96), (104, 200, 97), (105, 200, 97)])
    r2 = pf.run_portfolio({"T": _delisted_td(bars2, bars2[-1].d)}, pf.PortfolioConfig())
    assert r2["stats"]["exit_reasons"] == {"delisted": 1}  # delisted > decline


def test_backtest_entry_inside_liq_window_is_counted_not_blocked():
    import kr_pipeline.backtest.portfolio as pf
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (104, 200, 97), (105, 200, 97), (106, 200, 97)])
    td = _delisted_td(bars, bars[-1].d, liq_days=30)   # 창이 진입일을 포함
    r = pf.run_portfolio({"T": td}, pf.PortfolioConfig())
    assert r["stats"]["n_entries"] == 1 and r["stats"]["n_entries_in_liq_window"] == 1
    assert r["stats"]["exit_reasons"] == {"delisted": 1}


def test_backtest_survivor_path_unchanged():
    import kr_pipeline.backtest.portfolio as pf
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (104, 200, 97)] + [(104 + i * 0.5, 200, 97) for i in range(1, 30)])
    r = pf.run_portfolio({"T": _tdata(bars)}, pf.PortfolioConfig())
    assert r["stats"]["exit_reasons"] == {} and r["stats"]["n_entries_in_liq_window"] == 0


# ---------- B6 prompt_version ----------

def test_prompt_version_hash_recorded_in_meta(monkeypatch):
    from kr_pipeline.llm_runner.llm import claude_cli
    text = (claude_cli.PROMPTS_DIR / "analyze_chart_v3.md").read_text(encoding="utf-8")
    expect = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    meta: dict = {}
    calls = {}

    def fake_run(*a, **k):
        raise RuntimeError("stop-after-hash")
    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        claude_cli.call_claude(prompt_file="analyze_chart_v3.md", payload_inline={"x": 1}, meta_out=meta)
    assert meta.get("prompt_version") == expect and len(expect) == 12


def test_prompt_version_stored_in_weekly_and_backfill(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification, insert_classification
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('PVER1','p','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM weekly_classification WHERE symbol='PVER1'")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='PVER1'")
    db.commit()
    res = {"classification": "watch", "watch_reason": "base_forming", "pattern": "none", "confidence": 0.5,
           "reasoning": "x", "risk_flags": []}
    meta = {"duration_s": 1.0, "input_tokens": 1, "output_tokens": 1, "model": "m", "prompt_version": "abcdef012345"}
    insert_classification(db, symbol="PVER1", classified_at=datetime(2026, 9, 5, tzinfo=timezone.utc), market="KOSPI",
                          result=dict(res), source="weekend", llm_meta=meta)
    insert_backfill_classification(db, symbol="PVER1", classified_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
                                   analyzed_for_date=date(2026, 9, 5), market="KOSPI", result=dict(res),
                                   source="backtest", llm_meta=meta, table="backtest_classification")
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT prompt_version FROM weekly_classification WHERE symbol='PVER1'")
        assert cur.fetchone()[0] == "abcdef012345"
        cur.execute("SELECT prompt_version FROM backtest_classification WHERE symbol='PVER1'")
        assert cur.fetchone()[0] == "abcdef012345"
        cur.execute("DELETE FROM weekly_classification WHERE symbol='PVER1'")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='PVER1'")
        cur.execute("DELETE FROM stocks WHERE ticker='PVER1'")
    db.commit()


def test_b3_delisted_gate_is_forward_only_and_reads_stocks_security_group(db):
    """(Q-5 3번째 지점) 격리 산출도 SSOT 게이트: 기준일 이후+비허용 → NULL, 이전 → 산출. security_group 은 stocks 에서."""
    from datetime import timedelta
    from kr_pipeline.common.security_group import SECURITY_GROUP_GATE_EFFECTIVE_DATE as EFF
    from kr_pipeline.indicators.delisted import compute_delisted_rows
    import pandas as pd
    n = 300
    dates = [EFF - timedelta(days=n - 1 - i) for i in range(n)]      # 마지막 날 = EFF
    df = pd.DataFrame({"date": dates, "adj_close": [100.0 + i for i in range(n)],
                       "adj_high": [101.0 + i for i in range(n)], "adj_low": [99.0 + i for i in range(n)],
                       "adj_volume": [1e6] * n})
    idx = pd.DataFrame({"date": dates, "close": [1000.0 + i for i in range(n)]})
    rs = {d: 95 for d in dates}
    rows_q = compute_delisted_rows("DLQ", df, idx, rs, None, security_group="주권")
    rows_x = compute_delisted_rows("DLX", df, idx, rs, None, security_group="투자회사")
    last_q, last_x = rows_q[-1], rows_x[-1]
    assert last_q["date"] == EFF and last_x["date"] == EFF
    assert last_x["minervini_pass"] is None                              # 기준일 당일 비허용 → NULL
    assert rows_x[-2]["minervini_pass"] == rows_q[-2]["minervini_pass"]  # 기준일 이전 → 동일 산출(재산출 금지)
    assert last_x["minervini_c8"] is True                                # c8 은 그대로
