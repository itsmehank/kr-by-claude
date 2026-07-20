"""#44 D2-b — 제3안 watch_reason 차단·왕복 고정 (characterization).

배경: E1(§6.1 climax) 판정 불능 시 LLM 이 verdict=watch + watch_reason=
'suspected_climax_stage_indeterminate' 를 내도록 프롬프트가 개정될 예정(Task 9).
이 값은 trigger_gate.ALLOWED_WATCH_REASONS 에 비포함이라 breakout_from_watch 가
발화하지 않고 promotion 으로만 흐른다(go_now 금지 경로). store 는 watch_reason 을
검증 없이 pass-through 한다.

이 파일은 이미 green 인 동작(trigger_gate 평가 순서 + store pass-through, 둘 다
기존 구현이 그대로 만족)을 회귀 고정하는 characterization 테스트다 — red 단계
없음. 신규/변경 프로덕션 코드 없음(store.py 는 주석만 추가).
"""
from datetime import datetime, timezone

SUSPECTED_CLIMAX_STAGE_INDETERMINATE = "suspected_climax_stage_indeterminate"


def test_suspected_climax_stage_indeterminate_blocks_breakout_from_watch():
    """§6.1 판정불능 사유는 ALLOWED_WATCH_REASONS 비포함 → fresh_cross·거래량
    조건이 전부 충족돼도 breakout_from_watch 가 아니라 promotion 으로 강등.

    (매수 경로 차단 — promotion 은 go_now 금지, LLM 정밀판정 staging 만 가능.)
    """
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=1060.0,
        pivot_price=1000.0,
        volume=2_000_000,
        avg_volume_50d=1_000_000.0,
        stop_loss=None,
        sma_50=900.0,
        classification="watch",
        prev_close=990.0,
        watch_reason=SUSPECTED_CLIMAX_STAGE_INDETERMINATE,
    )
    assert result != "breakout_from_watch"
    assert result == "promotion"


def test_store_roundtrips_suspected_climax_stage_indeterminate(db):
    """store 는 watch_reason 값을 enum 검증 없이 그대로 저장·재조회 보존한다
    (스키마 CHECK 부재 회귀 고정 — 향후 누군가 enum 제약을 넣으면 이 테스트가 잡음)."""
    from kr_pipeline.llm_runner.store import insert_classification

    symbol = "CXSHDW"
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (symbol,))
    db.commit()

    insert_classification(
        db,
        symbol=symbol,
        classified_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch",
            "pattern": "flat_base",
            "pivot_price": 1000.0,
            "pivot_basis": "high_of_base",
            "base_high": 1000.0,
            "base_low": 900.0,
            "base_depth_pct": 10.0,
            "base_start_date": "2026-03-01",
            "risk_flags": [],
            "confidence": 0.5,
            "reasoning": "test",
            "watch_reason": SUSPECTED_CLIMAX_STAGE_INDETERMINATE,
        },
        source="weekend",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT watch_reason FROM weekly_classification WHERE symbol=%s", (symbol,)
        )
        row = cur.fetchone()
    assert row[0] == SUSPECTED_CLIMAX_STAGE_INDETERMINATE


# ===========================================================================
# (#44 Task 7) echo 배선 + §6.2 shadow backstop + verdict_original — TDD
# ===========================================================================
import shutil
from pathlib import Path
from datetime import date as _date, timedelta as _timedelta


def _shdw_seed_stock(db, ticker):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market, sector) "
            "VALUES (%s, 'P', 'KOSPI', '전기·전자') ON CONFLICT DO NOTHING",
            (ticker,),
        )
    db.commit()


def _shdw_weekly_rows(n: int, top: float, bot: float, start: _date) -> list[dict]:
    """(tests/test_climax_payload.py 시드 재사용) 완만한 하락 드리프트 주봉 n개."""
    step = (top - bot) / max(n - 1, 1)
    rows = []
    for i in range(n):
        p = top - step * i
        rows.append({
            "week_end": start + _timedelta(weeks=i),
            "open": p, "high": p * 1.02, "low": p * 0.98, "close": p, "volume": 100_000,
        })
    return rows


def _shdw_seed_weekly(db, ticker, rows: list[dict]):
    with db.cursor() as cur:
        for r in rows:
            cur.execute(
                """INSERT INTO weekly_prices
                     (ticker, week_end_date, open, high, low, close, adj_close,
                      volume, value, trading_days)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,5)
                   ON CONFLICT DO NOTHING""",
                (ticker, r["week_end"], r["open"], r["high"], r["low"], r["close"],
                 r["close"], r["volume"], r["volume"] * r["close"]),
            )
    db.commit()


def _shdw_seed_daily(db, ticker, on_date: _date, n: int = 25):
    """마지막(=on_date)부터 거슬러 n일 연속 daily_prices+daily_indicators 시드
    (adj_close/volume 을 양쪽 테이블에 동일하게 넣어 check_data_integrity 통과)."""
    with db.cursor() as cur:
        for i in range(n):
            d = on_date - _timedelta(days=(n - 1 - i))
            close = 80000.0 + i * 10
            cur.execute(
                """INSERT INTO daily_prices
                     (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (ticker, d, close, close * 1.01, close * 0.99, close, close,
                 1_000_000, 1_000_000 * close),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                     (ticker, date, adj_close, volume, distribution_day_flag)
                   VALUES (%s,%s,%s,%s,FALSE)
                   ON CONFLICT DO NOTHING""",
                (ticker, d, close, 1_000_000),
            )
    db.commit()


def test_build_analysis_inline_returns_4_tuple_matching_payload_gates(db, mocker):
    """inline_builder 단위: 4-튜플 반환 + 4번째 원소가 payload 의
    climax_topping_gates 와 동일 dict. 차트 렌더는 무거워(PNG 인코딩) 모킹."""
    from api.services.inline_builder import build_analysis_inline
    from api.services.payload_builder import build_payload

    ticker = "SHDWINL1"
    _shdw_seed_stock(db, ticker)
    start = _date(2018, 1, 5)
    weekly = _shdw_weekly_rows(40, 1000.0, 980.0, start)  # left_censored(<50주) — 단순 케이스
    _shdw_seed_weekly(db, ticker, weekly)
    on_date = weekly[-1]["week_end"]
    _shdw_seed_daily(db, ticker, on_date, n=25)

    mocker.patch("api.services.inline_builder.render_daily_chart", return_value=b"DAILYPNG")
    mocker.patch("api.services.inline_builder.render_weekly_chart", return_value=b"WEEKLYPNG")

    expected_payload = build_payload(db, ticker, on_date=on_date)

    result = build_analysis_inline(db, ticker, on_date)
    assert len(result) == 4
    inline_text, png_paths, freeze_bytes, gates = result
    try:
        assert isinstance(inline_text, str)
        assert isinstance(freeze_bytes, bytes)
        assert gates == expected_payload["climax_topping_gates"]
        # 결정론 산술 dict — g0_below_10w 등 핵심 키 존재 확인
        assert "g0_below_10w" in gates
        assert "quality_flag_topping" in gates
    finally:
        shutil.rmtree(str(Path(png_paths[0]).parent), ignore_errors=True)


def test_weekend_process_one_injects_climax_topping_gates_echo(db, mocker):
    """(#44 Task 7) build_analysis_inline 자체를 모킹 — weekend._process_one 이
    LLM 응답 파싱 직후 result['climax_topping_gates_echo'] 를 주입하는지 함수
    단위 검증(차트 렌더·freeze 실비용 우회, round 2 N5)."""
    import kr_pipeline.llm_runner.weekend as wk

    sentinel_gates = {"g0_below_10w": True, "tb_ok": True, "quality_flag_topping": False}
    mocker.patch.object(
        wk, "build_analysis_inline",
        return_value=(
            "inline",
            ["/tmp/_shdwecho/daily_chart.png", "/tmp/_shdwecho/weekly_chart.png"],
            b"zip",
            sentinel_gates,
        ),
    )
    canned_result = {"classification": "watch", "confidence": 0.5, "reasoning": "x", "risk_flags": []}
    mocker.patch.object(wk, "call_claude", return_value=canned_result)
    mocker.patch.object(wk, "save_freeze")

    wk._process_one(db, "SHDWECHO1", "KOSPI", dry_run=True, as_of=_date(2026, 7, 18))

    assert canned_result["climax_topping_gates_echo"] == sentinel_gates


def _shdw_base_result(classification="watch", quality_flag_topping=None):
    return {
        "classification": classification,
        "pattern": "flat_base",
        "pivot_price": 1000.0,
        "pivot_basis": "high_of_base",  # cup_with_handle 이 아님 → handle_quality 미발화
        "base_high": 1000.0, "base_low": 900.0, "base_depth_pct": 10.0,
        "base_start_date": None,  # 2F failed_breakout 도 미발화(base_start_date 없음)
        "risk_flags": [], "confidence": 0.5, "reasoning": "test",
        "climax_topping_gates_echo": {
            "g0_below_10w": True,
            "tb_ok": True,
            "td_dist_ok": None,
            "quality_flag_topping": quality_flag_topping,
            "tc_sma40_turndown": True,
            "tc_prolonged_ok": True,
        },
    }


def test_shadow_backstop_fires_verdict_kept_and_verdict_original_stored(db):
    """G0+T-B 충족 · quality_flag_topping 없음(None) · LLM=watch →
    verdict watch 유지 + triggered_rules.6_2_topping_shadow(fired=False·
    would_force=ignore·gate_version) 기록 + verdict_original='watch' 저장(store 왕복)."""
    from kr_pipeline.llm_runner.store import insert_classification

    symbol = "SHDWGATE1"
    _shdw_seed_stock(db, symbol)
    result = _shdw_base_result(classification="watch", quality_flag_topping=None)

    insert_classification(
        db, symbol=symbol,
        classified_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        market="KOSPI", result=result, source="weekend",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT classification, triggered_rules, verdict_original "
            "FROM weekly_classification WHERE symbol=%s",
            (symbol,),
        )
        cls, triggered_rules, verdict_original = cur.fetchone()

    assert cls == "watch", "verdict 는 절대 변경하지 않음"
    assert triggered_rules is not None
    shadow = triggered_rules["6_2_topping_shadow"]
    assert shadow["fired"] is False
    assert shadow["shadow"] is True
    assert shadow["would_force"] == "ignore"
    assert shadow["gate_version"] == "44-v1"
    assert shadow["inputs"] == {"g0_below_10w": True, "tb_ok": True, "td_dist_ok": None}
    assert shadow["observe"] == {"tc_sma40_turndown": True, "tc_prolonged_ok": True}
    assert verdict_original == "watch"


def test_shadow_backstop_not_recorded_when_quality_flag_topping_true(db):
    """quality_flag_topping=True(데이터 품질 결함) 면 자격 미충족 — shadow 미기록."""
    from kr_pipeline.llm_runner.store import insert_classification

    symbol = "SHDWGATE2"
    _shdw_seed_stock(db, symbol)
    result = _shdw_base_result(classification="watch", quality_flag_topping=True)

    insert_classification(
        db, symbol=symbol,
        classified_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        market="KOSPI", result=result, source="weekend",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT triggered_rules FROM weekly_classification WHERE symbol=%s", (symbol,)
        )
        (triggered_rules,) = cur.fetchone()

    assert triggered_rules is None or "6_2_topping_shadow" not in triggered_rules


def test_apply_phase1_gates_shadow_direct_unit(db):
    """apply_phase1_gates 를 직접 호출 — verdict 무변경(entry) + shadow 기록,
    entry 승격/강등 없음을 명시적으로 확인(§8.5 는 pivot_price 상회 미충족이라 미발화)."""
    from kr_pipeline.llm_runner import gates

    result = {
        "classification": "watch",
        "confidence": 0.55,
        "risk_flags": [],
        "pattern": "flat_base",
        "pivot_basis": "high_of_base",
        "pivot_price": None,
        "base_start_date": None,
        "climax_topping_gates_echo": {
            "g0_below_10w": True,
            "tb_ok": False,
            "td_dist_ok": True,   # T-D 분배일 경로로도 자격 충족(OR)
            "quality_flag_topping": False,
            "tc_sma40_turndown": False,
            "tc_prolonged_ok": None,
        },
    }
    out, tr = gates.apply_phase1_gates(
        db, "SHDWDIRECT1", datetime(2026, 7, 20, tzinfo=timezone.utc), result
    )
    assert out["classification"] == "watch"
    assert tr is not None and "6_2_topping_shadow" in tr
    assert tr["6_2_topping_shadow"]["fired"] is False
    assert tr["6_2_topping_shadow"]["would_force"] == "ignore"


def test_apply_phase1_gates_shadow_absent_when_classification_ignore(db):
    """이미 ignore 인 verdict 는 shadow 기록 자격 없음(방향=노출 축소인데 이미 ignore)."""
    from kr_pipeline.llm_runner import gates

    result = {
        "classification": "ignore",
        "confidence": 0.55,
        "risk_flags": [],
        "pattern": "flat_base",
        "pivot_basis": "high_of_base",
        "pivot_price": None,
        "base_start_date": None,
        "climax_topping_gates_echo": {
            "g0_below_10w": True,
            "tb_ok": True,
            "td_dist_ok": True,
            "quality_flag_topping": False,
            "tc_sma40_turndown": True,
            "tc_prolonged_ok": True,
        },
    }
    out, tr = gates.apply_phase1_gates(
        db, "SHDWDIRECT2", datetime(2026, 7, 20, tzinfo=timezone.utc), result
    )
    assert out["classification"] == "ignore"
    assert tr is None or "6_2_topping_shadow" not in tr
