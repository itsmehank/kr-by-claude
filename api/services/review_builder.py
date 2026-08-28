"""분석 회고(/review) 조립 — 스펙 docs/superpowers/specs/2026-08-22-….md 가 규칙 원본.

핵심 규칙 (스펙 §1):
- 회고 행 = weekly_classification ∪ classification_backfill(#132, 합성 이력 —
  backfilled 플래그로 세대 표기)에서 source∈(weekend,daily_delta,backfill) AND
  classification∈(entry,watch).
- 백필 병합 규약(주 단위 라이브 우선 dedup + 전역 하한 REVIEW_COVERAGE_START)은
  공유 SQL 조각 MERGED_ROWS_CTES 가 단일 정의 — _ROWS_SQL 과 streak 뷰
  (review_streaks._SCOPED_SQL)가 같은 조각을 조합한다.
- 트리거 귀속 = (symbol, prior_classification_at) 직접 조인. 시간창 추측 금지
  (backdate 로 최대 24/142 오귀속 실증).
- 구간 끝 next_key_date = LEAD(...) — 반드시 필터 **전** 전체 행(라이브+백필
  병합 후)에 적용 (ignore·disqualify 가 구간을 끝내고, 백필 행도 구간을 끊는다).
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.rows import dict_row

BREAKOUT_TYPES = frozenset({"breakout", "breakout_from_watch"})

# 라이브 weekly_classification 최초 key_date — /review 전역 하한.
# streak 뷰(review_streaks)와 공유 (#132 에서 정의를 이곳으로 이동).
REVIEW_COVERAGE_START = date(2026, 5, 18)

# ── 공유 SQL 조각: 라이브+백필 병합 규약의 단일 정의 (#132 / PR #138 리뷰) ──
# _ROWS_SQL(분석 행)과 review_streaks._SCOPED_SQL(streak 뷰)이 이 조각 하나를
# 조합한다 — 병합 규약의 parity 를 주석이 아니라 구조로 보장.
#
# - 전역 하한 %(floor)s(REVIEW_COVERAGE_START)는 라이브·백필 양쪽에 적용
#   (이전 라이브 행은 커버리지 밖, 이전 백필 행은 백테스트 유래 산발 표본).
# - 주 단위 라이브 우선 dedup: 백필 행 key_date=토요일(as_of)인데 라이브 주말
#   행 key_date=금요일(analyzed_for_date)이라, (symbol, key_date) 정확 일치로는
#   같은 주의 라이브·백필이 하루 차이로 둘 다 남는다. 백필은 주당 1앵커
#   설계이므로 "같은 ISO 주(date_trunc('week'))에 라이브 행 존재"가 의미상
#   정확한 기준. NOT EXISTS 는 materialized CTE 재스캔 대신
#   weekly_classification 베이스 테이블에 직접 correlate(인덱스 활용).
# - live-first 귀결(의도): 그 주의 라이브가 disqualify/ignore 만 남긴 경우에도
#   백필 행은 억제된다 → 해당 주 분석 행은 표시되지 않는다(라이브 판단 우선).
# - %(symbols)s: 종목 범위 한정(streak 뷰), NULL 이면 전 종목(분석 행).
MERGED_ROWS_CTES = """\
live AS (
    SELECT symbol, classified_at, market, source, classification, pattern,
           pivot_price, analyzed_for_date, reasoning,
           COALESCE(analyzed_for_date, classified_at::date) AS key_date,
           false AS backfilled
      FROM weekly_classification
     WHERE COALESCE(analyzed_for_date, classified_at::date) >= %(floor)s
       AND (%(symbols)s::text[] IS NULL OR symbol = ANY(%(symbols)s::text[]))
), bf AS (
    SELECT b.symbol, b.classified_at, b.market, b.source, b.classification,
           b.pattern, b.pivot_price, b.analyzed_for_date, b.reasoning,
           b.analyzed_for_date AS key_date, true AS backfilled
      FROM classification_backfill b
     WHERE b.analyzed_for_date >= %(floor)s
       AND (%(symbols)s::text[] IS NULL OR b.symbol = ANY(%(symbols)s::text[]))
       AND NOT EXISTS (
           SELECT 1 FROM weekly_classification l
            WHERE l.symbol = b.symbol
              AND date_trunc('week', COALESCE(l.analyzed_for_date,
                                              l.classified_at::date))
                  = date_trunc('week', b.analyzed_for_date)
       )
)"""

_ROWS_SQL = f"""
WITH {MERGED_ROWS_CTES}, ordered AS (
    SELECT u.*,
           LEAD(u.key_date) OVER (
               PARTITION BY u.symbol ORDER BY u.key_date, u.classified_at
           ) AS next_key_date
      FROM (SELECT * FROM live UNION ALL SELECT * FROM bf) u
)
SELECT o.symbol, s.name, o.market, o.source, o.classified_at, o.analyzed_for_date,
       o.key_date, o.next_key_date, o.classification, o.pattern, o.pivot_price,
       o.backfilled
  FROM ordered o
  LEFT JOIN stocks s ON s.ticker = o.symbol
 WHERE o.source IN ('weekend', 'daily_delta', 'backfill')
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
            "floor": REVIEW_COVERAGE_START, "symbols": None,  # 전 종목
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


_PRICES_SQL = """
SELECT date, adj_close FROM daily_prices
 WHERE ticker = %(symbol)s AND date >= %(start)s AND date <= %(end)s
 ORDER BY date
"""


def fetch_price_series(conn: Connection, symbol: str, start: date, end: date
                       ) -> list[tuple[date, float]]:
    with conn.cursor() as cur:
        cur.execute(_PRICES_SQL, {"symbol": symbol, "start": start, "end": end})
        return [(r[0], float(r[1])) for r in cur.fetchall()]


def chain_tn(series: list[tuple[date, float]], d: date, pivot_delta: float,
             n: int) -> float | None:
    """(1+pivot_delta) × adj(D+n거래일)/adj(D) − 1. 거래일 = 시리즈의 행."""
    idx = {dt: i for i, (dt, _) in enumerate(series)}
    if d not in idx or idx[d] + n >= len(series):
        return None
    base = series[idx[d]][1]
    later = series[idx[d] + n][1]
    if base <= 0:
        return None
    return (1.0 + pivot_delta) * (later / base) - 1.0


def max_reach(series: list[tuple[date, float]], key_date: date,
              next_key_date: date | None, pivot: float, *, today: date
              ) -> float | None:
    """창 = (key_date, t') — key_date 당일 제외(분석 입력), 연장 없음 (스펙 §1)."""
    end = next_key_date if next_key_date is not None else today
    window = [v for dt, v in series if key_date < dt < end] if next_key_date \
        else [v for dt, v in series if key_date < dt <= end]
    if not window or pivot <= 0:
        return None
    return max(window) / pivot - 1.0


def build_spark(series: list[tuple[date, float]], anchor: date, end: date,
                cap: int = 60) -> list[float]:
    """anchor~end 를 최대 cap 개로 다운샘플.

    보존 불변식(리뷰 지적으로 확정): (a) 최고점 (b) 최저점 (c) 마지막 인덱스
    (최신 가격) 는 다운샘플 후에도 항상 포함된다. (d) 반환 길이는 cap 을 넘지
    않는다. (e) 인덱스 오름차순으로 반환해 시간 순서를 유지한다.

    그리드는 양끝(인덱스 0, len(vals)-1)을 항상 포함하는 endpoint-inclusive
    선형 스텝(`round(i*(n-1)/(cap-1))`)으로 만들어 (c)·(e)를 구조적으로
    보장한다. 그 후 최고·최저 인덱스가 그리드에 없으면, 여유가 있으면 추가하고
    cap 이 꽉 찼으면(그 극점이 아닌) 가장 가까운 그리드 인덱스를 치환해 (a)(b)(d)를
    동시에 만족시킨다. (첫 버전은 이 그리드 대신 단순 스텝+union 이라 극점 2개
    추가만으로 cap 을 초과했고, 그 수정 과정에서 마지막 인덱스 강제 포함이 실수로
    빠졌던 것 — 이번 구현은 둘 다 구조적으로 보장한다.)
    """
    vals = [v for dt, v in series if anchor <= dt <= end]
    n = len(vals)
    if n <= cap:
        return vals
    if cap <= 1:
        return [vals[-1]] if cap == 1 else []

    hi, lo, last = vals.index(max(vals)), vals.index(min(vals)), n - 1
    picked = sorted({round(i * (n - 1) / (cap - 1)) for i in range(cap)})

    for extreme in (last, hi, lo):
        if extreme in picked:
            continue
        if len(picked) < cap:
            picked.append(extreme)
            picked.sort()
            continue
        protected = {x for x in (last, hi, lo) if x != extreme}
        candidates = [p for p in picked if p not in protected]
        nearest = min(candidates, key=lambda p: abs(p - extreme))
        picked.remove(nearest)
        picked.append(extreme)
        picked.sort()
    return [vals[i] for i in picked]


_CORP_SQL = """
SELECT DISTINCT ticker FROM corporate_actions
 WHERE ticker = ANY(%(symbols)s) AND event_date BETWEEN %(min_kd)s AND %(today)s
"""


def corp_action_flags(conn: Connection, pairs: list[tuple[str, date]], *,
                      today: date) -> set[tuple[str, date]]:
    """(symbol, key_date) 별 event_date ∈ [key_date, today] 존재 여부.
    상한이 '오늘'인 이유: 기업행위는 이전 전체 adj 이력을 rescale (스펙 §1)."""
    if not pairs:
        return set()
    symbols = sorted({s for s, _ in pairs})
    min_kd = min(kd for _, kd in pairs)
    with conn.cursor() as cur:
        cur.execute(_CORP_SQL, {"symbols": symbols, "min_kd": min_kd, "today": today})
        hit_symbols = {r[0] for r in cur.fetchall()}
    out: set[tuple[str, date]] = set()
    for sym, kd in pairs:
        if sym not in hit_symbols:
            continue
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM corporate_actions WHERE ticker=%s "
                "AND event_date BETWEEN %s AND %s LIMIT 1", (sym, kd, today))
            if cur.fetchone():
                out.add((sym, kd))
    return out
