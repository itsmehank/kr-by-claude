"""/review 종목 행(streak) 뷰 조립 — 스펙 docs/superpowers/specs/2026-08-25-review-stock-streak-view-design.md 가 원본.

핵심 규칙:
- 전역 하한 REVIEW_COVERAGE_START(라이브·백필 모두) — 이전 행은 산발 표본이라 제외.
- 묶음 종결 = ignore(모든 source) 또는 system_disqualify. 공백은 이어짐(>10일이면 has_gap).
- 좌측 절단 = 묶음 시작 ≤ 하한+7일.
"""
from __future__ import annotations

from datetime import date, timedelta

from psycopg import Connection
from psycopg.rows import dict_row

from api.services.review_builder import (
    # REVIEW_COVERAGE_START: #132 에서 정의를 review_builder 로 이동 —
    # 기존 import 경로(review_streaks) 호환을 위한 re-export.
    BREAKOUT_TYPES, MERGED_ROWS_CTES, REVIEW_COVERAGE_START, chain_tn,
    corp_action_flags, first_breakout, max_reach, count_orphan_triggers,
    fetch_price_series,
)
_CENSOR_WINDOW = timedelta(days=7)
_GAP_DAYS = 10
_VALID_SOURCES = ("weekend", "daily_delta", "backfill")

# 병합 규약(전역 하한·주 단위 라이브 우선 dedup)은 공유 조각 MERGED_ROWS_CTES
# (review_builder)가 단일 정의 — 분석 행 뷰(_ROWS_SQL)와 구조적으로 동일.
_SCOPED_SQL = f"""
WITH {MERGED_ROWS_CTES}
SELECT * FROM live UNION ALL SELECT * FROM bf
ORDER BY symbol, key_date, classified_at
"""

_PERIOD_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM (
    SELECT symbol, source, classification,
           COALESCE(analyzed_for_date, classified_at::date) AS key_date
      FROM weekly_classification
    UNION ALL
    SELECT symbol, source, classification, analyzed_for_date FROM classification_backfill
) u
WHERE key_date BETWEEN GREATEST(%(date_from)s, %(floor)s) AND %(date_to)s
  AND classification IN ('entry', 'watch')
  AND source = ANY(%(sources)s)
  AND (%(ticker)s::text IS NULL OR symbol = %(ticker)s)
ORDER BY symbol
"""


def fetch_scoped_rows(conn: Connection, *, symbols: list[str]) -> list[dict]:
    if not symbols:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SCOPED_SQL, {"symbols": symbols, "floor": REVIEW_COVERAGE_START})
        rows = cur.fetchall()
    for r in rows:
        r["pivot_price"] = float(r["pivot_price"]) if r["pivot_price"] is not None else None
    return rows


def find_period_symbols(conn: Connection, *, date_from: date, date_to: date,
                        source: str | None, ticker: str | None) -> list[str]:
    sources = [source] if source else list(_VALID_SOURCES)
    with conn.cursor() as cur:
        cur.execute(_PERIOD_SYMBOLS_SQL, {
            "date_from": date_from, "date_to": date_to, "floor": REVIEW_COVERAGE_START,
            "sources": sources, "ticker": ticker,
        })
        return [r[0] for r in cur.fetchall()]


def _is_valid(row: dict) -> bool:
    return row["classification"] in ("entry", "watch") and row["source"] in _VALID_SOURCES


def _closer_kind(row: dict) -> str | None:
    if row["classification"] == "ignore":
        return "ignore"
    if row["source"] == "system_disqualify":
        return "disqualify"
    return None


def segment_streaks(rows: list[dict]) -> list[dict]:
    """한 종목의 정렬된 전 이력 → streak 리스트 (스펙 §1)."""
    streaks: list[dict] = []
    cur: dict | None = None
    for row in rows:
        if _is_valid(row):
            row.setdefault("triggers", [])
            if cur is None:
                cur = {"symbol": row["symbol"], "start": row["key_date"], "end": None,
                       "closed_by": None, "has_gap": False, "backfilled": False,
                       "analyses": []}
            else:
                prev_kd = cur["analyses"][-1]["key_date"]
                if (row["key_date"] - prev_kd).days > _GAP_DAYS:
                    cur["has_gap"] = True
            cur["analyses"].append(row)
            cur["backfilled"] = cur["backfilled"] or row["backfilled"]
        else:
            kind = _closer_kind(row)
            if kind and cur is not None:
                cur["end"] = row["key_date"]
                cur["closed_by"] = kind
                cur["closed_reason"] = row.get("reasoning")
                streaks.append(cur)
                cur = None
            # 닫는 행인데 열린 묶음 없음 → 무시 (스펙 §6: 닫는 행만 있는 종목은 행 아님)
    if cur is not None:
        streaks.append(cur)
    for s in streaks:
        s["censored"] = s["start"] <= REVIEW_COVERAGE_START + _CENSOR_WINDOW
    return streaks


def intersect_period(streaks: list[dict], date_from: date, date_to: date) -> list[dict]:
    return [s for s in streaks
            if s["start"] <= date_to and (s["end"] is None or s["end"] >= date_from)]


_TRIGGERS_SQL = """
SELECT t.symbol, t.prior_classification_at, t.evaluated_at, t.trigger_type,
       t.decision, t.close, t.pivot_price, t.reasoning,
       COALESCE(t.analyzed_for_date,
                (t.evaluated_at AT TIME ZONE 'UTC')::date) AS d
  FROM trigger_evaluation_log t
  JOIN unnest(%(syms)s::text[], %(ats)s::timestamptz[]) AS k(symbol, classified_at)
    ON t.symbol = k.symbol AND t.prior_classification_at = k.classified_at
 ORDER BY d, t.evaluated_at
"""


def attach_triggers(conn: Connection, streaks: list[dict]) -> None:
    """prior_classification_at 직접 조인 — 분석별 중첩 (review_builder 와 동일 규칙.
    SQL 을 복제하는 이유: review_builder 무수정 계약(스펙 §4) — 사설 상수 import 회피."""
    index: dict[tuple, dict] = {}
    for s in streaks:
        for a in s["analyses"]:
            a["triggers"] = []
            index[(a["symbol"], a["classified_at"])] = a
    if not index:
        return
    syms = [k[0] for k in index]
    ats = [k[1] for k in index]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_TRIGGERS_SQL, {"syms": syms, "ats": ats})
        for t in cur.fetchall():
            t["close"] = float(t["close"]) if t["close"] is not None else None
            t["pivot_price"] = float(t["pivot_price"]) if t["pivot_price"] is not None else None
            index[(t["symbol"], t["prior_classification_at"])]["triggers"].append(t)


def _streak_triggers(streak: dict) -> list[dict]:
    return [t for a in streak["analyses"] for t in a["triggers"]]


def derive_stage(streak: dict) -> str:
    trigs = _streak_triggers(streak)
    if any(t["trigger_type"] in BREAKOUT_TYPES for t in trigs):
        return "breakout"
    if any(t["trigger_type"] == "promotion" for t in trigs):
        return "staging"
    if any(a["pivot_price"] is not None for a in streak["analyses"]):
        return "watching"
    return "base_forming"


def _last_pivot_analysis(streak: dict) -> dict | None:
    for a in reversed(streak["analyses"]):
        if a["pivot_price"] is not None:
            return a
    return None


def compute_metrics(streak: dict, series: list[tuple[date, float]], *,
                    today: date, corp_flagged: bool) -> dict:
    stage = derive_stage(streak)
    out = {"stage": stage, "t5_pct": None, "t20_pct": None, "max_reach_pct": None,
           "corp_action_flag": False, "first_breakout_at": None}
    if stage == "breakout":
        fb = first_breakout(_streak_triggers(streak))
        out["first_breakout_at"] = fb["d"]
        if fb["close"] and fb["pivot_price"]:
            delta = (fb["close"] - fb["pivot_price"]) / fb["pivot_price"]
            out["t5_pct"] = chain_tn(series, fb["d"], delta, 5)
            out["t20_pct"] = chain_tn(series, fb["d"], delta, 20)
    elif stage in ("staging", "watching"):
        anchor = _last_pivot_analysis(streak)
        if anchor is not None:
            out["max_reach_pct"] = max_reach(
                series, anchor["key_date"], streak["end"], anchor["pivot_price"],
                today=today)
            out["corp_action_flag"] = corp_flagged
    return out


_WINDOW_SQL = """
SELECT date FROM daily_prices
 WHERE ticker = %(symbol)s AND date < %(before)s
 ORDER BY date DESC OFFSET 119 LIMIT 1
"""
_FIRST_ROW_SQL = "SELECT min(date) FROM daily_prices WHERE ticker = %(symbol)s"


def chart_window_start(conn: Connection, symbol: str, earliest_start: date) -> date:
    with conn.cursor() as cur:
        cur.execute(_WINDOW_SQL, {"symbol": symbol, "before": earliest_start})
        r = cur.fetchone()
        if r:
            return r[0]
        cur.execute(_FIRST_ROW_SQL, {"symbol": symbol})
        first = cur.fetchone()[0]
    return first or earliest_start


def _clamp_display(streak: dict, date_to: date) -> dict:
    """(I1) 표시용 to 절단 — 스펙 §1. metrics·closed_by 는 원본 유지."""
    s = dict(streak)
    s["analyses"] = [
        dict(a, triggers=[t for t in a["triggers"] if t["d"] <= date_to])
        for a in streak["analyses"] if a["key_date"] <= date_to
    ]
    # (#144 리뷰 F1) 절단 여부를 표시층에 전달 — end 만 보고는 "그 날짜에 닫힘"과
    # "to 로 잘림"을 구분할 수 없어, 프론트의 닫힘 수직 점선·날짜 툴팁이 오정보가 됨.
    s["end_clamped"] = s["end"] is not None and s["end"] > date_to
    if s["end_clamped"]:
        s["end"] = date_to          # closed_by 는 그대로 (스펙 §1)
    return s


def build_pivot_steps(streaks: list[dict]) -> list[tuple[date, date | None, float]]:
    steps: list[tuple[date, date | None, float]] = []
    for s in streaks:
        analyses = s["analyses"]
        for i, a in enumerate(analyses):
            if a["pivot_price"] is None:
                continue
            if i + 1 < len(analyses):
                boundary: date | None = analyses[i + 1]["key_date"]
            else:
                boundary = s["end"]          # 닫는 행 kd, 진행중이면 None (스펙 §3 ②)
            steps.append((a["key_date"], boundary, a["pivot_price"]))
    return steps


def build_stock_rows(conn: Connection, *, date_from: date, date_to: date,
                     source: str | None, ticker: str | None, status: str | None,
                     limit: int, offset: int, today: date) -> dict:
    symbols = find_period_symbols(conn, date_from=date_from, date_to=date_to,
                                  source=source, ticker=ticker)
    all_rows = fetch_scoped_rows(conn, symbols=symbols)
    by_symbol: dict[str, list[dict]] = {}
    for r in all_rows:
        by_symbol.setdefault(r["symbol"], []).append(r)

    displayed: list[dict] = []
    for sym, rows in by_symbol.items():
        streaks = intersect_period(segment_streaks(rows), date_from, date_to)
        if streaks:
            displayed.append({"symbol": sym, "market": rows[0]["market"],
                              "streaks": streaks})
    flat = [s for d in displayed for s in d["streaks"]]
    attach_triggers(conn, flat)
    flags = corp_action_flags(
        conn,
        [(s["symbol"], a["key_date"]) for s in flat
         for a in ([_last_pivot_analysis(s)] if _last_pivot_analysis(s) else [])],
        today=today)

    out_rows = []
    for d in displayed:
        streaks = d["streaks"]
        earliest = min(s["start"] for s in streaks)
        w_start = chart_window_start(conn, d["symbol"], earliest)
        # (I2) metrics 창은 "오늘까지"(스펙 §2) — 과거 to 조회에서도 도달률이
        # 과소평가되지 않도록 오늘까지 fetch. 응답 series 는 아래 클램프에서 to 로 슬라이스.
        series = fetch_price_series(conn, d["symbol"], w_start, max(date_to, today))
        for s in streaks:
            anchor = _last_pivot_analysis(s)
            corp = anchor is not None and (d["symbol"], anchor["key_date"]) in flags
            s["metrics"] = compute_metrics(s, series, today=today, corp_flagged=corp)
            s["stage"] = s["metrics"]["stage"]
        # streaks 는 시간순(segment_streaks 출력 순서, intersect_period 도 순서 보존) —
        # max(key=start) 는 동일 시작일 중 '첫' 묶음을 고르므로(당일 종결-재개 시 과거
        # 묶음 선택) 대신 마지막 원소로 프론트(streaks[length-1])와 규칙을 맞춘다.
        latest = streaks[-1]
        out_rows.append({
            "symbol": d["symbol"], "market": d["market"],
            "latest": {
                "status": "open" if latest["closed_by"] is None else "closed",
                "closed_by": latest["closed_by"], **latest["metrics"],
                "censored": latest["censored"], "backfilled": latest["backfilled"],
                "streak_count": len(streaks),
            },
            "streaks": streaks, "series": series,
            "pivot_steps": build_pivot_steps(streaks),
            "_sort_key": latest["start"],
        })

    for r in out_rows:  # (I1) 표시 클램프 — 스펙 §1 "to 절단": 응답의 analyses/트리거/end/
        # pivot_steps 는 date_to 로 자르되 closed_by·status·metrics 는 원본(오늘 기준) 유지
        r["streaks"] = [_clamp_display(s, date_to) for s in r["streaks"]]
        r["pivot_steps"] = build_pivot_steps(r["streaks"])
        r["series"] = [p for p in r["series"] if p[0] <= date_to]

    if status:  # 원본 종결 기준 (스펙 §4) — 전체 계산 후 Python 필터
        out_rows = [r for r in out_rows if r["latest"]["status"] == status]
    out_rows.sort(key=lambda r: r["_sort_key"], reverse=True)
    out_rows = out_rows[offset:offset + limit]
    for r in out_rows:
        r.pop("_sort_key")

    orphans = count_orphan_triggers(conn, date_from=date_from, date_to=date_to)
    return {"rows": out_rows, "orphan_trigger_count": orphans}
