"""조정 드리프트(분할 등) 감지 + 단일종목 재적재 — #207 A안(회신 15·16) 이후 **외부 접촉 0**.

구 설계(DB adj_close vs Naver 재조회 비교·Naver 전 기간 재수신)는 Naver 원천 자격 상실(#207)로 제거.
현 설계: 조정일 = daily_prices.change_pct(KRX 등락률) 기반 판정(adjust.is_adjustment). 증분 적재(ohlcv._run_upsert)가
조정일을 기록·소급하므로 여기의 detect 는 **안전망**(창 안 미기록 조정일 스캔, DB 전용)이고 reload 는 미기록
이벤트 기록·소급 후 지표 재계산이다. 스펙: docs/superpowers/specs/2026-06-04-pipeline-integration-drift-reload-design.md §2(구),
#207 회신 15·16(현).
"""
from __future__ import annotations
import logging
from datetime import date, timedelta

from psycopg import Connection

from kr_pipeline.ohlcv import adjust
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators

log = logging.getLogger("kr_pipeline.pipeline.drift")

# 수정주가를 바꾸는 corporate action 유형 (현금배당 제외 — 수정주가 무관). recent_corp_action_tickers 참조용.
ADJ_AFFECTING_EVENT_TYPES = (
    "stock_split", "reverse_split", "bonus_issue", "rights_offering",
    "merger", "spinoff", "capital_reduction",
)

CA_LOOKBACK_DAYS = 90   # (참조) 공시 후보 창 — A안 이후 detect 는 후보 없이 전 종목 DB 스캔(접촉 0).
SWEEP_RECENT_DAYS = 90  # 토요일 스윕 비교창. ohlcv window_days(30)보다 커야 증분 창 너머 옛 구간의 미기록 조정을 잡는다.
RELOAD_LOOKBACK_DAYS = 365   # reload 시 미기록 이벤트 탐색 창


def recent_corp_action_tickers(conn: Connection, *, as_of: date, lookback_days: int) -> list[str]:
    """corporate_actions 에 [as_of-lookback, as_of] 영향 이벤트가 있는 활성 종목(distinct).

    event_type 가 ADJ_AFFECTING_EVENT_TYPES 이고 상장 유지(delisted_at IS NULL)인 종목만.
    인덱스 idx_corp_actions_event_type_date(event_type, event_date) 활용.
    """
    since = as_of - timedelta(days=lookback_days)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ca.ticker FROM corporate_actions ca "
            "JOIN stocks s ON s.ticker = ca.ticker "
            "WHERE ca.event_type = ANY(%s) AND ca.event_date BETWEEN %s AND %s "
            "AND s.delisted_at IS NULL "
            "ORDER BY ca.ticker",
            (list(ADJ_AFFECTING_EVENT_TYPES), since, as_of),
        )
        return [r[0] for r in cur.fetchall()]


def _active_tickers(conn: Connection, limit: int | None = None) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY ticker" + (f" LIMIT {int(limit)}" if limit else ""))
        return [r[0] for r in cur.fetchall()]


def _window_has_change_pct(conn: Connection, ticker: str, start: date, end: date) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM daily_prices WHERE ticker = %s AND date BETWEEN %s AND %s AND change_pct IS NOT NULL LIMIT 1",
                    (ticker, start, end))
        return cur.fetchone() is not None


def _unrecorded_events(conn: Connection, ticker: str, *, since: date) -> list[tuple[date, float]]:
    recorded = {d for d, _ in adjust.load_events(conn, ticker)}
    return [(d, c) for d, c in adjust.detect_events(conn, ticker, since=since) if d not in recorded]


def detect_drifted_tickers(
    conn: Connection,
    *,
    as_of: date,
    recent_days: int = 30,
    tickers: list[str] | None = None,
    limit_tickers: int | None = None,
    unverified_out: list[str] | None = None,
    **_legacy,   # rel_tol·wide_days·sleep_s(구 Naver 비교 인자) — 무시
) -> list[str]:
    """창(as_of−recent_days..as_of) 안에 change_pct 기반 조정일이 있는데 adj_factor_events 에 없는 종목(DB 전용, 접촉 0).

    tickers=None 이면 활성 전 종목. unverified_out: 창 안 행에 change_pct 가 하나도 없어 판정 못 한 종목
    ('이상 없음' 아님 — 등락률 미수집 구간).
    """
    scan = _active_tickers(conn, limit=limit_tickers) if tickers is None else \
        (list(tickers[:limit_tickers]) if limit_tickers else list(tickers))
    since = as_of - timedelta(days=recent_days)
    drifted: list[str] = []
    unverified: list[str] = []
    for t in scan:
        try:
            if not _window_has_change_pct(conn, t, since, as_of):
                unverified.append(t)
                continue
            if _unrecorded_events(conn, t, since=since):
                drifted.append(t)
        except Exception as e:  # noqa: BLE001 — 종목 단위 격리
            unverified.append(t)
            log.warning("drift detect skip %s: %s", t, e)
    if unverified:
        log.warning("drift unverified: %d tickers (등락률 미수집/예외 — '이상 없음' 아님) %s", len(unverified), unverified[:20])
    if unverified_out is not None:
        unverified_out.extend(unverified)
    log.info("drift detected: %d tickers %s", len(drifted), drifted[:20])
    return drifted


def reload_ticker(conn: Connection, ticker: str, *, as_of: date) -> dict:
    """단일 종목 재적재(접촉 0): 미기록 조정일 기록 + 이력 소급(adjust.apply_event) → daily Phase A 재계산 →
    주봉 가격 재집계(weekly FULL_REFRESH, 그 종목만) → weekly Phase A 재계산. 횡단면 RS 는 체인의 전 종목 실행이 확정.
    멱등: 이미 기록된 이벤트는 다시 적용하지 않는다. 단계별 commit(부분 상태는 다음 실행이 복구), 호출부가 종목 단위 격리.
    """
    events = _unrecorded_events(conn, ticker, since=as_of - timedelta(days=RELOAD_LOOKBACK_DAYS))
    applied = 0
    for d, c in events:
        applied += adjust.apply_event(conn, ticker, d, c)
    if events:
        adjust.record_events(conn, ticker, events)
        log.info("reload %s: adjustment events %s, rows rescaled %d", ticker, [(str(d), round(c, 6)) for d, c in events], applied)
    conn.commit()

    r_ind_d = indicators.recompute_ticker_daily(conn, ticker)
    r_wk = weekly.run(conn, weekly.Mode.FULL_REFRESH, only_tickers=[ticker])
    r_ind_w = indicators.recompute_ticker_weekly(conn, ticker)

    return {
        "ticker": ticker,
        "adj_events": len(events),
        "adj_rows": applied,
        "indicators_daily": r_ind_d,
        "weekly": r_wk.rows_affected,
        "indicators_weekly": r_ind_w,
    }
