"""단일 매매 단위 손절 변형 시뮬레이션 — 2026-07-06 사용자 요청 테스트. 읽기전용·결정론.

동결 100종목(2021-01-01~2024-12-31 watch/entry 분류) 대상, 지정된 규칙 그대로:

- watch/entry 종목의 pivot 돌파일, 거래량 > 50일 평균 거래량이면 pivot 가격에 매수
  (watch_reason 무관 — 사용자 지시에 그 조건이 없어 그대로 반영. entry 분류는
  fresh_cross 요구 없이 close>pivot 만으로 발화, watch 분류는 fresh_cross 요구.
  production 트리거의 사유 게이트(§3.5)는 미적용 — 이번 테스트 전용 단순화).
- 초기 손절 = 매수가(pivot) − 8%. 단 **진입일** 그 종목 시장(KOSPI/KOSDAQ)의 국면이
  하락기(downtrend 또는 correction — 기존 DOWN_PHASES 관례를 "하락장"에 적용,
  design-judgment)면 − 6%.
- 수익률 +20% 최초 도달 시 손절을 매수가(0%, 본전)로 상향(래치 — 이후 해제 없음).
- 매일 그날의 50일 이동평균선이 "현재 유효 손절가"보다 높으면 손절가를 그 값으로
  교체(하향 조정 없음 — max() 로 자연 구현).
  유효 손절가 = max(초기 손절가, 본전(armed 이후), 50일선(그 값이 더 높을 때만)).
- 종가가 유효 손절가 아래로 마감하면 그날 종가에 전량 청산.
- 추격 상한·거래비용·재시도 상한 등 이전 실험(v1~v4)의 부가 규칙은 이번 지시에
  없으므로 미적용 — 이번 테스트는 그 실험들과 별개의 단순 버전.

  python -m kr_pipeline.backtest.stop_variant_sim   # 전 종목 실행 + JSON 저장
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from psycopg import Connection

from kr_pipeline.backtest import phases as ph
from kr_pipeline.backtest.backfill import BT_TABLE
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.profitability_run import DOWN_PHASES, _market_of
from kr_pipeline.backtest.trigger_sim import DayBar, WatchRow, _active_row, load_daily_series

WATCH_START, WATCH_END = date(2021, 1, 1), date(2024, 12, 31)
PX_START, PX_END = date(2020, 7, 1), date(2025, 6, 30)

STOP_NORMAL_PCT = 0.08
STOP_DOWNTREND_PCT = 0.06
BREAKEVEN_TRIGGER_PCT = 0.20


@dataclass
class ClsRow:
    sat: date
    pivot_price: float | None
    classification: str   # 'watch' | 'entry'


@dataclass
class VTrade:
    ticker: str
    entry_date: date
    entry_price: float
    entry_classification: str
    entry_phase: str | None
    initial_stop_pct: float
    exit_date: date | None
    exit_price: float | None
    pnl_pct: float | None
    exit_reason: str | None   # 'initial_stop' | 'breakeven' | 'sma50_trail' | 'open'


def load_watch_entry_rows(conn: Connection, ticker: str, start: date,
                         end: date) -> list[ClsRow]:
    """watch·entry 분류(pivot_price 有)를 전부 가져온다 — watch_reason 무관."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT analyzed_for_date, pivot_price, classification
              FROM {BT_TABLE}
             WHERE symbol = %s AND classification IN ('watch', 'entry')
               AND pivot_price IS NOT NULL
               AND analyzed_for_date BETWEEN %s AND %s
             ORDER BY analyzed_for_date
            """,
            (ticker, start, end),
        )
        return [ClsRow(sat=r[0], pivot_price=float(r[1]), classification=r[2])
                for r in cur.fetchall()]


def simulate_ticker(ticker: str, rows: list[ClsRow], bars: list[DayBar],
                    phase_map: list[tuple[date, str]],
                    exclude_down_phases: bool = False) -> tuple[list[VTrade], int]:
    """지정 규칙 그대로의 단일-포지션 순차 매매 시뮬레이션(동시 보유 없음).

    exclude_down_phases=True 면 진입일 국면이 DOWN_PHASES(하락·조정)인 신호는
    스킵(2026-07-07 사용자 요청 — 하락장 배제 변형). 반환: (trades, n_skipped_down_phase).
    """
    rows = sorted(rows, key=lambda r: r.sat)
    bars = sorted(bars, key=lambda b: b.d)
    trades: list[VTrade] = []
    cur: VTrade | None = None
    armed = False
    effective_stop = 0.0
    entered_pivots: set[date] = set()
    n_skipped_down = 0

    # ClsRow -> WatchRow 형 어댑터 (sat 기준 최신 활성 행 탐색에 _active_row 재사용)
    as_watchrows = [WatchRow(ticker=ticker, sat=r.sat, pivot_price=r.pivot_price,
                             base_low=None, watch_reason=None) for r in rows]
    cls_by_sat = {r.sat: r.classification for r in rows}

    for b in bars:
        if cur is not None:
            candidates = [cur.entry_price * (1 - cur.initial_stop_pct)]
            if not armed and b.close >= cur.entry_price * (1 + BREAKEVEN_TRIGGER_PCT):
                armed = True
            if armed:
                candidates.append(cur.entry_price)
            if b.sma_50 is not None:
                candidates.append(b.sma_50)   # max() 가 "더 높을 때만 교체"를 구현
            effective_stop = max(candidates)
            if b.close < effective_stop:
                binding = max(
                    (("initial_stop", candidates[0]),
                     *([("breakeven", cur.entry_price)] if armed else []),
                     *([("sma50_trail", b.sma_50)] if b.sma_50 is not None else [])),
                    key=lambda x: x[1],
                )[0]
                cur.exit_date, cur.exit_price = b.d, b.close
                cur.pnl_pct = round((b.close / cur.entry_price - 1) * 100, 2)
                cur.exit_reason = binding
                trades.append(cur)
                cur, armed = None, False
            continue

        active = _active_row(as_watchrows, b.d)
        if active is None or b.sma_50 is None or b.avg_volume_50d is None:
            continue
        if active.sat in entered_pivots:
            continue
        classification = cls_by_sat[active.sat]
        vol_ok = b.volume > b.avg_volume_50d   # "50일 평균보다 큰" — 엄격 초과
        if classification == "entry":
            triggered = b.close > active.pivot_price and vol_ok
        else:  # watch — fresh cross 요구
            fresh = (b.prev_close is not None and b.prev_close <= active.pivot_price
                     and b.close > active.pivot_price)
            triggered = fresh and vol_ok
        if not triggered:
            continue

        phase = ph.phase_at(phase_map, b.d)
        if exclude_down_phases and phase in DOWN_PHASES:
            n_skipped_down += 1
            continue
        stop_pct = STOP_DOWNTREND_PCT if phase in DOWN_PHASES else STOP_NORMAL_PCT
        cur = VTrade(ticker=ticker, entry_date=b.d, entry_price=b.close,
                    entry_classification=classification, entry_phase=phase,
                    initial_stop_pct=stop_pct, exit_date=None, exit_price=None,
                    pnl_pct=None, exit_reason=None)
        entered_pivots.add(active.sat)

    if cur is not None and bars:
        last = bars[-1]
        cur.exit_date, cur.exit_price = last.d, last.close
        cur.pnl_pct = round((last.close / cur.entry_price - 1) * 100, 2)
        cur.exit_reason = "open"
        trades.append(cur)

    return trades, n_skipped_down


def run_all(conn: Connection, tickers: list[str] | None = None,
           exclude_down_phases: bool = False) -> tuple[dict[str, list[VTrade]], int]:
    pmaps: dict[str, list] = {}
    per_ticker: dict[str, list[VTrade]] = {}
    n_skipped_total = 0
    for ticker in (tickers if tickers is not None else FROZEN_SAMPLE):
        market = _market_of(conn, ticker)
        code = ph.INDEX_OF.get(market, "1001")
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
        rows = load_watch_entry_rows(conn, ticker, WATCH_START, WATCH_END)
        if not rows:
            per_ticker[ticker] = []
            continue
        bars = load_daily_series(conn, ticker, PX_START, PX_END)
        trades, n_skip = simulate_ticker(ticker, rows, bars, pmaps[code],
                                         exclude_down_phases=exclude_down_phases)
        per_ticker[ticker] = trades
        n_skipped_total += n_skip
    return per_ticker, n_skipped_total


def _trade_dict(t: VTrade) -> dict:
    return {
        "entry_date": str(t.entry_date), "entry_price": round(t.entry_price, 2),
        "entry_classification": t.entry_classification, "entry_phase": t.entry_phase,
        "initial_stop_pct": round(t.initial_stop_pct * 100, 1),
        "exit_date": str(t.exit_date) if t.exit_date else None,
        "exit_price": round(t.exit_price, 2) if t.exit_price else None,
        "pnl_pct": t.pnl_pct, "exit_reason": t.exit_reason,
    }


def build_report(per_ticker: dict[str, list[VTrade]], n_skipped_down: int = 0) -> dict:
    tickers_out = []
    all_closed: list[VTrade] = []
    for ticker, trades in per_ticker.items():
        closed = [t for t in trades if t.exit_reason != "open"]
        opened = [t for t in trades if t.exit_reason == "open"]
        all_closed.extend(closed)
        wins = [t for t in closed if t.pnl_pct > 0]
        tickers_out.append({
            "ticker": ticker,
            "n_trades": len(trades),
            "n_closed": len(closed),
            "n_open": len(opened),
            "win_rate": round(len(wins) / len(closed), 3) if closed else None,
            "total_pnl_pct": round(sum(t.pnl_pct for t in closed), 2) if closed else 0.0,
            "avg_pnl_pct": round(sum(t.pnl_pct for t in closed) / len(closed), 2)
            if closed else None,
            "best_pnl_pct": max((t.pnl_pct for t in closed), default=None),
            "worst_pnl_pct": min((t.pnl_pct for t in closed), default=None),
            "trades": [_trade_dict(t) for t in trades],
        })
    wins_all = [t for t in all_closed if t.pnl_pct > 0]
    losses_all = [t for t in all_closed if t.pnl_pct <= 0]
    by_stop = {}
    for label, pct in (("normal_8pct", STOP_NORMAL_PCT), ("downtrend_6pct", STOP_DOWNTREND_PCT)):
        grp = [t for t in all_closed if abs(t.initial_stop_pct - pct) < 1e-9]
        by_stop[label] = {
            "n": len(grp),
            "win_rate": round(sum(1 for t in grp if t.pnl_pct > 0) / len(grp), 3) if grp else None,
            "avg_pnl_pct": round(sum(t.pnl_pct for t in grp) / len(grp), 2) if grp else None,
        }
    by_reason: dict[str, int] = {}
    for t in all_closed:
        by_reason[t.exit_reason] = by_reason.get(t.exit_reason, 0) + 1
    return {
        "params": {"stop_normal_pct": STOP_NORMAL_PCT, "stop_downtrend_pct": STOP_DOWNTREND_PCT,
                  "breakeven_trigger_pct": BREAKEVEN_TRIGGER_PCT,
                  "down_phases_definition": list(DOWN_PHASES)},
        "n_skipped_down_phase": n_skipped_down,
        "n_tickers": len(per_ticker),
        "n_tickers_with_trades": sum(1 for v in per_ticker.values() if v),
        "n_trades_total": sum(len(v) for v in per_ticker.values()),
        "n_closed_total": len(all_closed),
        "n_open_total": sum(len(v) for v in per_ticker.values()) - len(all_closed),
        "win_rate_overall": round(len(wins_all) / len(all_closed), 3) if all_closed else None,
        "avg_pnl_overall": round(sum(t.pnl_pct for t in all_closed) / len(all_closed), 2)
        if all_closed else None,
        "sum_pnl_overall": round(sum(t.pnl_pct for t in all_closed), 2),
        "mean_win_pnl": round(sum(t.pnl_pct for t in wins_all) / len(wins_all), 2) if wins_all else None,
        "mean_loss_pnl": round(sum(t.pnl_pct for t in losses_all) / len(losses_all), 2) if losses_all else None,
        "by_initial_stop": by_stop,
        "by_exit_reason": by_reason,
        "tickers": sorted(tickers_out, key=lambda x: -x["total_pnl_pct"]),
    }


def main() -> int:
    from kr_pipeline.db.connection import connect
    with connect() as conn:
        per_ticker, n_skip = run_all(conn)
        report = build_report(per_ticker, n_skip)
    with open("data/backtest/stop_variant_20260706.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    summary = {k: v for k, v in report.items() if k != "tickers"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
