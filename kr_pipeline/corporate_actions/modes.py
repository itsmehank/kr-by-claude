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


def _date_chunks(start: date, end: date, *, days: int = 90):
    """[start..end] 를 최대 `days` 일 구간으로 분할 (빈틈·중복 없음).

    일괄 조회(corp_code 생략)는 전 회사 공시를 받으므로, 긴 기간(backfill 5y)을
    한 요청으로 던지면 페이지가 폭주한다 — 구간을 나눠 요청당 페이지 수를 bound.
    """
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=days - 1), end)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def _rows_from_disclosures(disclosures: list[dict], corp_to_ticker: dict[str, str]) -> list[dict]:
    """일괄 응답 → corp_code 역매핑 + 파싱. universe 밖 회사·비대상 공시는 skip."""
    rows = []
    seen: set[tuple] = set()
    for d in disclosures:
        ticker = corp_to_ticker.get(d.get("corp_code"))
        if ticker is None:
            continue   # 우리 universe(매핑된 활성 종목) 밖 회사
        report_nm = d.get("report_nm", "")
        event_type = parse_event_type(report_nm)
        if event_type is None:
            continue   # 6 종 외 공시 skip
        rcept_dt_str = d.get("rcept_dt", "")
        try:
            event_date = date(int(rcept_dt_str[:4]), int(rcept_dt_str[4:6]), int(rcept_dt_str[6:8]))
        except (ValueError, IndexError):
            continue
        key = (ticker, event_date, event_type, d.get("rcept_no"))
        if key in seen:
            continue   # 같은 executemany 안 중복 → ON CONFLICT 이중 갱신 에러 방지
        seen.add(key)
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
    return rows


def _process_chunk(
    conn: Connection,
    api_key: str,
    corp_to_ticker: dict[str, str],
    chunk_start: date,
    chunk_end: date,
) -> int:
    """한 날짜 청크의 전 회사 공시 일괄 fetch → 역매핑·파싱 → UPSERT. 처리 행수 반환."""
    disclosures = fetch_disclosures(api_key, None, chunk_start, chunk_end)
    rows = _rows_from_disclosures(disclosures, corp_to_ticker)
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
            corp_to_ticker = {corp_code: ticker for ticker, corp_code in tickers}
            chunks = list(_date_chunks(start_date, end_date))
            log.info(
                f"매핑 종목 {len(tickers)}개 — 기간 일괄 조회 {len(chunks)} 청크 "
                f"(종목별 반복 호출 아님)"
            )

            # failures 의 첫 원소는 청크 라벨 ('YYYY-MM-DD..YYYY-MM-DD') — 일괄 조회라
            # 실패 단위가 종목이 아니라 날짜 구간.
            for i, (cs, ce) in enumerate(chunks, 1):
                try:
                    rows_total += _process_chunk(conn, api_key, corp_to_ticker, cs, ce)
                except DartApiError as e:
                    failures.append((f"{cs}..{ce}", str(e)))
                    log.warning(f"chunk {cs}..{ce}: DART API error — {e}")
                    conn.rollback()
                except Exception as e:
                    failures.append((f"{cs}..{ce}", str(e)))
                    log.warning(f"chunk {cs}..{ce}: {e}")
                    conn.rollback()
                if i % 5 == 0 or i == len(chunks):
                    log.info(f"progress: {i}/{len(chunks)} chunks (failures: {len(failures)})")

            # 끝-of-run 1회 재시도 (실패 청크만)
            if failures:
                log.warning(f"Retrying {len(failures)} failed chunks")
                retry_failures = []
                for label, _ in failures:
                    cs_str, ce_str = label.split("..")
                    cs, ce = date.fromisoformat(cs_str), date.fromisoformat(ce_str)
                    try:
                        rows_total += _process_chunk(conn, api_key, corp_to_ticker, cs, ce)
                    except Exception as e:
                        retry_failures.append((label, str(e)))
                        conn.rollback()
                failures = retry_failures

        warnings = _run_sanity_checks(conn, rows_total)
        state["warnings"].extend(warnings)
        state["rows_affected"] = rows_total

    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)
