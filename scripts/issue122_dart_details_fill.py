"""#122 2단계 — DART 구조화 상세 보충 (KRX 0, DART 전용, 신규 행만 INSERT).

1단계(issue122_adj_missing_audit)는 corp_action_details 가 있는 종목만 검사할 수
있다. 본 스크립트가 검사 불가 사각을 메운다:
  (a) 상세 미보유 상장 종목 전부 — 4 엔드포인트 × 2015-06-15~오늘
  (b) 상세 보유 종목 — 마지막 적재일(fetched_at 최대) 이후 증분 창만
  (c) 주식배당(stkdpDecsn) 미조회 상장 종목 — list(pblntf_ty='I') → '주식배당결정'
      원문 파싱(parse_stkdp) → 적재 (#114 v5 경로 동형)
실행 후 1단계를 다시 돌리면 전수 대조가 된다.

  uv run python scripts/issue122_dart_details_fill.py --plan        # 호출 수 견적만(네트워크 0)
  uv run python scripts/issue122_dart_details_fill.py --run [--limit N] [--skip-stkdp]

체크포인트 data/verification/issue122_dart_checkpoint.json — 종목 단위 재개, 연속 오류
10회 중단, 페이싱 0.3s(상세)·0.15s(원문). 일 호출 누적을 체크포인트 calls 에 기록하고
DAILY_CAP(18,500) 도달 시 종료 코드 3(다음 날 재실행으로 이어짐).

호출 견적 주의(리뷰 R1 ⑤): list.json 은 100건/페이지 페이지네이션이라 주식배당 list 는
종목당 1콜이 아니라 2~3콜 — --plan 의 stkdp_list 는 하한. 현실 합계 ≈ 15~18k.

1회성 스크립트: 재실행(다른 날 증분)은 체크포인트 파일 삭제가 전제(키가 창을 포함하지
않음). 이미 stkdpDecsn 행이 있는 종목(62)의 마지막 적재 이후 주식배당은 보충하지 않는다
— 1단계 러너의 pending/unverifiable 로 드러나면 그때 추가.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import psycopg  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from kr_pipeline.corporate_actions.dart_client import fetch_disclosures  # noqa: E402
from kr_pipeline.corporate_actions.details import (  # noqa: E402
    ENDPOINTS, fetch_details, fetch_document_text, parse_stkdp, upsert_details,
)
from kr_pipeline.ohlcv.delisted_backfill import (  # noqa: E402
    add_calls, calls_today, load_checkpoint, save_checkpoint,
)

DB = os.environ.get("DATABASE_URL", "postgresql://localhost/kr_pipeline")
CP = Path("data/verification/issue122_dart_checkpoint.json")
BGN = "20150615"
PACE = 0.3
DOC_PACE = 0.15
ABORT_ERRORS = 10
DAILY_CAP = 18_500          # DART 일 2만 — morning-corp 등 다른 소비자 여유분 제외


def _cap_reached(cp: dict) -> bool:
    return calls_today(cp, date.today().isoformat()) >= DAILY_CAP


def _count(cp: dict, n: int = 1) -> None:
    add_calls(cp, date.today().isoformat(), n)


def plan(conn) -> dict:
    """대상 집합과 호출 수 견적(네트워크 0)."""
    with conn.cursor() as cur:
        cur.execute("SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY ticker")
        listed = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT ticker, max(fetched_at)::date FROM corp_action_details "
                    "WHERE endpoint = ANY(%s) GROUP BY ticker", (list(ENDPOINTS),))
        last_of = dict(cur.fetchall())
        cur.execute("SELECT DISTINCT ticker FROM corp_action_details WHERE endpoint='stkdpDecsn'")
        stkdp_has = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT stock_code FROM dart_corp_codes")
        mapped = {r[0] for r in cur.fetchall()}
    today = date.today()
    full = [t for t in listed if t not in last_of and t in mapped]
    incr = [(t, last_of[t]) for t in listed if t in last_of and t in mapped
            and last_of[t] < today - timedelta(days=1)]
    stkdp = [t for t in listed if t not in stkdp_has and t in mapped]
    unmapped = [t for t in listed if t not in mapped]
    return {"listed": len(listed), "unmapped": unmapped,
            "full": full, "incr": incr, "stkdp": stkdp,
            "calls": {"full": len(full) * len(ENDPOINTS),
                      "incr": len(incr) * len(ENDPOINTS),
                      "stkdp_list_min": len(stkdp),
                      "stkdp_list_note": "페이지네이션(100건/페이지)으로 종목당 2~3콜 — 하한",
                      "stkdp_docs": "주식배당결정 건수만큼 추가(미지, #114 실측 ~1.3건/보유종목)"}}


def run(limit: int | None, skip_stkdp: bool) -> int:
    api_key = os.environ.get("DART_API_KEY", "")
    if not api_key:
        print("DART_API_KEY 없음")
        return 1
    with psycopg.connect(DB) as conn:
        p = plan(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT stock_code, corp_code FROM dart_corp_codes")
            corp_of = dict(cur.fetchall())
    cp = load_checkpoint(CP)
    done = set(cp["done"])
    end = date.today().strftime("%Y%m%d")
    jobs: list[tuple[str, str, str]] = []           # (key, ticker, bgn)
    jobs += [(f"full:{t}", t, BGN) for t in p["full"]]
    jobs += [(f"incr:{t}", t, (d - timedelta(days=7)).strftime("%Y%m%d"))
             for t, d in p["incr"]]                 # 7일 겹침 — 정정 재접수 흡수
    todo = [j for j in jobs if j[0] not in done]
    print(f"details jobs={len(jobs)} todo={len(todo)} (full {len(p['full'])}, "
          f"incr {len(p['incr'])})")
    errors = processed = 0
    for key, t, bgn in todo:
        if limit is not None and processed >= limit:
            print("limit 도달 — 정상 종료")
            return 0
        if _cap_reached(cp):
            print("일 호출 상한 — 내일 재실행")
            return 3
        try:
            with psycopg.connect(DB) as conn:
                total = 0
                for ep in ENDPOINTS:
                    time.sleep(PACE)
                    _count(cp)
                    items = fetch_details(api_key, corp_of[t], ep, bgn, end)
                    total += upsert_details(conn, t, ep, items)
            cp["done"].append(key)
            errors = 0
            if total:
                print(f"[{key}] +{total}")
        except Exception as e:  # noqa: BLE001
            errors += 1
            cp["failed"][key] = cp["failed"].get(key, 0) + 1
            print(f"ERROR {key} — {type(e).__name__}: {e} (연속 {errors})")
            if errors >= ABORT_ERRORS:
                save_checkpoint(CP, cp)
                print("연속 오류 중단")
                return 1
        finally:
            save_checkpoint(CP, cp)
        processed += 1

    if skip_stkdp:
        return 0
    stk_todo = [t for t in p["stkdp"] if f"stkdp:{t}" not in done]
    print(f"stkdp todo={len(stk_todo)}")
    stats = {"disclosures": 0, "parsed": 0, "inserted": 0, "parse_fail": [],
             "doc_unavailable": []}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for i, t in enumerate(stk_todo, 1):
            if limit is not None and processed >= limit:
                print("limit 도달 — 정상 종료")
                break
            if _cap_reached(cp):
                print("일 호출 상한 — 내일 재실행")
                save_checkpoint(CP, cp)
                return 3
            try:
                time.sleep(DOC_PACE)
                items = fetch_disclosures(api_key, corp_of[t], date(2015, 1, 1),
                                          date.today(), pblntf_ty="I")
                _count(cp, len(items) // 100 + 1)       # 페이지 수 근사
                hits = [it for it in items if "주식배당결정" in it.get("report_nm", "")]
                stats["disclosures"] += len(hits)
                for it in hits:
                    rc = it["rcept_no"]
                    time.sleep(DOC_PACE)
                    _count(cp)
                    try:
                        text = fetch_document_text(api_key, rc)
                    except Exception as e:  # noqa: BLE001
                        stats["doc_unavailable"].append({"ticker": t, "rcept_no": rc,
                                                         "err": str(e)[:80]})
                        continue
                    parsed = parse_stkdp(text)
                    if not parsed:
                        stats["parse_fail"].append({"ticker": t, "rcept_no": rc,
                                                    "report_nm": it["report_nm"]})
                        continue
                    stats["parsed"] += 1
                    cur.execute(
                        "INSERT INTO corp_action_details "
                        "(ticker, rcept_no, endpoint, record_date, ratio, method, payload) "
                        "VALUES (%s, %s, 'stkdpDecsn', %s, %s, '주식배당', %s) "
                        "ON CONFLICT DO NOTHING",
                        (t, rc, parsed["record_date"], parsed["ratio"],
                         Jsonb({**{k: (v.isoformat() if isinstance(v, date) else v)
                                   for k, v in parsed.items()},
                                "report_nm": it["report_nm"]})))
                    stats["inserted"] += cur.rowcount
                conn.commit()
                cp["done"].append(f"stkdp:{t}")
                errors = 0
            except Exception as e:  # noqa: BLE001
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
                errors += 1
                cp["failed"][f"stkdp:{t}"] = cp["failed"].get(f"stkdp:{t}", 0) + 1
                print(f"ERROR stkdp:{t} — {type(e).__name__}: {e} (연속 {errors})")
                if errors >= ABORT_ERRORS:
                    save_checkpoint(CP, cp)
                    print("연속 오류 중단")
                    return 1
            finally:
                save_checkpoint(CP, cp)
            processed += 1
            if i % 100 == 0:
                print(f"  stkdp {i}/{len(stk_todo)} discl={stats['disclosures']} "
                      f"ins={stats['inserted']}")
    out = f"data/verification/issue122_stkdp_fill_{date.today():%Y%m%d}.json"
    with open(out, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: (v if not isinstance(v, list) else len(v))
                      for k, v in stats.items()}, ensure_ascii=False), "saved:", out)
    return 0


def main() -> int:
    if "--plan" in sys.argv:
        with psycopg.connect(DB) as conn:
            conn.read_only = True
            p = plan(conn)
        print(json.dumps({"listed": p["listed"], "unmapped": len(p["unmapped"]),
                          "full_tickers": len(p["full"]), "incr_tickers": len(p["incr"]),
                          "stkdp_tickers": len(p["stkdp"]), "calls": p["calls"]},
                         ensure_ascii=False, indent=1))
        return 0
    if "--run" in sys.argv:
        limit = None
        if "--limit" in sys.argv:
            i = sys.argv.index("--limit")
            if i + 1 >= len(sys.argv):
                print("--limit N 필요")
                return 1
            limit = int(sys.argv[i + 1])
        return run(limit, "--skip-stkdp" in sys.argv)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
