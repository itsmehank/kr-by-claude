"""결정론 트리거+P&L 시뮬레이션 코어. trigger_gate.evaluate 를 그대로 호출(재구현 금지).

읽기전용 분석 도구. 프로덕션은 이 모듈을 import 하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from psycopg import Connection

from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as gate_evaluate, ALLOWED_WATCH_REASONS

# shadow 모드에서 watch_reason 적격 게이트만 우회(가격/거래량/fresh_cross 로직은 동일 유지).
_SHADOW_REASON = "valid_base_awaiting_breakout"


@dataclass
class WatchRow:
    ticker: str
    sat: date
    pivot_price: float | None
    base_low: float | None
    watch_reason: str | None


@dataclass
class DayBar:
    d: date
    close: float
    volume: int
    sma_50: float | None
    avg_volume_50d: float | None
    prev_close: float | None


@dataclass
class Trade:
    ticker: str
    watch_reason: str | None
    pivot_sat: date
    pivot_price: float
    base_low: float | None
    entry_date: date
    entry_close: float
    exit_date: date | None
    exit_close: float | None
    pnl_pct: float | None
    binding_exit: str | None   # 'base_low' | 'sma_50' | 'open'


def _active_row(rows: list[WatchRow], d: date) -> WatchRow | None:
    """sat<=d 인 가장 최근 pivot 보유 watch row (rows 는 sat 오름차순 가정)."""
    cur = None
    for r in rows:
        if r.sat <= d:
            cur = r
        else:
            break
    return cur


def simulate(ticker: str, watch_rows: list[WatchRow], day_bars: list[DayBar],
             *, mode: str) -> tuple[list[Trade], int]:
    """일별 walk 로 트리거 발화→진입→청산 시뮬. mode: 'production'|'shadow'.

    production: watch_reason 을 그대로 전달(비적격은 자연 불발). shadow: 적격 사유로 치환해
    가격/거래량/fresh_cross 로직만 태움(이유 게이트 우회). 반환 (trades, promotion_count).
    """
    if mode not in ("production", "shadow"):
        raise ValueError(f"mode must be 'production' or 'shadow', got {mode!r}")
    rows = sorted([r for r in watch_rows if r.pivot_price is not None], key=lambda r: r.sat)
    bars = sorted(day_bars, key=lambda b: b.d)
    trades: list[Trade] = []
    promotion_count = 0
    cur: Trade | None = None
    last_entry_pivot_sat: date | None = None

    for b in bars:
        active = _active_row(rows, b.d)
        if active is None or b.sma_50 is None or b.avg_volume_50d is None:
            continue
        # 보유 중이면 진입 시점 base_low 로 invalidation 판정; 아니면 active 의 base_low.
        stop_for_gate = cur.base_low if cur is not None else active.base_low
        # shadow 치환은 *진입*(breakout_from_watch) 게이트 우회용. invalidation 은 평가순서상 가장 먼저이고
        # watch_reason 비의존이라, 이 치환은 청산 동작을 바꾸지 않는다(청산은 production 과 동일).
        reason_for_gate = _SHADOW_REASON if mode == "shadow" else active.watch_reason
        sig = gate_evaluate(
            close=b.close,
            pivot_price=active.pivot_price,
            volume=b.volume,
            avg_volume_50d=b.avg_volume_50d,
            stop_loss=stop_for_gate,
            sma_50=b.sma_50,
            classification="watch",
            prev_close=b.prev_close,
            watch_reason=reason_for_gate,
        )
        if cur is not None:
            if sig == "invalidation":
                binding = "base_low" if (cur.base_low is not None and b.close < cur.base_low) else "sma_50"
                cur.exit_date = b.d
                cur.exit_close = b.close
                cur.pnl_pct = (b.close / cur.entry_close - 1) * 100
                cur.binding_exit = binding
                trades.append(cur)
                cur = None
        else:
            if sig == "breakout_from_watch":
                if last_entry_pivot_sat == active.sat:
                    continue  # 재진입 상한: 같은 pivot 재진입 금지
                cur = Trade(
                    ticker=ticker, watch_reason=active.watch_reason, pivot_sat=active.sat,
                    pivot_price=active.pivot_price, base_low=active.base_low,
                    entry_date=b.d, entry_close=b.close,
                    exit_date=None, exit_close=None, pnl_pct=None, binding_exit=None,
                )
                last_entry_pivot_sat = active.sat
            elif sig == "promotion" and mode == "production":
                promotion_count += 1

    if cur is not None and bars:
        last = bars[-1]
        cur.exit_date = last.d
        cur.exit_close = last.close
        cur.pnl_pct = (last.close / cur.entry_close - 1) * 100
        cur.binding_exit = "open"
        trades.append(cur)

    return trades, promotion_count


def _nearest_on_or_before(series: dict[date, float], d: date) -> float | None:
    cands = [k for k in series if k <= d]
    return series[max(cands)] if cands else None


def market_relative(trade: Trade, index_series: dict[date, float]) -> float | None:
    """트레이드 보유기간 지수수익을 차감한 초과수익%. 데이터 없으면 None."""
    if trade.pnl_pct is None or trade.exit_date is None:
        return None
    base = _nearest_on_or_before(index_series, trade.entry_date)
    end = _nearest_on_or_before(index_series, trade.exit_date)
    if base is None or end is None or base == 0:
        return None
    index_pct = (end / base - 1) * 100
    return trade.pnl_pct - index_pct


_INDEX_CODE = {"KOSPI": "1001", "KOSDAQ": "2001"}


def load_watchlist(conn: Connection, ticker: str, start: date, end: date,
                   table: str = "classification_backfill") -> list[WatchRow]:
    if table not in ("classification_backfill", "backtest_classification"):
        raise ValueError(f"load_watchlist: unknown table {table!r}")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT analyzed_for_date, pivot_price, base_low, watch_reason
              FROM {table}
             WHERE symbol = %s AND classification = 'watch'
               AND analyzed_for_date BETWEEN %s AND %s
             ORDER BY analyzed_for_date
            """,
            (ticker, start, end),
        )
        return [
            WatchRow(ticker=ticker, sat=r[0],
                     pivot_price=float(r[1]) if r[1] is not None else None,
                     base_low=float(r[2]) if r[2] is not None else None,
                     watch_reason=r[3])
            for r in cur.fetchall()
        ]


def load_daily_series(conn: Connection, ticker: str, start: date, end: date) -> list[DayBar]:
    with conn.cursor() as cur:
        # adj_volume 사용 — gate 의 avg_volume_50d(=daily_indicators, adj 기준)와 단위 일치(raw 쓰면 기업행위 종목 오발화). cf. payload_raw_vs_adj_volume_mismatch
        cur.execute(
            """
            SELECT p.date, p.adj_close, p.adj_volume, i.sma_50, i.avg_volume_50d,
                   LAG(p.adj_close) OVER (ORDER BY p.date) AS prev_close
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %s AND p.date BETWEEN %s AND %s
             ORDER BY p.date
            """,
            (ticker, start, end),
        )
        return [
            DayBar(d=r[0], close=float(r[1]), volume=int(float(r[2])) if r[2] is not None else 0,
                   sma_50=float(r[3]) if r[3] is not None else None,
                   avg_volume_50d=float(r[4]) if r[4] is not None else None,
                   prev_close=float(r[5]) if r[5] is not None else None)
            for r in cur.fetchall()
        ]


def load_index_series(conn: Connection, market: str, start: date, end: date) -> dict[date, float]:
    code = _INDEX_CODE[market]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, close FROM index_daily WHERE index_code = %s AND date BETWEEN %s AND %s",
            (code, start, end),
        )
        return {r[0]: float(r[1]) for r in cur.fetchall()}


def classify_rows(watch_rows: list[WatchRow]) -> dict:
    """production(적격 reason+pivot) / shadow(비적격 reason+pivot) / census(pivot 없음) 분류."""
    production, shadow, census = [], [], []
    for r in watch_rows:
        if r.pivot_price is None:
            census.append(r)
        elif r.watch_reason in ALLOWED_WATCH_REASONS:
            production.append(r)
        else:
            shadow.append(r)
    return {"production": production, "shadow": shadow, "census": census}
