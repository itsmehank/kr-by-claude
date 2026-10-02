"""#221 — 잔여 변동 조사 보고서: 로컬 사실 수집 → claude -p(가짜 주입) → Slack(가짜 주입). 결정이 아니라 자료."""
from datetime import date

import pandas as pd
import pytest

from kr_pipeline.universe.exclusion_diff import classify_exclusion_diff
from kr_pipeline.universe.report import (
    PROMPT_FILE, REPORT_TOOLS, ReportFailed, build_local_facts, make_report, report_unexplained, send_report,
)


def _diff():
    ex = pd.DataFrame([("088980", "맵스리얼티", "KOSPI", "투자회사", "security_group")],
                      columns=["ticker", "name", "market", "security_group", "axis"])
    return classify_exclusion_diff(prev_set={"R9"}, excluded=ex, raw_tickers={"088980", "R9"}, ever_in_stocks={"088980"})


def test_prompt_file_exists_and_tools_open_web():
    from kr_pipeline.llm_runner.llm.claude_cli import PROMPTS_DIR
    assert (PROMPTS_DIR / PROMPT_FILE).exists()
    assert set(REPORT_TOOLS.split(",")) >= {"Read", "WebSearch"}


def test_build_local_facts_collects_db_evidence(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, security_group, delisted_at) VALUES ('088980','맵스리얼티','KOSPI','주권', NULL) "
                    "ON CONFLICT (ticker) DO UPDATE SET delisted_at = NULL")
        cur.execute("DELETE FROM daily_prices WHERE ticker='088980'")
        cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) VALUES ('088980', '2026-09-30', 1,1,1,1,1,1,1)")
        cur.execute("DELETE FROM universe_exclusion_snapshot WHERE snapshot_date='2026-09-22' AND ticker IN ('R9')")
        cur.execute("INSERT INTO universe_exclusion_snapshot (snapshot_date, ticker, name, market, security_group, axis) VALUES ('2026-09-22','R9','알구','KOSDAQ','주권','spac')")
        cur.execute("DELETE FROM universe_raw_snapshot WHERE snapshot_date='2026-10-01' AND ticker IN ('088980','R9')")
        cur.execute("INSERT INTO universe_raw_snapshot (snapshot_date, ticker, name, market, security_group) VALUES ('2026-10-01','088980','맵스리얼티','KOSPI','투자회사'), ('2026-10-01','R9','알구','KOSDAQ','주권')")
        cur.execute("DELETE FROM corporate_actions WHERE ticker='088980'")
        cur.execute("INSERT INTO corporate_actions (ticker, event_date, event_type, ratio, note) VALUES ('088980', '2026-09-15', 'merger', '1:0.3', '합병 공시')")
    facts = build_local_facts(db, _diff(), snapshot_date=date(2026, 10, 1), prev_snapshot_date=date(2026, 9, 22))
    a = facts["unexplained_added"][0]
    assert a["ticker"] == "088980" and a["in_stocks"] is True and a["delisted_at"] is None and a["last_daily_bar"] == "2026-09-30"
    assert a["raw_now"]["security_group"] == "투자회사" and a["corporate_actions"][0]["event_type"] == "merger"
    assert a["corporate_actions"][0]["ratio"] == "1:0.3"          # VARCHAR 그대로(float() 금지 — 리뷰 #223)
    r = facts["unexplained_removed"][0]
    assert r["ticker"] == "R9" and r["prev_snapshot"]["axis"] == "spac" and r["raw_now"] is not None
    assert facts["snapshot_date"] == "2026-10-01" and facts["prev_snapshot_date"] == "2026-09-22"


_GOOD = {"summary": "요약", "items": [{"ticker": "088980", "verdict": "axis_change", "evidence": "공시 X", "recommend": "hold"},
                                       {"ticker": "R9", "verdict": "unknown", "evidence": "근거 없음", "recommend": "hold"}]}


def test_make_report_validates_schema_and_retries_once():
    good = _GOOD
    calls = []

    def fake(prompt_file, payload_inline=None, **kw):
        calls.append((prompt_file, kw.get("tools")))
        return {"bad": 1} if len(calls) == 1 else good

    rep, meta = make_report(_diff(), {"unexplained_added": [], "unexplained_removed": []}, call=fake)
    assert rep["items"][0]["verdict"] == "axis_change" and len(calls) == 2
    assert calls[0] == (PROMPT_FILE, REPORT_TOOLS)

    def always_bad(prompt_file, payload_inline=None, **kw):
        return {"nope": True}
    with pytest.raises(ReportFailed):
        make_report(_diff(), {}, call=always_bad)


def test_make_report_rejects_llm_accept_as_decision():
    """LLM 이 'accept' 를 내도 보고서는 자료일 뿐 — recommend 는 전달하되 어떤 쓰기도 하지 않는다(여기선 스키마 허용값만 검증)."""
    out = {"summary": "s", "items": [{"ticker": "R9", "verdict": "delisted", "evidence": "e", "recommend": "accept"},
                                     {"ticker": "088980", "verdict": "unknown", "evidence": "e", "recommend": "hold"}]}
    rep, _ = make_report(_diff(), {}, call=lambda *a, **k: out)
    assert {it["ticker"]: it["recommend"] for it in rep["items"]} == {"R9": "accept", "088980": "hold"}


def test_make_report_requires_every_unexplained_ticker():
    """items 티커 집합 ≠ 잔여 집합(일부 누락)이면 재호출, 그래도 불일치면 ReportFailed — '1건' 과소 보고 방지(리뷰 #223)."""
    partial = {"summary": "s", "items": [{"ticker": "088980", "verdict": "unknown", "evidence": "e", "recommend": "hold"}]}
    calls = []
    def fake(prompt_file, payload_inline=None, **kw):
        calls.append(1); return partial
    with pytest.raises(ReportFailed, match="티커 집합 불일치"):
        make_report(_diff(), {}, call=fake)
    assert len(calls) == 2


def test_send_report_posts_text_and_logs_body_on_failure(caplog):
    import logging
    posted = []
    rep = {"summary": "요약 한 줄", "items": [{"ticker": "088980", "verdict": "axis_change", "evidence": "근거", "recommend": "hold"}]}
    assert send_report(rep, snapshot_date=date(2026, 10, 1), post=lambda text: posted.append(text)) is True
    assert "088980" in posted[0] and "accept-exclusion-diff" in posted[0] and "axis_change" in posted[0]

    def boom(text):
        raise RuntimeError("webhook down")
    with caplog.at_level(logging.WARNING, logger="kr_pipeline.universe.report"):
        assert send_report(rep, snapshot_date=date(2026, 10, 1), post=boom) is False
    assert "webhook down" in caplog.text and "088980" in caplog.text        # LLM 비용이 든 본문은 로그에 보존(리뷰 #223)


def test_report_unexplained_end_to_end_non_blocking(db, caplog):
    import logging
    posted = []
    facts = build_local_facts(db, _diff(), snapshot_date=date(2026, 10, 1), prev_snapshot_date=date(2026, 9, 22))
    report_unexplained(_diff(), facts, snapshot_date=date(2026, 10, 1), call=lambda *a, **k: _GOOD, post=lambda t: posted.append(t))
    assert posted and "088980" in posted[0] and "R9" in posted[0]
    with caplog.at_level(logging.WARNING, logger="kr_pipeline.universe.report"):
        report_unexplained(_diff(), facts, snapshot_date=date(2026, 10, 1),
                           call=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("claude down")), post=lambda t: posted.append(t))
    assert "exclusion_report_failed" in caplog.text and len(posted) == 1
