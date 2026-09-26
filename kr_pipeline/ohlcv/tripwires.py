"""#207 회신 16·17 — 수정주가 내부 정합성 트립와이어. **수집 fail-open / 지표 fail-closed**(회신 15 원칙).

위치(회신 17 조건): ohlcv._run_upsert 안 — ① 전 종목 raw 적재·commit **후**(당일 KRX 봉 유실 없음), 이벤트 기록·소급·
adj 재유도 **전**에 (1′)(3) 검사 → 위반 시 AdjustmentTripwireError → ohlcv run failed(run_tracking) → data_daily 체인 중단 →
지표 미계산. ② 이벤트 유도 완료 후 (2) 검사(유도 결과 자체의 검사라 유도 뒤가 유일한 위치). 2차 방어로 indicators.run_daily
시작에서 3건을 다시 확인한다(다른 writer 경로 대비).

임계 출처·태그(measurement-based, 새 숫자 창작 없음):
(1′) ADJ_DAILY_EVENTS_MAX = 16 — 2026-01-02~09-11 171거래일, Naver 구정의 R=adj/close 점프(0.5%↑) 일별 종목 수의
     **실측 최댓값**(p50 1 · p90 6 · p99 13; 분포 0일 53·1일 36·2일 35·3일 15·4일 9·5~7일 16·9~16일 7, #207 코멘트 09-26).
     목적 = 원천 정의 변경(수백 건 규모)·직전 거래일 결측 오판 감지. 구 (1) "계수≠1 ⇔ 기준가≠전일종가"는 회신 16 (i)로 항등식 → 폐기.
     **개정 규칙(회신 17)**: 위반 시 당일 조정 종목 전수 확인 → 전부 정당한 기업행위면 새 최댓값으로
     docs/superpowers/threshold-change-checklist.md 절차(적용 이력 1줄)로 갱신. 설명 불가 1건 이상이면 원천 결함으로 처리(갱신 금지).
(2)  ADJ_ENVELOPE_TOL = 0.5% — #207 최초 감지 임계(adj_close/close 편차 0.5%) 재사용, 출처 #207. 시임(adjust.ADJ_SELF_START)
     이후 행만: adj_high ≤ raw_high×계수 · adj_low ≥ raw_low×계수(계수 = adj_close/close). 기준선 2026-06-01~09-11 비할트
     176,076행 중 1행. 시임 이후 유도는 raw×F 정확식 → 위반 = 다른 writer(연장시간 봉 등) 유입 신호.
(3)  raw 봉 low ≤ close ≤ high(비할트, high>0) — 정의상 검사, 임계 없음(기준선 전 이력 5,284,501행 0).
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection

from kr_pipeline.ohlcv.adjust import ADJ_SELF_START

ADJ_DAILY_EVENTS_MAX = 16      # (1′) 관측 최댓값, 2026-01-02~09-11
ADJ_ENVELOPE_TOL = 0.005       # (2) 0.5%


class AdjustmentTripwireError(RuntimeError):
    """수정주가 정합성 위반 — 지표 단계 중단(fail-closed)."""


def check_pending_event_counts(pending: dict[str, list[tuple[date, float]]]) -> list[str]:
    """(1′) 아직 기록 전인 후보 이벤트를 날짜별로 세어 최댓값 초과를 잡는다 — 기록·소급 **전** 호출(순수 함수)."""
    counts: dict[date, int] = {}
    for evs in pending.values():
        for d, _ in evs:
            counts[d] = counts.get(d, 0) + 1
    return [f"daily_event_count: {d} 조정 종목 {n} > 사전등록 최댓값 {ADJ_DAILY_EVENTS_MAX}(2026-01-02~09-11 실측)"
            for d, n in sorted(counts.items()) if n > ADJ_DAILY_EVENTS_MAX]


def check_recorded_event_counts(conn: Connection, *, start: date, end: date) -> list[str]:
    """(1′) 기록된 이벤트 기준(2차 방어·다른 writer 경로)."""
    with conn.cursor() as cur:
        cur.execute("SELECT date, count(*) FROM adj_factor_events WHERE date BETWEEN %s AND %s GROUP BY date HAVING count(*) > %s ORDER BY date",
                    (start, end, ADJ_DAILY_EVENTS_MAX))
        return [f"daily_event_count: {d} 조정 종목 {n} > 사전등록 최댓값 {ADJ_DAILY_EVENTS_MAX}(2026-01-02~09-11 실측)" for d, n in cur.fetchall()]


def check_adj_envelope(conn: Connection, *, start: date, end: date) -> list[str]:
    """(2) 시임 이후 행만."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker, date FROM daily_prices
             WHERE date BETWEEN GREATEST(%s, %s) AND %s AND high > 0 AND close > 0 AND adj_close IS NOT NULL
               AND (adj_high > high * (adj_close/close) * (1 + %s) OR adj_low < low * (adj_close/close) * (1 - %s))
             ORDER BY ticker, date LIMIT 50
            """,
            (start, ADJ_SELF_START, end, ADJ_ENVELOPE_TOL, ADJ_ENVELOPE_TOL))
        rows = cur.fetchall()
    if not rows:
        return []
    return [f"adj_envelope: 시임 이후 adj_high/low 가 raw×계수 허용 {ADJ_ENVELOPE_TOL:.1%} 밖 {len(rows)}행(상한 50): {[(t, str(d)) for t, d in rows[:10]]}"]


def check_raw_bars(conn: Connection, *, start: date, end: date) -> list[str]:
    """(3) raw low ≤ close ≤ high(비할트)."""
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, date FROM daily_prices WHERE date BETWEEN %s AND %s AND high > 0 AND NOT (low <= close AND close <= high) ORDER BY 1, 2 LIMIT 50",
                    (start, end))
        rows = cur.fetchall()
    if not rows:
        return []
    return [f"raw_bar: low ≤ close ≤ high 위반 {len(rows)}행(상한 50): {[(t, str(d)) for t, d in rows[:10]]}"]


def check_adjustment_tripwires(conn: Connection, *, start: date, end: date) -> list[str]:
    """[start, end] 창의 위반 목록(빈 리스트 = 통과) — 3건 전부(2차 방어용 합본). 접두어: daily_event_count / adj_envelope / raw_bar."""
    return check_recorded_event_counts(conn, start=start, end=end) + check_adj_envelope(conn, start=start, end=end) + check_raw_bars(conn, start=start, end=end)


def raise_if_violations(violations: list[str]) -> None:
    if violations:
        raise AdjustmentTripwireError("; ".join(violations))
