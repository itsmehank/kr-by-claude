"""#207 회신 16 — 수정주가 내부 정합성 트립와이어. 지표 단계 fail-closed(indicators.run_daily 시작에서 위반 시 예외 →
run_tracking 이 run failed 기록), 수집(ohlcv)은 fail-open 유지.

임계는 **측정 기반 사전등록**(새 숫자 창작 없음, #207 코멘트 2026-09-26):
(1′) 일별 조정(계수≠1) 종목 수: 2026-01-02~09-11 171거래일 Naver 구정의 R 점프(0.5%↑) 분포 p50 1·p90 6·p99 13·max 16
     → ADJ_DAILY_EVENTS_MAX = 16(관측 최댓값). 초과 = 데이터 결함 신호(예: 직전 거래일 결측으로 전 종목 오판).
     (구 (1) "계수≠1 ⇔ 기준가≠전일종가" 는 회신 16 (i) 채택으로 항등식 → 폐기.)
(2)  시임(adjust.ADJ_SELF_START) 이후 행: adj_high ≤ raw_high×계수·adj_low ≥ raw_low×계수, 계수 = adj_close/close,
     허용 ADJ_ENVELOPE_TOL = 0.5%(기준선 2026-06-01~09-11 비할트 176,076행 중 1행). 시임 이후 유도는 raw×F 정확식이라
     위반 = 다른 writer(연장시간 봉 등) 유입 신호. 시임 이전(Naver 이력)은 검사하지 않는다.
(3)  raw 봉: low ≤ close ≤ high(비할트, high>0), 기준선 전 이력 5,284,501행 0 위반 → 0.
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection

from kr_pipeline.ohlcv.adjust import ADJ_SELF_START

ADJ_DAILY_EVENTS_MAX = 16      # (1′) 관측 최댓값, 2026-01-02~09-11
ADJ_ENVELOPE_TOL = 0.005       # (2) 0.5%


class AdjustmentTripwireError(RuntimeError):
    """수정주가 정합성 위반 — 지표 단계 중단(fail-closed)."""


def check_adjustment_tripwires(conn: Connection, *, start: date, end: date) -> list[str]:
    """[start, end] 창의 위반 목록(빈 리스트 = 통과). 문자열 접두어: daily_event_count / adj_envelope / raw_bar."""
    out: list[str] = []
    with conn.cursor() as cur:
        # (1′)
        cur.execute("SELECT date, count(*) FROM adj_factor_events WHERE date BETWEEN %s AND %s GROUP BY date HAVING count(*) > %s ORDER BY date",
                    (start, end, ADJ_DAILY_EVENTS_MAX))
        for d, n in cur.fetchall():
            out.append(f"daily_event_count: {d} 조정 종목 {n} > 사전등록 최댓값 {ADJ_DAILY_EVENTS_MAX}(2026-01-02~09-11 실측)")
        # (2) — 시임 이후만
        cur.execute(
            """
            SELECT ticker, date FROM daily_prices
             WHERE date BETWEEN GREATEST(%s, %s) AND %s AND high > 0 AND close > 0 AND adj_close IS NOT NULL
               AND (adj_high > high * (adj_close/close) * (1 + %s) OR adj_low < low * (adj_close/close) * (1 - %s))
             ORDER BY ticker, date LIMIT 50
            """,
            (start, ADJ_SELF_START, end, ADJ_ENVELOPE_TOL, ADJ_ENVELOPE_TOL))
        rows = cur.fetchall()
        if rows:
            out.append(f"adj_envelope: 시임 이후 adj_high/low 가 raw×계수 허용 {ADJ_ENVELOPE_TOL:.1%} 밖 {len(rows)}행(상한 50): "
                       f"{[(t, str(d)) for t, d in rows[:10]]}")
        # (3)
        cur.execute("SELECT ticker, date FROM daily_prices WHERE date BETWEEN %s AND %s AND high > 0 AND NOT (low <= close AND close <= high) ORDER BY 1, 2 LIMIT 50",
                    (start, end))
        rows = cur.fetchall()
        if rows:
            out.append(f"raw_bar: low ≤ close ≤ high 위반 {len(rows)}행(상한 50): {[(t, str(d)) for t, d in rows[:10]]}")
    return out


def assert_adjustment_tripwires(conn: Connection, *, start: date, end: date) -> None:
    v = check_adjustment_tripwires(conn, start=start, end=end)
    if v:
        raise AdjustmentTripwireError("; ".join(v))
