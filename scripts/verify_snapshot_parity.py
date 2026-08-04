"""#94 동일성 실측 — 날짜별 전종목 스냅샷 vs 기존(종목별 수집) daily_prices raw 비교.

용법: uv run python scripts/verify_snapshot_parity.py [YYYY-MM-DD]
  기본 날짜 = 2026-07-30 (구 종목별 경로로 적재된 마지막 완전 수집일 부근 —
  7/31 은 1,197/2,549 부분 적재라 비교 모수가 준다)

KRX 접촉 = 로그인 1회(pykrx import 부작용) + 전종목시세 1요청.
차단 대기 기간(08-06 전) 실행 거부 — 불가피하면 PARITY_FORCE=1.

판정: DB 에 저장된 그 날짜 전 종목 raw(open/high/low/close/volume/value)와
스냅샷 값이 전부 일치하면 rc=0 — 새 수집 경로가 기존 로직과 동일함을 실데이터로
실증한다. 하나라도 다르면 rc=1 (재개 보류, 불일치 목록 확인).

주의: pykrx/config import 는 main() 안에서만 한다 — 이 파일을 import 하는
테스트(compare_rows 단위 테스트)가 KRX 접촉을 유발하면 안 되기 때문(#92 격리).
"""
from __future__ import annotations

import os
import sys
from datetime import date

RAW_COLS = ["open", "high", "low", "close", "volume", "value"]


def compare_rows(db_rows: dict[str, tuple], snap) -> dict:
    """DB raw 행과 스냅샷 DataFrame 을 비교해 요약 dict 반환 (순수 함수).

    db_rows: {ticker: (open, high, low, close, volume, value)}
    snap: fetch_market_snapshot 반환 DF (ticker + RAW_COLS + date 컬럼)
    extra_in_snapshot(스냅샷에만 있는 티커)는 universe 밖 신규상장 등 — 정보성.
    """
    snap_map = {
        r["ticker"]: tuple(int(r[c]) for c in RAW_COLS)
        for _, r in snap.iterrows()
    }
    mismatches: list[tuple[str, tuple, tuple]] = []
    missing: list[str] = []
    for t, db_vals in sorted(db_rows.items()):
        got = snap_map.get(t)
        if got is None:
            missing.append(t)
        elif tuple(int(v) for v in db_vals) != got:
            mismatches.append((t, tuple(int(v) for v in db_vals), got))
    return {
        "db_count": len(db_rows),
        "snap_count": len(snap_map),
        "matched": len(db_rows) - len(missing) - len(mismatches),
        "mismatches": mismatches,
        "missing_in_snapshot": missing,
        "extra_in_snapshot": sorted(set(snap_map) - set(db_rows)),
    }


def main() -> int:
    if date.today().strftime("%Y%m%d") < "20260806" and os.environ.get("PARITY_FORCE") != "1":
        print("[parity] 차단 대기 기간(08-06 전) — 실행 거부. 불가피하면 PARITY_FORCE=1")
        return 2

    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 7, 30)

    from kr_pipeline.common import config  # noqa: F401 — .env 로드(KRX 인증·DATABASE_URL)
    from kr_pipeline.db.connection import connect
    from kr_pipeline.ohlcv.fetch import fetch_market_snapshot

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, open, high, low, close, volume, value "
            "FROM daily_prices WHERE date = %s",
            (target,),
        )
        db_rows = {t: vals for t, *vals in ((r[0], *r[1:]) for r in cur.fetchall())}

    if not db_rows:
        print(f"[parity] DB 에 {target} 일봉이 없음 — 비교 불능. 다른 날짜를 지정할 것")
        return 2

    snap = fetch_market_snapshot(target)
    if snap.empty:
        status = snap.attrs.get("snapshot_status", "empty")
        print(f"[parity] 스냅샷 빈 응답(status={status}) — 차단 지속 또는 휴일. 재개 보류")
        return 1

    r = compare_rows(db_rows, snap)
    print(f"[parity] {target} — DB {r['db_count']}종목 vs 스냅샷 {r['snap_count']}종목")
    print(f"[parity] 일치 {r['matched']} / 불일치 {len(r['mismatches'])} / "
          f"스냅샷 미출현 {len(r['missing_in_snapshot'])} / universe 밖 {len(r['extra_in_snapshot'])}")
    for t, db_v, snap_v in r["mismatches"][:20]:
        print(f"  [불일치] {t}: DB(OHLCVv)={db_v} vs 스냅샷={snap_v}")
    if r["missing_in_snapshot"]:
        print(f"  [미출현] {r['missing_in_snapshot'][:20]}")

    if r["mismatches"] or r["missing_in_snapshot"]:
        print("[parity] 판정: 불일치 — 재개 보류, 원인 확인 필요")
        return 1
    print("[parity] 판정: 전량 일치 — 새 수집 경로가 기존 로직과 동일 (재개 가능 근거)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
