from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


# 브리프 원 시드는 2026-06-01~06-15 대를 썼으나, 그 구간은 다른 테스트 파일들이
# db.commit() 으로 커밋(그리고 teardown 은 rollback 뿐이라 미청소)한
# trigger_evaluation_log 잔여 행들과 겹친다 — 특히 tests/test_api_review_builder.py
# 의 RVTEST02 고아 트리거(analyzed_for_date=2026-06-04)가 정확히 우리 D 와 같은
# 날짜라 count_orphan_triggers(ticker 스코프 없는 전역 지표)를 오염시켜 전체
# suite 실행 시(파일 알파벳순: review_builder → review_router) orphan_trigger_count
# 가 0 이 아니게 됐다. 상대·절대 날짜 모두 이 구간(05-17~06-15, 07-21, 07-24)을
# 피해 2026-07-02~07-15 대로 이동해 시드했다(그 외 값·거래일 간격은 브리프와 동일).
@pytest.fixture
def seed(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    with db.cursor() as cur:
        for tbl, col in [("trigger_evaluation_log", "symbol"),
                         ("weekly_classification", "symbol"),
                         ("daily_prices", "ticker"), ("stocks", "ticker")]:
            cur.execute(f"DELETE FROM {tbl} WHERE {col} LIKE 'RVAPI%'")
        cur.execute("""INSERT INTO stocks (ticker, name, market, sector, listed_at)
                       VALUES ('RVAPI01','에이','KOSPI','반도체','2020-01-01')""")
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES ('RVAPI01','2026-07-01 10:00:00+09','KOSPI','watch',
                       'cup_with_handle', 10000, 'weekend', '2026-06-29')""")
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, reasoning, prior_classification_at, analyzed_for_date)
               VALUES ('RVAPI01','2026-07-04 21:00:00+09','breakout_from_watch',
                       10200, 500000, 10000, 'wait', '돌파',
                       '2026-07-01 10:00:00+09', '2026-07-04')""")
        # 거래일 8개: D=7/4, T+5 = 7/12 종가 11000
        # (브리프 원 시드는 잉여 행이 하나 더 섞여 9행이 돼 T+5 가 하루 밀렸음
        #  — 8행으로 정정해 comment 대로 idx[D]+5 == 7/12 가 되도록 함)
        cur.execute(
            """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                                         adj_close, volume, value)
               SELECT 'RVAPI01', d::date, 1,1,1,1, v, 1000, 1000
                 FROM (VALUES ('2026-07-02',9500.0),('2026-07-03',9800.0),
                              ('2026-07-04',10200.0),('2026-07-05',10400.0),
                              ('2026-07-08',10500.0),('2026-07-09',10600.0),
                              ('2026-07-10',10800.0),
                              ('2026-07-12',11000.0)) AS t(d, v)""")
    db.commit()
    yield
    app.dependency_overrides.pop(get_conn, None)


def test_breakout_row_chain_t5(client, seed):
    r = client.get("/api/review/analyses?from=2026-06-25&to=2026-07-15&ticker=RVAPI01")
    assert r.status_code == 200
    body = r.json()
    assert body["orphan_trigger_count"] == 0
    row = body["rows"][0]
    assert row["status"].startswith("돌파")
    assert row["first_breakout_at"] == "2026-07-04"
    assert row["first_breakout_type"] == "breakout_from_watch"
    # pivot_delta(D) = (10200−10000)/10000 = +2%; adj(D)=10200, T+5=adj(7/12)=11000
    # T+5 = 1.02 × 11000/10200 − 1 = 0.1  (부동소수 오차 허용)
    assert abs(row["t5_pct"] - 0.10) < 1e-6
    assert row["t20_pct"] is None            # 미도래
    assert row["trigger_count"] == 1
    # 체인 기저 기준선 = 10200 / 1.02 = 10000
    assert abs(row["pivot_baseline"] - 10000.0) < 1e-6


def test_triggered_filter_and_limit_cap(client, seed):
    r = client.get("/api/review/analyses?from=2026-06-25&to=2026-07-15&triggered=false")
    assert all(row["first_breakout_at"] is None for row in r.json()["rows"])
    r2 = client.get("/api/review/analyses?limit=9999")
    assert r2.status_code == 200   # limit 은 500 으로 캡 (에러 아님)


def test_negative_limit_offset_rejected(client, seed):
    r = client.get("/api/review/analyses?limit=-1")
    assert r.status_code == 422
    r2 = client.get("/api/review/analyses?offset=-1")
    assert r2.status_code == 422


def test_pivot_null_hidden_by_default(client, seed, db):
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES ('RVAPI01','2026-07-15 10:00:00+09','KOSPI','watch',
                       NULL, NULL, 'weekend', '2026-07-13')""")
    db.commit()
    r = client.get("/api/review/analyses?from=2026-06-25&to=2026-07-15&ticker=RVAPI01")
    assert len(r.json()["rows"]) == 1        # pivot null 행 숨김
    r2 = client.get("/api/review/analyses?from=2026-06-25&to=2026-07-15"
                    "&ticker=RVAPI01&include_pivot_null=true")
    assert len(r2.json()["rows"]) == 2
