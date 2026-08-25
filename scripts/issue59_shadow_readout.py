"""이슈 #59 — §6.2 topping shadow 1차 실전 관측창 집계 (read-only).

production DB(kr_pipeline)에서 SELECT 만 수행한다(서버측 read-only 세션 강제).
LLM 재실행 0회 — 저장본 집계만. 결과는 JSON 으로 저장하며, 동일 DB 상태에서
재실행 시 generated_at 제외 바이트 동일(결정론: sort_keys + 고정 반올림 + 세션
TimeZone=Asia/Seoul 고정 — 실행 환경 TZ 무관). 출력 파일명은 실행일 날짜로
파생되므로 다른 날 재실행하면 새 파일이 생성돼 기존 기준선 파일이 보존된다.

정의 출처:
- 발화·would_force: kr_pipeline/llm_runner/gates.py:117-121 (6_2_topping_shadow 는
  classification != 'ignore' 일 때만 기록 → production 로그에서 발화 행 = would_force
  행이 구조적으로 동일 집합).
- 강제율 상한 5%·E1 실전 카운터 분모: docs/superpowers/specs/
  2026-07-21-issue44-stage3-verification-prereg.md §4·§7.
- D_climax 참고 분모 패턴: docs/superpowers/specs/
  2026-07-20-issue44-e1-indeterminacy-prereg.md §2.

실행: uv run python scripts/issue59_shadow_readout.py
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

DSN = "postgresql://localhost/kr_pipeline"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "verification" / (
    f"issue59_shadow_readout_{date.today():%Y%m%d}.json"
)

# 관측창 시작 = 실전 전환 첫 주말 분류일(이슈 #59 deployed 기준, 스펙 A1)
WINDOW_START = "2026-07-25 00:00:00+09"

E1_REASON = "suspected_climax_stage_indeterminate"
SHADOW_RULE = "6_2_topping_shadow"
LLM_SOURCES = ("weekend", "daily_delta")

# E1 prereg §2 D_climax 패턴(대소문자 무시) — 참고 분모용, 문언 그대로
D_CLIMAX_PATTERN = r"climax|클라이맥스|수직 급등|blow-off|블로우오프"

# trigger_gate.py:45-47 사실 전사(코드 인용 — 판정 로직 아님, 문서 병기용)
ALLOWED_WATCH_REASONS = ["marginal_tt", "unfavorable_market", "valid_base_awaiting_breakout"]

PREREG_REFS = [
    "docs/superpowers/specs/2026-07-20-issue44-e1-indeterminacy-prereg.md",
    "docs/superpowers/specs/2026-07-21-issue44-stage3-verification-prereg.md",
    "docs/superpowers/specs/2026-07-21-issue44-62-mismatch-readout.md",
]


def _rate(numer: int, denom: int) -> float | None:
    """분모 0 이면 None(산정 불능) — 고정 6자리 반올림(결정론)."""
    if denom == 0:
        return None
    return round(numer / denom, 6)


def collect(conn: psycopg.Connection) -> dict:
    cur = conn.cursor(row_factory=dict_row)

    # --- 모수: source별 전수(system_disqualify 포함 — 스펙 리뷰 ①) ---
    cur.execute(
        """
        SELECT source,
               count(*) AS rows,
               count(DISTINCT analyzed_for_date) AS distinct_analyzed_dates,
               count(*) FILTER (WHERE llm_model IS NOT NULL) AS llm_model_rows,
               count(watch_reason) AS watch_reason_rows,
               min(analyzed_for_date)::text AS min_analyzed_for_date,
               max(analyzed_for_date)::text AS max_analyzed_for_date,
               min(classified_at)::text AS min_classified_at,
               max(classified_at)::text AS max_classified_at
        FROM weekly_classification
        WHERE classified_at >= %(ws)s::timestamptz
        GROUP BY source ORDER BY source
        """,
        {"ws": WINDOW_START},
    )
    by_source = {r.pop("source"): r for r in cur.fetchall()}

    llm_rows = sum(by_source.get(s, {}).get("rows", 0) for s in LLM_SOURCES)
    non_llm = {s: r["rows"] for s, r in by_source.items() if s not in LLM_SOURCES}
    total_rows = llm_rows + sum(non_llm.values())  # 등록식(§7-1) 분모: source 무제한

    # weekend 실행일 상세(사전 확인 실측 대조용)
    cur.execute(
        """
        SELECT analyzed_for_date::text AS analyzed_for_date, count(*) AS rows
        FROM weekly_classification
        WHERE classified_at >= %(ws)s::timestamptz AND source = 'weekend'
        GROUP BY analyzed_for_date ORDER BY analyzed_for_date
        """,
        {"ws": WINDOW_START},
    )
    weekend_runs = cur.fetchall()

    # --- shadow 발화(= would_force, gates.py 구조상 동일 집합) ---
    # 분자는 분모(LLM 모수)와 동일한 source 필터를 명시 — 분자⊄분모 결함 봉쇄.
    # any_source 는 필터 밖 발화 잔여 검출용 방어 카운트(분자 아님).
    cur.execute(
        """
        SELECT count(*) FILTER (WHERE source = ANY(%(llm)s)) AS n,
               count(*) AS n_any_source
        FROM weekly_classification
        WHERE classified_at >= %(ws)s::timestamptz
          AND triggered_rules ? %(rule)s
        """,
        {"ws": WINDOW_START, "rule": SHADOW_RULE, "llm": list(LLM_SOURCES)},
    )
    fired = cur.fetchone()

    # 전 기간 광역 검색(규칙명 변형 누락 방어)
    cur.execute(
        "SELECT count(*) AS n FROM weekly_classification "
        "WHERE triggered_rules::text LIKE '%topping%'"
    )
    all_time_topping = cur.fetchone()["n"]
    cur.execute(
        "SELECT count(*) AS n FROM classification_backfill "
        "WHERE triggered_rules::text LIKE '%topping%'"
    )
    backfill_topping = cur.fetchone()["n"]

    # --- E1 카운터 (주 지표 분모 = 관측창 LLM 분류 행 — 분자에 동일 source 필터) ---
    cur.execute(
        """
        SELECT symbol, classified_at::text AS classified_at,
               analyzed_for_date::text AS analyzed_for_date,
               source, classification, verdict_original, watch_reason
        FROM weekly_classification
        WHERE classified_at >= %(ws)s::timestamptz AND watch_reason = %(r)s
          AND source = ANY(%(llm)s)
        ORDER BY classified_at, symbol
        """,
        {"ws": WINDOW_START, "r": E1_REASON, "llm": list(LLM_SOURCES)},
    )
    e1_rows = cur.fetchall()

    # 등록식(stage3 prereg §7-1) 분자 — source 무제한(등록식 문언 그대로)
    cur.execute(
        """
        SELECT count(*) AS n FROM weekly_classification
        WHERE classified_at >= %(ws)s::timestamptz AND watch_reason = %(r)s
        """,
        {"ws": WINDOW_START, "r": E1_REASON},
    )
    e1_any_source = cur.fetchone()["n"]

    # 주 단위 분해 — 주 경계 = KST 기준 ISO 주(월요일 시작), 스펙 리뷰 ④
    cur.execute(
        """
        SELECT date_trunc('week', classified_at AT TIME ZONE 'Asia/Seoul')::date::text AS week_kst,
               count(*) FILTER (WHERE source = ANY(%(llm)s)) AS llm_rows,
               count(*) FILTER (WHERE watch_reason = %(r)s
                                AND source = ANY(%(llm)s)) AS e1_rows
        FROM weekly_classification
        WHERE classified_at >= %(ws)s::timestamptz
        GROUP BY week_kst ORDER BY week_kst
        """,
        {"ws": WINDOW_START, "r": E1_REASON, "llm": list(LLM_SOURCES)},
    )
    weekly = cur.fetchall()

    # 참고 분모 D_climax (E1 prereg §2 패턴, LLM 행 reasoning 대상 — 리뷰 ③)
    cur.execute(
        """
        SELECT count(*) AS n
        FROM weekly_classification
        WHERE classified_at >= %(ws)s::timestamptz
          AND source = ANY(%(llm)s)
          AND reasoning ~* %(pat)s
        """,
        {"ws": WINDOW_START, "llm": list(LLM_SOURCES), "pat": D_CLIMAX_PATTERN},
    )
    d_climax = cur.fetchone()["n"]

    # rate_vs_d_climax 분자 = D_climax 분모 집합의 부분집합(동일 source·패턴 제약)
    # — 분자⊄분모(이론상 1.0 초과) 결함 봉쇄. 패턴 비매칭 E1 은 별도 보고.
    cur.execute(
        """
        SELECT count(*) AS n
        FROM weekly_classification
        WHERE classified_at >= %(ws)s::timestamptz
          AND source = ANY(%(llm)s)
          AND watch_reason = %(r)s
          AND reasoning ~* %(pat)s
        """,
        {
            "ws": WINDOW_START,
            "llm": list(LLM_SOURCES),
            "r": E1_REASON,
            "pat": D_CLIMAX_PATTERN,
        },
    )
    e1_in_d_climax = cur.fetchone()["n"]

    # classification_backfill 관측창 병기(주 분모 비합산 — 스펙 A2)
    cur.execute(
        """
        SELECT count(*) AS n,
               count(*) FILTER (WHERE watch_reason = %(r)s) AS e1
        FROM classification_backfill
        WHERE classified_at >= %(ws)s::timestamptz
        """,
        {"ws": WINDOW_START, "r": E1_REASON},
    )
    backfill = cur.fetchone()

    # 관측창 실효 경계
    cur.execute(
        """
        SELECT min(classified_at)::text AS first_classified_at,
               max(classified_at)::text AS last_classified_at
        FROM weekly_classification
        WHERE classified_at >= %(ws)s::timestamptz
        """,
        {"ws": WINDOW_START},
    )
    bounds = cur.fetchone()

    n_fired = fired["n"]
    return {
        "issue": 59,
        "purpose": (
            "§6.2 topping shadow 1차 실전 관측창 집계 — 활성화 판정 보류(사용자 결정), "
            "판독 문서 docs/superpowers/specs/2026-08-25-issue59-shadow-readout.md 의 원자료"
        ),
        "prereg_refs": PREREG_REFS,
        "window": {
            "start_kst": WINDOW_START,
            "start_rationale": "실전 전환 첫 주말 분류일(이슈 #59 deployed 기준)",
            "first_classified_at": bounds["first_classified_at"],
            "last_classified_at": bounds["last_classified_at"],
        },
        "population": {
            "by_source": by_source,
            "llm_rows": llm_rows,
            "llm_sources": list(LLM_SOURCES),
            "non_llm_rows_excluded_from_denominators": non_llm,
            "non_llm_exclusion_rationale": (
                "system_disqualify 는 비-LLM 결정론 경로(llm_model NULL·watch_reason NULL, "
                "gates.py 미통과)라 shadow 발화·E1 이 구조적으로 불가능 — 분모 제외, 전수 병기"
            ),
            "weekend_runs": weekend_runs,
        },
        "shadow": {
            "rule": SHADOW_RULE,
            "fired_rows_window": n_fired,
            "fired_rows_window_source_filter": list(LLM_SOURCES),
            "fired_rows_window_any_source": fired["n_any_source"],
            "fired_rows_window_any_source_note": (
                "source 필터 없는 방어 카운트(분자 아님) — 분자는 분모와 동일한 "
                "LLM source 필터를 적용한 fired_rows_window"
            ),
            "fired_equals_would_force_note": (
                "gates.py:117-121 이 classification != 'ignore' 일 때만 기록하므로 "
                "production 로그에서 발화 행 = would_force 행(동일 집합)"
            ),
            "would_force_rows_window": n_fired,
            "force_rate_vs_llm_population": _rate(n_fired, llm_rows),
            "force_share_within_fired": _rate(n_fired, n_fired),
            "force_share_within_fired_note": (
                None if n_fired else "산정 불능(분모 0 — 관측창 발화 0건)"
            ),
            "all_time_topping_like_weekly_classification": all_time_topping,
            "all_time_topping_like_classification_backfill": backfill_topping,
        },
        "e1_counter": {
            "watch_reason": E1_REASON,
            "numerator_rows_window": len(e1_rows),
            "numerator_source_filter": list(LLM_SOURCES),
            "denominator_llm_rows_window": llm_rows,
            "rate": _rate(len(e1_rows), llm_rows),
            "registered_formula": {
                "numerator_rows_window_any_source": e1_any_source,
                "denominator_all_rows_window": total_rows,
                "rate": _rate(e1_any_source, total_rows),
                "note": (
                    "stage3 prereg §7-1 등록식 그대로(source 무제한 — "
                    "system_disqualify 포함). 주 지표의 LLM-only 분모는 등록식"
                    "으로부터의 명시적 이탈(사유: 비-LLM 결정론 경로는 "
                    "watch_reason 생성 불가)"
                ),
            },
            "rows": e1_rows,
            "weekly_breakdown_kst_monday": weekly,
            "reference_denominator_d_climax": {
                "pattern": D_CLIMAX_PATTERN,
                "rows": d_climax,
                "numerator_e1_in_d_climax": e1_in_d_climax,
                "numerator_subset_note": (
                    "분자는 D_climax 분모 집합의 부분집합(동일 source·패턴 제약) — "
                    "분자⊄분모(이론상 1.0 초과) 결함 봉쇄"
                ),
                "e1_rows_pattern_unmatched": len(e1_rows) - e1_in_d_climax,
                "rate_vs_d_climax": _rate(e1_in_d_climax, d_climax),
                "note": (
                    "E1 prereg §2 패턴(reasoning 내 climax 논의 행) — 3.4~20% proxy 구간과 "
                    "분모 호환 보완용 참고 지표(판정 아님)"
                ),
            },
            "allowed_watch_reasons_code_fact": {
                "values": ALLOWED_WATCH_REASONS,
                "e1_included": False,
                "source": "kr_pipeline/llm_runner/compute/trigger_gate.py:45-47",
                "effect": (
                    "E1 사유는 ALLOWED_WATCH_REASONS 비포함 → breakout_from_watch 미발화, "
                    "promotion 경로만(go_now 금지) — store.py:84-89"
                ),
            },
        },
        "classification_backfill_window": {
            "rows": backfill["n"],
            "e1_rows": backfill["e1"],
            "note": "백필은 실전 관측이 아니므로 주 분모 비합산(별도 병기 — 스펙 A2)",
        },
    }


def main() -> None:
    # 서버측 read-only 세션 강제 — 이 스크립트는 SELECT 만 수행한다.
    with psycopg.connect(
        DSN, autocommit=True, options="-c default_transaction_read_only=on"
    ) as conn:
        # TimeZone 고정: timestamptz ::text 렌더링을 실행 환경(TZ/PGTZ 환경변수·
        # 서버 기본값)과 무관하게 KST 로 결정론화(byte 동일 보장). 접속 후 SET 이
        # startup 파라미터보다 뒤에 적용되므로 환경변수를 확실히 이긴다.
        conn.execute("SET TIME ZONE 'Asia/Seoul'")
        payload = collect(conn)

    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"saved: {OUT_PATH}")
    print(
        "llm_rows={llm} fired={f} e1={e} e1_rate={r}".format(
            llm=payload["population"]["llm_rows"],
            f=payload["shadow"]["fired_rows_window"],
            e=payload["e1_counter"]["numerator_rows_window"],
            r=payload["e1_counter"]["rate"],
        )
    )


if __name__ == "__main__":
    main()
