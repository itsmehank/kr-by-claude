"""P1-5 Part A: universe 빈/부족 응답 가드 — 대량 오폐지 방어.

배경: KRX throttling 은 예외가 아니라 '빈 리스트' 로 나타날 수 있다(ohlcv 에서
기관찰). fetch_tickers 가 빈 리스트를 정상 반환하면 mark_delisted 가 그 시장
전 종목(~1,700개)을 일괄 폐지 처리하고, 월 1회 cron 까지 자가치유도 없다.
"""
from datetime import date

import pytest


# ---------- 가드 1: fetch_tickers 시장별 최소 종목 수 ----------

def test_fetch_tickers_raises_on_suspiciously_small_list(mocker):
    """빈/비정상적으로 적은 목록 → ValueError (with_retry 가 재시도 후 전파).

    가드를 fetch_tickers '내부' 에 두는 이유: @with_retry 는 모든 예외를
    백오프 재시도하므로, 일시적 throttle 빈 응답은 자동 회복 기회를 얻고
    지속 실패만 전파된다.
    """
    import kr_pipeline.universe.fetch as uf

    stock_mock = mocker.patch.object(uf, "stock")
    stock_mock.get_market_ticker_list.return_value = []

    with pytest.raises(ValueError, match="KOSDAQ"):
        uf.fetch_tickers("KOSDAQ", date(2026, 7, 7))
    # with_retry(attempts=3) — 재시도가 실제로 이뤄졌는지
    assert stock_mock.get_market_ticker_list.call_count == 3


def test_fetch_tickers_passes_on_normal_count(mocker):
    """정상 규모 목록은 그대로 반환."""
    import kr_pipeline.universe.fetch as uf

    tickers = [f"{i:06d}" for i in range(900)]  # KOSPI 하한(700) 이상
    stock_mock = mocker.patch.object(uf, "stock")
    stock_mock.get_market_ticker_list.return_value = tickers

    assert uf.fetch_tickers("KOSPI", date(2026, 7, 7)) == tickers
    assert stock_mock.get_market_ticker_list.call_count == 1


# ---------- 가드 2: mark_delisted 폐지 비율 상한 ----------

def _insert_active(cur, prefix, n):
    for i in range(n):
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') "
            "ON CONFLICT (ticker) DO UPDATE SET delisted_at = NULL",
            (f"{prefix}{i:03d}", "가드테스트"),
        )


def _active_tickers(cur):
    cur.execute("SELECT ticker FROM stocks WHERE delisted_at IS NULL")
    return {r[0] for r in cur.fetchall()}


def test_mark_delisted_aborts_on_mass_delist(db):
    """활성 종목의 2% 초과를 한 번에 폐지하려 하면 UPDATE 전에 abort.

    kr_test 잔존 데이터와 무관하게: 현재 활성 집합을 조회해 그중 10% 를
    '목록에서 누락' 시켜 구성 — 고정 숫자 baseline 에 의존하지 않는다.
    """
    from kr_pipeline.universe.store import mark_delisted

    with db.cursor() as cur:
        _insert_active(cur, "GRD", 60)  # 활성 최소 규모 보장
        active = _active_tickers(cur)
    db.commit()

    drop_n = max(int(len(active) * 0.10), 2)  # 10% 누락 → 상한(2%) 초과
    dropped = set(list(active)[:drop_n])
    current = active - dropped

    try:
        with pytest.raises(ValueError, match="delist"):
            mark_delisted(db, current_tickers=current, on_date=date(2026, 7, 7))
        db.rollback()
        with db.cursor() as cur:
            after = _active_tickers(cur)
        assert after == active, "abort 인데 일부가 폐지 처리됨 (fail-closed 깨짐)"
    finally:
        # 실패 경로(예: 가드 미구현 red 단계)에서 mass delist 가 실제 실행된 채
        # 정리 commit 에 묻어가는 것 방지 — 반드시 rollback 후 정리만 commit.
        db.rollback()
        with db.cursor() as cur:
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'GRD%' AND name='가드테스트'")
        db.commit()


def test_mark_delisted_normal_small_delist_still_works(db):
    """정상 소량 폐지(상한 이하)는 기존 동작 그대로."""
    from kr_pipeline.universe.store import mark_delisted

    with db.cursor() as cur:
        _insert_active(cur, "GRD", 60)
        active = _active_tickers(cur)
    db.commit()

    victim = "GRD000"
    current = active - {victim}  # 1건 폐지 — 활성 60+ 의 2% 미만

    try:
        n = mark_delisted(db, current_tickers=current, on_date=date(2026, 7, 7))
        db.commit()
        assert n == 1
        with db.cursor() as cur:
            cur.execute("SELECT delisted_at FROM stocks WHERE ticker = %s", (victim,))
            assert cur.fetchone()[0] is not None
    finally:
        # 실패 경로의 잔여 변경이 정리 commit 에 묻어가지 않게 rollback 선행
        db.rollback()
        with db.cursor() as cur:
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'GRD%' AND name='가드테스트'")
        db.commit()


def test_mark_delisted_empty_set_still_noop(db):
    """기존 가드 보존: current_tickers 완전 빈 집합 → no-op (0건)."""
    from kr_pipeline.universe.store import mark_delisted

    assert mark_delisted(db, current_tickers=set(), on_date=date(2026, 7, 7)) == 0


# ---------- 가드 3: fetch_security_groups 부분 응답 fail-closed (SECUGRP 필터 Task 3) ----------

def _secugrp_df(rows):
    import pandas as pd
    return pd.DataFrame(rows, columns=["ISU_CD", "ISU_ABBRV", "SECUGRP_NM"])


def test_fetch_security_groups_merges_markets(monkeypatch):
    import kr_pipeline.universe.fetch as uf

    calls = []

    class _Fake:
        def fetch(self, trd_dd, mkt, secugrp):
            calls.append((trd_dd, mkt, tuple(secugrp)))
            n = 1000 if mkt == "STK" else 1800
            base = 0 if mkt == "STK" else 100000   # 시장 간 가짜 티커 충돌 방지
            rows = [(f"{base + i:06d}", f"N{i}", "주권") for i in range(n)]
            rows.append(("094800", "맵스리얼티", "투자회사") if mkt == "STK" else ("900070", "글로벌에스엠", "외국주권"))
            return _secugrp_df(rows)

    monkeypatch.setattr(uf, "_short_sale_all_stocks", lambda: _Fake())
    monkeypatch.setattr(uf.time, "sleep", lambda s: None)
    out = uf.fetch_security_groups(date(2026, 9, 11))
    assert out["094800"] == "투자회사" and out["900070"] == "외국주권"
    assert [c[1] for c in calls] == ["STK", "KSQ"]
    assert all(c[0] == "20260911" and c[2] == ("STMFRTSCIFDRFS",) for c in calls)


def test_fetch_security_groups_raises_on_partial_response(monkeypatch):
    """한 시장이 비어 합계가 하한 미달이면 ValueError — 조용한 UNRESOLVED 대량 전환(유니버스 무음 축소) 방어."""
    import kr_pipeline.universe.fetch as uf

    class _Fake:
        def fetch(self, trd_dd, mkt, secugrp):
            return _secugrp_df([(f"{i:06d}", "N", "주권") for i in range(50)])

    monkeypatch.setattr(uf, "_short_sale_all_stocks", lambda: _Fake())
    monkeypatch.setattr(uf.time, "sleep", lambda s: None)
    with pytest.raises(ValueError, match="security_group"):
        uf.fetch_security_groups(date(2026, 9, 11))


# ---------- 가드 4: 적재 후 회귀 가드 [3-b] (SECUGRP 필터 Task 4) ----------
import pandas as pd
from kr_pipeline.universe.guards import (
    UniverseGuardError, count_active, preflight_exclusion_diff, verify_universe_after_load, write_exclusion_snapshot,
)
from kr_pipeline.universe.store import upsert_stocks


def _excluded(*rows):
    return pd.DataFrame(list(rows), columns=["ticker", "name", "market", "security_group", "axis"])


def _seed(db, rows):
    upsert_stocks(db, pd.DataFrame(rows))


@pytest.fixture
def clean_universe(db):
    """가드는 *활성 유니버스 전체* 를 단언한다 — 다른 테스트가 autocommit 으로 남긴 픽스처 종목
    (예: 'ASOFC2'·'ZIPLA1' = 6자·끝자리≠'0' → 우선주 코드 규칙에 걸림)을 같은 트랜잭션 안에서
    폐지 처리해 시작점을 비운다. db 픽스처가 ROLLBACK 하므로 kr_test 상태는 변하지 않는다."""
    with db.cursor() as cur:
        cur.execute("UPDATE stocks SET delisted_at = CURRENT_DATE WHERE delisted_at IS NULL")


def test_guard_a_rejects_preload_group_in_active_universe(db, clean_universe):
    """(a) 활성 stocks 의 security_group 집합 ⊆ 허용 ∪ {UNRESOLVED} ∪ 행생성예외. 부동산투자회사 유입 = 실패."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"},
               {"ticker": "T2", "name": "리츠누수", "market": "KOSPI", "security_group": "부동산투자회사"}])
    with pytest.raises(UniverseGuardError, match="부동산투자회사"):
        verify_universe_after_load(db, snapshot_date=date(2026, 9, 15), excluded=_excluded())


def test_guard_a_allows_row_kept_groups_and_unresolved(db, clean_universe):
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"},
               {"ticker": "T3", "name": "맵스리얼티", "market": "KOSPI", "security_group": "투자회사"},
               {"ticker": "T4", "name": "알에프세미", "market": "KOSDAQ", "security_group": "UNRESOLVED"}])
    info = verify_universe_after_load(db, snapshot_date=date(2026, 9, 15), excluded=_excluded())
    assert info["unresolved"] >= 1 and info["row_kept_excluded"] >= 1
    assert info["qualifying_pool"] == info["active_after"] - info["unresolved"] - info["row_kept_excluded"]


def test_guard_b_rejects_name_axis_hit_in_active_universe(db, clean_universe):
    """(b) 우선주·스팩·ETF 이름축 카운트 = 0. 하나라도 있으면 실패."""
    _seed(db, [{"ticker": "005935", "name": "삼성전자우", "market": "KOSPI", "security_group": "주권"}])   # 코드 끝자리 5 = 우선주
    with pytest.raises(UniverseGuardError, match="preferred"):
        verify_universe_after_load(db, snapshot_date=date(2026, 9, 15), excluded=_excluded())


def test_snapshot_first_run_writes_baseline_and_diff_fails_next(db, clean_universe):
    """(신규) 배제 집합 스냅샷: 첫 실행은 기준선 저장, 다음 실행에서 집합 변동은 accept 없이 실패."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"}])
    ex1 = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"), ("R1", "리츠", "KOSPI", "부동산투자회사", "security_group"))
    info = verify_universe_after_load(db, snapshot_date=date(2026, 9, 15), excluded=ex1)
    assert info["exclusion_added"] == [] and info["exclusion_removed"] == []
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM universe_exclusion_snapshot WHERE snapshot_date = '2026-09-15'")
        assert cur.fetchone()[0] == 2
    ex2 = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"))   # R1 사라짐
    with pytest.raises(UniverseGuardError, match="R1"):
        verify_universe_after_load(db, snapshot_date=date(2026, 10, 15), excluded=ex2)
    info2 = verify_universe_after_load(db, snapshot_date=date(2026, 10, 15), excluded=ex2, accept_exclusion_diff=True)
    assert info2["exclusion_removed"] == ["R1"]
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM universe_exclusion_snapshot WHERE snapshot_date = '2026-10-15'")
        assert cur.fetchone()[0] == 1


def test_guard_c_records_count_delta_without_threshold(db, clean_universe):
    before = count_active(db)
    _seed(db, [{"ticker": "T9", "name": "신규", "market": "KOSDAQ", "security_group": "주권"}])
    info = verify_universe_after_load(db, snapshot_date=date(2026, 9, 15), excluded=_excluded())
    assert info["active_after"] >= before + 1      # 기록만, 임계 없음(별도 판정 사안)


# ---------- (#221) 배제 집합 변동 자동 판정 ----------
def test_snapshot_auto_accepts_delisted_and_new_listing(db, clean_universe):
    """상폐(raw 에 없음)·신규 상장 배제(stocks 에 없던 spac)만 변동이면 실패하지 않고 details 에 기록."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"}])
    ex1 = _excluded(("465320", "교보15호스팩", "KOSDAQ", "주권", "spac"))
    verify_universe_after_load(db, snapshot_date=date(2026, 9, 22), excluded=ex1, raw_tickers={"T1", "465320"})
    ex2 = _excluded(("0200G0", "한국제17호스팩", "KOSDAQ", "주권", "spac"))
    info = verify_universe_after_load(db, snapshot_date=date(2026, 10, 1), excluded=ex2, raw_tickers={"T1", "0200G0"})
    assert info["exclusion_auto_accepted"] == {"removed_delisted": ["465320"], "added_new_listing": ["0200G0"]}
    assert info["exclusion_unexplained"] == {"added": [], "removed": []}
    assert info["exclusion_added"] == ["0200G0"] and info["exclusion_removed"] == ["465320"]
    with db.cursor() as cur:
        cur.execute("SELECT ticker FROM universe_exclusion_snapshot WHERE snapshot_date='2026-10-01'")
        assert [r[0] for r in cur.fetchall()] == ["0200G0"]


def test_snapshot_unexplained_raises_with_diff_attached(db, clean_universe):
    """기존 활성 종목(#199 유형)이 새로 배제되면 실패 — 예외에 판정(diff)이 붙어 보고서 입력이 된다."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"},
               {"ticker": "088980", "name": "맵스리얼티", "market": "KOSPI", "security_group": "주권"}])
    base = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"))     # 빈 배제 집합은 스냅샷을 쓰지 않으므로 기준선 1행
    verify_universe_after_load(db, snapshot_date=date(2026, 9, 22), excluded=base, raw_tickers={"T1", "P1", "088980"})
    ex2 = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"), ("088980", "맵스리얼티", "KOSPI", "투자회사", "security_group"))
    with db.cursor() as cur:   # 가드 (b) 를 통과시키기 위해 활성에서는 제외(이번 적재 전 배제 대상이 됐다는 시나리오)
        cur.execute("UPDATE stocks SET delisted_at = CURRENT_DATE WHERE ticker='088980'")
    with pytest.raises(UniverseGuardError, match="088980") as ei:
        verify_universe_after_load(db, snapshot_date=date(2026, 10, 1), excluded=ex2, raw_tickers={"T1", "P1", "088980"})
    assert ei.value.diff is not None and [u["ticker"] for u in ei.value.diff.unexplained_added] == ["088980"]
    assert "#199" in ei.value.diff.unexplained_added[0]["reason"] and ei.value.prev_date == date(2026, 9, 22)


def test_snapshot_strict_mode_fails_even_auto_types(db, clean_universe):
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"}])
    verify_universe_after_load(db, snapshot_date=date(2026, 9, 22), excluded=_excluded(("465320", "스팩", "KOSDAQ", "주권", "spac")),
                               raw_tickers={"T1", "465320"})
    with pytest.raises(UniverseGuardError, match="465320"):
        verify_universe_after_load(db, snapshot_date=date(2026, 10, 1), excluded=_excluded(), raw_tickers={"T1"}, auto_accept=False)
    info = verify_universe_after_load(db, snapshot_date=date(2026, 10, 1), excluded=_excluded(), raw_tickers={"T1"},
                                      accept_exclusion_diff=True)     # 명시 수용은 종전대로(strict 와 동시 지정은 ValueError — 별도 테스트)
    assert info["exclusion_removed"] == ["465320"]


def test_snapshot_without_raw_tickers_treats_removed_as_unexplained(db, clean_universe):
    """raw 미제공(구 호출처)이면 상폐 판정 불가 → removed 는 잔여(보수)."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"}])
    verify_universe_after_load(db, snapshot_date=date(2026, 9, 22), excluded=_excluded(("465320", "스팩", "KOSDAQ", "주권", "spac")))
    with pytest.raises(UniverseGuardError, match="465320"):
        verify_universe_after_load(db, snapshot_date=date(2026, 10, 1), excluded=_excluded())


def test_snapshot_accept_and_strict_together_is_an_error(db, clean_universe):
    with pytest.raises(ValueError, match="동시 지정 불가"):
        verify_universe_after_load(db, snapshot_date=date(2026, 10, 1), excluded=_excluded(), accept_exclusion_diff=True, auto_accept=False)


def test_snapshot_accept_marks_unexplained_as_human_accepted(db, clean_universe):
    """accept 로 통과한 잔여는 info.exclusion_accepted_unexplained=True — 호출자가 warnings 로 pipeline_runs 에 남긴다."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"}])
    verify_universe_after_load(db, snapshot_date=date(2026, 9, 22), excluded=_excluded(("R1", "리츠", "KOSPI", "부동산투자회사", "security_group")),
                               raw_tickers={"T1", "R1"})
    info = verify_universe_after_load(db, snapshot_date=date(2026, 10, 1), excluded=_excluded(), raw_tickers={"T1", "R1"},
                                      accept_exclusion_diff=True)
    assert info["exclusion_accepted_unexplained"] is True and info["exclusion_unexplained"]["removed"] == ["R1"]


def test_snapshot_round_trip_ticker_is_unexplained_not_new_listing(db, clean_universe):
    """상폐로 자동 수용된 스팩이 다음 달 원본에 다시 나타나면(부분 응답 왕복) 신규 상장으로 자동 수용하지 않는다 — 이전 스냅샷 기억."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"}])
    P = ("P1", "가우", "KOSPI", "주권", "preferred")                          # 빈 배제 집합은 스냅샷을 쓰지 않으므로 고정 1행 유지
    verify_universe_after_load(db, snapshot_date=date(2026, 8, 22), excluded=_excluded(P, ("S1", "스팩1", "KOSDAQ", "주권", "spac")), raw_tickers={"T1", "P1", "S1"})
    info = verify_universe_after_load(db, snapshot_date=date(2026, 9, 22), excluded=_excluded(P), raw_tickers={"T1", "P1"})    # S1 부재 → 상폐 자동
    assert info["exclusion_auto_accepted"]["removed_delisted"] == ["S1"]
    with pytest.raises(UniverseGuardError, match="S1"):                                                                   # 재등장 → 잔여
        verify_universe_after_load(db, snapshot_date=date(2026, 10, 22), excluded=_excluded(P, ("S1", "스팩1", "KOSDAQ", "주권", "spac")), raw_tickers={"T1", "P1", "S1"})


def test_snapshot_accept_refuses_199_type(db, clean_universe):
    """#199 유형(기존 활성 종목 → 신규 배제)은 --accept-exclusion-diff 로도 수용 불가 — 수용 시 mark_delisted 가 상장 종목을 폐지 처리(리뷰 #223 3차)."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"},
               {"ticker": "088980", "name": "맵스리얼티", "market": "KOSPI", "security_group": "주권"}])
    base = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"))
    verify_universe_after_load(db, snapshot_date=date(2026, 9, 22), excluded=base, raw_tickers={"T1", "P1", "088980"})
    with db.cursor() as cur:
        cur.execute("UPDATE stocks SET delisted_at = CURRENT_DATE WHERE ticker='088980'")
    ex2 = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"), ("088980", "맵스리얼티", "KOSPI", "투자회사", "security_group"))
    with pytest.raises(UniverseGuardError, match="#199 유형.*수용 불가"):
        verify_universe_after_load(db, snapshot_date=date(2026, 10, 1), excluded=ex2, raw_tickers={"T1", "P1", "088980"}, accept_exclusion_diff=True)


def test_preflight_raises_without_writing_snapshot(db, clean_universe):
    """쓰기 전 판정: 잔여면 예외, 통과해도 스냅샷을 쓰지 않는다(적재 후 verify 가 기록)."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"}])
    base = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"))
    verify_universe_after_load(db, snapshot_date=date(2026, 9, 22), excluded=base, raw_tickers={"T1", "P1"})
    d = preflight_exclusion_diff(db, snapshot_date=date(2026, 10, 1), excluded=_excluded(base.iloc[0].tolist(), ("S9", "스팩9", "KOSDAQ", "주권", "spac")),
                                 raw_tickers={"T1", "P1", "S9"})
    assert d.added_new_listing == ["S9"]
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM universe_exclusion_snapshot WHERE snapshot_date='2026-10-01'")
        assert cur.fetchone()[0] == 0
    with pytest.raises(UniverseGuardError, match="X1"):
        preflight_exclusion_diff(db, snapshot_date=date(2026, 10, 1), excluded=_excluded(base.iloc[0].tolist(), ("X1", "뭔가", "KOSPI", "주권", "etf")),
                                 raw_tickers={"T1", "P1", "X1"})


def test_snapshot_accept_refuses_late_resolution_of_unresolved_row(db, clean_universe):
    """UNRESOLVED 로 적재돼 있던 행이 배제 그룹으로 분류됨 = 늦은 분류 — 잔여(보고)이고 accept 로도 거부(회신 23 Q-G: 수용하면
    mark_delisted 가 상장 종목을 폐지로 기록 — #199 와 결과 동일). 첫 발생 = #199 착수 신호."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"},
               {"ticker": "R7", "name": "리츠7", "market": "KOSPI", "security_group": "UNRESOLVED"}])
    base = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"))
    verify_universe_after_load(db, snapshot_date=date(2026, 9, 22), excluded=base, raw_tickers={"T1", "P1", "R7"})
    with db.cursor() as cur:
        cur.execute("UPDATE stocks SET delisted_at = CURRENT_DATE WHERE ticker='R7'")
    ex2 = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"), ("R7", "리츠7", "KOSPI", "부동산투자회사", "security_group"))
    with pytest.raises(UniverseGuardError, match="R7"):
        verify_universe_after_load(db, snapshot_date=date(2026, 10, 1), excluded=ex2, raw_tickers={"T1", "P1", "R7"})
    with pytest.raises(UniverseGuardError, match=r"R7.*accept-exclusion-diff 로 수용 불가"):
        verify_universe_after_load(db, snapshot_date=date(2026, 10, 1), excluded=ex2, raw_tickers={"T1", "P1", "R7"}, accept_exclusion_diff=True)
