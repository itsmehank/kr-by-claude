"""(#47) 일일 손절 평가 러너 — open 포지션마다 evaluate_stop 호출·기록·알림.

스펙 §3 불변 계약 준수:
- anchor = positions.entry_price (매수 시점 고정) — 분류 테이블의 pivot/base_low
  를 조회조차 하지 않는다(구조적 유입 차단, D4 체크리스트).
- 래치(breakeven_armed)는 positions 에 영속 — 해제 없음(단조 True).
- halt 센티널(close<=0)·봉 부재는 평가 skip (stop_stack 규약 — 러너가 거름).
- 재분류·abort 상태와 독립 — 분류 테이블 미참조.

close 원천 = daily_prices.close (raw): 당일 봉의 raw == 당일 adj (수정주가는 현재
앵커)라 sma_50(adj 기반)과 스케일 일관. 보유 중 기업행위 발생 시 entry_price 만
과거 스케일로 남는 한계는 corp_action_after_entry 경고로 노출(수동 기록 모델 —
사용자가 entry_price 재조정).
"""
from __future__ import annotations

import json
import logging
from datetime import date

from psycopg import Connection

from kr_pipeline.llm_runner.slack import notify_stop_triggered
from kr_pipeline.trade_management.stop_stack import evaluate_stop
from kr_pipeline.trade_management.store import get_open_positions

log = logging.getLogger("kr_pipeline.trade_management")


def _latest_bar_date(conn: Connection) -> date | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(date) FROM daily_prices")
        row = cur.fetchone()
    return row[0] if row else None


def run_daily_eval(conn: Connection, *, as_of: date | None = None) -> dict:
    """open 포지션 전체를 as_of 종가로 평가. 멱등: (position_id, eval_date).

    as_of 미지정 → daily_prices 최신 날짜(일봉 체인 완료 후 cron 실행 규약).
    반환: {"as_of", "evaluated", "triggered", "skipped": [{symbol, reason}]}.
    """
    if as_of is None:
        as_of = _latest_bar_date(conn)
        if as_of is None:
            return {"as_of": None, "evaluated": 0, "triggered": 0, "skipped": []}

    evaluated = 0
    triggered = 0
    skipped: list[dict] = []

    for p in get_open_positions(conn):
        # (리뷰) backdated 재실행 차단 — 이미 더 나중 날짜가 평가된 포지션에 과거
        # as_of 를 새로 평가하면 현재 래치가 과거에 소급 적용(시대착오)되고, 과거
        # raw close 와 현재 앵커 sma_50 의 스케일 불일치 위험도 있다. 기존 행이
        # 있는 날짜의 재실행은 ON CONFLICT 멱등으로 무해 — 신규 과거일만 거부.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(eval_date) FROM position_stop_evaluations "
                "WHERE position_id = %s",
                (p["id"],),
            )
            last_eval = cur.fetchone()[0]
        if last_eval is not None and as_of < last_eval:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM position_stop_evaluations "
                    "WHERE position_id = %s AND eval_date = %s",
                    (p["id"], as_of),
                )
                exists = cur.fetchone() is not None
            if not exists:
                skipped.append({"symbol": p["symbol"], "reason": "backdated_as_of"})
                continue

        with conn.cursor() as cur:
            cur.execute(
                "SELECT close FROM daily_prices WHERE ticker = %s AND date = %s",
                (p["symbol"], as_of),
            )
            bar = cur.fetchone()
        if bar is None:
            skipped.append({"symbol": p["symbol"], "reason": "no_bar"})
            continue
        close = float(bar[0]) if bar[0] is not None else 0.0
        if close <= 0:
            skipped.append({"symbol": p["symbol"], "reason": "halt_bar"})
            continue

        with conn.cursor() as cur:
            cur.execute(
                "SELECT sma_50 FROM daily_indicators WHERE ticker = %s AND date = %s",
                (p["symbol"], as_of),
            )
            row = cur.fetchone()
        sma_50 = float(row[0]) if row and row[0] is not None else None

        warnings: list[str] = []
        with conn.cursor() as cur:
            # 경계 >= : 매수 당일 발효 기업행위도 경고 대상 (리뷰 — 보수 방향)
            cur.execute(
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE ticker = %s AND event_date >= %s AND event_date <= %s",
                (p["symbol"], p["entry_date"], as_of),
            )
            ca = cur.fetchone()[0] or 0
        if ca:
            warnings.append(
                f"corp_action_after_entry:{ca} — entry_price 수동 재확인 필요"
                "(수동 기록 모델 한계)"
            )

        d = evaluate_stop(
            entry_price=p["entry_price"], close=close, sma_50=sma_50,
            breakeven_armed=p["breakeven_armed"],
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO position_stop_evaluations
                  (position_id, eval_date, close, sma_50, effective_stop, binding,
                   breakeven_armed, triggered, warnings)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (position_id, eval_date) DO NOTHING
                """,
                (p["id"], as_of, close, sma_50, d.effective_stop, d.binding,
                 d.breakeven_armed, d.triggered,
                 json.dumps(warnings) if warnings else None),
            )
            inserted = cur.rowcount == 1
            # 래치 영속화 — 단조 True (해제 없음, 스펙 §2②)
            if d.breakeven_armed and not p["breakeven_armed"]:
                cur.execute(
                    "UPDATE positions SET breakeven_armed = TRUE WHERE id = %s",
                    (p["id"],),
                )
        evaluated += 1
        if d.triggered:
            triggered += 1
            if inserted:  # 멱등 재실행의 중복 알림 방지
                with conn.cursor() as cur:
                    cur.execute("SELECT name FROM stocks WHERE ticker = %s",
                                (p["symbol"],))
                    nrow = cur.fetchone()
                notify_stop_triggered(
                    symbol=p["symbol"], name=nrow[0] if nrow else p["symbol"],
                    close=close, effective_stop=d.effective_stop, binding=d.binding,
                    eval_date=as_of,
                )
                log.warning(
                    "[stop-triggered] %s close %.0f < stop %.0f (%s)",
                    p["symbol"], close, d.effective_stop, d.binding,
                )

    return {"as_of": as_of, "evaluated": evaluated, "triggered": triggered,
            "skipped": skipped}
