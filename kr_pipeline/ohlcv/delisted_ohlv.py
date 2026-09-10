"""(#181 B1) 상폐 수정 OHLV 유도 — delisted_adj_prices 에 adj_open/high/low/volume 채움.

규칙(전문가 사양, 2026-09-10):
- factor = adj_close / close (행별, v5-d 체인이 남긴 adj_close 로부터 결정론 복원 — 팩터 자체는
  미저장이므로 이 비율이 유일한 원천).
- adj_open/high/low = raw × factor, adj_volume = raw ÷ factor.
- zero-bar(open=high=low=0 AND volume=0, 종가 carry) 행은 라이브 `nullify_halt_adj` 와 **동일 규칙**:
  adj_open/high/low/volume 만 NULL, **adj_close(체인값) 유지**(PR #183 Q-1 판정 (B) — 사양 초안의
  "adj_close 포함 NULL" 은 방법론 세션 오류로 plan 기록). 한 번 NULL 로 전환됐던 행은
  `restore_zero_bar_adj_close` 가 v5-d 체인 재계산(결정론·0오차)으로 복원한다.
- 라이브 daily_prices 의 adj OHLV 는 pykrx adjusted(Naver) 소스 제공값(컬럼별 독립 반올림)이라
  방식이 다르다 — 여기서는 단일 팩터 유도(반올림 없음). plan 문서 기록.
"""
from __future__ import annotations

from dataclasses import dataclass

from psycopg import Connection


@dataclass(frozen=True)
class AdjOHLV:
    adj_open: float | None
    adj_high: float | None
    adj_low: float | None
    adj_close: float | None
    adj_volume: float | None


def is_zero_bar(open_: float, high: float, low: float, volume: float) -> bool:
    """payload_builder._DAILY_NOT_ZERO_BAR / nullify_halt_adj 와 동일 판정."""
    return open_ == 0 and high == 0 and low == 0 and volume == 0


def derive_adj_ohlv(open_: float, high: float, low: float, close: float, volume: float,
                    adj_close: float | None) -> AdjOHLV:
    """순수 함수. zero-bar → OHLV·volume None, adj_close 유지(nullify_halt_adj 동형).
    adj_close 부재/close≤0 → 전부 None(유도 불가)."""
    if adj_close is None or close is None or close <= 0:
        return AdjOHLV(None, None, None, None, None)
    if is_zero_bar(open_, high, low, volume):
        return AdjOHLV(None, None, None, float(adj_close), None)
    factor = float(adj_close) / float(close)
    return AdjOHLV(
        adj_open=float(open_) * factor,
        adj_high=float(high) * factor,
        adj_low=float(low) * factor,
        adj_close=float(adj_close),
        adj_volume=float(volume) / factor if factor > 0 else None,
    )


def apply_delisted_adj_ohlv(conn: Connection, tickers: list[str] | None = None) -> dict:
    """delisted_daily_prices ⨝ delisted_adj_prices 전 행에 derive_adj_ohlv 적용 → UPDATE.
    멱등(재실행 시 같은 값). 반환: {rows, zero_bar_nulled, derived, tickers}."""
    stats = {"rows": 0, "zero_bar_nulled": 0, "derived": 0, "tickers": 0}
    with conn.cursor() as cur:
        if tickers is None:
            cur.execute("SELECT DISTINCT ticker FROM delisted_adj_prices ORDER BY 1")
            tickers = [r[0] for r in cur.fetchall()]
        for t in tickers:
            cur.execute(
                """SELECT d.date, d.open, d.high, d.low, d.close, d.volume, a.adj_close
                     FROM delisted_daily_prices d JOIN delisted_adj_prices a USING (ticker, date)
                    WHERE d.ticker = %s ORDER BY d.date""", (t,))
            rows = cur.fetchall()
            if not rows:
                continue
            cur.execute("CREATE TEMP TABLE IF NOT EXISTS _adj_ohlv_tmp (date DATE, adj_open NUMERIC(16,4), "
                        "adj_high NUMERIC(16,4), adj_low NUMERIC(16,4), adj_close NUMERIC(16,4), "
                        "adj_volume NUMERIC(20,2)) ON COMMIT DROP")
            cur.execute("TRUNCATE _adj_ohlv_tmp")
            with cur.copy("COPY _adj_ohlv_tmp (date, adj_open, adj_high, adj_low, adj_close, adj_volume) FROM STDIN") as cp:
                for d, o, h, l, c, v, ac in rows:
                    r = derive_adj_ohlv(float(o), float(h), float(l), float(c), float(v),
                                        float(ac) if ac is not None else None)
                    if r.adj_open is None:
                        stats["zero_bar_nulled"] += 1   # OHLV·volume NULL(adj_close 유지)
                    else:
                        stats["derived"] += 1
                    cp.write_row((d, r.adj_open, r.adj_high, r.adj_low, r.adj_close, r.adj_volume))
            cur.execute(
                """UPDATE delisted_adj_prices a
                      SET adj_open = t.adj_open, adj_high = t.adj_high, adj_low = t.adj_low,
                          adj_close = t.adj_close, adj_volume = t.adj_volume
                     FROM _adj_ohlv_tmp t WHERE a.ticker = %s AND a.date = t.date""", (t,))
            stats["rows"] += cur.rowcount
            stats["tickers"] += 1
            conn.commit()
    return stats


def restore_zero_bar_adj_close(conn: Connection, tickers: list[str] | None = None) -> dict:
    """(Q-1 (B)) zero-bar 행의 adj_close 가 NULL 이면 v5-d 체인 재계산값으로 복원 — 결정론, 0오차(plan §2).
    입력 로더는 scripts/issue114_delisted_adj_produce.py 와 동일(delisted_daily_prices·share_counts·
    corp_action_details, stkdp 원장). 반환 {tickers, restored}."""
    import glob
    import json
    from kr_pipeline.ohlcv.delisted_adj import produce_delisted_adj
    paths = sorted(glob.glob("data/verification/issue114_stkdp_backfill_delisted_*.json"))
    unresolved: set[str] = set()
    if paths:
        st = json.load(open(paths[-1]))
        unresolved = {r["ticker"] for r in st.get("doc_unavailable", [])} | {r["ticker"] for r in st.get("parse_fail", [])}
    stats = {"tickers": 0, "restored": 0}
    with conn.cursor() as cur:
        if tickers is None:
            cur.execute("SELECT DISTINCT ticker FROM delisted_adj_prices WHERE adj_close IS NULL ORDER BY 1")
            tickers = [r[0] for r in cur.fetchall()]
        for t in tickers:
            cur.execute("SELECT date FROM delisted_adj_prices WHERE ticker=%s AND adj_close IS NULL", (t,))
            missing = [r[0] for r in cur.fetchall()]
            if not missing:
                continue
            cur.execute("SELECT date, close FROM delisted_daily_prices WHERE ticker=%s ORDER BY date", (t,))
            closes = [(d, float(c)) for d, c in cur.fetchall()]
            cur.execute("SELECT date, shares FROM share_counts WHERE ticker=%s ORDER BY date", (t,))
            shares = {d: int(sh) for d, sh in cur.fetchall()}
            cur.execute("SELECT endpoint, record_date, ratio::float, method, rcept_no FROM corp_action_details WHERE ticker=%s", (t,))
            details = [{"endpoint": e, "record_date": rd, "ratio": rt, "method": m, "rcept_no": rn}
                       for e, rd, rt, m, rn in cur.fetchall()]
            r = produce_delisted_adj(closes, shares, details, stkdp_unresolved=(t in unresolved))
            for d in missing:
                if d in r.adj:
                    cur.execute("UPDATE delisted_adj_prices SET adj_close=%s WHERE ticker=%s AND date=%s",
                                (round(r.adj[d], 4), t, d))
                    stats["restored"] += 1
            stats["tickers"] += 1
            conn.commit()
    return stats
