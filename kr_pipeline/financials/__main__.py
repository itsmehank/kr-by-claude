# kr_pipeline/financials/__main__.py
"""(#68 2단계) DART 실적 백필 — 표본 B 100종목, 멱등 재개.

  uv run python -m kr_pipeline.financials --mode=backfill [--limit-tickers N]
스펙: docs/superpowers/specs/2026-07-22-issue68-stage2-ingest.md
"""
import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.financials.fetch import (
    fetch_disclosures, fetch_shares, fetch_single_account,
)
from kr_pipeline.financials.parse import (
    match_disclosure, normalize_accounts, parse_thstrm,
)
from kr_pipeline.financials.store import upsert_financial

log = logging.getLogger("kr_pipeline.financials")

YEARS = list(range(2017, 2025))
REPRTS = ("11011", "11013", "11012", "11014")  # 연간 먼저 — 분기 EPS 가 연간 주식수 근사
EXCLUDED_SECTORS = ("금융", "기타금융", "증권", "은행", "보험")
SAMPLE_JSON = Path(__file__).resolve().parents[2] / "data" / "backtest" / "sample_b_draw_20260713.json"
_QUARTER_END_MONTH = {"11013": 3, "11012": 6, "11014": 9, "11011": 12}
_SLEEP = 0.08


def _period_end_guess(year: int, reprt: str) -> date:
    m = _QUARTER_END_MONTH[reprt]
    return date(year, m, 28)  # 원공시 매칭용 근사 — 실제 회계기간은 thstrm 파싱이 확정


def parse_args():
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.financials")
    p.add_argument("--mode", required=True, choices=["backfill"])
    p.add_argument("--limit-tickers", type=int, default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    if not cfg.dart_api_key:
        log.error("DART_API_KEY 필요 (.env)")
        return 1

    sample = json.loads(SAMPLE_JSON.read_text())["sample_b"]
    if args.limit_tickers:
        sample = sample[: args.limit_tickers]

    with connect(cfg.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, sector FROM stocks WHERE ticker = ANY(%s)", (sample,))
            sectors = dict(cur.fetchall())
            cur.execute(
                "SELECT stock_code, corp_code FROM dart_corp_codes "
                "WHERE stock_code = ANY(%s)", (sample,))
            cmap = dict(cur.fetchall())
            cur.execute(
                "SELECT ticker, bsns_year, reprt_code FROM dart_financials "
                "WHERE ticker = ANY(%s)", (sample,))
            done = {(t, y, rc) for t, y, rc in cur.fetchall()}

        excluded = [t for t in sample if any(
            fs in (sectors.get(t) or "") for fs in EXCLUDED_SECTORS)]
        unmapped = [t for t in sample if t not in cmap and t not in excluded]
        targets = [t for t in sample if t not in excluded and t in cmap]
        log.info("backfill 대상 %d / 금융업 제외 %d(%s) / 미매핑 %d(%s) / 기적재 셀 %d",
                 len(targets), len(excluded), ",".join(excluded) or "-",
                 len(unmapped), ",".join(unmapped) or "-", len(done))

        with run_tracking(conn, pipeline="financials", mode="backfill",
                          params={"tickers": len(targets), "years": f"{YEARS[0]}-{YEARS[-1]}"}) as state:
            if excluded:
                state["warnings"].append(f"금융업 제외 {len(excluded)}: {excluded}")
            if unmapped:
                state["warnings"].append(f"corp_code 미매핑 {len(unmapped)}: {unmapped}")
            rows = 0
            for i, t in enumerate(targets, 1):
                cc = cmap[t]
                need = [(y, rc) for y in YEARS for rc in REPRTS
                        if (t, y, rc) not in done]
                if not need:
                    continue
                disclosures = fetch_disclosures(
                    cfg.dart_api_key, cc, f"{YEARS[0]}0101", f"{YEARS[-1] + 1}1231")
                time.sleep(_SLEEP)
                shares_by_year: dict[int, float | None] = {}
                for y, rc in need:
                    try:
                        resp = fetch_single_account(cfg.dart_api_key, cc, y, rc)
                    except Exception as e:  # noqa: BLE001 — 단건 격리, 재실행 재시도
                        log.warning("fetch fail %s %s %s: %s", t, y, rc, e)
                        time.sleep(_SLEEP)
                        continue
                    time.sleep(_SLEEP)
                    if resp.get("status") != "000":
                        upsert_financial(conn, {
                            "ticker": t, "bsns_year": y, "reprt_code": rc,
                            "status": "no_data"})
                        rows += 1
                        continue
                    acct = normalize_accounts(resp.get("list") or [])
                    sub = [r for r in resp["list"] if r.get("fs_div") == acct["fs_div"]]
                    thstrm = next((r.get("thstrm_dt") for r in sub
                                   if "~" in (r.get("thstrm_dt") or "")),
                                  sub[0].get("thstrm_dt") if sub else None)
                    f_start, f_end = parse_thstrm(thstrm)
                    rcept = (sub[0].get("rcept_no") if sub else None)
                    disclosed = match_disclosure(
                        disclosures, y, rc,
                        fiscal_end=f_end or _period_end_guess(y, rc))
                    if y not in shares_by_year:
                        # 연간 우선 순회지만, 재개 시 연간이 기적재면 분기가 먼저
                        # 올 수 있어 rc 무관 1회 조회 (조회 자체는 11011 기준)
                        shares_by_year[y] = fetch_shares(cfg.dart_api_key, cc, y, "11011")
                        time.sleep(_SLEEP)
                    shares = shares_by_year.get(y)
                    ni = acct["net_income"]
                    eps = round(ni / shares, 2) if (ni is not None and shares) else None
                    upsert_financial(conn, {
                        "ticker": t, "bsns_year": y, "reprt_code": rc,
                        "status": "ok", "fs_div": acct["fs_div"],
                        "fiscal_start": f_start, "fiscal_end": f_end,
                        "revenue": acct["revenue"],
                        "operating_income": acct["operating_income"],
                        "net_income": ni, "shares_outstanding": shares,
                        "eps_derived": eps, "rcept_no": rcept,
                        "disclosed_at": disclosed,
                    })
                    rows += 1
                conn.commit()
                log.info("[%d/%d] %s done (+%d rows)", i, len(targets), t, len(need))
            state["rows_affected"] = rows
    return 0


if __name__ == "__main__":
    sys.exit(main())
