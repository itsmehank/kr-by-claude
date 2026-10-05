"""#221 — 잔여 변동 조사 보고서: 실패 run details → 로컬 사실(커밋 상태) → claude -p(가짜 주입) → Slack(가짜 주입) → 전송 마커.
결정이 아니라 자료. 구조적 원인(상한·security_group 조회 실패)은 LLM 생략."""
import json
from datetime import date

import pandas as pd
import pytest

from kr_pipeline.universe.exclusion_diff import SYSTEMIC_CAP_DELISTED, ExclusionDiff, classify_exclusion_diff
from kr_pipeline.universe.report import (
    CALL_MAX_ATTEMPTS, MAX_LLM_ITEMS, MAX_SLACK_ITEMS, PROMPT_FILE, REPORT_TOOLS, ReportFailed, build_local_facts, format_report,
    make_report, report_last_failed, send_text,
)


def _diff():
    ex = pd.DataFrame([("088980", "맵스리얼티", "KOSPI", "투자회사", "security_group")],
                      columns=["ticker", "name", "market", "security_group", "axis"])
    return classify_exclusion_diff(prev_set={"R9"}, excluded=ex, raw_tickers={"088980", "R9"}, ever_in_stocks={"088980"})


_GOOD = {"summary": "요약", "items": [{"ticker": "088980", "verdict": "axis_change", "evidence": "공시 X", "recommend": "hold"},
                                       {"ticker": "R9", "verdict": "unknown", "evidence": "근거 없음", "recommend": "hold"}]}


def test_prompt_file_exists_and_tools_search_only():
    from kr_pipeline.llm_runner.llm.claude_cli import ALLOWED_TOOLSETS, PROMPTS_DIR
    assert (PROMPTS_DIR / PROMPT_FILE).exists()
    assert REPORT_TOOLS == "WebSearch" and REPORT_TOOLS in ALLOWED_TOOLSETS     # 파일 Read 없음(cwd .env 노출 차단), URL 열기 없음


def test_build_local_facts_collects_committed_evidence_and_raw_copy(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, security_group, delisted_at) VALUES ('088980','맵스리얼티','KOSPI','주권', NULL) "
                    "ON CONFLICT (ticker) DO UPDATE SET delisted_at = NULL")
        cur.execute("DELETE FROM daily_prices WHERE ticker='088980'")
        cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) VALUES ('088980', '2026-09-30', 1,1,1,1,1,1,1)")
        cur.execute("DELETE FROM universe_exclusion_snapshot WHERE snapshot_date='2026-09-22' AND ticker IN ('R9')")
        cur.execute("INSERT INTO universe_exclusion_snapshot (snapshot_date, ticker, name, market, security_group, axis) VALUES ('2026-09-22','R9','알구','KOSDAQ','주권','spac')")
        cur.execute("DELETE FROM corporate_actions WHERE ticker='088980'")
        cur.execute("INSERT INTO corporate_actions (ticker, event_date, event_type, ratio, note) VALUES ('088980', '2026-09-15', 'merger', '1:0.3', '합병 공시')")
    raw_now = {"088980": {"name": "맵스리얼티", "market": "KOSPI", "security_group": "투자회사"}, "R9": {"name": "알구", "market": "KOSDAQ", "security_group": "주권"}}
    facts = build_local_facts(db, _diff(), snapshot_date=date(2026, 10, 1), prev_snapshot_date=date(2026, 9, 22), raw_now=raw_now)
    a = facts["unexplained_added"][0]
    assert a["ticker"] == "088980" and a["in_stocks"] is True and a["delisted_at"] is None and a["last_daily_bar"] == "2026-09-30"
    assert a["raw_now"]["security_group"] == "투자회사"                      # 롤백된 원본은 details 사본에서
    assert a["corporate_actions"][0]["event_type"] == "merger" and a["corporate_actions"][0]["ratio"] == "1:0.3"   # VARCHAR 그대로
    r = facts["unexplained_removed"][0]
    assert r["ticker"] == "R9" and r["prev_snapshot"]["axis"] == "spac" and r["raw_now"]["name"] == "알구"
    assert facts["auto_accepted"] == {"removed_delisted": [], "added_new_listing": []} and "unexplained" not in facts["auto_accepted"]


def test_make_report_validates_schema_and_retries_once():
    calls = []

    def fake(prompt_file, payload_inline=None, **kw):
        calls.append((prompt_file, kw.get("tools"), kw.get("max_attempts")))
        return {"bad": 1} if len(calls) == 1 else _GOOD

    rep, meta = make_report(_diff(), {"unexplained_added": [], "unexplained_removed": []}, call=fake)
    assert rep["items"][0]["verdict"] == "axis_change" and len(calls) == 2
    assert calls[0] == (PROMPT_FILE, REPORT_TOOLS, CALL_MAX_ATTEMPTS) and CALL_MAX_ATTEMPTS == 1     # CLI 내부 재시도 없음(예산 ≤ 8분)
    with pytest.raises(ReportFailed):
        make_report(_diff(), {}, call=lambda *a, **k: {"nope": True})


def test_make_report_requires_every_unexplained_ticker_and_caps_bulk():
    partial = {"summary": "s", "items": [{"ticker": "088980", "verdict": "unknown", "evidence": "e", "recommend": "hold"}]}
    calls = []

    def fake(prompt_file, payload_inline=None, **kw):
        calls.append(1); return partial
    with pytest.raises(ReportFailed, match="티커 집합 불일치"):
        make_report(_diff(), {}, call=fake)
    assert len(calls) == 2
    bulk = ExclusionDiff(unexplained_removed=[{"ticker": f"S{i:05d}", "reason": "x"} for i in range(MAX_LLM_ITEMS + 1)])
    with pytest.raises(ReportFailed, match="MAX_LLM_ITEMS"):
        make_report(bulk, {}, call=lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM 호출 금지")))


def test_format_report_caps_items_and_keeps_accept_hint():
    rep = {"summary": "s", "items": [{"ticker": f"T{i}", "verdict": "unknown", "evidence": "e" * 500, "recommend": "hold"} for i in range(MAX_SLACK_ITEMS + 5)]}
    text = format_report(rep, date(2026, 10, 1))
    assert f"외 5건" in text and "accept-exclusion-diff" in text and text.count("• ") == MAX_SLACK_ITEMS and len(text) < 20000


def test_send_text_logs_body_on_failure(caplog):
    import logging
    posted = []
    assert send_text("본문 088980", post=lambda t: posted.append(t)) is True and posted == ["본문 088980"]

    def boom(text):
        raise RuntimeError("webhook down")
    with caplog.at_level(logging.WARNING, logger="kr_pipeline.universe.report"):
        assert send_text("본문 088980", post=boom) is False
    assert "webhook down" in caplog.text and "088980" in caplog.text


def _seed_failed_run(db, details: dict, *, on_date="2026-10-01", status="failed", minutes_ago=10):
    with db.cursor() as cur:
        cur.execute("INSERT INTO pipeline_runs (pipeline, mode, started_at, finished_at, status, params, details) VALUES "
                    "('universe', 'full', now() - make_interval(mins => %s), now() - make_interval(mins => %s), %s, %s, %s) RETURNING id",
                    (minutes_ago, minutes_ago, status, json.dumps({"on_date": on_date}), json.dumps(details)))
        return cur.fetchone()[0]


def _details(diff: ExclusionDiff, **extra):
    return {**diff.summary(), "snapshot_prev_date": "2026-09-22",
            "exclusion_raw_now": {t: {"name": t, "market": "KOSPI", "security_group": "주권"} for t in diff.unexplained_tickers}, **extra}


def test_report_last_failed_sends_marks_and_dedups(db):
    posted, calls = [], []
    rid = _seed_failed_run(db, _details(_diff()))
    out = report_last_failed(db, commit=False, call=lambda *a, **k: calls.append(1) or _GOOD, post=lambda t: posted.append(t))
    assert out == "sent" and len(posted) == 1 and "088980" in posted[0] and "R9" in posted[0] and len(calls) == 1
    with db.cursor() as cur:
        cur.execute("SELECT details->>'report_sent_at', details->'report_key_sent' FROM pipeline_runs WHERE id=%s", (rid,))
        sent_at, key = cur.fetchone()
    assert sent_at and key == ["+088980", "-R9"]
    assert report_last_failed(db, commit=False, call=lambda *a, **k: calls.append(1) or _GOOD, post=lambda t: posted.append(t)) == "already_sent"
    assert len(posted) == 1 and len(calls) == 1                                  # RunAtLoad 재발화 — 재전송·재호출 없음


def test_report_last_failed_not_marked_when_delivery_fails_then_retries(db):
    """Slack 실패면 마커를 찍지 않는다 → 다음 발화에서 다시 시도(1차 반영의 '실패 run 존재 = 전송됨' 오판 제거)."""
    posted = []
    _seed_failed_run(db, _details(_diff()))
    boom = lambda t: (_ for _ in ()).throw(RuntimeError("webhook down"))  # noqa: E731
    assert report_last_failed(db, commit=False, call=lambda *a, **k: _GOOD, post=boom) == "failed"
    assert report_last_failed(db, commit=False, call=lambda *a, **k: _GOOD, post=lambda t: posted.append(t)) == "sent"


def test_report_last_failed_ignores_runs_before_last_success(db):
    _seed_failed_run(db, _details(_diff()), minutes_ago=30)
    _seed_failed_run(db, {}, status="success", minutes_ago=20)
    assert report_last_failed(db, commit=False, call=lambda *a, **k: _GOOD, post=lambda t: None) == "nothing"


def test_report_last_failed_systemic_skips_llm_and_posts_facts(db):
    posted = []
    bulk = ExclusionDiff(unexplained_removed=[{"ticker": f"S{i:05d}", "reason": "상한"} for i in range(12)],
                         systemic=[SYSTEMIC_CAP_DELISTED, "security_group_unavailable"])
    _seed_failed_run(db, _details(bulk))
    out = report_last_failed(db, commit=False, call=lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM 호출 금지")), post=lambda t: posted.append(t))
    assert out == "sent" and SYSTEMIC_CAP_DELISTED in posted[0] and "security_group_unavailable" in posted[0] and "LLM 조사 없음" in posted[0]


def test_report_last_failed_llm_failure_still_posts_rule_facts(db):
    """LLM 단계 실패(한도·CLI 부재·타임아웃)여도 잔여 목록·accept 안내는 Slack 으로 간다(리뷰 #223 3차)."""
    posted = []
    _seed_failed_run(db, _details(_diff()))
    out = report_last_failed(db, commit=False, call=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("usage limit")), post=lambda t: posted.append(t))
    assert out == "sent" and "LLM 조사 실패" in posted[0] and "+088980" in posted[0] and "-R9" in posted[0] and "accept-exclusion-diff" in posted[0]


def test_report_last_failed_dedups_across_daily_retries(db):
    """매일 재시도로 새 실패 run 이 생겨도(마커 없음) 같은 잔여 키가 마지막 성공 이후 이미 전송됐으면 생략(리뷰 #223 3차)."""
    posted = []
    older = _seed_failed_run(db, {**_details(_diff()), "report_sent_at": "2026-10-01T06:40:00+00:00", "report_key_sent": ["+088980", "-R9"]}, minutes_ago=60)
    _seed_failed_run(db, _details(_diff()), minutes_ago=5)
    assert report_last_failed(db, commit=False, call=lambda *a, **k: _GOOD, post=lambda t: posted.append(t)) == "already_sent"
    assert posted == []
    different = classify_exclusion_diff(prev_set=set(), excluded=pd.DataFrame([("X9", "엑스", "KOSPI", "주권", "etf")], columns=["ticker", "name", "market", "security_group", "axis"]),
                                        raw_tickers={"X9"}, ever_in_stocks=set())
    _seed_failed_run(db, _details(different), minutes_ago=1)
    out = report_last_failed(db, commit=False, call=lambda *a, **k: {"summary": "s", "items": [{"ticker": "X9", "verdict": "unknown", "evidence": "e", "recommend": "hold"}]},
                             post=lambda t: posted.append(t))
    assert out == "sent" and len(posted) == 1


def test_report_last_failed_never_raises(db, caplog, monkeypatch):
    """DB 단계 예외(조회 실패)도 올리지 않는다 — 'failed' + 경고(LLM 단계 실패는 사실만 전송으로 'sent', 별도 테스트)."""
    import logging
    import kr_pipeline.universe.report as rp
    _seed_failed_run(db, _details(_diff()))
    monkeypatch.setattr(rp, "_last_failed_run", lambda conn: (_ for _ in ()).throw(RuntimeError("db down")))
    with caplog.at_level(logging.WARNING, logger="kr_pipeline.universe.report"):
        out = report_last_failed(db, commit=False, call=lambda *a, **k: _GOOD, post=lambda t: None)
    assert out == "failed" and "exclusion_report_failed" in caplog.text


def test_report_last_failed_strict_row_does_not_mask_older_residue(db):
    """strict 실패(report_key=[])가 더 최근이어도, 잔여가 있는 옛 실패 run 의 미전송 보고서를 가리지 않는다(리뷰 #223 4차)."""
    posted = []
    _seed_failed_run(db, _details(_diff()), minutes_ago=30)
    _seed_failed_run(db, {**ExclusionDiff(removed_delisted=["S1"]).summary(), "snapshot_prev_date": "2026-09-22", "strict": True}, minutes_ago=5)
    assert report_last_failed(db, commit=False, call=lambda *a, **k: _GOOD, post=lambda t: posted.append(t)) == "sent" and "088980" in posted[0]


def test_report_last_failed_facts_only_is_retried_next_day(db):
    """LLM 실패로 사실만 보낸 전송은 당일만 dedup — 날짜가 지나면 같은 키라도 LLM 조사를 다시 시도(한도·CLI 장애 복구)."""
    posted = []
    _seed_failed_run(db, {**_details(_diff()), "report_sent_at": "2026-10-01T06:40:00+00:00", "report_key_sent": ["+088980", "-R9"], "report_kind": "facts_only"}, minutes_ago=60)
    _seed_failed_run(db, _details(_diff()), minutes_ago=5)
    assert report_last_failed(db, commit=False, call=lambda *a, **k: _GOOD, post=lambda t: posted.append(t)) == "sent"
    assert "axis_change" in posted[0]                                            # 이번엔 LLM 보고서
    with db.cursor() as cur:
        cur.execute("SELECT details->>'report_kind' FROM pipeline_runs WHERE pipeline='universe' AND status='failed' AND details ? 'report_sent_at' "
                    "ORDER BY started_at DESC LIMIT 1")
        assert cur.fetchone()[0] == "full"


def test_facts_only_dedup_uses_kst_day(db, monkeypatch):
    """사실만 전송의 '당일' 은 KST 기준 — 06:30 KST(=전날 21:30 UTC) 전송 후 같은 아침 10:00 KST 재발화는 같은 날로 본다(리뷰 #223 5차)."""
    import kr_pipeline.universe.report as rp
    from datetime import datetime as _dt

    class _FixedNow(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt(2026, 11, 2, 1, 0, tzinfo=rp.timezone.utc).astimezone(tz) if tz else _dt(2026, 11, 2, 1, 0)   # = 11-02 10:00 KST

    monkeypatch.setattr(rp, "datetime", _FixedNow)
    posted = []
    _seed_failed_run(db, {**_details(_diff()), "report_sent_at": "2026-11-01T21:30:00+00:00",     # = 11-02 06:30 KST
                          "report_key_sent": ["+088980", "-R9"], "report_kind": "facts_only"}, minutes_ago=60)
    _seed_failed_run(db, _details(_diff()), minutes_ago=5)
    assert report_last_failed(db, commit=False, call=lambda *a, **k: _GOOD, post=lambda t: posted.append(t)) == "already_sent"
    assert posted == []


def test_accept_hint_names_refused_tickers():
    """accept 불가 유형(#199·late_resolution)이 섞이면 Slack 안내가 그 종목을 명시 — accept 재실행이 거부될 것을 미리 알린다(회신 23 Q-G)."""
    from kr_pipeline.universe.report import format_facts_only, format_report
    ex = pd.DataFrame([("R7", "리츠7", "KOSPI", "부동산투자회사", "security_group")], columns=["ticker", "name", "market", "security_group", "axis"])
    late = classify_exclusion_diff(prev_set={"R9"}, excluded=ex, raw_tickers={"R7", "R9"}, ever_in_stocks={"R7": "UNRESOLVED"})
    good = {"summary": "s", "items": [{"ticker": "R7", "verdict": "axis_change", "evidence": "e", "recommend": "accept"},
                                      {"ticker": "R9", "verdict": "unknown", "evidence": "e", "recommend": "hold"}]}
    for text in (format_report(good, date(2026, 11, 1), late), format_facts_only(late, date(2026, 11, 1), "x")):
        assert "accept 불가" in text and "R7" in text.split("accept 불가", 1)[1]
    plain = _diff()                                                    # 088980 은 확정 그룹 → 199, R9 는 축 풀림
    assert "R9" not in format_facts_only(plain, date(2026, 11, 1), "x").split("accept 불가", 1)[1]
