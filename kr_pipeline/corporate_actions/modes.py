# kr_pipeline/corporate_actions/modes.py
"""corporate_actions 모드 분기 + 오케스트레이션."""
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.corporate_actions.corp_code_sync import sync_corp_codes
from kr_pipeline.corporate_actions.dart_client import fetch_disclosures, DartApiError
from kr_pipeline.corporate_actions.load import (
    load_active_tickers_with_corp_code, count_active_tickers_without_mapping,
)
from kr_pipeline.corporate_actions.parser import parse_event_type, parse_ratio
from kr_pipeline.corporate_actions.store import upsert_corporate_actions


log = logging.getLogger("kr_pipeline.corporate_actions")


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    REFRESH_MAPPING = "refresh-mapping"


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]
    warnings: list[str] = field(default_factory=list)


def compute_date_range(
    mode: Mode,
    *,
    years: int = 5,
    window_days: int = 7,
) -> tuple[date | None, date | None]:
    today = date.today()
    if mode == Mode.BACKFILL:
        return today - timedelta(days=years * 365), today
    if mode == Mode.INCREMENTAL:
        return today - timedelta(days=window_days), today
    if mode == Mode.REFRESH_MAPPING:
        return None, None
    raise ValueError(f"Unknown mode: {mode}")


def _process_ticker(
    conn: Connection,
    api_key: str,
    ticker: str,
    corp_code: str,
    start_date: date,
    end_date: date,
) -> int:
    """한 종목의 공시 fetch → 파싱 → UPSERT. 처리 행수 반환."""
    disclosures = fetch_disclosures(api_key, corp_code, start_date, end_date)
    rows = []
    for d in disclosures:
        report_nm = d.get("report_nm", "")
        event_type = parse_event_type(report_nm)
        if event_type is None:
            continue   # 6 종 외 공시 skip
        rcept_dt_str = d.get("rcept_dt", "")
        try:
            event_date = date(int(rcept_dt_str[:4]), int(rcept_dt_str[4:6]), int(rcept_dt_str[6:8]))
        except (ValueError, IndexError):
            continue
        ratio = parse_ratio(report_nm, event_type)
        rows.append({
            "ticker": ticker,
            "event_date": event_date,
            "event_type": event_type,
            "ratio": ratio,
            "note": None,
            "dart_rcept_no": d.get("rcept_no"),
            "raw_disclosure_title": report_nm,
        })
    if not rows:
        return 0
    affected = upsert_corporate_actions(conn, rows)
    conn.commit()
    return affected


def _run_sanity_checks(conn: Connection, rows_affected: int) -> list[str]:
    """sanity 검증."""
    warnings = []

    # 1. fetch 행수 너무 많음 (파싱 오류 또는 광범위 이벤트)
    if rows_affected > 1000:
        warnings.append(f"high_action_count: 이번 fetch 에 {rows_affected} 행 — 파싱 또는 데이터 오류 의심")

    # 2. corp_code 매핑 없는 활성 종목 비율
    no_mapping = count_active_tickers_without_mapping(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM stocks WHERE delisted_at IS NULL")
        total = cur.fetchone()[0] or 0
    if total > 0:
        ratio = no_mapping / total
        if ratio > 0.05:
            warnings.append(f"mapping_low: 매핑 없는 활성 종목 {no_mapping}/{total} ({ratio*100:.1f}%, 임계 5%) — refresh-mapping 권장")

    return warnings


def run(
    conn: Connection,
    mode: Mode,
    api_key: str,
    *,
    years: int = 5,
    window_days: int = 7,
    limit_tickers: int | None = None,
) -> RunStats:
    """파이프라인 실행."""
    rows_total = 0
    failures: list[tuple[str, str]] = []

    params = {"window_days": window_days if mode == Mode.INCREMENTAL else None,
              "years": years if mode == Mode.BACKFILL else None,
              "limit_tickers": limit_tickers}
    params = {k: v for k, v in params.items() if v is not None}

    with run_tracking(
        conn, pipeline="corporate_actions", mode=mode.value, params=params,
    ) as state:
        if mode == Mode.REFRESH_MAPPING:
            log.info("Refreshing DART corp_code mapping...")
            rows_total = sync_corp_codes(conn, api_key)
            conn.commit()
            log.info(f"corp_code mapping: {rows_total} rows")
        else:
            start_date, end_date = compute_date_range(mode, years=years, window_days=window_days)
            log.info(f"corporate_actions mode={mode.value} range={start_date}..{end_date}")

            # dart_corp_codes 비어있으면 자동 sync
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM dart_corp_codes")
                if cur.fetchone()[0] == 0:
                    log.warning("dart_corp_codes 비어있음. 먼저 sync_corp_codes 실행.")
                    sync_corp_codes(conn, api_key)
                    conn.commit()

            tickers = load_active_tickers_with_corp_code(conn, limit=limit_tickers)
            log.info(f"tickers to process: {len(tickers)}")

            for i, (ticker, corp_code) in enumerate(tickers, 1):
                try:
                    rows_total += _process_ticker(conn, api_key, ticker, corp_code, start_date, end_date)
                except DartApiError as e:
                    failures.append((ticker, str(e)))
                    log.warning(f"{ticker}: DART API error — {e}")
                    conn.rollback()
                except Exception as e:
                    failures.append((ticker, str(e)))
                    log.warning(f"{ticker}: {e}")
                    conn.rollback()
                if i % 100 == 0:
                    log.info(f"progress: {i}/{len(tickers)} (failures: {len(failures)})")

            # 끝-of-run 1회 재시도
            if failures:
                log.warning(f"Retrying {len(failures)} failed tickers")
                retry_failures = []
                ticker_to_corp = {t: c for t, c in tickers}
                for ticker, _ in failures:
                    try:
                        rows_total += _process_ticker(conn, api_key, ticker, ticker_to_corp[ticker], start_date, end_date)
                    except Exception as e:
                        retry_failures.append((ticker, str(e)))
                        conn.rollback()
                failures = retry_failures

        warnings = _run_sanity_checks(conn, rows_total)
        state["warnings"].extend(warnings)
        state["rows_affected"] = rows_total

    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)
