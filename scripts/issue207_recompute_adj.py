"""#207 회신 15·16 — 시임(2026-09-14) 전진 재산출: adj_* (raw × F) → 주봉 → 지표(RS·minervini_pass·7m 게이트).
**외부 접촉 0**(DB 전용). dry-run 기본(이벤트·기준선·내재 검증만, 쓰기 0). --execute 로 5단계 실행.

전제(배포 순서): 라이브 체크아웃이 계수 PR main 으로 전환된 **뒤**, 새 코드의 첫 평일 체인 **전**에 실행.
  adjust.ADJ_NAVER_HISTORY_THROUGH(구 코드 마지막 실행일) 이하 조정일은 시임 이전 이력에 이미 소급돼 있어 기록만 한다 —
  이 전제를 1단계에서 이벤트별로 검증(R = adj_close/close 가 이벤트 전후 시임 이전 구간에서 Π coef 만큼 다르지 않고
  일정한가). 불일치가 있으면 중단(쓰기 0)하고 회신.

단계
 0 기준선: 시임 이전 adj_* 체크섬(불변 확인용) + 시임 이후 daily_indicators(minervini_pass·rs_rating·rs_line_not_declining_7m) 스냅샷
 1 이벤트: 활성 종목 change_pct 로 시임 이후 조정일 검출(달력 결측 보류) → 내재 검증 → adjust.ingest_events(정책: THROUGH 이하 기록만,
   이후는 시임 이전 소급 + 시임 이후 재유도)
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
from kr_pipeline.weekly.load import load_active_tickers

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


def _verify_embodiment(cn, events: dict) -> dict:
    """이벤트별 내재 검증(정확한 기준 = 행 updated_at): 이벤트일 이후 Naver 구코드가 재적재한 시임 이전 행(new)은 그 이벤트를
    소급 반영했고, 이벤트일 전에 마지막으로 적재된 행(old)은 반영 못 했을 수 있다. 경계에서 R=adj/close 비율
    R(new 첫 행)/R(old 마지막 행) ≈ 1 이면 전 이력 정합(주말 스윕 reload 가 갱신), ≈ coef 이면 old 구간 stale(재산출 전 수리 필요).
    과거 다른 기업행위로 인한 R 변동은 경계 비교라 영향 없다."""
    out = {}
    for t, evs in events.items():
        rows = cn.execute("SELECT date, adj_close/close, updated_at::date FROM daily_prices WHERE ticker=%s AND date < %s AND high>0 "
                          "AND close>0 AND adj_close IS NOT NULL ORDER BY date", (t, SEAM)).fetchall()
        for d, coef in evs:
            old = [(dt, float(r)) for dt, r, u in rows if u < d]
            new = [(dt, float(r)) for dt, r, u in rows if u >= d]
            key = f"{t}|{d}"
            policy = "record_only" if d <= adjust.ADJ_NAVER_HISTORY_THROUGH else "apply_pre_seam"
            if not old or not new:
                out[key] = {"ok": True, "note": f"비교 불가(old {len(old)}·new {len(new)}) — 전 이력이 한쪽", "policy": policy}
                continue
            ratio = new[0][1] / old[-1][1]
            stale = abs(ratio - coef) < 0.002 * max(1.0, coef)
            out[key] = {"ok": abs(ratio - 1) < 0.002, "ratio_new_over_old": round(ratio, 6), "coef": round(coef, 6),
                        "old_rows": len(old), "old_last": old[-1][0].isoformat(), "new_first": new[0][0].isoformat(),
                        "stale_old_segment": stale, "policy": policy}
    return out


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
        active = load_active_tickers(cn)
        events = adjust.detect_events_all(cn, since=SEAM, tickers=active)
        rep["events"] = {t: [(d.isoformat(), round(c, 6)) for d, c in e] for t, e in events.items()}
        print(f"활성 {len(active)} · 시임 이후 미기록 조정일 {sum(len(e) for e in events.values())}건/{len(events)}종목")
        # 1a 내재 검증: THROUGH 이하 이벤트는 시임 이전 이력에 이미 소급돼 있어야 한다(R 일정), 이후 이벤트는 반영돼 있지 않아야 한다.
        rep["embodiment"] = _verify_embodiment(cn, events)
        bad = [k for k, v in rep["embodiment"].items() if not v["ok"]]
        if bad:
            json.dump(rep, open(a.report, "w"), ensure_ascii=False, indent=1)
            print(f"내재 검증 불일치 {len(bad)}건 → 중단(쓰기 0), 회신 필요: {bad[:10]}"); return 3
        if not a.execute:
            json.dump(rep, open(a.report, "w"), ensure_ascii=False, indent=1)
            print("dry-run — 쓰기 0. --execute 로 실행."); return 0

        # 1b 이벤트 반영(정책은 adjust.ingest_events 단일 정의)
        ing = {t: adjust.ingest_events(cn, t, e) for t, e in events.items()}
        rep["ingest"] = {"recorded": sum(v["recorded"] for v in ing.values()), "applied_rows": sum(v["applied_rows"] for v in ing.values()),
                         "rederived_rows": sum(v["rederived_rows"] for v in ing.values())}
        cn.commit()
        # 2 adj 재유도(이벤트 없는 종목 포함 전 종목 시임 이후 raw×F)
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
