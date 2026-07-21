"""(#68 1단계) DART 재무 데이터 타당성 프로브 — 커버리지·공시 시차·소급 가능성.

read-only (DB 조회 + OpenDART API 호출). 결과 JSON:
data/verification/issue68_dart_probe.json — 보고서가 판독.

측정 설계 (조사이지 판정 아님 — 게이트 결정은 사용자):
- 표본: 백테스트 표본 종목 15 + 활성 종목 임의 15 (KOSPI/KOSDAQ 혼합)
- 연간: 2017~2024 사업보고서(11011) 주요계정(fnlttSinglAcnt) — 매출액/영업이익/
  당기순이익 존재 여부 + 접수일(rcept_no 앞 8자리) 시차(회계연도말 대비)
- 분기: 2023 1분기(11013)·3분기(11014) 존재 여부 + 분기말 대비 시차
  (look-ahead 방지 기준의 재료 — as-of 공시일 조회 유틸의 요구 스펙)
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import date

import psycopg

from kr_pipeline.common.config import Config

BASE = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
ACCOUNTS = ("매출액", "영업이익", "당기순이익")
YEARS = list(range(2017, 2025))
QUARTERS = [("11013", date(2023, 3, 31)), ("11014", date(2023, 9, 30))]


def _call(key: str, corp_code: str, year: int, reprt: str) -> dict:
    q = urllib.parse.urlencode({
        "crtfc_key": key, "corp_code": corp_code,
        "bsns_year": str(year), "reprt_code": reprt,
    })
    with urllib.request.urlopen(f"{BASE}?{q}", timeout=15) as r:
        return json.load(r)


def _probe_report(key, corp_code, year, reprt, period_end) -> dict:
    try:
        resp = _call(key, corp_code, year, reprt)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)}
    if resp.get("status") != "000":
        return {"status": resp.get("status")}
    rows = resp.get("list") or []
    # 연결(CFS) 우선, 없으면 별도(OFS)
    have = set()
    rcept = None
    for fs in ("CFS", "OFS"):
        sub = [r for r in rows if r.get("fs_div") == fs]
        if not sub:
            continue
        have = {r.get("account_nm") for r in sub} & set(ACCOUNTS)
        rcept = sub[0].get("rcept_no", "")[:8]
        if have:
            break
    lag = None
    if rcept and len(rcept) == 8:
        rd = date(int(rcept[:4]), int(rcept[4:6]), int(rcept[6:8]))
        lag = (rd - period_end).days
    return {"status": "000", "accounts": sorted(have), "rcept_date": rcept,
            "lag_days": lag}


def main() -> None:
    cfg = Config.load()
    assert cfg.dart_api_key, "DART_API_KEY 필요 (.env)"
    with psycopg.connect(cfg.database_url) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT b.symbol FROM backtest_classification b
            ORDER BY b.symbol LIMIT 15
        """)
        bt = [r[0] for r in cur.fetchall()]
        cur.execute("""
            SELECT ticker FROM stocks
            WHERE delisted_at IS NULL AND NOT ticker = ANY(%s)
            ORDER BY md5(ticker) LIMIT 15
        """, (bt,))
        rnd = [r[0] for r in cur.fetchall()]
        tickers = bt + rnd
        cur.execute(
            "SELECT stock_code, corp_code FROM dart_corp_codes WHERE stock_code = ANY(%s)",
            (tickers,))
        cmap = dict(cur.fetchall())

    out = {"sample": {"backtest": bt, "random": rnd},
           "unmapped": [t for t in tickers if t not in cmap],
           "tickers": {}}
    for t in tickers:
        cc = cmap.get(t)
        if not cc:
            continue
        rec = {"annual": {}, "quarterly": {}}
        for y in YEARS:
            rec["annual"][y] = _probe_report(
                cfg.dart_api_key, cc, y, "11011", date(y, 12, 31))
            time.sleep(0.12)
        for reprt, qend in QUARTERS:
            rec["quarterly"][reprt] = _probe_report(
                cfg.dart_api_key, cc, 2023, reprt, qend)
            time.sleep(0.12)
        out["tickers"][t] = rec
        print(f"{t}: annual_ok="
              f"{sum(1 for v in rec['annual'].values() if v.get('status') == '000')}"
              f"/{len(YEARS)}")

    path = "data/verification/issue68_dart_probe.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"saved {path}")


if __name__ == "__main__":
    main()
