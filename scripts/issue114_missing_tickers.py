"""#114 §0 — 부재 종목 목록 재산출·영속화 (~24 KRX 요청, 페이싱 1.5s).

연말 스냅샷 12개에서 (등장 시장, 첫/마지막 관측 스냅샷)을 수집해
DB stocks 에 없는 보통주 근사(끝자리 0) 종목 목록을 JSON 으로 저장.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from pykrx import stock as krx  # noqa: E402
import psycopg  # noqa: E402

SNAP_DATES = ["20160613", "20161229", "20171228", "20181228", "20191230",
              "20201230", "20211230", "20221229", "20231228", "20241230",
              "20251230", "20260814"]
PACE_SEC = 1.5
OUT = "data/verification/issue114_missing_tickers.json"


def snapshot(d: str) -> dict[str, str]:
    """{ticker: market} — 빈 응답이면 하루씩 당겨 최대 5회."""
    for back in range(6):
        dd = (date.fromisoformat(f"{d[:4]}-{d[4:6]}-{d[6:]}")
              - timedelta(days=back)).strftime("%Y%m%d")
        out: dict[str, str] = {}
        ok = True
        for mkt in ("KOSPI", "KOSDAQ"):
            time.sleep(PACE_SEC)
            lst = krx.get_market_ticker_list(dd, market=mkt)
            if not lst:
                ok = False
                break
            out.update({t: mkt for t in lst})
        if ok:
            print(f"snapshot {dd}: {len(out)}")
            return out
    raise RuntimeError(f"no data near {d}")


def main() -> int:
    snaps = {d: snapshot(d) for d in SNAP_DATES}
    with psycopg.connect("postgresql://localhost/kr_pipeline") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker FROM stocks")
            known = {r[0] for r in cur.fetchall()}

    info: dict[str, dict] = {}
    for d in SNAP_DATES:
        for t, mkt in snaps[d].items():
            if not t.endswith("0") or t in known:
                continue
            e = info.setdefault(t, {"first_seen": d, "last_seen": d, "market": mkt})
            e["last_seen"] = d
            e["market"] = mkt          # 마지막 관측 시장(이전상장 반영)
    # 최신 스냅샷(현재)에도 존재하면 상장 유지인데 DB에 없는 것 — 별도 표기
    still_listed = {t for t in info if t in snaps[SNAP_DATES[-1]]}
    out = {"generated": date.today().isoformat(),
           "missing": [{"ticker": t, **v, "still_listed": t in still_listed}
                       for t, v in sorted(info.items())],
           "n": len(info), "n_still_listed": len(still_listed)}
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"missing={out['n']} (still_listed={out['n_still_listed']}) saved: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
