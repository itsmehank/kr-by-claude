"""#186 B — DART 주요계정 원본 보존 배치 러너(2026-09-27 전문가 회신 Q-1 B·Q-2 ①②③).

대상: 라이브 자격 종목(활성 · security_group ∈ QUALIFYING) + 격리 종목(delisted_daily_prices 보유) 의 corp_code.
셀: 연도(2015~today.year) × 보고서 4종 중 **기간 말 ≤ today** 이고 dart_fin_raw 에 없는 것. 종목당 공시 목록(list.json) 1콜 선행.
순서: 파리티 종목(dart_financials 보유, 276) 셀 전부 → 파리티 판정(raw_parity, 오차 0·미귀속 0) 통과 시에만 잔여 종목.
상한: 일 cap(기본 18,000; 타 소비자 2,000 예약) — dart_batch_log 계정. status 020 → 당일 중단·마킹. 그 외 환경성 실패(DartApiError) → 중단.
보존: 모든 응답을 DB 적재 **전** `save_dir/<YYYYMMDD>.jsonl` 에 append(CLAUDE.md 규칙 5).
접촉 게이트: CLI 는 DART_ALLOW_BATCH=1 필수(운영 스키마 적용·배치 실행은 09-28 첫 실행 관측 보고 후 사용자 승인).
"""
from __future__ import annotations

import argparse
import http.client
import json
import logging
import os
import sys
import ssl
import time
import urllib.error
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg
from psycopg import Connection

from kr_pipeline.common.security_group import QUALIFYING_SECURITY_GROUPS
from kr_pipeline.financials import raw_labels, raw_parity, raw_store
from kr_pipeline.financials.asof import rcept_dt_of
from kr_pipeline.financials.fetch import DartApiError, fetch_disclosures, fetch_single_account

log = logging.getLogger("kr_pipeline.financials.raw_batch")

REPRTS = ("11011", "11013", "11012", "11014")
YEAR_START = 2015            # OpenDART 재무 제공 시작 연도(회신 12)
DAILY_CAP = 18_000           # 회신 ①: 20,000 중 2,000 은 타 소비자(평일 공시 조회) 예약
_SLEEP = 0.08                # 기존 재무 러너와 동일 페이싱
# 일시 네트워크 실패(timeout·연결 끊김) — DartApiError(서버가 status 로 답한 환경성 실패)와 달리 응답 자체가 없다.
# 10-06 1일차 실측: urlopen 20s timeout 1회가 미처리 예외로 배치 전체를 크래시. 백오프 재시도 후에도 실패면 정상 중단(재개는 멱등).
# + 본문 읽기 중 SSL 오류(urlopen 은 연결 단계만 URLError 로 감싼다), 점검 페이지 HTML 등 잘린/비JSON 본문(ValueError ⊃ JSONDecodeError) — 리뷰.
TRANSIENT_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException, ssl.SSLError, ValueError)
TRANSIENT_BACKOFF_S = (10, 60, 300)


@dataclass
class Plan:
    targets: list[tuple[str, str]]                 # (ticker, corp_code)
    parity_tickers: list[str]
    cells: list[tuple[str, str, int, str]]         # (ticker, corp_code, bsns_year, reprt_code) — 파리티 종목 우선
    skipped_done: int = 0
    notes: list[str] = field(default_factory=list)


def plan(conn: Connection, *, years: tuple[int, int], today: date, tickers: list[str] | None = None) -> Plan:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.ticker, c.corp_code
              FROM stocks s JOIN dart_corp_codes c ON c.stock_code = s.ticker
             WHERE ((s.delisted_at IS NULL AND s.security_group = ANY(%s))
                    OR s.ticker IN (SELECT DISTINCT ticker FROM delisted_daily_prices))
               AND (%s::text[] IS NULL OR s.ticker = ANY(%s::text[]))
             ORDER BY s.ticker
            """,
            (list(QUALIFYING_SECURITY_GROUPS), tickers, tickers))
        targets = [(t, c) for t, c in cur.fetchall()]
        cur.execute("SELECT DISTINCT ticker FROM dart_financials WHERE ticker = ANY(%s)", ([t for t, _ in targets],))
        parity = sorted(r[0] for r in cur.fetchall())
    done = raw_store.done_cells(conn, [c for _, c in targets])
    cells: list[tuple[str, str, int, str]] = []
    skipped = 0
    ordered = sorted(targets, key=lambda tc: (tc[0] not in parity, tc[0]))
    for t, c in ordered:
        for y in range(years[0], years[1] + 1):
            for rc in REPRTS:
                if raw_labels.period_end(y, rc) > today:
                    continue
                if (c, y, rc) in done:
                    skipped += 1
                    continue
                cells.append((t, c, y, rc))
    return Plan(targets=targets, parity_tickers=parity, cells=cells, skipped_done=skipped)


def _save(save_dir: Path, today: date, rec: dict) -> None:
    save_dir.mkdir(parents=True, exist_ok=True)
    with open(save_dir / f"{today:%Y%m%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _orig_rcept_dt(filings: list[dict], y: int, rc: str, fiscal_end: date | None) -> date | None:
    p_end = fiscal_end or raw_labels.period_end(y, rc)
    hits = [f["rcept_dt"] for f in filings if not f["report_nm"].lstrip().startswith("[") and raw_labels._matches_report(f["report_nm"], rc, p_end)]
    return min(hits) if hits else None


def _parity_check(conn: Connection, plan_: Plan) -> dict:
    results = []
    with conn.cursor() as cur:
        for t, c in plan_.targets:
            if t not in plan_.parity_tickers:
                continue
            cur.execute("SELECT bsns_year, reprt_code, revenue, operating_income, net_income, fs_div, rcept_no FROM dart_financials WHERE ticker = %s AND status = 'ok'", (t,))
            stored = {(int(y), rc): {"revenue": rv, "operating_income": oi, "net_income": ni, "fs_div": fs, "rcept_no": rn} for y, rc, rv, oi, ni, fs, rn in cur.fetchall()}
            cur.execute("SELECT bsns_year, reprt_code, response FROM dart_fin_raw WHERE corp_code = %s AND status = '000'", (c,))
            for y, rc, resp in cur.fetchall():
                results.append({**raw_parity.compare_cell(resp, stored.get((int(y), rc))), "ticker": t, "cell": (int(y), rc)})
    summary = raw_parity.summarize(results)
    summary["unattributed_cells"] = [(r["ticker"], r["cell"], r["diffs"]) for r in results if not r["ok"] and r["reason"] is None][:50]
    return summary


def _transient_kind(e: BaseException) -> str:
    """중단 사유 라벨 — URLError 는 reason 이 예외면 그 타입(TimeoutError 등), HTTPError 는 'HTTPError<코드>'(reason 이 문자열이라
    type 이름이 'str' 로 찍히던 문제, 리뷰)."""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTPError{e.code}"
    r = getattr(e, "reason", None)
    return type(r).__name__ if isinstance(r, BaseException) else type(e).__name__


def run(conn: Connection, plan_: Plan, *, today: date, cap: int = DAILY_CAP, save_dir: Path, api_key: str,
        max_calls: int | None = None) -> dict:
    st = {"calls": 0, "cells_done": 0, "no_data": 0, "stopped": None, "parity": None, "errors": [], "transient_retries": 0}
    parity_set = set(plan_.parity_tickers)
    parity_passed = not parity_set   # 파리티 종목이 없으면 게이트 없음
    lists_done: set[str] = set()
    delisted = _delisted_map(conn, [t for t, _ in plan_.targets])

    def _budget() -> bool:
        if max_calls is not None and st["calls"] >= max_calls:
            st["stopped"] = "max_calls"; return False
        if raw_store.remaining_today(conn, today, cap=cap) <= 0:
            st["stopped"] = "cap"; return False
        return True

    def _count_call() -> None:
        raw_store.add_calls(conn, today, 1, cap=cap); st["calls"] += 1

    def _call(endpoint: str, fn, *args) -> dict | list | None:
        for attempt in range(len(TRANSIENT_BACKOFF_S) + 1):
            try:
                out = fn(*args)
            except DartApiError as e:
                _count_call()
                if e.status == "020":
                    raw_store.mark_stopped_020(conn, today, cap=cap); conn.commit()
                    st["stopped"] = "020"
                else:
                    st["stopped"] = f"fatal:{e.status}"; st["errors"].append(str(e))
                return None
            except TRANSIENT_ERRORS as e:
                _count_call(); conn.commit()     # 시도도 호출로 센다(서버 도달 여부 불명 — 한도 보수), 크래시돼도 계정 보존
                kind = _transient_kind(e)
                if attempt < len(TRANSIENT_BACKOFF_S) and _budget():
                    st["transient_retries"] += 1
                    log.warning("transient %s %s (%s) — %ss 후 재시도 %d/%d", endpoint, kind, e, TRANSIENT_BACKOFF_S[attempt],
                                attempt + 1, len(TRANSIENT_BACKOFF_S))
                    time.sleep(TRANSIENT_BACKOFF_S[attempt])
                    continue
                if st["stopped"] is None:            # _budget() 이 cap/max_calls 로 먼저 표시했으면 그 사유 유지
                    st["stopped"] = f"transient:{kind}"
                st["errors"].append(f"{endpoint} {kind}: {e}")
                return None
            _count_call()
            _save(save_dir, today, {"endpoint": endpoint, "args": [str(a) for a in args[1:]], "response": out})
            time.sleep(_SLEEP)
            return out
        return None

    i = 0
    cells = plan_.cells
    while i < len(cells):
        t, c, y, rc = cells[i]
        if not parity_passed and t not in parity_set:
            # 파리티 종목 셀이 전부 끝난 지점 — 판정
            st["parity"] = _parity_check(conn, plan_)
            if not st["parity"]["passed"]:
                st["stopped"] = "parity"; break
            parity_passed = True
        if not _budget():
            break
        if c not in lists_done:
            items = _call("list", fetch_disclosures, api_key, c, f"{YEAR_START}0101", f"{today:%Y%m%d}")
            if items is None:
                break
            raw_store.upsert_disclosures(conn, c, items, batch_date=today); conn.commit()
            lists_done.add(c)
            if not _budget():
                break
        resp = _call("fnlttSinglAcnt", fetch_single_account, api_key, c, y, rc)
        if resp is None:
            break
        filings = raw_store.load_disclosures(conn, c)
        status = str(resp.get("status"))
        rec = {"corp_code": c, "bsns_year": y, "reprt_code": rc, "ticker": t, "status": status, "response": resp, "batch_date": today,
               "rcept_no": None, "rcept_dt": None, "orig_rcept_dt": None, "is_correction": None, "no_data_reason": None}
        if status == "000":
            rows = resp.get("list") or []
            rec["rcept_no"] = next((r.get("rcept_no") for r in rows if r.get("rcept_no")), None)
            rec["rcept_dt"] = rcept_dt_of(rec["rcept_no"])
            rec["orig_rcept_dt"] = _orig_rcept_dt(filings, y, rc, None)
            if rec["rcept_dt"] and rec["orig_rcept_dt"]:
                rec["is_correction"] = rec["rcept_dt"] > rec["orig_rcept_dt"]
        elif status == "013":
            rec["no_data_reason"] = raw_labels.decide_no_data(
                bsns_year=y, reprt_code=rc, today=today, first_filing_dt=raw_store.first_filing_dt(conn, c),
                delisted_at=delisted.get(t), filings=filings)
            st["no_data"] += 1
        else:
            st["errors"].append(f"unexpected status {status} {t}/{y}/{rc}"); i += 1; continue   # 미기록(done 오염 금지)
        raw_store.upsert_fin_raw(conn, rec); conn.commit()
        st["cells_done"] += 1
        i += 1
    if st["stopped"] is None and not parity_passed and parity_set:
        st["parity"] = _parity_check(conn, plan_)
        if not st["parity"]["passed"]:
            st["stopped"] = "parity"
    if st["stopped"] is None:
        st["stopped"] = "complete"
    return st


def _delisted_map(conn: Connection, tickers: list[str]) -> dict[str, date | None]:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, delisted_at FROM stocks WHERE ticker = ANY(%s)", (tickers,))
        return dict(cur.fetchall())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="대상·셀 수만 계산(접촉 0)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--cap", type=int, default=DAILY_CAP)
    ap.add_argument("--max-calls", type=int, default=None)
    ap.add_argument("--save-dir", default="data/dart_raw")
    ap.add_argument("--tickers", default=None)
    a = ap.parse_args()
    from kr_pipeline.common.config import Config
    cfg = Config.load()
    today = date.today()
    with psycopg.connect(cfg.database_url) as cn:
        p = plan(cn, years=(YEAR_START, today.year), today=today, tickers=a.tickers.split(",") if a.tickers else None)
        print(json.dumps({"targets": len(p.targets), "parity_tickers": len(p.parity_tickers), "cells": len(p.cells),
                          "skipped_done": p.skipped_done, "est_calls": len(p.cells) + len({c for _, c, _, _ in p.cells})}, ensure_ascii=False))
        if not a.run:
            return 0
        if os.environ.get("DART_ALLOW_BATCH") != "1":
            print("DART_ALLOW_BATCH=1 없이는 실행하지 않는다(외부 접촉 승인 게이트)."); return 2
        st = run(cn, p, today=today, cap=a.cap, save_dir=Path(a.save_dir), api_key=cfg.dart_api_key, max_calls=a.max_calls)
        print(json.dumps(st, ensure_ascii=False, default=str, indent=1))
    return exit_code_for(st)


def exit_code_for(st: dict) -> int:
    """완주(complete)·일 cap·max_calls 는 0(정상 — 다음 날 이어감), 020·fatal·parity·transient 중단은 1(사람 확인)."""
    return 0 if st.get("stopped") in (None, "complete", "cap", "max_calls") else 1


if __name__ == "__main__":
    sys.exit(main())
