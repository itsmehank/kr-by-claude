"""분석 회고(/review) 조립 — 스펙 docs/superpowers/specs/2026-08-22-….md 가 규칙 원본.

핵심 규칙 (스펙 §1):
- 회고 행 = weekly_classification 에서 source∈(weekend,daily_delta) AND
  classification∈(entry,watch).
- 트리거 귀속 = (symbol, prior_classification_at) 직접 조인. 시간창 추측 금지
  (backdate 로 최대 24/142 오귀속 실증).
- 구간 끝 next_key_date = LEAD(...) — 반드시 필터 **전** 전체 행에 적용
  (ignore·disqualify 가 구간을 끝낸다).
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.rows import dict_row

BREAKOUT_TYPES = frozenset({"breakout", "breakout_from_watch"})

_ROWS_SQL = """
WITH ordered AS (
    SELECT symbol, classified_at, market, source, classification, pattern,
           pivot_price, analyzed_for_date,
           COALESCE(analyzed_for_date, classified_at::date) AS key_date,
           LEAD(COALESCE(analyzed_for_date, classified_at::date)) OVER (
               PARTITION BY symbol
               ORDER BY COALESCE(analyzed_for_date, classified_at::date), classified_at
           ) AS next_key_date
      FROM weekly_classification
)
SELECT o.symbol, s.name, o.market, o.source, o.classified_at, o.analyzed_for_date,
       o.key_date, o.next_key_date, o.classification, o.pattern, o.pivot_price
  FROM ordered o
  LEFT JOIN stocks s ON s.ticker = o.symbol
 WHERE o.source IN ('weekend', 'daily_delta')
   AND o.classification IN ('entry', 'watch')
   AND o.key_date BETWEEN %(date_from)s AND %(date_to)s
   AND (%(classification)s::text IS NULL OR o.classification = %(classification)s)
   AND (%(source)s::text IS NULL OR o.source = %(source)s)
   AND (%(pattern)s::text IS NULL OR o.pattern = %(pattern)s)
   AND (%(ticker)s::text IS NULL OR o.symbol = %(ticker)s)
   AND (%(include_pivot_null)s OR o.pivot_price IS NOT NULL)
 ORDER BY o.key_date DESC, o.symbol
 LIMIT %(limit)s OFFSET %(offset)s
"""

_TRIGGERS_SQL = """
SELECT t.symbol, t.prior_classification_at, t.evaluated_at, t.trigger_type,
       t.decision, t.close, t.pivot_price, t.reasoning,
       COALESCE(t.analyzed_for_date,
                (t.evaluated_at AT TIME ZONE 'UTC')::date) AS d
  FROM trigger_evaluation_log t
 WHERE (t.symbol, t.prior_classification_at) IN (
     SELECT unnest(%(syms)s::text[]), unnest(%(ats)s::timestamptz[])
 )
 ORDER BY d, t.evaluated_at
"""

_ORPHAN_SQL = """
SELECT COUNT(*)
  FROM trigger_evaluation_log t
 WHERE NOT EXISTS (SELECT 1 FROM weekly_classification wc
                    WHERE wc.symbol = t.symbol
                      AND wc.classified_at = t.prior_classification_at)
   AND COALESCE(t.analyzed_for_date, (t.evaluated_at AT TIME ZONE 'UTC')::date)
       BETWEEN %(date_from)s AND %(date_to)s
"""


def fetch_analysis_rows(conn: Connection, *, date_from: date, date_to: date,
                        classification: str | None, source: str | None,
                        pattern: str | None, ticker: str | None,
                        include_pivot_null: bool, limit: int, offset: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_ROWS_SQL, {
            "date_from": date_from, "date_to": date_to,
            "classification": classification, "source": source,
            "pattern": pattern, "ticker": ticker,
            "include_pivot_null": include_pivot_null,
            "limit": limit, "offset": offset,
        })
        rows = cur.fetchall()
        for r in rows:
            r["pivot_price"] = float(r["pivot_price"]) if r["pivot_price"] is not None else None
            r["triggers"] = []
        if rows:
            syms = [r["symbol"] for r in rows]
            ats = [r["classified_at"] for r in rows]
            by_key = {(r["symbol"], r["classified_at"]): r for r in rows}
            cur.execute(_TRIGGERS_SQL, {"syms": syms, "ats": ats})
            for t in cur.fetchall():
                t["close"] = float(t["close"]) if t["close"] is not None else None
                t["pivot_price"] = float(t["pivot_price"]) if t["pivot_price"] is not None else None
                key = (t["symbol"], t["prior_classification_at"])
                if key in by_key:
                    by_key[key]["triggers"].append(t)
    return rows


def count_orphan_triggers(conn: Connection, *, date_from: date, date_to: date) -> int:
    with conn.cursor() as cur:
        cur.execute(_ORPHAN_SQL, {"date_from": date_from, "date_to": date_to})
        return cur.fetchone()[0]


def _sorted_by_d(triggers: list[dict]) -> list[dict]:
    # "최초" 순서 기준 = D, 동률이면 evaluated_at (스펙 §1 — catch-up 어긋남 대비)
    return sorted(triggers, key=lambda t: (t["d"], t["evaluated_at"]))


def first_breakout(triggers: list[dict]) -> dict | None:
    for t in _sorted_by_d(triggers):
        if t["trigger_type"] in BREAKOUT_TYPES:
            return t
    return None


def first_promotion_d(triggers: list[dict]) -> date | None:
    for t in _sorted_by_d(triggers):
        if t["trigger_type"] == "promotion":
            return t["d"]
    return None


def derive_status(triggers: list[dict], t5_pct, t20_pct) -> str:
    """스펙 §1 상태 판정 표. 돌파≥1 → 진행중/완료(T+20 도래), promotion≥1 → staging,
    나머지(invalidation-only 포함) → 미발동."""
    if first_breakout(triggers) is not None:
        return "돌파-완료" if t20_pct is not None else "돌파-진행중"
    if any(t["trigger_type"] == "promotion" for t in triggers):
        return "staging"
    return "미발동"
