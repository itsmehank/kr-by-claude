"""#242 — #110 확장 백필 제어(backfill_control): 웹 스위치·셀 스냅샷·진행·트립와이어·커밋 핀.

설계(이슈 #242, 2026-11-02 승인):
- 스위치는 DB 행의 값만 바꾼다(cron/launchd 등록 금지 — #86 이중등록 교훈). 일요일 워치독·루프가 읽는다.
- on 시 1회 대상 셀(ticker, 토요일, market)을 스냅샷해 동결 — stocks.delisted_at·security_group·지표가
  라이브값이라 14개월 캠페인 중 모집단이 표류하지 않게. off/on 반복해도 스냅샷·기준선 유지(멱등 재개).
- 셀 정의 = 0단계 견적(scripts/issue110_stage0_estimate.py)과 동일: 토요일 이하 최신 daily_indicators 행이
  minervini_pass ∧ rs_line_not_declining_7m ∧ 당일 거래정지 아님 ∧ security_group ∈ QUALIFYING_SECURITY_GROUPS
  ∧ 현재 상장 ∧ backtest_classification 에 없음.
- 미열람 보존: 여기서 노출하는 값은 건수·모델 종수뿐(분류 결과 없음).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from psycopg import Connection
from psycopg.types.json import Jsonb

from kr_pipeline.common.security_group import QUALIFYING_SECURITY_GROUPS

KEY = "bt110"
DEFAULT_SLICE: list[list[str]] = [["2021-01-02", "2021-12-25"], ["2024-01-06", "2024-12-28"]]
BT_TABLE = "backtest_classification"

_CELLS_SQL = """
WITH sat AS (SELECT d::date AS s FROM generate_series(%(start)s::date, %(end)s::date, '7 days') d),
tgt AS (SELECT s, (SELECT max(date) FROM daily_indicators WHERE date <= s) AS t FROM sat)
SELECT i.ticker, tg.s, st.market
FROM tgt tg JOIN daily_indicators i ON i.date = tg.t
JOIN stocks st ON st.ticker = i.ticker
WHERE i.minervini_pass AND i.rs_line_not_declining_7m
  AND st.delisted_at IS NULL
  AND st.security_group = ANY(%(groups)s)
  AND NOT EXISTS (SELECT 1 FROM daily_prices p
                   WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL)
  AND NOT EXISTS (SELECT 1 FROM backtest_classification b
                   WHERE b.symbol = i.ticker AND b.analyzed_for_date = tg.s)
ORDER BY tg.s, i.ticker
"""


def _first_saturday(d: date) -> date:
    from datetime import timedelta
    return d + timedelta(days=(5 - d.weekday()) % 7)


def _ranges(slice_: list[list[str]]) -> list[tuple[date, date]]:
    return [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in slice_]


def enumerate_cells(conn: Connection, slice_: list[list[str]],
                    groups: frozenset[str] = QUALIFYING_SECURITY_GROUPS) -> list[list[str]]:
    """대상 셀 [[ticker, saturday_iso, market], …] — 설계 §2 필터 전부 적용(읽기 전용)."""
    out: list[list[str]] = []
    with conn.cursor() as cur:
        for a, b in _ranges(slice_):
            # generate_series 는 start 로부터 7일 간격 — start 를 첫 토요일로 맞춘다(평일 start 오입력 방어)
            cur.execute(_CELLS_SQL, {"start": _first_saturday(a), "end": b, "groups": sorted(groups)})
            out.extend([t, s.isoformat(), m] for t, s, m in cur.fetchall())
    return out


def _slice_where(slice_: list[list[str]]) -> tuple[str, list]:
    conds, params = [], []
    for a, b in _ranges(slice_):
        conds.append("(analyzed_for_date BETWEEN %s AND %s)")
        params.extend([a, b])
    return "(" + " OR ".join(conds) + ")", params


def baseline(conn: Connection, slice_: list[list[str]]) -> dict:
    """스위치 on 시점 backtest_classification 기준선 — 트립와이어 대조용."""
    where, params = _slice_where(slice_)
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*), count(DISTINCT symbol) FROM {BT_TABLE}")
        total, symbols = cur.fetchone()
        cur.execute(f"SELECT symbol, analyzed_for_date::text FROM {BT_TABLE} WHERE {where} ORDER BY 2, 1", params)
        pairs = [[a, b] for a, b in cur.fetchall()]
    # slice_pairs: on 시점 슬라이스 내 기존 (symbol, date) — 트립와이어가 시각 비교 없이(now() 는 트랜잭션 시작 시각)
    # "기존 ∪ 스냅샷 밖" 행을 집합으로 판정하게 한다.
    return {"total_rows": total, "slice_rows": len(pairs), "symbols": symbols, "slice_pairs": pairs,
            "at": datetime.now(timezone.utc).isoformat()}


def _row_to_dict(row) -> dict:
    keys = ("key", "enabled", "slice", "cells", "baseline", "pinned_commit", "switched_at", "note", "updated_at")
    d = dict(zip(keys, row))
    for k in ("switched_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


def get_control(conn: Connection, key: str = KEY) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT key, enabled, slice, cells, baseline, pinned_commit, switched_at, note, updated_at "
                    "FROM backfill_control WHERE key = %s", (key,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def set_switch(conn: Connection, enabled: bool, *, slice_: list[list[str]] | None = None,
               note: str | None = None, key: str = KEY) -> dict:
    """스위치 전환. on 이고 스냅샷이 없으면 셀·기준선을 1회 생성. 행이 없으면 생성(기본 슬라이스)."""
    cur_ctl = get_control(conn, key)
    slice_use = slice_ or (cur_ctl["slice"] if cur_ctl else DEFAULT_SLICE)
    cells = cur_ctl["cells"] if cur_ctl else None
    base = cur_ctl["baseline"] if cur_ctl else None
    if cur_ctl and slice_ and slice_ != cur_ctl["slice"]:
        # 슬라이스 변경(2차 조각 전환) = 새 모집단 — 구 스냅샷·기준선을 버리고 on 시 재생성(리뷰 R1-2: 구 쌍으로
        # 새 범위를 판정하면 tripwire 오탐). 구 조각의 COMPLETE 기록은 로그·#110 코멘트에 남는다.
        cells, base = None, None
    if enabled and cells is None:
        base = baseline(conn, slice_use)
        cells = enumerate_cells(conn, slice_use)
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO backfill_control (key, enabled, slice, cells, baseline, switched_at, note, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (key) DO UPDATE SET enabled = EXCLUDED.enabled, slice = EXCLUDED.slice, "
            "cells = EXCLUDED.cells, baseline = EXCLUDED.baseline, switched_at = EXCLUDED.switched_at, "
            "note = COALESCE(EXCLUDED.note, backfill_control.note), updated_at = EXCLUDED.updated_at",
            (key, enabled, Jsonb(slice_use), Jsonb(cells) if cells is not None else None,
             Jsonb(base) if base is not None else None, now, note, now))
    # commit 은 호출자 몫(API get_conn 컨텍스트·CLI connect() 컨텍스트가 종료 시 commit; 테스트는 롤백 격리)
    return get_control(conn, key)


def candidates_by_date(control: dict) -> dict[date, list[dict]]:
    """스냅샷 → run_backtest_backfill(candidates_by_date=…) 입력."""
    out: dict[date, list[dict]] = {}
    for t, s, m in control.get("cells") or []:
        out.setdefault(date.fromisoformat(s), []).append({"symbol": t, "market": m})
    return out


def progress(conn: Connection, control: dict) -> dict:
    """진행 건수·모델 종수(신규 행만 — 미열람 보존: 분류 결과 없음)."""
    cells = control.get("cells") or []
    if not cells:
        return {"target": 0, "done": 0, "remaining": 0, "complete": False, "models_in_slice": {},
                "last_row_at": None}
    pairs = [(t, s) for t, s, _ in cells]
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT symbol, analyzed_for_date::text, COALESCE(llm_model, 'NULL'), created_at "
            f"FROM {BT_TABLE} WHERE (symbol, analyzed_for_date) IN "
            f"(SELECT (v->>0), (v->>1)::date FROM jsonb_array_elements(%s) v)",
            (Jsonb([[t, s] for t, s in pairs]),))
        rows = cur.fetchall()
    done = len(rows)
    models: dict[str, int] = {}
    last = None
    for _, _, model, created in rows:
        models[model] = models.get(model, 0) + 1
        if last is None or created > last:
            last = created
    return {"target": len(cells), "done": done, "remaining": len(cells) - done,
            "complete": done >= len(cells), "models_in_slice": models,
            "last_row_at": last.isoformat() if last else None}


def tripwire(conn: Connection, control: dict) -> list[str]:
    """위반 목록(빈 리스트 = 정상). on 시점 기준선 + 스냅샷 밖의 신규 행이 있으면 위반."""
    base = control.get("baseline") or {}
    slice_ = control["slice"]
    cells = control.get("cells") or []
    violations: list[str] = []
    where, params = _slice_where(slice_)
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*), count(DISTINCT symbol) FROM {BT_TABLE}")
        total, symbols = cur.fetchone()
        # 슬라이스 내 행 중 (on 시점 기존 행 ∪ 스냅샷) 밖 = 외부 적재 의심
        known = [[t, s] for t, s, _ in cells] + list(base.get("slice_pairs") or [])
        cur.execute(
            f"SELECT count(*) FROM {BT_TABLE} b WHERE {where} "
            f"AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(%s) v "
            f"WHERE (v->>0) = b.symbol AND (v->>1)::date = b.analyzed_for_date)",
            params + [Jsonb(known)])
        outside = cur.fetchone()[0]
    if outside:
        violations.append(f"outside_snapshot:{outside}")
    if base and total - base["total_rows"] > len(cells):
        violations.append(f"rows_over_snapshot:{total - base['total_rows']}>{len(cells)}")
    snapshot_symbols = {t for t, _, _ in cells}
    if base and symbols > base["symbols"] + len(snapshot_symbols):
        violations.append(f"symbols_over:{symbols}")
    return violations


def check_or_pin_commit(conn: Connection, head: str, key: str = KEY) -> str:
    """첫 패스: HEAD 기록("pinned"). 이후: 일치 "ok" / 불일치 "mismatch:<pinned>". 제어 행 없음: "no_row"."""
    ctl = get_control(conn, key)
    if ctl is None:
        return "no_row"
    pinned = ctl.get("pinned_commit")
    if not pinned:
        with conn.cursor() as cur:
            cur.execute("UPDATE backfill_control SET pinned_commit = %s, updated_at = now() WHERE key = %s",
                        (head, key))
        return "pinned"
    return "ok" if pinned == head else f"mismatch:{pinned}"


def status(conn: Connection, key: str = KEY) -> dict:
    """API 응답 — 제어 행 + 진행 + 트립와이어(값만, 결과 없음)."""
    ctl = get_control(conn, key)
    if ctl is None:
        return {"key": key, "exists": False, "enabled": False, "slice": DEFAULT_SLICE, "cells_count": 0,
                "baseline": None, "pinned_commit": None, "switched_at": None, "progress": None, "tripwire": []}
    prog = progress(conn, ctl)
    base_pub = {k: v for k, v in (ctl.get("baseline") or {}).items() if k != "slice_pairs"} or None  # 웹 폴링 경량화
    return {"key": key, "exists": True, "enabled": ctl["enabled"], "slice": ctl["slice"],
            "cells_count": len(ctl.get("cells") or []), "baseline": base_pub,
            "pinned_commit": ctl.get("pinned_commit"), "switched_at": ctl.get("switched_at"),
            "note": ctl.get("note"), "progress": prog, "tripwire": tripwire(conn, ctl)}


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
