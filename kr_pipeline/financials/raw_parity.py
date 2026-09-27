"""#186 B — 파리티(2026-09-27 전문가 회신 ③): 새 원본 응답에 **기존 parse.normalize_accounts** 를 적용한 값 vs
dart_financials 저장값. 수치 허용오차 0(1원 차이도 불일치). 불일치는 전수 사유 귀속, 미귀속 1건↑ = 실패.
귀속 3종: RCEPT_CHANGED(정정공시로 rcept_no 가 바뀜) / ROW_ABSENT(기존 행 부재) / FS_DIV_PATH(CFS↔OFS 선택 경로 차이).
"""
from __future__ import annotations

from kr_pipeline.financials.parse import normalize_accounts

RCEPT_CHANGED = "rcept_changed"
ROW_ABSENT = "row_absent"
FS_DIV_PATH = "fs_div_path"
REASONS = (RCEPT_CHANGED, ROW_ABSENT, FS_DIV_PATH)
_FIELDS = ("revenue", "operating_income", "net_income")


def compare_cell(response: dict, stored: dict | None) -> dict:
    """{ok, reason(None=미귀속 또는 일치), diffs{field: (stored, new)}, new_rcept_no, stored_rcept_no}."""
    rows = response.get("list") or []
    acct = normalize_accounts(rows)
    new_rcept = next((r.get("rcept_no") for r in rows if r.get("rcept_no")), None)
    if stored is None:
        return {"ok": False, "reason": ROW_ABSENT, "diffs": {}, "new_rcept_no": new_rcept, "stored_rcept_no": None}
    diffs = {f: (stored.get(f), acct.get(f)) for f in _FIELDS if _ne(stored.get(f), acct.get(f))}
    if stored.get("fs_div") != acct.get("fs_div"):
        diffs["fs_div"] = (stored.get("fs_div"), acct.get("fs_div"))
    if not diffs:
        return {"ok": True, "reason": None, "diffs": {}, "new_rcept_no": new_rcept, "stored_rcept_no": stored.get("rcept_no")}
    if new_rcept and stored.get("rcept_no") and new_rcept != stored.get("rcept_no"):
        reason = RCEPT_CHANGED
    elif "fs_div" in diffs:
        reason = FS_DIV_PATH
    else:
        reason = None
    return {"ok": False, "reason": reason, "diffs": diffs, "new_rcept_no": new_rcept, "stored_rcept_no": stored.get("rcept_no")}


def _ne(a, b) -> bool:
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return float(a) != float(b)


def summarize(results: list[dict]) -> dict:
    attributed = {r: 0 for r in REASONS}
    ok = un = 0
    for r in results:
        if r["ok"]:
            ok += 1
        elif r["reason"] in attributed:
            attributed[r["reason"]] += 1
        else:
            un += 1
    return {"total": len(results), "ok": ok, "attributed": attributed, "unattributed": un, "passed": un == 0}
