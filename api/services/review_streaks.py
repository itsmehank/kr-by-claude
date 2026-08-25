"""/review 종목 행(streak) 뷰 조립 — 스펙 docs/superpowers/specs/2026-08-25-….md 가 원본.

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
    BREAKOUT_TYPES, chain_tn, corp_action_flags, first_breakout, max_reach,
)

REVIEW_COVERAGE_START = date(2026, 5, 18)  # 라이브 weekly_classification 최초 key_date
_CENSOR_WINDOW = timedelta(days=7)
_GAP_DAYS = 10
_VALID_SOURCES = ("weekend", "daily_delta", "backfill")

_SCOPED_SQL = """
WITH live AS (
    SELECT symbol, classified_at, market, source, classification, pattern, pivot_price,
           COALESCE(analyzed_for_date, classified_at::date) AS key_date,
           false AS backfilled
      FROM weekly_classification
     WHERE symbol = ANY(%(symbols)s)
       AND COALESCE(analyzed_for_date, classified_at::date) >= %(floor)s
), bf AS (
    SELECT b.symbol, b.classified_at, b.market, b.source, b.classification, b.pattern,
           b.pivot_price, b.analyzed_for_date AS key_date, true AS backfilled
      FROM classification_backfill b
     WHERE b.symbol = ANY(%(symbols)s)
       AND b.analyzed_for_date >= %(floor)s
       -- 라이브 우선 dedup: 같은 (symbol, key_date)에 라이브가 있으면 백필 제외
       AND NOT EXISTS (SELECT 1 FROM live l
                        WHERE l.symbol = b.symbol AND l.key_date = b.analyzed_for_date)
)
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
