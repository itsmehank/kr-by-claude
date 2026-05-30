"""go_now 후보에서 2E_tier2 watch 종목 제외 (spec §4-3)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from kr_pipeline.llm_runner import entry_params


def _seed_go_now(db, symbol, triggered_rules_json):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING", (symbol, symbol))
        classified = datetime(2026, 5, 28, tzinfo=timezone.utc)
        cur.execute(
            "INSERT INTO weekly_classification (symbol,classified_at,market,classification,source,triggered_rules) "
            "VALUES (%s,%s,'KOSPI','watch','test',%s) ON CONFLICT DO NOTHING",
            (symbol, classified, triggered_rules_json),
        )
        eval_at = datetime(2026, 5, 29, 6, 0, tzinfo=timezone.utc)
        cur.execute(
            "INSERT INTO trigger_evaluation_log (symbol,evaluated_at,decision,trigger_type,prior_classification_at) "
            "VALUES (%s,%s,'go_now','breakout',%s) ON CONFLICT DO NOTHING",
            (symbol, eval_at, classified),
        )


def test_tier2_excluded_tier1_and_none_allowed(db):
    from kr_pipeline.llm_runner.entry_params import _fetch_go_now_candidates
    _seed_go_now(db, "BLOCK2E", '{"2E_tier2": {"fired": true}}')
    _seed_go_now(db, "ALLOW2E1", '{"2E_tier1": {"fired": true}}')
    _seed_go_now(db, "ALLOWNONE", None)

    cands = _fetch_go_now_candidates(db, date(2026, 5, 29))
    symbols = {c[0] for c in cands}
    assert "BLOCK2E" not in symbols, "2E_tier2 는 차단"
    assert "ALLOW2E1" in symbols, "2E_tier1 은 허용 (entry_params 차단 없음)"
    assert "ALLOWNONE" in symbols, "triggered_rules NULL 은 허용"
