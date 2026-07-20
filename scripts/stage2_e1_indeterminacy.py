"""#44 D2-b 선결 측정 — E1/base 카운트 판정 불능률 집계 (LLM 0회, read-only).

사전등록: docs/superpowers/specs/2026-07-20-issue44-e1-indeterminacy-prereg.md
(지표 M1~M6·해석 밴드는 저 문서가 유일 정의 — 이 스크립트는 그 정의의 구현.
측정 전 커밋된 문서와 패턴이 어긋나면 문서가 이긴다.)

출력: data/verification/2026-07-20-stage2/e1_indeterminacy.json + 요약 stdout.
수동 검수용으로 M4 해당/비해당 각 10건의 (symbol, sat, reasoning 발췌)도 저장.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from kr_pipeline.db.connection import connect

OUT_PATH = Path("data/verification/2026-07-20-stage2/e1_indeterminacy.json")

CLIMAX_PAT = re.compile(r"climax|클라이맥스|수직 급등|blow-off|블로우오프", re.I)
ORDINAL_PAT = re.compile(
    r"[0-9]\s*번째|첫\s*번째|첫\s*(base|베이스)|(1st|2nd|3rd|4th)|base\s*#[0-9]"
    r"|후기\s*(베이스|base)|late[- ]stage|초기\s*(베이스|base)|early[- ]stage"
    r"|(두|세|네)\s*번째",
    re.I,
)
UNCERTAIN_PAT = re.compile(
    r"불명확|애매|판단(하기)?\s*어려|불확실|단정(하기)?\s*어려|left-censored"
    r"|잘려|창 밖|uncertain|unclear|indeterminate|식별 불가|구분 불가",
    re.I,
)
# M6 서수 분포 분류
EARLY_PAT = re.compile(r"첫\s*(번째|base|베이스)|1\s*번째|1st|base\s*#1|2\s*번째|2nd|base\s*#2|두\s*번째|초기\s*(베이스|base)|early[- ]stage", re.I)
LATE_PAT = re.compile(r"[3-9]\s*번째|(3rd|4th)|base\s*#[3-9]|(세|네)\s*번째|후기\s*(베이스|base)|late[- ]stage", re.I)


def _measure(rows: list[tuple]) -> dict:
    total = len(rows)
    d_climax = []
    for sym, sat, reasoning, flags in rows:
        text = reasoning or ""
        if CLIMAX_PAT.search(text):
            d_climax.append((sym, str(sat), text, flags or []))
    m2 = [r for r in d_climax if ORDINAL_PAT.search(r[2])]
    m3 = [r for r in d_climax if UNCERTAIN_PAT.search(r[2])]
    m4 = [r for r in d_climax if (not ORDINAL_PAT.search(r[2])) or UNCERTAIN_PAT.search(r[2])]
    late_flag_rows = [(sym, str(sat), reasoning or "", flags or [])
                      for sym, sat, reasoning, flags in rows
                      if flags and "late_stage_base" in flags]
    m5 = [r for r in late_flag_rows if ORDINAL_PAT.search(r[2])]
    m6 = {"early_1_2": sum(1 for r in m2 if EARLY_PAT.search(r[2]) and not LATE_PAT.search(r[2])),
          "late_3plus": sum(1 for r in m2 if LATE_PAT.search(r[2])),
          "both_or_other": sum(1 for r in m2 if not EARLY_PAT.search(r[2]) and not LATE_PAT.search(r[2])
                               or (EARLY_PAT.search(r[2]) and LATE_PAT.search(r[2])))}

    def pct(n, d):
        return round(100.0 * n / d, 1) if d else None

    return {
        "rows_total": total,
        "M1_climax_rows": {"n": len(d_climax), "pct_of_total": pct(len(d_climax), total)},
        "M2_ordinal_stated": {"n": len(m2), "pct_of_climax": pct(len(m2), len(d_climax))},
        "M3_uncertainty": {"n": len(m3), "pct_of_climax": pct(len(m3), len(d_climax))},
        "M4_indeterminate_proxy": {"n": len(m4), "pct_of_climax": pct(len(m4), len(d_climax))},
        "M5_lateflag_with_ordinal": {"late_flag_rows": len(late_flag_rows), "n": len(m5),
                                     "pct": pct(len(m5), len(late_flag_rows))},
        "M6_stage_distribution": m6,
        "_m4_sample": [{"symbol": r[0], "sat": r[1], "excerpt": r[2][:300]} for r in m4[:10]],
        "_non_m4_sample": [{"symbol": r[0], "sat": r[1], "excerpt": r[2][:300]}
                           for r in d_climax if r not in m4][:10],
    }


def main() -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT symbol, analyzed_for_date, reasoning, risk_flags FROM backtest_classification")
        bt = cur.fetchall()
        cur.execute("SELECT symbol, classified_at::date, reasoning, risk_flags FROM weekly_classification")
        wk = cur.fetchall()
        # D_flag 부분집합 (실발화 — base 판정이 규약상 필수였던 행)
        cur.execute(
            "SELECT symbol, analyzed_for_date, reasoning, risk_flags FROM backtest_classification "
            "WHERE risk_flags::jsonb ? 'climax_run'")
        bt_flag = cur.fetchall()

    out = {
        "executed_at": datetime.now().isoformat(timespec="seconds"),
        "prereg": "docs/superpowers/specs/2026-07-20-issue44-e1-indeterminacy-prereg.md",
        "backtest_classification": _measure(bt),
        "weekly_classification_reference": _measure(wk),
        "backtest_climax_run_flag_subset": _measure(bt_flag),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    slim = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} if isinstance(v, dict) else v
            for k, v in out.items()}
    print(json.dumps(slim, ensure_ascii=False, indent=2))
    print(f"saved → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
