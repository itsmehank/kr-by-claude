# tests/test_financials_filters.py
# (#68 4단계) 잠긴 사전등록 §2·§3 필터 판정 로직 — 순수 함수.
# 준거: docs/superpowers/specs/2026-07-22-issue68-stage3-filter-prereg.md (LOCKED)
from datetime import date

from kr_pipeline.financials.filters import evaluate_filters


def row(year, reprt, *, fs="CFS", rev=1000.0, oi=100.0, ni=80.0, shares=100.0,
        eps=None, pub=None, pub_prior=None, fstart=None, fend=None):
    q_end = {"11013": (3, 31), "11012": (6, 30), "11014": (9, 30),
             "11011": (12, 31)}[reprt]
    return {"ticker": "T", "bsns_year": year, "reprt_code": reprt,
            "status": "ok", "fs_div": fs,
            "fiscal_start": fstart or date(year, 1, 1),
            "fiscal_end": fend or date(year, *q_end),
            "revenue": rev, "operating_income": oi, "net_income": ni,
            "shares_outstanding": shares,
            "eps_derived": eps if eps is not None else (ni / shares),
            "eps_published": pub, "eps_published_prior": pub_prior,
            "disclosed_at": date(year, 12, 31)}


def test_c1_published_pair_pass_and_fail():
    """공시 쌍 1순위: g = (당기−전년동기)/|전년동기|, +25% 경계 포함."""
    rows = [row(2024, "11014", pub=150.0, pub_prior=100.0)]  # g=+50%
    out = evaluate_filters(rows)
    assert out["F-C1"]["label"] == "pass"
    assert "published" in out["F-C1"]["tags"]
    rows2 = [row(2024, "11014", pub=110.0, pub_prior=100.0)]  # g=+10%
    assert evaluate_filters(rows2)["F-C1"]["label"] == "fail"
    rows3 = [row(2024, "11014", pub=125.0, pub_prior=100.0)]  # g=+25% 경계=통과
    assert evaluate_filters(rows3)["F-C1"]["label"] == "pass"


def test_c1_turnaround_fourth_label():
    """흑자전환 = 통과 아닌 제4 라벨. 적자 지속 = 탈락."""
    rows = [row(2024, "11014", pub=10.0, pub_prior=-5.0)]
    assert evaluate_filters(rows)["F-C1"]["label"] == "turnaround"
    rows2 = [row(2024, "11014", pub=-10.0, pub_prior=-5.0)]
    assert evaluate_filters(rows2)["F-C1"]["label"] == "fail"


def test_c1_derived_fallback_with_shares_guard():
    """공시 쌍 결측 → 파생 폴백(eps_fallback 태그) + 주식수 2단 가드."""
    # 정상 폴백: 2024 Q3 eps 2.0 vs 2023 Q3 eps 1.0 → +100% pass
    rows = [row(2024, "11014", eps=2.0, shares=100.0),
            row(2023, "11014", eps=1.0, shares=100.0)]
    out = evaluate_filters(rows)
    assert out["F-C1"]["label"] == "pass"
    assert "eps_fallback" in out["F-C1"]["tags"]
    # 가드 1단: 주식수 1000× → 데이터 오류 판정불가
    rows2 = [row(2024, "11014", eps=2.0, shares=100000.0),
             row(2023, "11014", eps=1.0, shares=100.0)]
    assert evaluate_filters(rows2)["F-C1"]["label"] == "indeterminate"
    # 가드 2단: ×3 (밴드 [0.5,2] 밖) → 기업행위 의심 판정불가
    rows3 = [row(2024, "11014", eps=2.0, shares=300.0),
             row(2023, "11014", eps=1.0, shares=100.0)]
    assert evaluate_filters(rows3)["F-C1"]["label"] == "indeterminate"


def test_annual_latest_q4_derivation():
    """최신이 연간이면 4Q 단독 파생(연간−3분기 합) — q4_derived 태그.

    OI: 2024 연간 100, 분기 20×3 → 4Q=40. 2023 연간 80, 분기 20×3 → 4Q=20.
    g = +100% → F-C3 pass.
    """
    rows = []
    for y, annual_oi in ((2024, 100.0), (2023, 80.0)):
        rows.append(row(y, "11011", oi=annual_oi))
        for rc in ("11013", "11012", "11014"):
            rows.append(row(y, rc, oi=20.0))
    rows.sort(key=lambda r: r["fiscal_end"], reverse=True)
    out = evaluate_filters(rows)
    assert out["F-C3"]["label"] == "pass"
    assert "q4_derived" in out["F-C3"]["tags"]
    # 분기 3개 중 하나 결측 → 파생 불가 → 판정불가
    rows2 = [r for r in rows if not (r["bsns_year"] == 2024
                                     and r["reprt_code"] == "11012")]
    assert evaluate_filters(rows2)["F-C3"]["label"] == "indeterminate"


def test_c2_acceleration():
    """F-C2 = F-C1 pass AND g_t > g_{t−1q}. 직전 분기 g 미정의 → 판정불가."""
    # g_t(2024Q3) = +50%, g_{t-1q}(2024Q2) = +20% → 가속 pass
    rows = [row(2024, "11014", pub=150.0, pub_prior=100.0),
            row(2024, "11012", pub=120.0, pub_prior=100.0)]
    assert evaluate_filters(rows)["F-C2"]["label"] == "pass"
    # g_{t-1q} = +80% > g_t → 가속 아님 → fail
    rows2 = [row(2024, "11014", pub=150.0, pub_prior=100.0),
             row(2024, "11012", pub=180.0, pub_prior=100.0)]
    assert evaluate_filters(rows2)["F-C2"]["label"] == "fail"
    # 직전 분기가 흑자전환(기저 ≤0) → g 미정의 → 판정불가
    rows3 = [row(2024, "11014", pub=150.0, pub_prior=100.0),
             row(2024, "11012", pub=120.0, pub_prior=-10.0)]
    assert evaluate_filters(rows3)["F-C2"]["label"] == "indeterminate"


def test_s1_revenue_null_indeterminate():
    """F-S1: revenue NULL → 판정불가(사전등록 §3 — NULL 1.5% 흡수)."""
    rows = [row(2024, "11014", rev=None),
            row(2023, "11014", rev=100.0)]
    assert evaluate_filters(rows)["F-S1"]["label"] == "indeterminate"


def test_fiscal_transition_year_indeterminate():
    """결산기 변경 이행기(연간 ≠ 12개월±20일)가 낀 YoY → 판정불가."""
    rows = [row(2024, "11014", oi=50.0),
            row(2023, "11014", oi=20.0),
            row(2023, "11011", fstart=date(2023, 4, 1))]  # 9개월 연간 — 이행기
    assert evaluate_filters(rows)["F-C3"]["label"] == "indeterminate"


def test_no_rows_all_indeterminate():
    out = evaluate_filters([])
    for f in ("F-C1", "F-C2", "F-C3", "F-S1"):
        assert out[f]["label"] == "indeterminate"


def _fs2_rows(rev_2023, rev_2024):
    """분기별 매출 시계열 → 행 목록 (2023 Q1~Q3 + 2024 Q1~Q3)."""
    rows = []
    for y, revs in ((2023, rev_2023), (2024, rev_2024)):
        for rc, r_ in zip(("11013", "11012", "11014"), revs):
            if r_ is not None:
                rows.append(row(y, rc, rev=r_))
    return rows


def test_fs2_branch1_pass_and_accel_branch():
    """(신규 후보 사전등록 2026-07-24 §2) F-S2 = ≥25% OR 3분기 연속 가속."""
    from kr_pipeline.financials.filters import evaluate_fs2
    # 지선 ①: 최신 분기 +50% → pass
    out = evaluate_fs2(_fs2_rows([100, 100, 100], [100, 100, 150]))
    assert out["label"] == "pass"
    # 지선 ②: g = +5% → +10% → +20% (전부 25% 미달이지만 단조 가속) → pass
    out2 = evaluate_fs2(_fs2_rows([100, 100, 100], [105, 110, 120]))
    assert out2["label"] == "pass"
    assert "accel_branch" in out2["tags"]


def test_fs2_both_fail_and_indeterminate():
    from kr_pipeline.financials.filters import evaluate_fs2
    # 감속(+20% → +10% → +5%) + 지선① 미달 → 둘 다 fail → fail
    out = evaluate_fs2(_fs2_rows([100, 100, 100], [120, 110, 105]))
    assert out["label"] == "fail"
    # 지선① 미달 + 지선② 체인 결측(2023 Q1 부재 → g_{t−2q} 미정의) → 판정불가
    out2 = evaluate_fs2(_fs2_rows([None, 100, 100], [105, 110, 120]))
    assert out2["label"] == "indeterminate"
