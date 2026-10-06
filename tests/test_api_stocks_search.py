"""#189 — 분석 API 종목 검색의 ILIKE 와일드카드(`%`·`_`·`\`)를 리터럴로 취급."""
import pytest
from fastapi.testclient import TestClient

from api.deps import get_conn
from api.main import app


@pytest.fixture
def client(db):
    with db.cursor() as cur:
        cur.executemany("INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT (ticker) DO NOTHING",
                        [("SRC189", "검색테스트일반"), ("SRC_89", "검색_밑줄"), ("SRC%89", "검색%퍼센트")])

    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_conn, None)


def test_search_escapes_wildcards(client):
    """결과 전원이 리터럴 문자를 포함해야 한다 — 공유 kr_test 의 다른 시드(literal `_` 티커)가 정당하게 섞일 수 있어 '빈 결과'가 아니라
    '모두 포함'으로 판정(test_trade_api_read.test_search_escapes_wildcards 와 같은 방식)."""
    under = client.get("/api/stocks", params={"q": "_", "limit": 1000}).json()
    assert under and all("_" in s["ticker"] or "_" in s["name"] for s in under)
    assert "SRC189" not in {s["ticker"] for s in under}                       # 이스케이프 안 되면 '_' 가 임의 1글자로 매칭
    pct = client.get("/api/stocks", params={"q": "%", "limit": 1000}).json()
    assert pct and all("%" in s["ticker"] or "%" in s["name"] for s in pct)
    back = client.get("/api/stocks", params={"q": "\\", "limit": 1000}).json()
    assert all("\\" in s["ticker"] or "\\" in s["name"] for s in back)


def test_search_plain_text_unchanged(client):
    assert [s["ticker"] for s in client.get("/api/stocks", params={"q": "검색테스트일반"}).json()] == ["SRC189"]
    assert {s["ticker"] for s in client.get("/api/stocks", params={"q": "src_8"}).json()} == {"SRC_89"}   # 대소문자 무시 유지


def test_escape_like_unit():
    from kr_pipeline.common.sql_text import escape_like
    assert escape_like("a_b%c\\d") == "a\\_b\\%c\\\\d"
    assert escape_like("삼성") == "삼성"
