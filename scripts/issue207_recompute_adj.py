"""#207 회신 15·16 — 시임(2026-09-14) 전진 재산출: adj_* (raw × F) → 주봉 → 지표(RS·minervini_pass·7m 게이트).
**외부 접촉 0**(DB 전용). dry-run 기본(이벤트·기준선만 계산, 쓰기 0). --execute 로 5단계 실행.

단계
 0 기준선: 시임 이전 adj_* 체크섬(불변 확인용) + 시임 이후 daily_indicators(minervini_pass·rs_rating·rs_line_not_declining_7m) 스냅샷
 1 이벤트: 활성 종목 change_pct 로 시임 이후 조정일 검출 → adj_factor_events 기록(소급 적용 없음 — 사전 실측: 16건 전부
   Naver 구정의 이력에 이미 소급돼 있음, R(08-01)=R(09-11)≈Π coef)
 2 adj 재유도: ohlcv FULL_REFRESH(시임 이후 행 raw × F, 시임 이전 불변)
 3 주봉: weekly INCREMENTAL(창 4주 = 09-18·09-23 주 포함)
 4 지표: indicators run_daily INCREMENTAL(window = 시임~오늘 + 여유) → run_weekly INCREMENTAL(Phase D 미러 포함)
 5 검증: 시임 이전 adj 체크섬 동일 · 지표 차분 요약(뒤집힌 셀·종목) → 리포트 JSON
파리티(백테스트)는 별도 명령(README/#207): uv run python -m kr_pipeline.backtest.portfolio --sample=ab
"""
from __future__ import annotations
import argparse, json, sys
from datetime import date, timedelta

import psycopg

from kr_pipeline.common.config import Config
from kr_pipeline.ohlcv import adjust
from kr_pipeline.ohlcv import modes as ohlcv
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators

SEAM = adjust.ADJ_SELF_START


def _checksum_pre_seam(cn) -> dict:
    row = cn.execute(
        "SELECT count(*), md5(string_agg(ticker||date||coalesce(adj_close::text,'')||coalesce(adj_high::text,'')||"
        "coalesce(adj_low::text,'')||coalesce(adj_open::text,'')||coalesce(adj_volume::text,''), ',' ORDER BY ticker, date)) "
        "FROM daily_prices WHERE date < %s", (SEAM,)).fetchone()
    return {"rows": row[0], "md5": row[1]}


def _snapshot_indicators(cn) -> dict:
    rows = cn.execute(
        "SELECT ticker, date, minervini_pass, rs_rating, rs_line_not_declining_7m FROM daily_indicators WHERE date >= %s",
        (SEAM,)).fetchall()
    return {f"{t}|{d}": (mp, None if rs is None else float(rs), g) for t, d, mp, rs, g in rows}


def _diff(before: dict, after: dict) -> dict:
    keys = set(before) | set(after)
    flip_mp = [k for k in keys if (before.get(k) or (None,))[0] != (after.get(k) or (None,))[0]]
    flip_gate = [k for k in keys if (before.get(k) or (None, None, None))[2] != (after.get(k) or (None, None, None))[2]]
    rs_moved = [k for k in keys if k in before and k in after and before[k][1] != after[k][1]]
    return {
        "cells": len(keys), "minervini_pass_flipped_cells": len(flip_mp),
        "minervini_pass_flipped_tickers": sorted({k.split("|")[0] for k in flip_mp}),
        "rs_gate_flipped_cells": len(flip_gate), "rs_rating_changed_cells": len(rs_moved),
        "sample_flips": sorted(flip_mp)[:30],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--report", default="data/verification/issue207_recompute_report.json")
    a = ap.parse_args()
    cfg = Config.load()
    rep: dict = {"execute": a.execute, "seam": SEAM.isoformat()}
    with psycopg.connect(cfg.database_url) as cn:
        rep["pre_seam_checksum_before"] = _checksum_pre_seam(cn)
        before = _snapshot_indicators(cn)
        rep["indicator_cells_before"] = len(before)
        active = [r[0] for r in cn.execute("SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY 1").fetchall()]
        events = {t: adjust.detect_events(cn, t, since=SEAM) for t in active}
        events = {t: e for t, e in events.items() if e}
        rep["events"] = {t: [(d.isoformat(), round(c, 6)) for d, c in e] for t, e in events.items()}
        print(f"활성 {len(active)} · 시임 이후 조정일 {sum(len(e) for e in events.values())}건/{len(events)}종목")
        if not a.execute:
            json.dump(rep, open(a.report, "w"), ensure_ascii=False, indent=1)
            print("dry-run — 쓰기 0. --execute 로 실행."); return 0

        # 1 이벤트 기록(소급 없음)
        rep["events_recorded"] = sum(adjust.record_events(cn, t, e) for t, e in events.items())
        cn.commit()
        # 2 adj 재유도
        r2 = ohlcv.run(cn, ohlcv.Mode.FULL_REFRESH)
        rep["adj_rederived_rows"] = r2.rows_affected; rep["adj_failures"] = r2.failures[:20]
        # 3 주봉
        r3 = weekly.run(cn, weekly.Mode.INCREMENTAL, window_weeks=4)
        rep["weekly_rows"] = r3.rows_affected
        # 4 지표
        win = (date.today() - SEAM).days + 5
        r4 = indicators.run_daily(cn, indicators.Mode.INCREMENTAL, window=win)
        r5 = indicators.run_weekly(cn, indicators.Mode.INCREMENTAL)
        rep["indicators_daily_rows"] = r4.rows_affected; rep["indicators_weekly_rows"] = r5.rows_affected
        rep["indicator_failures"] = (r4.failures + r5.failures)[:20]
        # 5 검증
        rep["pre_seam_checksum_after"] = _checksum_pre_seam(cn)
        rep["pre_seam_unchanged"] = rep["pre_seam_checksum_after"] == rep["pre_seam_checksum_before"]
        after = _snapshot_indicators(cn)
        rep["diff"] = _diff(before, after)
    json.dump(rep, open(a.report, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != "events"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
