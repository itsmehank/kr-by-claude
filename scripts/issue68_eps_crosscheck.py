"""(#68 3단계 선행 체크) 파생 EPS vs 공시 EPS 대조 — 스펙 §7 예약분 실행.

  uv run python scripts/issue68_eps_crosscheck.py [--n-tickers 12] [--seed 20260722]

목적: 2단계 파생식(eps_derived = net_income / 연간 주식수)과 §3 동명 중복 "첫 행"
규칙이 공시 EPS(전체계정 API 기본주당이익)와 정합한지 잠금 전 검증.
- 표본: dart_financials(status=ok, eps_derived NOT NULL) 종목에서 결정론 추첨
  (seed 고정) → 종목당 연간 2셀 + 분기 2셀 (최신 우선).
- 판정 기준(사전등록 초안 §선행 체크와 동일): 부호 일치 100% AND
  상대오차 중앙값 <= 5% AND 개별 최대 <= 15% (분기는 연간 주식수 근사 여유).
- 산출: data/verification/issue68_eps_crosscheck.json + stdout 요약.
  읽기 전용(DB 쓰기 0) — DART ~50콜(무료).
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect
from kr_pipeline.financials.fetch import DartApiError, fetch_all_accounts
from kr_pipeline.financials.parse import extract_eps

OUT = Path(__file__).resolve().parents[1] / "data" / "verification" / "issue68_eps_crosscheck.json"
_SLEEP = 0.08

PASS_SIGN = 1.0          # 부호 일치율 요구
PASS_MEDIAN_REL = 0.05   # 상대오차 중앙값
PASS_MAX_REL = 0.15      # 개별 상대오차 상한


def pick_cells(conn, n_tickers: int, seed: int) -> list[dict]:
    """결정론 표본: 종목 무작위(seed) → 종목당 연간 2 + 분기 2 (fiscal_end 최신 우선)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ticker FROM dart_financials
             WHERE status = 'ok' AND eps_derived IS NOT NULL
             ORDER BY ticker
            """)
        tickers = [r[0] for r in cur.fetchall()]
    chosen = random.Random(seed).sample(tickers, min(n_tickers, len(tickers)))
    cells: list[dict] = []
    with conn.cursor() as cur:
        for t in chosen:
            for cond, k in (("= '11011'", 2), ("<> '11011'", 2)):
                cur.execute(
                    f"""
                    SELECT ticker, bsns_year, reprt_code, fs_div, eps_derived
                      FROM dart_financials
                     WHERE ticker = %s AND status = 'ok'
                       AND eps_derived IS NOT NULL AND reprt_code {cond}
                     ORDER BY fiscal_end DESC NULLS LAST
                     LIMIT %s
                    """, (t, k))
                cells += [dict(zip(("ticker", "bsns_year", "reprt_code",
                                    "fs_div", "eps_derived"), r))
                          for r in cur.fetchall()]
    return cells


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n-tickers", type=int, default=12)
    p.add_argument("--seed", type=int, default=20260722)
    args = p.parse_args()

    cfg = Config.load()
    if not cfg.dart_api_key:
        print("DART_API_KEY 필요 (.env)", file=sys.stderr)
        return 1

    with connect(cfg.database_url) as conn:
        cells = pick_cells(conn, args.n_tickers, args.seed)
        with conn.cursor() as cur:
            cur.execute("SELECT stock_code, corp_code FROM dart_corp_codes "
                        "WHERE stock_code = ANY(%s)",
                        (sorted({c["ticker"] for c in cells}),))
            cmap = dict(cur.fetchall())

    results = []
    for c in cells:
        cc = cmap.get(c["ticker"])
        if not cc:
            results.append({**c, "outcome": "no_corp_code"})
            continue
        try:
            resp = fetch_all_accounts(cfg.dart_api_key, cc, c["bsns_year"],
                                      c["reprt_code"], c["fs_div"])
        except DartApiError as e:
            print(f"DART 환경성 실패({e}) — 중단, 부분 결과 저장", file=sys.stderr)
            break
        time.sleep(_SLEEP)
        pub = (extract_eps(resp.get("list") or [], c["fs_div"])
               if resp.get("status") == "000" else None)
        if pub is None:
            results.append({**c, "outcome": "no_pub_eps"})
            continue
        der = float(c["eps_derived"])
        rel = abs(der - pub) / abs(pub) if pub != 0 else None
        results.append({**c, "eps_derived": der, "eps_published": pub,
                        "outcome": "compared",
                        "sign_match": (der >= 0) == (pub >= 0),
                        "rel_err": rel})

    # 2차: YoY 성장률 대조 — 필터 ①②가 실제 소비하는 값. 수준(level) 편향
    # (자기주식·가중평균)이 성장률에서 상쇄되는지 실측.
    comp = [r for r in results if r["outcome"] == "compared"]
    with connect(cfg.database_url) as conn, conn.cursor() as cur:
        for r in comp:
            cur.execute(
                """
                SELECT eps_derived FROM dart_financials
                 WHERE ticker=%s AND bsns_year=%s AND reprt_code=%s
                   AND status='ok' AND eps_derived IS NOT NULL
                """, (r["ticker"], r["bsns_year"] - 1, r["reprt_code"]))
            row = cur.fetchone()
            if not row:
                continue
            prev_der = float(row[0])
            cc = cmap[r["ticker"]]
            try:
                resp = fetch_all_accounts(cfg.dart_api_key, cc,
                                          r["bsns_year"] - 1, r["reprt_code"],
                                          r["fs_div"])
            except DartApiError as e:
                print(f"DART 환경성 실패({e}) — YoY 대조 중단", file=sys.stderr)
                break
            time.sleep(_SLEEP)
            prev_pub = (extract_eps(resp.get("list") or [], r["fs_div"])
                        if resp.get("status") == "000" else None)
            if prev_pub in (None, 0) or prev_der == 0:
                continue
            yoy_der = (r["eps_derived"] - prev_der) / abs(prev_der)
            yoy_pub = (r["eps_published"] - prev_pub) / abs(prev_pub)
            r["yoy_derived"], r["yoy_published"] = yoy_der, yoy_pub
            r["yoy_abs_diff"] = abs(yoy_der - yoy_pub)
            r["threshold_concordant"] = (yoy_der >= 0.25) == (yoy_pub >= 0.25)

    yoy = [r for r in comp if "yoy_abs_diff" in r]
    rels = [r["rel_err"] for r in comp if r["rel_err"] is not None]
    summary = {
        "seed": args.seed, "n_tickers": args.n_tickers,
        "cells_total": len(results), "cells_compared": len(comp),
        "cells_no_pub_eps": sum(r["outcome"] == "no_pub_eps" for r in results),
        "sign_match_rate": (sum(r["sign_match"] for r in comp) / len(comp)) if comp else None,
        "rel_err_median": statistics.median(rels) if rels else None,
        "rel_err_max": max(rels) if rels else None,
        "criteria": {"sign": PASS_SIGN, "median_rel": PASS_MEDIAN_REL,
                     "max_rel": PASS_MAX_REL},
        "yoy_pairs": len(yoy),
        "yoy_abs_diff_median": (statistics.median(r["yoy_abs_diff"] for r in yoy)
                                if yoy else None),
        "yoy_threshold_concordance": (sum(r["threshold_concordant"] for r in yoy)
                                      / len(yoy)) if yoy else None,
    }
    summary["verdict"] = (
        "PASS" if comp and summary["sign_match_rate"] >= PASS_SIGN
        and summary["rel_err_median"] is not None
        and summary["rel_err_median"] <= PASS_MEDIAN_REL
        and summary["rel_err_max"] <= PASS_MAX_REL else "FAIL")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "cells": results},
                              ensure_ascii=False, indent=2, default=str))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    worst = sorted((r for r in comp if r["rel_err"]),
                   key=lambda r: -r["rel_err"])[:5]
    for r in worst:
        print(f"  worst: {r['ticker']} {r['bsns_year']}/{r['reprt_code']} "
              f"derived={r['eps_derived']} pub={r['eps_published']} "
              f"rel={r['rel_err']:.3f}")
    return 0 if summary["verdict"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
