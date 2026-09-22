"""[보고 전용] 비-SECUGRP 2축(우선주 코드 규칙·스팩 이름) 부분문자열/접두사 오탐 점검 — 전문가 판정 회신 4 [3-b](b).

입력 = krx_secugrp_full.json(공매도 전종목, ETF 미포함 모집단). 이 모집단에서 ETF 접두사에 걸리는 종목은
전부 오탐이다(ETF 가 아님). 우선주·스팩은 SECUGRP 가 '주권'이라 직접 판별 불가 → 이름 패턴만 나열.
DB·코드 무접촉. 결과는 stdout + JSON. 이번 스프린트에서 수정하지 않는다(별건 보고).

usage: uv run python scripts/secugrp_name_axis_audit.py <krx_secugrp_full.json> <out.json>
"""
import json
import re
import sys
from collections import Counter

from kr_pipeline.universe.transform import _is_preferred_code, _is_spac

src, out = sys.argv[1], sys.argv[2]
krx = json.load(open(src))
pref_hits = [(t, v["name"]) for t, v in krx.items() if _is_preferred_code(t)]   # #195 커밋1: 코드 말미 규칙
spac_hits = [(t, v["name"]) for t, v in krx.items() if _is_spac(v["name"])]
# (#195 커밋1 이후) 우선주 판별이 코드 규칙이므로 "끝자리 0 인데 적중" 은 정의상 0 — 회귀 확인용
pref_suspect = [(t, n) for t, n in pref_hits if t.endswith("0")]
spac_suspect = [(t, n) for t, n in spac_hits
                if not re.search(r"(호스팩|스팩\d+호|스팩)$", n) and "호스팩" not in n]   # "OO스팩N호"·"OO제N호스팩" = 진짜 스팩
report = {
    "etf_axis": "removed in #195 커밋2 (governance 1-1)",
    "preferred_hits": len(pref_hits),
    "preferred_suspects(끝자리 0 보통주 코드)": pref_suspect,
    "spac_hits": len(spac_hits),
    "spac_suspects": spac_suspect,
}
json.dump(report, open(out, "w"), ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1))
