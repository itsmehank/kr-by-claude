"""[보고 전용] 이름 휴리스틱 3축(우선주·스팩·ETF) 부분문자열/접두사 오탐 점검 — 전문가 판정 회신 4 [3-b](b).

입력 = krx_secugrp_full.json(공매도 전종목, ETF 미포함 모집단). 이 모집단에서 ETF 접두사에 걸리는 종목은
전부 오탐이다(ETF 가 아님). 우선주·스팩은 SECUGRP 가 '주권'이라 직접 판별 불가 → 이름 패턴만 나열.
DB·코드 무접촉. 결과는 stdout + JSON. 이번 스프린트에서 수정하지 않는다(별건 보고).

usage: uv run python scripts/secugrp_name_axis_audit.py <krx_secugrp_full.json> <out.json>
"""
import json
import sys
from collections import Counter

from kr_pipeline.universe.transform import ETF_PREFIXES, _is_etf, _is_preferred, _is_spac

src, out = sys.argv[1], sys.argv[2]
krx = json.load(open(src))
etf_hits = [(t, v["name"], v["secugrp"], next(p for p in ETF_PREFIXES if v["name"].startswith(p)))
            for t, v in krx.items() if _is_etf(v["name"])]
pref_hits = [(t, v["name"]) for t, v in krx.items() if _is_preferred(v["name"])]
spac_hits = [(t, v["name"]) for t, v in krx.items() if _is_spac(v["name"])]
# 우선주 의심 오탐: 6자리 숫자 코드가 0 으로 끝나면 보통주 관례 — 정규식에 걸렸다면 이름이 '우'로 끝나는 보통주
pref_suspect = [(t, n) for t, n in pref_hits if t.isdigit() and t.endswith("0")]
import re
spac_suspect = [(t, n) for t, n in spac_hits
                if not re.search(r"(호스팩|스팩\d+호|스팩)$", n) and "호스팩" not in n]   # "OO스팩N호"·"OO제N호스팩" = 진짜 스팩
report = {
    "etf_prefix_hits_in_short_sale_population(=오탐 확정)": etf_hits,
    "etf_prefix_hit_count_by_prefix": dict(Counter(h[3] for h in etf_hits)),
    "preferred_hits": len(pref_hits),
    "preferred_suspects(끝자리 0 보통주 코드)": pref_suspect,
    "spac_hits": len(spac_hits),
    "spac_suspects": spac_suspect,
}
json.dump(report, open(out, "w"), ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1))
