"""0단계 층① — #37 B(5b) computed_gates 과거 재생 실측 (#44 착수 전 검증).

backtest_classification 의 entry/watch 행(피벗 보유)을 유효 주간(분류 토요일
다음 거래주)에 재생한다 — production 경로와 동일하게:
  trigger_gate.evaluate — production 규약 정합(PR #51 리뷰 반영):
    · stop_loss = base_low 주입 (load.py get_active_with_current:164 와 동일)
    · 트리거가 발동한 **모든 날** 재생 — production 의 _already_evaluated_symbols
      는 당일만 dedupe 하므로 트리거 유지 시 다음 날 재평가된다
    · prev_close 는 행 기반 무제한 lookback (production 의 DISTINCT ON
      date < as_of 와 동일 — 캘린더 창 경계로 자르지 않음)
  → build_for_5b(as_of=발동일, prior_row=해당 백테스트 행)  [look-ahead 차단]
  → payload["computed_gates"] 수집.
LLM 호출 없음. production DB 는 read-only (SELECT 만).

알려진 한계(리포트에 명시): production 은 LLM 이 abort 를 내면 그 분류에 대한
후속 트리거를 skip 하지만(_aborted_since_classification), 재생은 LLM 판정이
없으므로 abort 체인을 시뮬레이션하지 않는다 — 재생 모집단은 production 의
**상위집합**이다(누락이 아니라 과잉 방향 — 검증 목적상 보수적).

집계(판독 기준은 리포트 문서에):
  - 트리거 유형별 건수 (행 단위 아님 — 발동일 단위)
  - 게이트 키별: null 비율 / boolean 발화율 / 수치 게이트 요약
  - ohlcv_last_date != as_of 건수 + **None 건수 별도 계수** (falsy 단락으로
    결측이 '불일치 0' 에 숨지 않게 — PR #51 리뷰)
  - build 실패 건수(예외 유형별)
"""
from __future__ import annotations

import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from kr_pipeline.db.connection import connect
from kr_pipeline.backtest.trigger_audit import prior_row_for
from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as evaluate_gate

log = logging.getLogger("stage0.replay_5b")

OUT_PATH = Path("data/verification/2026-07-17-stage0/5b_gate_replay.json")

# 트리거 검출용 최소 필드 (payload 주입용 전체 행은 prior_row_for 가 단일 정의)
_ROWS_SQL = """
SELECT symbol, analyzed_for_date, classification, pivot_price, watch_reason, base_low
  FROM backtest_classification
 WHERE classification IN ('entry', 'watch')
   AND pivot_price IS NOT NULL
 ORDER BY analyzed_for_date, symbol
"""

# 유효 주간 + 무제한 lookback: 행 기반 LIMIT 로 과거를 확보 (장기 halt 도 통과).
# 45행 = 유효주 최대 5거래일 + lookback 40행 — production 의 무제한 조회와
# 실질 동일 (직전 거래일 1개만 필요).
_DAYS_SQL = """
SELECT date, adj_close, volume, avg_volume_50d, sma_50
  FROM daily_indicators
 WHERE ticker = %s AND date <= %s
 ORDER BY date DESC
 LIMIT 45
"""


def _trigger_days(conn, row: dict) -> list[tuple[date, str]]:
    """유효 주간(토+1 ~ 토+7)에서 트리거가 발동한 모든 (날짜, 유형)."""
    sat: date = row["sat"]
    with conn.cursor() as cur:
        cur.execute(_DAYS_SQL, (row["symbol"], sat + timedelta(days=7)))
        days = list(reversed(cur.fetchall()))  # 오름차순
    out: list[tuple[date, str]] = []
    prev_close = None
    for d, close, volume, avg_vol, sma_50 in days:
        if d <= sat:
            if close is not None:
                prev_close = float(close)  # 무제한 lookback 의 직전 종가
            continue
        if close is None or volume is None or avg_vol is None or sma_50 is None:
            continue
        trig = evaluate_gate(
            close=float(close),
            pivot_price=row["pivot_price"],
            volume=int(volume),
            avg_volume_50d=float(avg_vol),
            stop_loss=row["base_low"],  # production 과 동일 (load.py:164)
            sma_50=float(sma_50),
            classification=row["classification"],
            prev_close=prev_close,
            watch_reason=row["watch_reason"],
        )
        if trig is not None:
            out.append((d, trig))
        prev_close = float(close)
    return out


def _classify_value(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return "numeric"
    return "string"  # 날짜·라벨 등 (예: ohlcv_last_date)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    agg = {
        "rows_total": 0,
        "rows_triggered": 0,
        "replays_total": 0,
        "trigger_types": Counter(),
        "build_errors": Counter(),
        "ohlcv_last_date_mismatch": 0,
        "ohlcv_last_date_none": 0,
        "gate_values": defaultdict(Counter),   # key → {null|true|false|numeric|string: n}
        "numeric_samples": defaultdict(list),  # key → [float] (분포 요약용)
    }
    records = []

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_ROWS_SQL)
            rows = [
                {"symbol": r[0], "sat": r[1], "classification": r[2],
                 "pivot_price": float(r[3]), "watch_reason": r[4],
                 "base_low": float(r[5]) if r[5] is not None else None}
                for r in cur.fetchall()
            ]
        if limit:
            rows = rows[:limit]
        agg["rows_total"] = len(rows)

        for i, row in enumerate(rows):
            hits = _trigger_days(conn, row)
            if not hits:
                continue
            agg["rows_triggered"] += 1
            prior = prior_row_for(conn, row["symbol"], row["sat"])
            for as_of, trig in hits:
                agg["replays_total"] += 1
                agg["trigger_types"][trig] += 1
                try:
                    payload = build_for_5b(conn, row["symbol"], trigger_type=trig,
                                           as_of=as_of, prior_row=prior)
                except Exception as e:  # 측정 대상: 실데이터에서의 build 실패 유형
                    agg["build_errors"][f"{type(e).__name__}: {e}"] += 1
                    continue
                gates = payload.get("computed_gates") or {}
                flat = {}
                for k, v in gates.items():
                    if isinstance(v, dict):
                        for k2, v2 in v.items():
                            flat[f"{k}.{k2}"] = v2
                    else:
                        flat[k] = v
                for k, v in flat.items():
                    kind = _classify_value(v)
                    agg["gate_values"][k][kind] += 1
                    if kind == "numeric":
                        agg["numeric_samples"][k].append(float(v))
                last = gates.get("ohlcv_last_date")
                if last is None:
                    agg["ohlcv_last_date_none"] += 1  # 결측 = 별도 계수 (숨김 금지)
                elif str(last) != str(as_of):
                    agg["ohlcv_last_date_mismatch"] += 1
                records.append({
                    "symbol": row["symbol"], "sat": str(row["sat"]),
                    "as_of": str(as_of), "trigger": trig, "computed_gates": flat,
                })
            if (i + 1) % 200 == 0:
                log.info("progress %d/%d (rows_triggered %d, replays %d)",
                         i + 1, len(rows), agg["rows_triggered"],
                         agg["replays_total"])

    def _num_summary(vals: list[float]) -> dict:
        vs = sorted(vals)
        n = len(vs)
        return {"n": n, "min": vs[0], "p50": vs[n // 2], "max": vs[-1]}

    out = {
        "rows_total": agg["rows_total"],
        "rows_triggered": agg["rows_triggered"],
        "replays_total": agg["replays_total"],
        "trigger_types": dict(agg["trigger_types"]),
        "build_errors": dict(agg["build_errors"]),
        "ohlcv_last_date_mismatch": agg["ohlcv_last_date_mismatch"],
        "ohlcv_last_date_none": agg["ohlcv_last_date_none"],
        "gate_value_counts": {k: dict(v) for k, v in sorted(agg["gate_values"].items())},
        "numeric_summaries": {k: _num_summary(v)
                              for k, v in sorted(agg["numeric_samples"].items())},
        "records": records,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2,
                                   default=str), encoding="utf-8")

    print(json.dumps({k: out[k] for k in
                      ("rows_total", "rows_triggered", "replays_total",
                       "trigger_types", "build_errors",
                       "ohlcv_last_date_mismatch", "ohlcv_last_date_none")},
                     ensure_ascii=False, indent=2))
    print("\n[gate_value_counts]")
    for k, v in out["gate_value_counts"].items():
        print(f"  {k}: {v}")
    print(f"\nsaved → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
