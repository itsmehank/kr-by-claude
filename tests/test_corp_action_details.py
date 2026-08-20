"""#114 경로B corp_action_details 단위 테스트 — 실검증 응답 형태 기반."""
from datetime import date

from kr_pipeline.corporate_actions.details import (
    normalize, parse_kr_date, parse_num, upsert_details,
)


def test_parse_kr_date():
    assert parse_kr_date("2026년 07월 27일") == date(2026, 7, 27)
    assert parse_kr_date("2026년 8월 3일") == date(2026, 8, 3)
    assert parse_kr_date("-") is None
    assert parse_kr_date(None) is None
    assert parse_kr_date("기재정정") is None


def test_parse_num():
    assert parse_num("29,731,461") == 29731461.0
    assert parse_num("0.5") == 0.5
    assert parse_num("-") is None
    assert parse_num(None) is None


def test_normalize_fric():
    # 실검증 표본(비비안 2026-08): 1주당 1주 무상증자, 기준일 08-03
    item = {"rcept_no": "20260812000624", "nstk_asstd": "2026년 08월 03일",
            "nstk_ascnt_ps_ostk": "1", "nstk_lstprd": "2026년 08월 20일"}
    n = normalize("fricDecsn", item)
    assert n["record_date"] == date(2026, 8, 3)
    assert n["ratio"] == 1.0


def test_normalize_cr():
    # 실검증 표본(101000 2026-08): 75% 무상감자, 기준일 07-27
    item = {"rcept_no": "20260814001573", "cr_std": "2026년 07월 27일",
            "cr_rt_ostk": "75", "cr_mth": "4주를 1주로 병합하는 무상감자"}
    n = normalize("crDecsn", item)
    assert n["record_date"] == date(2026, 7, 27)
    assert n["ratio"] == 0.75
    assert "무상감자" in n["method"]


def test_normalize_piic_3rd_party():
    # 실검증 표본(275630 2026-08): 3자배정 — 기준일 없음, 방식 보존
    item = {"rcept_no": "20260818000327", "ic_mthn": "제3자배정증자",
            "nstk_ostk_cnt": "1,902,173", "bfic_tisstk_ostk": "10,000,000"}
    n = normalize("piicDecsn", item)
    assert n["record_date"] is None
    assert n["method"] == "제3자배정증자"
    assert abs(n["ratio"] - 0.1902173) < 1e-9


def test_upsert_idempotent(db):
    items = [{"rcept_no": "20260101000001", "cr_std": "2026년 01월 02일",
              "cr_rt_ostk": "50", "cr_mth": "무상감자"}]
    assert upsert_details(db, "999990", "crDecsn", items) == 1
    assert upsert_details(db, "999990", "crDecsn", items) == 0
    with db.cursor() as cur:
        cur.execute("SELECT record_date, ratio::float FROM corp_action_details "
                    "WHERE ticker='999990'")
        assert cur.fetchone() == (date(2026, 1, 2), 0.5)


def test_parse_stkdp_normal_and_fallback():
    from kr_pipeline.corporate_actions.details import parse_stkdp
    # 실공시(20191220800361) 축약 형태 — 총수 기반 ratio
    t = ("주식배당 결정 1. 1주당 배당주식수 (주) 보통주식 0.0308160 종류주식 - "
         "2. 배당주식총수 (주) 보통주식 657,500 종류주식 - "
         "3. 발행주식총수 보통주식 22,342,500 종류주식 - "
         "4. 배당기준일 2019-12-31 5. 이사회결의일(결정일) 2019-12-20")
    p = parse_stkdp(t)
    assert p is not None
    assert p["record_date"] == date(2019, 12, 31)
    assert abs(p["ratio"] - 657500 / 22342500) < 1e-9
    # 총수 미제공 — 1주당 fallback
    t2 = ("주식배당 결정 1. 1주당 배당주식수 (주) 보통주식 0.05 "
          "4. 배당기준일 2020-12-31")
    p2 = parse_stkdp(t2)
    assert p2 is not None and abs(p2["ratio"] - 0.05) < 1e-9


def test_parse_stkdp_rejects_scrambled_correction():
    from kr_pipeline.corporate_actions.details import parse_stkdp
    # 기재정정 2단 표 오정렬 계열(실사례 3건): 라벨-값 어긋나 전 필드가 동일
    # 대수(발행총수)로 잡히거나(001040), 총수 자리에 1주당이 오는(049950 역전) 경우
    # — 타당성 한계로 기각/안전 fallback 되어야 한다.
    t = ("주식배당 결정 1. 1주당 배당주식수 (주) 보통주식 29,176,998 "
         "2. 배당주식총수 (주) 보통주식 29,176,998 "
         "3. 발행주식총수 보통주식 29,176,998 4. 배당기준일 2018-12-31")
    assert parse_stkdp(t) is None            # ratio 1.0 — 비현실
    t2 = ("주식배당 결정 1. 1주당 배당주식수 (주) 보통주식 0.03 "
          "2. 배당주식총수 (주) 보통주식 224,514 "
          "3. 발행주식총수 보통주식 0.03 4. 배당기준일 2021-12-31")
    p2 = parse_stkdp(t2)                     # 총수/발행 역전 → 1주당 fallback
    assert p2 is not None and abs(p2["ratio"] - 0.03) < 1e-9
