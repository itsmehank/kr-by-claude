"""#122 — pykrx×DART 전 유니버스 대조: 참조 adj 조정 누락 전수 탐지. 읽기 전용.

대상 = 상장 전 종목(stocks.delisted_at IS NULL). 로컬 DB 만(KRX 0·DART 0):
  daily_prices(close/adj_close) → 참조 factor 점프(db_factor_jumps)
  corp_action_details(기준일·배율) → 기대 권리락 이벤트(expected_events)
  두 목록 대조 → matched / size_mismatch / missing.
missing 은 raw 종가 갭으로 실재를 재확인해 status 를 나눈다:
  missing_confirmed   — raw 갭이 기대 배율과 정합(이벤트 실재) + 참조 점프 없음 = 누락 확정
  missing_unconfirmed — raw 갭도 없음(철회·기준일 변경 가능) = DART 원공시 심판 대상
  missing_unverifiable — 주식배당(≈2%)·유상(배율 미지) 등 갭으로 확인 불가 = 후보
  pending             — 대조 창 끝이 마지막 가격일 이후(미래 권리락) = 판정 보류
missing·size_mismatch 건은 오염 창(권리락일~+380일) 내 minervini_pass 일수를
daily_indicators 에서 집계해 소급 표기한다(판정 뒤집기 아님 — 표본 누락 방향).

양성 대조군: 221800·232830·388610(#114 11차 ③ 확정 무상증자 누락)이 missing 으로
나오지 않으면 종료 코드 2 — 검출기 자체 결함으로 간주.

상세 미보유 종목(DART 미조회)은 검사 불가로 분리 집계하고, 그중 corporate_actions
에 조정성 공시(bonus_issue·capital_reduction·rights_offering)가 있는 종목을
2단계(DART 상세 조회) 대상 목록으로 JSON 에 남긴다.

  uv run python scripts/issue122_adj_missing_audit.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import date

import psycopg

from kr_pipeline.ohlcv.adj_missing_audit import (
    contamination_window, expected_events, is_pending, match_expected,
    raw_gap_evidence, resume_offset,
)
from kr_pipeline.ohlcv.adj_reconstruct import db_factor_jumps

DB = os.environ.get("DATABASE_URL", "postgresql://localhost/kr_pipeline")
POSITIVE_CONTROL = (("221800", "2023-02-23"), ("232830", "2020-09-04"),
                    ("388610", "2023-07-24"))          # (종목, 권리락일) 단위
JUDGMENT_TABLES = (("weekly_classification", "analyzed_for_date", "classification"),
                   ("classification_backfill", "analyzed_for_date", "classification"),
                   ("backtest_classification", "analyzed_for_date", "classification"),
                   ("recall_audit_classification", "analyzed_for_date", "classification"),
                   ("entry_params", "analyzed_for_date", None),
                   ("positions", "entry_date", None))
RELEVANT_CA = ("bonus_issue", "capital_reduction", "rights_offering")


def load_ticker(cur, t: str):
    cur.execute("SELECT date, close, adj_close FROM daily_prices WHERE ticker=%s "
                "AND close>0 AND adj_close>0 ORDER BY date", (t,))
    rows = cur.fetchall()
    closes = [(d, float(c)) for d, c, _ in rows]
    adj = {d: float(a) for d, _, a in rows}
    cur.execute("SELECT endpoint, record_date, ratio::float, method, rcept_no "
                "FROM corp_action_details WHERE ticker=%s", (t,))
    details = [{"endpoint": e, "record_date": rd, "ratio": rt, "method": m,
                "rcept_no": rc} for e, rd, rt, m, rc in cur.fetchall()]
    methods = {d["rcept_no"]: d["method"] for d in details}
    return closes, adj, details, methods


def judgments_in_window(cur, t: str, ex: date, end: date) -> dict:
    """오염 창 내 저장 판정 전수(#114 11차 ③ 동형) — 입력 룩백이 이벤트를 교차."""
    out: dict = {}
    for tab, dcol, vcol in JUDGMENT_TABLES:
        if vcol:
            cur.execute(f"SELECT {vcol}, count(*) FROM {tab} WHERE symbol=%s "
                        f"AND {dcol} BETWEEN %s AND %s GROUP BY 1", (t, ex, end))
            rows = dict(cur.fetchall())
        else:
            cur.execute(f"SELECT count(*) FROM {tab} WHERE symbol=%s "
                        f"AND {dcol} BETWEEN %s AND %s", (t, ex, end))
            n = cur.fetchone()[0]
            rows = {"rows": n} if n else {}
        if rows:
            out[tab] = rows
    return out


def load_passes(cur, t: str) -> dict[date, bool]:
    cur.execute("SELECT date, COALESCE(minervini_pass, FALSE) FROM daily_indicators "
                "WHERE ticker=%s", (t,))
    return dict(cur.fetchall())


def main() -> int:
    rows: list[dict] = []
    by_class: Counter = Counter()
    by_kind_class: Counter = Counter()
    by_status: Counter = Counter()
    checked = no_details = no_prices = future_rd = 0
    with psycopg.connect(DB) as conn:
        conn.read_only = True               # 세션 전체 읽기 전용(트랜잭션 속성 — 리뷰 R1 ①)
        cur = conn.cursor()
        cur.execute("SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY ticker")
        tickers = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT date FROM daily_prices ORDER BY date")
        market_dates = [r[0] for r in cur.fetchall()]   # 시장 거래일(휴장 vs 정지 구분)
        cur.execute("SELECT DISTINCT ticker FROM corporate_actions "
                    "WHERE event_type = ANY(%s)", (list(RELEVANT_CA),))
        ca_tickers = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT max(fetched_at)::date FROM corp_action_details")
        details_as_of = cur.fetchone()[0]

        phase2_targets: list[str] = []
        for i, t in enumerate(tickers, 1):
            closes, adj, details, methods = load_ticker(cur, t)
            if not closes:
                no_prices += 1
                continue
            if not details:
                no_details += 1
                if t in ca_tickers:
                    phase2_targets.append(t)
                continue
            checked += 1
            dates = [d for d, _ in closes]
            future_rd += sum(1 for x in details               # 집계 밖(미래 기준일, R2 ③)
                             if x["record_date"] and x["record_date"] > dates[-1])
            jumps = db_factor_jumps(closes, adj)
            passes: dict[date, bool] | None = None
            for ex, r_exp, kind, rc in expected_events(dates, details,
                                                       market_dates=market_dates):
                halt = resume_offset(closes, ex)
                cls = match_expected(ex, r_exp, kind, jumps, extra_days=halt)
                if cls != "matched" and is_pending(ex, kind, dates[-1], extra_days=halt):
                    cls = "pending"
                by_class[cls] += 1
                by_kind_class[f"{kind}:{cls}"] += 1
                if cls == "matched":
                    continue
                if passes is None:
                    passes = load_passes(cur, t)
                near = [(d.isoformat(), round(r, 4)) for d, r in jumps
                        if -7 <= (d - ex).days <= 90 + halt]
                nearest = min(((abs((d - ex).days), d, r) for d, r in jumps
                               if abs((d - ex).days) <= 120), default=None)
                nearest = ([nearest[1].isoformat(), round(nearest[2], 4), (nearest[1] - ex).days]
                           if nearest else None)       # 심판용: 창 밖 최근접 점프(리뷰 R1 ⑥)
                w = contamination_window(ex, passes)
                ev = raw_gap_evidence(closes, ex, r_exp, kind, extra_days=halt)
                if cls == "missing":
                    status = {"raw_gap_confirmed": "missing_confirmed",
                              "raw_gap_absent": "missing_unconfirmed"}.get(
                        ev["evidence"], "missing_unverifiable")
                else:
                    status = cls            # size_mismatch / pending
                by_status[status] += 1
                judg = (judgments_in_window(cur, t, ex, w["window_end"])
                        if status == "missing_confirmed" else None)
                rows.append({
                    "ticker": t, "ex_date": ex.isoformat(), "kind": kind,
                    "rcept_no": rc, "method": methods.get(rc),
                    "expected_ratio": r_exp and round(r_exp, 4),
                    "class": cls, "status": status, "halt_days": halt,
                    "db_jumps_near": near, "nearest_jump_120d": nearest,
                    "evidence": ev["evidence"], "gap_date": ev["gap_date"],
                    "raw_gap": ev["raw_gap"] and round(ev["raw_gap"], 4),
                    "window_end": w["window_end"].isoformat(),
                    "window_days": w["window_days"],
                    "window_pass_days": w["window_pass_days"],
                    "total_pass_days": w["total_pass_days"],
                    "judgments_in_window": judg,
                })
            if i % 500 == 0:
                print(f"  {i}/{len(tickers)} …", file=sys.stderr)

    confirmed = [r for r in rows if r["status"] == "missing_confirmed"]
    confirmed_tickers = sorted({r["ticker"] for r in confirmed})
    confirmed_keys = {(r["ticker"], r["ex_date"]) for r in confirmed}
    control_ok = all(k in confirmed_keys for k in POSITIVE_CONTROL)

    out = {
        "issue": 122, "generated": date.today().isoformat(),
        "method": ("corp_action_details 기준일 → 권리락일(v3 동형, 대형 갭 억제 없음, "
                   "휴장/정지 구분, 정지 중 권리락은 재개일 연장) vs daily_prices adj/raw "
                   "factor 점프(±5일·감자 [−7,+90], 크기 log 1.15·감자 1.5) 대조. "
                   "읽기 전용, KRX 0·DART 0."),
        "details_as_of": details_as_of.isoformat() if details_as_of else None,
        "universe": {"listed": len(tickers), "checked": checked,
                     "no_details": no_details, "no_prices": no_prices,
                     "future_record_dates_excluded": future_rd,
                     "phase2_targets": len(phase2_targets)},
        "events": {"by_class": dict(by_class),
                   "by_kind_class": dict(sorted(by_kind_class.items())),
                   "by_status": dict(sorted(by_status.items()))},
        "missing_confirmed": {
            "n_events": len(confirmed), "n_tickers": len(confirmed_tickers),
            "by_kind": dict(Counter(r["kind"] for r in confirmed)),
            "tickers": confirmed_tickers,
            "window_zero_pass_events":
                sum(1 for r in confirmed if r["window_days"] > 0 and r["window_pass_days"] == 0),
            "window_zero_pass_but_pass_elsewhere":
                sum(1 for r in confirmed if r["window_pass_days"] == 0 and r["total_pass_days"] > 0),
            "with_judgments_in_window":
                [{"ticker": r["ticker"], "kind": r["kind"], "ex_date": r["ex_date"],
                  "judgments": r["judgments_in_window"]}
                 for r in confirmed if r["judgments_in_window"]],
        },
        "positive_control": {"events": [list(k) for k in POSITIVE_CONTROL], "ok": control_ok},
        "phase2_targets": phase2_targets,
        "rows": sorted(rows, key=lambda r: (r["class"], r["ticker"], r["ex_date"])),
    }
    path = f"data/verification/issue122_adj_missing_audit_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in ("universe", "events", "positive_control")}
                     | {"missing_confirmed": {k: v for k, v in out["missing_confirmed"].items()
                                              if k != "tickers"}},
                     ensure_ascii=False, indent=1))
    print("saved:", path)
    if not control_ok:
        print("양성 대조군 미검출 — 검출기 결함", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
