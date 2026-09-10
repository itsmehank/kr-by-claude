"""(#181 B1) 상폐 수정 OHLV 유도 — delisted_adj_prices 에 adj_open/high/low/volume 채움.

규칙(전문가 사양, 2026-09-10):
- factor = adj_close / close (행별, v5-d 체인이 남긴 adj_close 로부터 결정론 복원 — 팩터 자체는
  미저장이므로 이 비율이 유일한 원천).
- adj_open/high/low = raw × factor, adj_volume = raw ÷ factor.
- zero-bar(open=high=low=0 AND volume=0, 종가 carry) 행은 nullify_halt_adj 규칙대로 adj_* 전부
  NULL — **adj_close 포함**(기존 값이 있던 행도 NULL 전환; 사유 = 거래정지일의 carry 종가는 수정
  OHLV 없이 단독 존재하면 산술 오염원, 라이브 daily 규약과 동형).
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
    """순수 함수. zero-bar → 전부 None. adj_close 부재/close≤0 → 전부 None(유도 불가)."""
    if is_zero_bar(open_, high, low, volume) or adj_close is None or close is None or close <= 0:
        return AdjOHLV(None, None, None, None, None)
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
                    if r.adj_close is None:
                        stats["zero_bar_nulled"] += 1
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
