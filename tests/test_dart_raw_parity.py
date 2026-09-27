"""#186 B — 파리티(회신 ③): 새 원본에 기존 parse.normalize_accounts 적용 vs dart_financials 저장값, 오차 0.
불일치 귀속 3종(정정 rcept_no 변경 / 기존 행 부재 / fs_div 경로 차이), 미귀속 1건↑ = 실패."""
from kr_pipeline.financials import raw_parity as P


def _resp(rev="1,000", oi="100", ni="50", fs="CFS", rcept="20250311001085"):
    return {"status": "000", "list": [
        {"rcept_no": rcept, "fs_div": fs, "account_nm": "매출액", "thstrm_amount": rev},
        {"rcept_no": rcept, "fs_div": fs, "account_nm": "영업이익", "thstrm_amount": oi},
        {"rcept_no": rcept, "fs_div": fs, "account_nm": "당기순이익", "thstrm_amount": ni}]}


STORED = {"revenue": 1000.0, "operating_income": 100.0, "net_income": 50.0, "fs_div": "CFS", "rcept_no": "20250311001085"}


def test_exact_match_is_ok():
    r = P.compare_cell(_resp(), STORED)
    assert r["ok"] and r["reason"] is None


def test_row_absent_is_attributed():
    r = P.compare_cell(_resp(), None)
    assert not r["ok"] and r["reason"] == P.ROW_ABSENT


def test_value_diff_with_changed_rcept_no_is_correction():
    r = P.compare_cell(_resp(rev="1,200", rcept="20260402001139"), STORED)
    assert not r["ok"] and r["reason"] == P.RCEPT_CHANGED and r["diffs"]["revenue"] == (1000.0, 1200.0)


def test_value_diff_with_fs_div_path_change_is_attributed():
    r = P.compare_cell(_resp(rev="900", fs="OFS"), STORED)
    assert not r["ok"] and r["reason"] == P.FS_DIV_PATH


def test_value_diff_same_rcept_same_fs_is_unattributed():
    r = P.compare_cell(_resp(rev="1,001"), STORED)          # 오차 0 — 1원 차이도 불일치
    assert not r["ok"] and r["reason"] is None


def test_summary_fails_on_any_unattributed():
    ok = P.compare_cell(_resp(), STORED)
    corr = P.compare_cell(_resp(rev="1,200", rcept="20260402001139"), STORED)
    un = P.compare_cell(_resp(rev="1,001"), STORED)
    s1 = P.summarize([ok, corr]); s2 = P.summarize([ok, corr, un])
    assert s1["passed"] and s1["attributed"][P.RCEPT_CHANGED] == 1 and s1["unattributed"] == 0
    assert not s2["passed"] and s2["unattributed"] == 1
